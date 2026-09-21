from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import (
    Account, Agent, AgentLease, AgentRent, Employee, PayrollLine, PayrollRun,
    Settlement, SettlementStatus, Shift, Voucher, VoucherType,
)
from ..permissions import can, permission_required
from ..services.accounting import D, account_balance, get_system_account, create_posted_entry
from ..services.accounts import ensure_agent_account, ensure_employee_payroll_account, ensure_user_collector_account
from ..services.audit import audit
from ..services.operations import (
    approve_settlement, build_payroll, charge_rent, pay_rent, pay_salary,
    post_payroll, post_voucher, create_settlement, post_expense,
)


bp=Blueprint("operations",__name__,url_prefix="/operations")

def _account_picker():
    all_accounts=Account.query.filter_by(active=True).order_by(Account.code).all()
    children={}
    for a in all_accounts:
        children.setdefault(a.parent_id,[]).append(a)
    for values in children.values():
        values.sort(key=lambda a:a.code)
    result=[]
    def walk(parent_id,depth=0):
        for a in children.get(parent_id,[]):
            result.append((a,depth))
            walk(a.id,depth+1)
    walk(None)
    return result


@bp.route("/vouchers",methods=["GET","POST"])
@permission_required("vouchers.post")
def vouchers():
    account_options=_account_picker()
    accounts=[a for a,_ in account_options if not a.is_group and a.allow_manual_posting]
    rows=Voucher.query.order_by(Voucher.id.desc()).limit(200).all()
    if request.method=="POST":
        try:
            from_account=db.session.get(Account,int(request.form["from_account_id"]))
            to_account=db.session.get(Account,int(request.form["to_account_id"]))
            if not from_account or not to_account: raise ValueError("اختر حسابي المصدر والهدف")
            voucher,entry=post_voucher(
                voucher_type=request.form.get("voucher_type","transfer"),
                amount=request.form.get("amount"),
                from_account=from_account,to_account=to_account,
                description=request.form.get("description","سند محاسبي"),
                user_id=current_user.id,beneficiary=request.form.get("beneficiary",""),
            )
            audit("create_voucher","voucher",voucher.id,voucher.number)
            db.session.commit(); flash(f"تم ترحيل السند {voucher.number} والقيد {entry.number}","success")
            return redirect(url_for("operations.vouchers"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    selected_type=request.args.get("type","receipt")
    return render_template("operations/vouchers.html",accounts=accounts,account_options=account_options,vouchers=rows,types=[
        (VoucherType.RECEIPT.value,"سند قبض"),(VoucherType.PAYMENT.value,"سند صرف"),
        (VoucherType.TRANSFER.value,"سند تحويل")])

@bp.get("/vouchers/<int:voucher_id>")
@permission_required("vouchers.post")
def voucher_detail(voucher_id):
    voucher=db.session.get(Voucher,voucher_id)
    if not voucher: return ("السند غير موجود",404)
    entry=db.session.get(__import__("app.models",fromlist=["JournalEntry"]).JournalEntry,voucher.journal_entry_id) if voucher.journal_entry_id else None
    return render_template("operations/voucher_detail.html",voucher=voucher,entry=entry)



@bp.route("/expenses",methods=["GET","POST"])
@permission_required("expenses.view")
def expenses():
    from ..models import Expense
    expense_accounts=Account.query.filter_by(account_type="expense",is_group=False,active=True,allow_manual_posting=True).order_by(Account.code).all()
    cash_accounts=Account.query.filter_by(account_type="asset",is_group=False,active=True,allow_manual_posting=True).order_by(Account.code).all()
    default_expense=get_system_account("operating_expense")
    default_cash=get_system_account("main_cash")
    rows=Expense.query.order_by(Expense.expense_date.desc(),Expense.id.desc()).limit(250).all()
    if request.method=="POST":
        try:
            if not can("expenses.manage"): raise ValueError("ليست لديك صلاحية إدارة المصروفات")
            expense_account=db.session.get(Account,int(request.form["expense_account_id"]))
            cash_account=db.session.get(Account,int(request.form.get("cash_account_id") or default_cash.id))
            expense,entry=post_expense(amount=request.form["amount"],expense_account=expense_account,cash_account=cash_account,
                description=request.form.get("description","مصروف تشغيلي"),beneficiary=request.form.get("beneficiary",""),
                expense_date=date.fromisoformat(request.form.get("expense_date") or date.today().isoformat()),user_id=current_user.id)
            audit("create_expense","expense",expense.id,expense.number)
            db.session.commit(); flash(f"تم ترحيل المصروف {expense.number}","success")
            return redirect(url_for("operations.expenses"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/expenses.html",rows=rows,expense_accounts=expense_accounts,cash_accounts=cash_accounts,
                           default_expense=default_expense,default_cash=default_cash)

@bp.get("/expenses/<int:expense_id>")
@permission_required("expenses.view")
def expense_detail(expense_id):
    from ..models import Expense, JournalEntry
    expense=db.session.get(Expense,expense_id)
    if not expense: return ("المصروف غير موجود",404)
    entry=db.session.get(JournalEntry,expense.journal_entry_id) if expense.journal_entry_id else None
    return render_template("operations/expense_detail.html",expense=expense,entry=entry)

@bp.route("/manual-journal",methods=["GET","POST"])
@permission_required("accounting.post")
def manual_journal():
    account_options=_account_picker()
    accounts=[a for a,_ in account_options if not a.is_group and a.allow_manual_posting]
    if request.method=="POST":
        try:
            indices=[k.rsplit("_",1)[-1] for k in request.form if k.startswith("account_id_")]
            lines=[]
            for idx in sorted(set(indices),key=lambda x:int(x)):
                aid=request.form.get(f"account_id_{idx}")
                if not aid: continue
                lines.append({"account":db.session.get(Account,int(aid)),
                              "debit":request.form.get(f"debit_{idx}","0"),
                              "credit":request.form.get(f"credit_{idx}","0"),
                              "description":request.form.get(f"line_description_{idx}",request.form.get("description","قيد يدوي"))})
            entry=create_posted_entry(description=request.form.get("description","قيد يدوي"),
                entry_date=date.fromisoformat(request.form.get("entry_date") or date.today().isoformat()),
                created_by_id=current_user.id,lines=lines,prefix="MAN",
                audit="قيد يدوي من شاشة المحاسبة")
            db.session.commit(); flash(f"تم ترحيل القيد {entry.number}","success")
            return redirect(url_for("accounting.journal"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/manual_journal.html",accounts=accounts,account_options=account_options,rows=range(1,9),today=date.today())

@bp.route("/settlements",methods=["GET","POST"])
@permission_required("collector.settle")
def settlements():
    custody_root=get_system_account("collector_root")
    sources=Account.query.filter_by(account_type="asset",is_group=False,active=True,allow_manual_posting=True,parent_id=custody_root.id).order_by(Account.code).all()
    source_balances=[(a,account_balance(a.id)) for a in sources]
    target=get_system_account("main_cash")
    rows=Settlement.query.order_by(Settlement.id.desc()).limit(200).all()
    shifts=Shift.query.filter_by(status="open").order_by(Shift.opened_at.desc()).all()
    if request.method=="POST":
        try:
            source=db.session.get(Account,int(request.form["source_account_id"]))
            if not source: raise ValueError("اختر حساب العهدة")
            amount=D(request.form["amount"])
            settlement=create_settlement(source_account=source,target_account=target,amount=amount,
                requested_by_id=current_user.id,
                shift_id=int(request.form["shift_id"]) if request.form.get("shift_id") else None,
                description=request.form.get("description","إخلاء عهدة إلى الصندوق"))
            audit("request_settlement","settlement",settlement.id,settlement.number)
            db.session.commit(); flash(f"تم إنشاء طلب الإخلاء {settlement.number}","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/settlements.html",sources=sources,source_balances=source_balances,target=target,rows=rows,shifts=shifts)

@bp.post("/settlements/<int:settlement_id>/approve")
@permission_required("collector.approve_settlement")
def approve(settlement_id):
    settlement=db.session.get(Settlement,settlement_id)
    try:
        entry=approve_settlement(settlement,current_user.id)
        audit("approve_settlement","settlement",settlement.id,entry.number)
        db.session.commit(); flash(f"تم اعتماد {settlement.number}","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.settlements"))

@bp.route("/shifts",methods=["GET","POST"])
@permission_required("collector.view")
def shifts():
    if request.method=="POST":
        try:
            existing=Shift.query.filter_by(collector_id=current_user.id,status="open").first()
            if existing: raise ValueError(f"لديك وردية مفتوحة بالفعل: {existing.shift_name}")
            shift=Shift(collector_id=current_user.id,shift_name=request.form.get("shift_name") or "وردية",
                opening_balance=D(request.form.get("opening_balance")))
            db.session.add(shift); audit("open_shift","shift",None,shift.shift_name); db.session.commit()
            flash("تم فتح الوردية","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    own=Shift.query.filter_by(collector_id=current_user.id).order_by(Shift.opened_at.desc()).limit(50).all()
    return render_template("operations/shifts.html",shifts=own)

@bp.post("/shifts/<int:shift_id>/close")
@permission_required("collector.settle")
def close_shift(shift_id):
    shift=db.session.get(Shift,shift_id)
    try:
        if shift.collector_id != current_user.id and not can("collector.approve_settlement"):
            raise ValueError("لا يمكنك إغلاق وردية مستخدم آخر")
        txs=__import__("app.models",fromlist=["GateTransaction"]).GateTransaction.query.filter_by(shift_id=shift.id,direction="entry").all()
        total=sum((D(x.amount) for x in txs),D(0))
        collector_account=ensure_user_collector_account(current_user)
        unassigned=sum((D(x.amount) for x in txs if not x.agent_id),D(0))
        if unassigned>0:
            settlement=create_settlement(source_account=collector_account,target_account=get_system_account("main_cash"),amount=unassigned,requested_by_id=current_user.id,shift_id=shift.id,description=f"إخلاء عهدة المتحصل للوردية {shift.shift_name}")
            audit("auto_request_shift_settlement","settlement",settlement.id,settlement.number)
        shift.closing_balance=D(shift.opening_balance)+total; shift.status="pending"; shift.closed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        audit("close_shift","shift",shift.id,str(total)); db.session.commit()
        flash("تمت إحالة الوردية للمراجعة، وإنشاء إخلاء عهدة المتحصل تلقائيًا","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.shifts"))

@bp.route("/leases",methods=["GET","POST"])
@permission_required("leases.view")
def leases():
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    rows=AgentLease.query.order_by(AgentLease.active.desc(),AgentLease.id.desc()).all()
    if request.method=="POST":
        try:
            if not can("leases.manage"): raise ValueError("ليست لديك صلاحية إدارة الإيجارات")
            agent=db.session.get(Agent,int(request.form["agent_id"]))
            lease=AgentLease(agent_id=agent.id,name=request.form.get("name") or "إيجار",
                monthly_amount=D(request.form["monthly_amount"]),
                starts_on=date.fromisoformat(request.form["starts_on"]),
                ends_on=date.fromisoformat(request.form["ends_on"]) if request.form.get("ends_on") else None,
                due_day=int(request.form.get("due_day") or 1))
            db.session.add(lease); db.session.flush(); ensure_agent_account(agent)
            audit("create_lease","agent_lease",lease.id,lease.name); db.session.commit(); flash("تم إنشاء عقد الإيجار","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/leases.html",agents=agents,leases=rows)

@bp.post("/leases/<int:lease_id>/charge")
@permission_required("leases.manage")
def charge_lease(lease_id):
    try:
        lease=db.session.get(AgentLease,lease_id)
        rent,entry=charge_rent(lease=lease,rent_month=date.fromisoformat(request.form["rent_month"]),user_id=current_user.id,
            base_amount=request.form.get("base_amount") or None,discount=request.form.get("discount","0"),addition=request.form.get("addition","0"))
        audit("charge_rent","agent_rent",rent.id,entry.number); db.session.commit(); flash("تم إثبات استحقاق الإيجار","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.leases"))

@bp.get("/rents")
@permission_required("leases.view")
def rents():
    rows=AgentRent.query.order_by(AgentRent.rent_month.desc(),AgentRent.id.desc()).limit(300).all()
    leases=AgentLease.query.filter_by(active=True).order_by(AgentLease.id.desc()).all()
    return render_template("operations/rents.html",rows=rows,leases=leases,cash=get_system_account("main_cash"))

@bp.post("/rents/<int:rent_id>/pay")
@permission_required("leases.pay")
def pay_rent_route(rent_id):
    try:
        rent=db.session.get(AgentRent,rent_id)
        entry=pay_rent(rent=rent,cash_account=get_system_account("main_cash"),user_id=current_user.id)
        audit("pay_rent","agent_rent",rent.id,entry.number); db.session.commit(); flash("تم تحصيل الإيجار","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.rents"))

@bp.route("/payroll",methods=["GET","POST"])
@permission_required("payroll.view")
def payroll():
    runs=PayrollRun.query.order_by(PayrollRun.payroll_month.desc()).all()
    employees=Employee.query.filter_by(active=True).order_by(Employee.code).all()
    if request.method=="POST":
        try:
            if not can("payroll.manage"): raise ValueError("ليست لديك صلاحية إدارة الرواتب")
            run=build_payroll(payroll_month=date.fromisoformat(request.form["payroll_month"]),created_by_id=current_user.id)
            audit("create_payroll","payroll_run",run.id,run.payroll_month.isoformat()); db.session.commit(); flash("تم إنشاء مسير الرواتب","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/payroll.html",runs=runs,employees=employees)

@bp.post("/payroll/<int:run_id>/post")
@permission_required("payroll.manage")
def payroll_post(run_id):
    try:
        run=db.session.get(PayrollRun,run_id)
        entry=post_payroll(run=run,user_id=current_user.id)
        audit("post_payroll","payroll_run",run.id,entry.number); db.session.commit(); flash("تم ترحيل مسير الرواتب","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.payroll"))

@bp.route("/payroll/<int:run_id>",methods=["GET","POST"])
@permission_required("payroll.view")
def payroll_detail(run_id):
    run=db.session.get(PayrollRun,run_id)
    lines=PayrollLine.query.filter_by(payroll_run_id=run.id).order_by(PayrollLine.id).all()
    if request.method=="POST":
        try:
            if not can("payroll.manage"): raise ValueError("ليست لديك صلاحية تعديل مسير الرواتب")
            if run.status!="draft": raise ValueError("لا يمكن تعديل مسير مرحل")
            for line in lines:
                gross=D(request.form.get(f"gross_{line.id}",line.gross_amount))
                deductions=D(request.form.get(f"deductions_{line.id}",line.deductions))
                if gross<0 or deductions<0 or deductions>gross: raise ValueError("بيانات الراتب غير صالحة")
                line.gross_amount=gross; line.deductions=deductions; line.net_amount=gross-deductions
            audit("update_payroll_lines","payroll_run",run.id,run.payroll_month.isoformat())
            db.session.commit(); flash("تم تحديث بنود المسير","success")
            return redirect(url_for("operations.payroll_detail",run_id=run.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/payroll_detail.html",run=run,lines=lines)

@bp.post("/payroll/employee/<int:employee_id>/pay")
@permission_required("payroll.pay")
def payroll_pay_employee(employee_id):
    employee=db.session.get(Employee,employee_id)
    try:
        entry=pay_salary(employee=employee,cash_account=get_system_account("main_cash"),
                         amount=request.form["amount"],user_id=current_user.id)
        audit("pay_salary","employee",employee.id,entry.number); db.session.commit(); flash("تم صرف الراتب","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.payroll"))
