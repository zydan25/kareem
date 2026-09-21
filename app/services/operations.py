from datetime import date, datetime, timezone
from decimal import Decimal
from ..extensions import db
from ..models import Account, Agent, AgentLease, AgentRent, Employee, Expense, PayrollLine, PayrollRun, Settlement, SettlementStatus, Shift, Voucher, VoucherType, VoucherStatus
from .accounts import ensure_agent_account, ensure_employee_payroll_account
from .accounting import D, account_balance, create_posted_entry, get_system_account, next_number

def ensure_user_shift(user_id, shift_name="وردية تشغيل"):
    shift=(Shift.query.filter_by(collector_id=user_id,status="open")
           .order_by(Shift.opened_at.desc()).first())
    if shift:
        return shift
    shift=Shift(collector_id=user_id,shift_name=shift_name,opened_at=datetime.now(timezone.utc),opening_balance=D("0"))
    db.session.add(shift); db.session.flush()
    return shift

def infer_voucher_type(from_account,to_account):
    cash=get_system_account("main_cash")
    if from_account.id==cash.id and to_account.id!=cash.id:
        return VoucherType.PAYMENT.value
    if to_account.id==cash.id and from_account.id!=cash.id:
        return VoucherType.RECEIPT.value
    return VoucherType.TRANSFER.value

def post_voucher(*, voucher_type=None, amount, from_account, to_account, description, user_id, beneficiary=""):
    amount=D(amount)
    if amount<=0: raise ValueError("قيمة السند يجب أن تكون أكبر من صفر")
    if not from_account or not to_account or from_account.is_group or to_account.is_group:
        raise ValueError("اختر حسابات فرعية قابلة للقيد")
    if not from_account.active or not to_account.active or not from_account.allow_manual_posting or not to_account.allow_manual_posting:
        raise ValueError("الحساب المصدر والهدف يجب أن يكونا نشطين وقابلين للقيد")
    ensure_user_shift(user_id,"وردية مالية")
    inferred=infer_voucher_type(from_account,to_account)
    entry=create_posted_entry(description=description,entry_date=date.today(),created_by_id=user_id,source_type="voucher",
        lines=[{"account":to_account,"debit":amount},{"account":from_account,"credit":amount}],prefix="VCH")
    voucher=Voucher(number=next_number("V"),voucher_type=inferred,voucher_date=date.today(),amount=amount,
        from_account_id=from_account.id,to_account_id=to_account.id,beneficiary=beneficiary,
        description=description,status=VoucherStatus.POSTED.value,journal_entry_id=entry.id,created_by_id=user_id)
    db.session.add(voucher)
    return voucher,entry

def post_expense(*, amount, expense_account, cash_account, description, user_id, beneficiary="", expense_date=None):
    amount=D(amount)
    if amount<=0: raise ValueError("قيمة المصروف يجب أن تكون أكبر من صفر")
    if not expense_account or expense_account.is_group or expense_account.account_type!="expense":
        raise ValueError("اختر حساب مصروف فرعي فقط")
    if not cash_account or cash_account.is_group or cash_account.account_type!="asset":
        raise ValueError("اختر حسابًا نقديًا فرعيًا")
    ensure_user_shift(user_id,"وردية مالية")
    expense_date=expense_date or date.today()
    entry=create_posted_entry(description=description,entry_date=expense_date,created_by_id=user_id,source_type="expense",
        lines=[{"account":expense_account,"debit":amount},{"account":cash_account,"credit":amount}],prefix="EXP")
    expense=Expense(number=next_number("EXP"),expense_date=expense_date,amount=amount,
        expense_account_id=expense_account.id,cash_account_id=cash_account.id,beneficiary=beneficiary,
        description=description,status="posted",journal_entry_id=entry.id,created_by_id=user_id)
    db.session.add(expense)
    return expense,entry

def create_settlement(*, source_account, target_account, amount, requested_by_id, shift_id=None, description="إخلاء عهدة"):
    amount=D(amount)
    if amount<=0: raise ValueError("قيمة الإخلاء يجب أن تكون أكبر من صفر")
    if source_account.account_type!="asset" or target_account.account_type!="asset": raise ValueError("الإخلاء متاح لحسابات الأصول فقط")
    if source_account.id==target_account.id: raise ValueError("حساب المصدر والهدف يجب أن يختلفا")
    available=account_balance(source_account.id)
    if available<amount: raise ValueError(f"الرصيد المتاح في العهدة {available} أقل من مبلغ الإخلاء {amount}")
    settlement=Settlement(number=next_number("SET"),settlement_date=date.today(),source_account_id=source_account.id,
        target_account_id=target_account.id,amount=amount,description=description,
        status=SettlementStatus.PENDING.value,requested_by_id=requested_by_id,shift_id=shift_id)
    db.session.add(settlement); db.session.flush(); return settlement

def approve_settlement(settlement, approver_id):
    if not settlement or settlement.status!=SettlementStatus.PENDING.value: raise ValueError("الإخلاء ليس في حالة انتظار")
    if account_balance(settlement.source_account_id)<D(settlement.amount): raise ValueError("رصيد العهدة تغير ولا يكفي للإخلاء")
    entry=create_posted_entry(description=settlement.description,entry_date=settlement.settlement_date,created_by_id=approver_id,
        source_type="settlement",source_id=settlement.id,
        lines=[{"account":settlement.target_account,"debit":settlement.amount},{"account":settlement.source_account,"credit":settlement.amount}],prefix="SET")
    settlement.status=SettlementStatus.POSTED.value; settlement.approved_by_id=approver_id
    settlement.approved_at=datetime.now(timezone.utc); settlement.journal_entry_id=entry.id
    if settlement.shift_id:
        shift=db.session.get(Shift,settlement.shift_id)
        if shift:
            shift.status="closed"; shift.closing_balance=shift.closing_balance or D(shift.opening_balance)
    return entry

def charge_rent(*, lease, rent_month, user_id, discount=0, addition=0, base_amount=None):
    rent_month=rent_month.replace(day=1)
    if rent_month<lease.starts_on.replace(day=1): raise ValueError("شهر الإيجار قبل بداية العقد")
    if lease.ends_on and rent_month>lease.ends_on.replace(day=1): raise ValueError("شهر الإيجار بعد نهاية العقد")
    if db.session.query(AgentRent).filter_by(agent_id=lease.agent_id,rent_month=rent_month).first(): raise ValueError("تم إنشاء إيجار هذا الشهر مسبقًا")
    base=D(base_amount if base_amount is not None else lease.monthly_amount)
    discount=D(discount); addition=D(addition)
    if base<=0 or discount<0 or addition<0 or discount>base: raise ValueError("قيمة الإيجار أو الخصم/الإضافة غير صالحة")
    final=base-discount+addition
    if final<=0: raise ValueError("صافي الإيجار يجب أن يكون أكبر من صفر")
    ensure_user_shift(user_id,"وردية مالية")
    agent=db.session.get(Agent,lease.agent_id); agent_account=ensure_agent_account(agent); revenue=get_system_account("rent_revenue")
    detail=f"إيجار {agent.name} عن {rent_month:%Y-%m} | أساسي {base} | خصم {discount} | إضافة {addition}"
    entry=create_posted_entry(description=detail,entry_date=rent_month,created_by_id=user_id,source_type="rent",
        lines=[{"account":agent_account,"debit":final},{"account":revenue,"credit":final}],prefix="RENT")
    rent=AgentRent(agent_id=agent.id,lease_id=lease.id,rent_month=rent_month,base_amount=base,discount=discount,
        addition=addition,amount=final,status="unpaid",journal_entry_id=entry.id)
    db.session.add(rent); return rent,entry

def pay_rent(*, rent, cash_account, user_id):
    if rent.status=="paid": raise ValueError("الإيجار مسدد بالفعل")
    ensure_user_shift(user_id,"وردية مالية")
    agent=db.session.get(Agent,rent.agent_id); agent_account=ensure_agent_account(agent)
    entry=create_posted_entry(description=f"تحصيل إيجار {agent.name} عن {rent.rent_month:%Y-%m}",entry_date=date.today(),created_by_id=user_id,
        source_type="rent_payment",source_id=rent.id,lines=[{"account":cash_account,"debit":rent.amount},{"account":agent_account,"credit":rent.amount}],prefix="RCP")
    rent.status="paid"; rent.payment_journal_id=entry.id; return entry

def build_payroll(*, payroll_month, created_by_id):
    payroll_month=payroll_month.replace(day=1)
    if db.session.query(PayrollRun).filter_by(payroll_month=payroll_month).first(): raise ValueError("تم إنشاء رواتب هذا الشهر مسبقًا")
    employees=db.session.query(Employee).filter_by(active=True).order_by(Employee.code).all()
    if not employees: raise ValueError("لا يوجد موظفون نشطون")
    run=PayrollRun(payroll_month=payroll_month,status="draft"); db.session.add(run); db.session.flush()
    for emp in employees:
        gross=D(emp.monthly_salary)
        db.session.add(PayrollLine(payroll_run_id=run.id,employee_id=emp.id,gross_amount=gross,deductions=0,net_amount=gross))
    return run

def post_payroll(*, run, user_id):
    if run.status!="draft": raise ValueError("مسير الرواتب ليس مسودة")
    lines=db.session.query(PayrollLine).filter_by(payroll_run_id=run.id).all()
    if not lines: raise ValueError("لا توجد بنود رواتب")
    ensure_user_shift(user_id,"وردية مالية")
    expense=get_system_account("salary_expense"); deduction=get_system_account("salary_deduction_liability")
    journal_lines=[{"account":expense,"debit":sum((D(x.gross_amount) for x in lines),Decimal("0")),"description":f"رواتب {run.payroll_month:%Y-%m}"}]
    deduction_total=Decimal("0")
    for line in lines:
        emp=db.session.get(Employee,line.employee_id); pay_account=ensure_employee_payroll_account(emp)
        net=D(line.net_amount); deduction_total+=D(line.deductions)
        if net: journal_lines.append({"account":pay_account,"credit":net,"description":f"راتب مستحق: {emp.full_name}"})
    if deduction_total: journal_lines.append({"account":deduction,"credit":deduction_total,"description":"استقطاعات رواتب"})
    entry=create_posted_entry(description=f"مسير رواتب {run.payroll_month:%Y-%m}",entry_date=run.payroll_month,created_by_id=user_id,
        source_type="payroll",source_id=run.id,lines=journal_lines,prefix="PAY")
    run.status="posted"; run.journal_entry_id=entry.id; return entry

def pay_salary(*, employee, cash_account, amount, user_id):
    pay_account=ensure_employee_payroll_account(employee); amount=D(amount); available=-account_balance(pay_account.id)
    if amount<=0 or amount>available: raise ValueError(f"المبلغ أكبر من الراتب المستحق، المتاح {available}")
    ensure_user_shift(user_id,"وردية مالية")
    return create_posted_entry(description=f"صرف راتب {employee.full_name}",entry_date=date.today(),created_by_id=user_id,source_type="salary_payment",
        lines=[{"account":pay_account,"debit":amount},{"account":cash_account,"credit":amount}],prefix="SAL")
