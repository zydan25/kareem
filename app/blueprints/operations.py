from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from ..extensions import db
from ..models import Account, Agent, AgentLease, Employee, PayrollLine, PayrollRun, Settlement, SettlementStatus, User, Voucher, VoucherType
from ..permissions import permission_required
from ..services.accounting import D, account_balance
from ..services.audit import audit
from ..services.accounts import ensure_agent_account
from ..services.operations import (
    approve_settlement, build_payroll, charge_rent, pay_rent, pay_salary,
    post_payroll, post_voucher, create_settlement,
)

bp=Blueprint("operations",__name__,url_prefix="/operations")

@bp.route("/vouchers",methods=["GET","POST"])
@permission_required("vouchers.post")
def vouchers():
    accounts=Account.query.filter_by(is_group=False,active=True).order_by(Account.code).all()
    rows=Voucher.query.order_by(Voucher.id.desc()).limit(100).all()
    if request.method=="POST":
        try:
            typ=request.form.get("voucher_type")
            from_account=db.session.get(Account,int(request.form.get("from_account_id")))
            to_account=db.session.get(Account,int(request.form.get("to_account_id")))
            voucher,entry=post_voucher(voucher_type=typ,amount=request.form.get("amount"),
                from_account=from_account,to_account=to_account,
                description=request.form.get("description","سند محاسبي"),user_id=request.form.get("_user_id") or 0,
                beneficiary=request.form.get("beneficiary",""))
            voucher.created_by_id=__import__("flask_login").current_user.id
            audit("create_voucher","voucher",voucher.id,voucher.number)
            db.session.commit(); flash(f"تم ترحيل السند {voucher.number}","success")
            return redirect(url_for("operations.vouchers"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/vouchers.html",accounts=accounts,vouchers=rows,types=[
        (VoucherType.RECEIPT.value,"سند قبض"),(VoucherType.PAYMENT.value,"سند صرف"),
        (VoucherType.TRANSFER.value,"سند تحويل")])

@bp.route("/manual-journal",methods=["GET","POST"])
@permission_required("accounting.post")
def manual_journal():
    accounts=Account.query.filter_by(is_group=False,active=True,allow_manual_posting=True).order_by(Account.code).all()
    if request.method=="POST":
        try:
            description=request.form.get("description","قيد يدوي")
            indices=[k.rsplit("_",1)[-1] for k in request.form if k.startswith("account_id_")]
            lines=[]
            for idx in sorted(set(indices),key=lambda x:int(x)):
                aid=request.form.get(f"account_id_{idx}")
                if not aid: continue
                lines.append({"account":db.session.get(Account,int(aid)),
                              "debit":request.form.get(f"debit_{idx}","0"),
                              "credit":request.form.get(f"credit_{idx}","0"),
                              "description":request.form.get(f"line_description_{idx}",description)})
            from flask_login import current_user
            entry=__import__("app.services.accounting",fromlist=["create_posted_entry"]).create_posted_entry(
                description=description,entry_date=date.today(),created_by_id=current_user.id,lines=lines,prefix="MAN")
            audit("post_manual_journal","journal_entry",entry.id,entry.number)
            db.session.commit(); flash(f"تم ترحيل القيد {entry.number}","success")
            return redirect(url_for("accounting.journal"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/manual_journal.html",accounts=accounts,rows=range(1,7))

@bp.route("/settlements",methods=["GET","POST"])
@permission_required("collector.settle")
def settlements():
    from flask_login import current_user
    sources=Account.query.filter_by(is_group=False,active=True).order_by(Account.code).all()
    target=__import__("app.services.accounting",fromlist=["get_system_account"]).get_system_account("main_cash")
    rows=Settlement.query.order_by(Settlement.id.desc()).limit(100).all()
    if request.method=="POST":
        try:
            source=db.session.get(Account,int(request.form.get("source_account_id")))
            settlement=create_settlement(source_account=source,target_account=target,
                amount=request.form.get("amount"),requested_by_id=current_user.id,
                shift_id=(int(request.form.get("shift_id")) if request.form.get("shift_id") else None),
                description=request.form.get("description","إخلاء عهدة"))
            audit("request_settlement","settlement",settlement.id,settlement.number)
            db.session.commit(); flash(f"تم إرسال {settlement.number} للاعتماد","success")
            return redirect(url_for("operations.settlements"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/settlements.html",sources=sources,target=target,rows=rows)

@bp.post("/settlements/<int:settlement_id>/approve")
@permission_required("collector.approve_settlement")
def approve(settlement_id):
    from flask_login import current_user
    settlement=db.session.get(Settlement,settlement_id)
    try:
        approve_settlement(settlement,current_user.id)
        audit("approve_settlement","settlement",settlement.id,settlement.number)
        db.session.commit(); flash(f"تم اعتماد {settlement.number}","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.settlements"))

@bp.route("/leases",methods=["GET","POST"])
@permission_required("leases.view")
def leases():
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    rows=AgentLease.query.order_by(AgentLease.active.desc(),AgentLease.id.desc()).all()
    if request.method=="POST":
        from flask_login import current_user
        try:
            if not __import__("app.permissions",fromlist=["can"]).can("leases.manage"): raise ValueError("ليست لديك صلاحية إدارة الإيجارات")
            agent=db.session.get(Agent,int(request.form.get("agent_id")))
            lease=AgentLease(agent_id=agent.id,name=request.form.get("name") or "إيجار",
                monthly_amount=D(request.form.get("monthly_amount")),starts_on=date.fromisoformat(request.form.get("starts_on")),
                ends_on=(date.fromisoformat(request.form.get("ends_on")) if request.form.get("ends_on") else None),
                due_day=int(request.form.get("due_day") or 1))
            db.session.add(lease); db.session.flush(); ensure_agent_account(agent)
            audit("create_lease","agent_lease",lease.id,lease.name)
            db.session.commit(); flash("تم إنشاء عقد الإيجار","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/leases.html",agents=agents,leases=rows)

@bp.post("/leases/<int:lease_id>/charge")
@permission_required("leases.manage")
def charge_lease(lease_id):
    from flask_login import current_user
    try:
        lease=db.session.get(AgentLease,lease_id)
        rent,entry=charge_rent(lease=lease,rent_month=date.fromisoformat(request.form.get("rent_month")),
            user_id=current_user.id)
        audit("charge_rent","agent_rent",rent.id,entry.number)
        db.session.commit(); flash("تم إثبات استحقاق الإيجار","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.leases"))

@bp.get("/rents")
@permission_required("leases.view")
def rents():
    from ..models import AgentRent
    rows=AgentRent.query.order_by(AgentRent.rent_month.desc(),AgentRent.id.desc()).limit(300).all()
    cash=__import__("app.services.accounting",fromlist=["get_system_account"]).get_system_account("main_cash")
    return render_template("operations/rents.html",rows=rows,cash=cash)

@bp.post("/rents/<int:rent_id>/pay")
@permission_required("leases.pay")
def pay_rent_route(rent_id):
    from flask_login import current_user
    from ..models import AgentRent
    try:
        rent=db.session.get(AgentRent,rent_id)
        entry=pay_rent(rent=rent,cash_account=__import__("app.services.accounting",fromlist=["get_system_account"]).get_system_account("main_cash"),user_id=current_user.id)
        audit("pay_rent","agent_rent",rent.id,entry.number)
        db.session.commit(); flash("تم تحصيل الإيجار","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.rents"))

@bp.route("/payroll",methods=["GET","POST"])
@permission_required("payroll.view")
def payroll():
    runs=PayrollRun.query.order_by(PayrollRun.payroll_month.desc()).all()
    employees=Employee.query.filter_by(active=True).order_by(Employee.code).all()
    if request.method=="POST":
        from flask_login import current_user
        try:
            if not __import__("app.permissions",fromlist=["can"]).can("payroll.manage"): raise ValueError("ليست لديك صلاحية إدارة الرواتب")
            month=date.fromisoformat(request.form.get("payroll_month"))
            run=build_payroll(payroll_month=month,created_by_id=current_user.id)
            audit("create_payroll","payroll_run",run.id,run.payroll_month.isoformat())
            db.session.commit(); flash("تم إنشاء مسير الرواتب","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("operations/payroll.html",runs=runs,employees=employees)

@bp.post("/payroll/<int:run_id>/post")
@permission_required("payroll.manage")
def payroll_post(run_id):
    from flask_login import current_user
    try:
        run=db.session.get(PayrollRun,run_id)
        entry=post_payroll(run=run,user_id=current_user.id)
        audit("post_payroll","payroll_run",run.id,entry.number)
        db.session.commit(); flash("تم ترحيل مسير الرواتب","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("operations.payroll"))

@bp.get("/payroll/<int:run_id>")
@permission_required("payroll.view")
def payroll_detail(run_id):
    run=db.session.get(PayrollRun,run_id)
    return render_template("operations/payroll_detail.html",run=run,lines=PayrollLine.query.filter_by(payroll_run_id=run.id).all(),
        balance=lambda e: account_balance(e.id))
