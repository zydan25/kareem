from datetime import date, datetime, timezone
from decimal import Decimal

from ..extensions import db
from ..models import (
    Account, Agent, AgentLease, AgentRent, Employee, GateTransaction,
    JournalEntry, PayrollLine, PayrollRun, Settlement, SettlementStatus,
    Shift, Voucher, VoucherType, VoucherStatus, User,
)
from .accounts import ensure_agent_account, ensure_employee_account, ensure_employee_payroll_account
from .accounting import D, account_balance, create_posted_entry, get_system_account, next_number


def post_voucher(*, voucher_type, amount, from_account, to_account, description, user_id, beneficiary=""):
    amount=D(amount)
    if amount <= 0:
        raise ValueError("قيمة السند يجب أن تكون أكبر من صفر")
    if from_account.is_group or to_account.is_group:
        raise ValueError("اختر حسابات فرعية قابلة للقيد")
    if voucher_type == VoucherType.RECEIPT.value:
        debit_account, credit_account = to_account, from_account
    elif voucher_type == VoucherType.PAYMENT.value:
        debit_account, credit_account = to_account, from_account
    elif voucher_type == VoucherType.TRANSFER.value:
        debit_account, credit_account = to_account, from_account
    else:
        raise ValueError("نوع السند غير مدعوم")
    entry=create_posted_entry(
        description=description, entry_date=date.today(), created_by_id=user_id,
        source_type="voucher", lines=[
            {"account":debit_account,"debit":amount,"description":description},
            {"account":credit_account,"credit":amount,"description":description},
        ], prefix="VCH")
    voucher=Voucher(
        number=next_number("V"), voucher_type=voucher_type, voucher_date=date.today(),
        amount=amount, from_account_id=from_account.id, to_account_id=to_account.id,
        beneficiary=beneficiary, description=description,
        status=VoucherStatus.POSTED.value, journal_entry_id=entry.id, created_by_id=user_id,
    )
    db.session.add(voucher)
    return voucher, entry


def create_settlement(*, source_account, target_account, amount, requested_by_id, shift_id=None, description="إخلاء عهدة"):
    amount=D(amount)
    if amount <= 0:
        raise ValueError("قيمة الإخلاء يجب أن تكون أكبر من صفر")
    if source_account.id == target_account.id:
        raise ValueError("حساب المصدر والهدف يجب أن يختلفا")
    if source_account.is_group or target_account.is_group:
        raise ValueError("لا يمكن الإخلاء من/إلى حساب رئيسي")
    available=account_balance(source_account.id)
    if available < amount:
        raise ValueError(f"الرصيد المتاح في العهدة {available} أقل من مبلغ الإخلاء {amount}")
    settlement=Settlement(number=next_number("SET"), settlement_date=date.today(),
        source_account_id=source_account.id,target_account_id=target_account.id,amount=amount,
        description=description,status=SettlementStatus.PENDING.value,
        requested_by_id=requested_by_id,shift_id=shift_id)
    db.session.add(settlement)
    return settlement


def approve_settlement(settlement, approver_id):
    if settlement.status != SettlementStatus.PENDING.value:
        raise ValueError("الإخلاء ليس في حالة انتظار")
    entry=create_posted_entry(
        description=settlement.description, entry_date=settlement.settlement_date,
        created_by_id=approver_id, source_type="settlement", source_id=settlement.id,
        lines=[{"account":settlement.target_account,"debit":settlement.amount},
               {"account":settlement.source_account,"credit":settlement.amount}],
        prefix="SET",
    )
    settlement.status=SettlementStatus.POSTED.value
    settlement.approved_by_id=approver_id
    settlement.approved_at=datetime.now(timezone.utc)
    settlement.journal_entry_id=entry.id
    if settlement.shift_id:
        shift=db.session.get(Shift,settlement.shift_id)
        if shift and shift.status == "open":
            shift.status="pending"
    return entry


def charge_rent(*, lease, rent_month, user_id):
    if rent_month.replace(day=1) < lease.starts_on.replace(day=1):
        raise ValueError("شهر الإيجار قبل بداية العقد")
    if lease.ends_on and rent_month.replace(day=1) > lease.ends_on.replace(day=1):
        raise ValueError("شهر الإيجار بعد نهاية العقد")
    existing=db.session.query(AgentRent).filter_by(agent_id=lease.agent_id,
        rent_month=rent_month.replace(day=1)).first()
    if existing:
        raise ValueError("تم إنشاء إيجار هذا الشهر مسبقًا")
    agent=db.session.get(Agent,lease.agent_id)
    agent_account=ensure_agent_account(agent)
    revenue=get_system_account("rent_revenue")
    entry=create_posted_entry(
        description=f"استحقاق إيجار {agent.name} عن {rent_month.strftime('%Y-%m')}",
        entry_date=rent_month.replace(day=1),created_by_id=user_id,source_type="rent",
        lines=[{"account":agent_account,"debit":lease.monthly_amount},
               {"account":revenue,"credit":lease.monthly_amount}],prefix="RENT")
    rent=AgentRent(agent_id=agent.id,lease_id=lease.id,rent_month=rent_month.replace(day=1),
        amount=lease.monthly_amount,status="unpaid",journal_entry_id=entry.id)
    db.session.add(rent)
    return rent,entry


def pay_rent(*, rent, cash_account, user_id):
    if rent.status == "paid":
        raise ValueError("الإيجار مسدد بالفعل")
    agent=db.session.get(Agent,rent.agent_id)
    agent_account=ensure_agent_account(agent)
    entry=create_posted_entry(
        description=f"تحصيل إيجار {agent.name} عن {rent.rent_month.strftime('%Y-%m')}",
        entry_date=date.today(),created_by_id=user_id,source_type="rent_payment",source_id=rent.id,
        lines=[{"account":cash_account,"debit":rent.amount},
               {"account":agent_account,"credit":rent.amount}],prefix="RCP")
    rent.status="paid"; rent.journal_entry_id=entry.id
    return entry


def build_payroll(*, payroll_month, created_by_id):
    payroll_month=payroll_month.replace(day=1)
    existing=db.session.query(PayrollRun).filter_by(payroll_month=payroll_month).first()
    if existing:
        raise ValueError("تم إنشاء رواتب هذا الشهر مسبقًا")
    employees=db.session.query(Employee).filter_by(active=True).order_by(Employee.code).all()
    if not employees:
        raise ValueError("لا يوجد موظفون نشطون")
    run=PayrollRun(payroll_month=payroll_month,status="draft")
    db.session.add(run); db.session.flush()
    for emp in employees:
        gross=D(emp.monthly_salary)
        db.session.add(PayrollLine(payroll_run_id=run.id,employee_id=emp.id,gross_amount=gross,deductions=0,net_amount=gross))
    return run


def post_payroll(*, run, user_id):
    if run.status != "draft":
        raise ValueError("مسير الرواتب ليس مسودة")
    lines=db.session.query(PayrollLine).filter_by(payroll_run_id=run.id).all()
    if not lines:
        raise ValueError("لا توجد بنود رواتب")
    expense=get_system_account("salary_expense")
    payable=get_system_account("salary_payable")
    deduction=get_system_account("salary_deduction_liability")
    journal_lines=[{"account":expense,"debit":sum((D(x.gross_amount) for x in lines),Decimal("0")),
                    "description":f"رواتب {run.payroll_month.strftime('%Y-%m')}"}]
    net_total=Decimal("0"); deduction_total=Decimal("0")
    for line in lines:
        emp=db.session.get(Employee,line.employee_id)
        pay_account=ensure_employee_payroll_account(emp)
        net=D(line.net_amount); ded=D(line.deductions)
        net_total += net; deduction_total += ded
        if net:
            journal_lines.append({"account":pay_account,"credit":net,"description":f"راتب مستحق: {emp.full_name}"})
    if deduction_total:
        journal_lines.append({"account":deduction,"credit":deduction_total,"description":"استقطاعات رواتب"})
    entry=create_posted_entry(description=f"مسير رواتب {run.payroll_month.strftime('%Y-%m')}",
        entry_date=run.payroll_month,created_by_id=user_id,source_type="payroll",source_id=run.id,
        lines=journal_lines,prefix="PAY")
    run.status="posted"; run.journal_entry_id=entry.id
    return entry


def pay_salary(*, employee, cash_account, amount, user_id):
    pay_account=ensure_employee_payroll_account(employee)
    amount=D(amount)
    balance=-account_balance(pay_account.id)
    if amount <= 0 or amount > balance:
        raise ValueError(f"المبلغ أكبر من الراتب المستحق، المتاح {balance}")
    entry=create_posted_entry(description=f"صرف راتب {employee.full_name}",
        entry_date=date.today(),created_by_id=user_id,source_type="salary_payment",
        lines=[{"account":pay_account,"debit":amount},{"account":cash_account,"credit":amount}],prefix="SAL")
    return entry
