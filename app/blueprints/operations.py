from datetime import date, timedelta
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import (
    Account, Agent, AgentLease, AgentRent, Employee, PayrollLine, PayrollRun,
    Settlement, SettlementStatus, Shift, Voucher, VoucherStatus, VoucherType,
)
from ..permissions import can, permission_required
from ..services.accounting import D, account_balance, get_system_account, create_posted_entry, reverse_entry
from ..services.accounts import ensure_agent_account, ensure_employee_payroll_account, ensure_user_collector_account
from ..services.audit import audit
from ..services.operations import (
    approve_settlement, build_payroll, charge_rent, pay_rent, pay_salary,
    is_cash_account, post_payroll, post_voucher, create_settlement, post_expense,
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
@permission_required("vouchers.view")
def vouchers():
    account_options=_account_picker()
    postable=[a for a,_ in account_options if not a.is_group and a.active and a.allow_manual_posting]
    cash_accounts=[a for a in postable if is_cash_account(a)]
    cash_ids={a.id for a in cash_accounts}
    counterpart_ids={a.id for a in postable if a.id not in cash_ids}
    rows=Voucher.query.order_by(Voucher.id.desc()).limit(500).all()
    editing_voucher=None

    edit_id=request.args.get("edit",type=int)
    if not edit_id and request.method=="POST":
        edit_id=request.form.get("edit_id",type=int)
    if edit_id:
        editing_voucher=db.session.get(Voucher,edit_id)
        if not editing_voucher:
            flash("السند المطلوب تعديله غير موجود","warning")
            return redirect(url_for("operations.vouchers"))
        if editing_voucher.status!="posted" or (
            editing_voucher.journal_entry and (
                editing_voucher.journal_entry.status!="posted" or editing_voucher.journal_entry.reversed_entry_id
            )
        ):
            flash("لا يمكن تعديل سند غير مرحّل أو تم عكس قيده","warning")
            return redirect(url_for("operations.vouchers"))

    if request.method=="POST":
        try:
            if not can("vouchers.post"):
                raise ValueError("ليست لديك صلاحية إصدار السندات")

            voucher_type=request.form.get("voucher_type","receipt")
            description=request.form.get("description","سند محاسبي").strip() or "سند محاسبي"
            beneficiary=request.form.get("beneficiary","").strip()

            if voucher_type==VoucherType.RECEIPT.value:
                counterpart=db.session.get(Account,request.form.get("account_id",type=int))
                cash_account=db.session.get(Account,request.form.get("cash_account_id",type=int))
                if not counterpart or not cash_account:
                    raise ValueError("اختر الحساب والصندوق")
                from_account,to_account=counterpart,cash_account
            elif voucher_type==VoucherType.PAYMENT.value:
                counterpart=db.session.get(Account,request.form.get("account_id",type=int))
                cash_account=db.session.get(Account,request.form.get("cash_account_id",type=int))
                if not counterpart or not cash_account:
                    raise ValueError("اختر الحساب والصندوق")
                from_account,to_account=cash_account,counterpart
            elif voucher_type==VoucherType.TRANSFER.value:
                from_account=db.session.get(Account,request.form.get("from_account_id",type=int))
                to_account=db.session.get(Account,request.form.get("to_account_id",type=int))
                if not from_account or not to_account:
                    raise ValueError("اختر الحساب المصدر والحساب الهدف")
            else:
                raise ValueError("نوع السند غير صالح")

            edit_target=db.session.get(Voucher,request.form.get("edit_id",type=int)) if request.form.get("edit_id") else None
            if edit_target and (
                edit_target.status!="posted" or
                (edit_target.journal_entry and (
                    edit_target.journal_entry.status!="posted" or edit_target.journal_entry.reversed_entry_id
                ))
            ):
                raise ValueError("لا يمكن تعديل سند غير مرحّل أو تم عكس قيده")

            if edit_target:
                old_entry=db.session.get(__import__("app.models",fromlist=["JournalEntry"]).JournalEntry,edit_target.journal_entry_id)
                if not old_entry or old_entry.reversed_entry_id:
                    raise ValueError("لا يمكن تعديل السند لأن قيده الأصلي غير قابل للعكس")
                reverse_entry(old_entry,current_user.id,"تعديل السند وإنشاء النسخة الجديدة")

            voucher,entry=post_voucher(
                voucher_type=voucher_type,amount=request.form.get("amount"),
                from_account=from_account,to_account=to_account,
                description=description,user_id=current_user.id,beneficiary=beneficiary,
            )
            db.session.flush()

            if edit_target:
                db.session.query(Voucher).filter(Voucher.id==edit_target.id).update(
                    {"status":VoucherStatus.VOID.value},synchronize_session=False
                )
                db.session.flush()
                audit("edit_voucher","voucher",edit_target.id,f"{edit_target.number} -> {voucher.number}")
                message=f"تم تعديل السند {edit_target.number} وإصدار {voucher.number} مع إنشاء قيد عكسي آمن"
            else:
                audit("create_voucher","voucher",voucher.id,voucher.number)
                message=f"تم إصدار السند {voucher.number} والقيد {entry.number}"

            db.session.commit()
            flash(message,"success")
            return redirect(url_for("operations.vouchers"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc),"danger")

    selected_type=request.args.get("type") or request.form.get("voucher_type") or (editing_voucher.voucher_type if editing_voucher else "")
    if selected_type not in {
        VoucherType.RECEIPT.value,VoucherType.PAYMENT.value,VoucherType.TRANSFER.value
    }:
        selected_type=""

    return render_template("operations/vouchers.html",
        account_options=account_options,counterpart_ids=counterpart_ids,
        cash_ids=cash_ids,postable_ids={a.id for a in postable},
        vouchers=rows,selected_type=selected_type,
        editing_voucher=editing_voucher)

@bp.post("/vouchers/<int:voucher_id>/reverse")
@permission_required("vouchers.post")
def reverse_voucher(voucher_id):
    voucher=db.session.get(Voucher,voucher_id)
    try:
        if not voucher:
            raise ValueError("السند غير موجود")
        if voucher.status!=VoucherStatus.POSTED.value:
            raise ValueError("السند غير مرحّل أو تم عكسه مسبقًا")
        entry=voucher.journal_entry
        if not entry or entry.status!="posted" or entry.reversed_entry_id:
            raise ValueError("السند غير مرحّل أو تم عكس قيده مسبقًا")
        reverse=reverse_entry(entry,current_user.id,request.form.get("reason","عكس السند"))
        # Keep the original journal posted and linked to its posted reversal.
        # Reports count both entries, so their net accounting effect is zero.
        # The voucher is voided separately to prevent reuse of the document.
        db.session.query(Voucher).filter(Voucher.id==voucher.id).update(
            {"status":VoucherStatus.VOID.value},synchronize_session=False
        )
        db.session.flush()
        audit("reverse_voucher","voucher",voucher.id,f"{voucher.number} -> {reverse.number}")
        db.session.commit()
        flash(f"تم عكس السند {voucher.number} وإنشاء القيد {reverse.number}","success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("operations.vouchers"))

@bp.get("/vouchers/<int:voucher_id>")
@permission_required("vouchers.view")
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
    expense_account_ids={a.id for a in expense_accounts}
    cash_account_ids={a.id for a in cash_accounts if is_cash_account(a)}
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
                           default_expense=default_expense,default_cash=default_cash,
                           expense_account_ids=expense_account_ids,cash_account_ids=cash_account_ids,
                           account_options=_account_picker())

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
            from_account=db.session.get(Account,request.form.get("from_account_id",type=int))
            to_account=db.session.get(Account,request.form.get("to_account_id",type=int))
            if not from_account or not to_account:
                raise ValueError("اختر الحساب الدائن والحساب المدين")
            if from_account.id==to_account.id:
                raise ValueError("لا يمكن أن يكون الحساب المدين والدائن نفس الحساب")
            amount=D(request.form.get("amount","0"))
            if amount<=0:
                raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
            description=request.form.get("description","").strip() or "قيد يومية"
            entry_date=date.fromisoformat(request.form.get("entry_date") or date.today().isoformat())
            entry=create_posted_entry(
                description=description,entry_date=entry_date,created_by_id=current_user.id,
                lines=[
                    {"account":to_account,"debit":amount,"credit":0,"description":description},
                    {"account":from_account,"debit":0,"credit":amount,"description":description},
                ],
                prefix="MAN",audit="قيد يومية من حساب إلى حساب")
            db.session.commit()
            flash(f"تم ترحيل القيد {entry.number}: من {from_account.name} إلى {to_account.name}","success")
            return redirect(url_for("accounting.journal"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc),"danger")
    return render_template("operations/manual_journal.html",accounts=accounts,account_options=account_options,today=date.today())



@bp.route("/settlements",methods=["GET","POST"])
@permission_required("collector.settle")
def settlements():
    if current_user.role == "collector":
        return ("Forbidden",403)
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
    return render_template("operations/settlements.html",sources=sources,source_balances=source_balances,source_account_ids=[a.id for a,_ in source_balances],target=target,rows=rows,shifts=shifts,account_options=_account_picker())

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
    if can("collector.approve_settlement") or current_user.role in ["admin","manager"]:
        own=Shift.query.order_by(Shift.opened_at.desc()).limit(100).all()
    else:
        own=Shift.query.filter_by(collector_id=current_user.id).order_by(Shift.opened_at.desc()).limit(50).all()
    return render_template("operations/shifts.html",shifts=own)

@bp.post("/shifts/<int:shift_id>/close")
@permission_required("collector.post")
def close_shift(shift_id):
    shift=db.session.get(Shift,shift_id)
    try:
        if shift.collector_id != current_user.id and not can("collector.approve_settlement"):
            raise ValueError("لا يمكنك إغلاق وردية مستخدم آخر")
        txs=(__import__("app.models",fromlist=["GateTransaction"]).GateTransaction.query
             .filter_by(shift_id=shift.id,direction="entry")
             .filter(__import__("app.models",fromlist=["GateTransaction"]).GateTransaction.agent_id.is_(None))
             .filter(__import__("app.models",fromlist=["GateTransaction"]).GateTransaction.counted_for_work.is_(True))
             .all())
        # Only unassigned gate collections are physically held by the collector.
        total=sum((D(x.amount) for x in txs),D(0))
        shift_owner=shift.collector
        if not shift_owner:
            raise ValueError("لا يمكن إغلاق وردية بدون متحصل مرتبط")
        collector_account=ensure_user_collector_account(shift_owner)
        if total>0:
            existing=Settlement.query.filter_by(shift_id=shift.id).filter(Settlement.status.in_(["pending","posted"])).first()
            if not existing:
                settlement=create_settlement(source_account=collector_account,target_account=get_system_account("main_cash"),amount=total,requested_by_id=current_user.id,shift_id=shift.id,description=f"إخلاء كامل عهدة المتحصل للوردية {shift.shift_name}")
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
    all_agents=Agent.query.order_by(Agent.active.desc(),Agent.name).all()
    rows=AgentLease.query.order_by(AgentLease.active.desc(),AgentLease.id.desc()).all()
    form_open=False
    form_data={}
    today=date.today()
    current_month=today.replace(day=1)
    next_month_start=(today.replace(day=28)+timedelta(days=4)).replace(day=1)
    current_rents={r.lease_id:r for r in AgentRent.query.filter_by(rent_month=current_month).all()}
    current_due_eligible={
        lease.id: lease.active
        and lease.starts_on.replace(day=1)<=current_month
        and (not lease.ends_on or lease.ends_on.replace(day=1)>=current_month)
        for lease in rows
    }
    unpaid_stats_by_lease={}
    for rent in AgentRent.query.filter_by(status="unpaid").all():
        stats=unpaid_stats_by_lease.setdefault(rent.lease_id,{"count":0,"amount":D("0")})
        stats["count"]+=1
        stats["amount"]+=D(rent.amount)
    if request.method=="POST":
        form_open=True
        form_data=request.form
        try:
            if not can("leases.manage"):
                raise ValueError("ليست لديك صلاحية إدارة الإيجارات")

            agent_id=request.form.get("agent_id",type=int)
            agent=db.session.get(Agent,agent_id) if agent_id else None
            if not agent or not agent.active:
                raise ValueError("اختر وكيلًا نشطًا قبل حفظ العقد")

            name=(request.form.get("name") or "إيجار").strip() or "إيجار"
            if len(name)>120:
                raise ValueError("اسم العقد يجب ألا يتجاوز 120 حرفًا")
            monthly_amount=D(request.form.get("monthly_amount"))
            if monthly_amount<=0:
                raise ValueError("المبلغ الشهري يجب أن يكون أكبر من صفر")

            try:
                starts_on=date.fromisoformat((request.form.get("starts_on") or "").strip())
            except ValueError:
                raise ValueError("حدد تاريخ بداية صحيحًا للعقد")
            end_value=(request.form.get("ends_on") or "").strip()
            try:
                ends_on=date.fromisoformat(end_value) if end_value else None
            except ValueError:
                raise ValueError("تاريخ نهاية العقد غير صحيح")
            if ends_on and ends_on<starts_on:
                raise ValueError("تاريخ نهاية العقد لا يمكن أن يسبق تاريخ بدايته")

            try:
                due_day=int(request.form.get("due_day") or 1)
            except (TypeError,ValueError):
                raise ValueError("يوم الاستحقاق يجب أن يكون رقمًا من 1 إلى 31")
            if not 1<=due_day<=31:
                raise ValueError("يوم الاستحقاق يجب أن يكون بين 1 و31")

            lease=AgentLease(agent_id=agent.id,name=name,monthly_amount=monthly_amount,
                starts_on=starts_on,ends_on=ends_on,due_day=due_day)
            db.session.add(lease)
            db.session.flush()
            ensure_agent_account(agent)
            audit("create_lease","agent_lease",lease.id,f"{lease.name}|{agent.name}|{monthly_amount}")
            db.session.commit()
            flash(f"تم إنشاء عقد الإيجار للوكيل {agent.name} بنجاح","success")
            return redirect(url_for("operations.leases"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc),"danger")
    return render_template("operations/leases.html",agents=agents,all_agents=all_agents,leases=rows,
        form_open=form_open,form_data=form_data,today=today,current_month=current_month,
        next_month_start=next_month_start,current_rents=current_rents,
        current_due_eligible=current_due_eligible,unpaid_stats_by_lease=unpaid_stats_by_lease)

@bp.post("/leases/<int:lease_id>/edit")
@permission_required("leases.manage")
def edit_lease(lease_id):
    lease=db.session.get(AgentLease,lease_id)
    if not lease:
        return ("العقد غير موجود",404)
    try:
        agent_id=request.form.get("agent_id",type=int)
        agent=db.session.get(Agent,agent_id) if agent_id else None
        if not agent or (not agent.active and agent.id!=lease.agent_id):
            raise ValueError("اختر وكيلًا نشطًا")
        recorded_rents=AgentRent.query.filter_by(lease_id=lease.id).all()
        if agent.id!=lease.agent_id and recorded_rents:
            raise ValueError("لا يمكن تغيير الوكيل بعد تسجيل استحقاق لهذا العقد؛ احتفظنا بالاستحقاقات والقيود كما هي.")
        name=(request.form.get("name") or "إيجار").strip() or "إيجار"
        if len(name)>120:
            raise ValueError("اسم العقد يجب ألا يتجاوز 120 حرفًا")
        monthly_amount=D(request.form.get("monthly_amount"))
        if monthly_amount<=0:
            raise ValueError("المبلغ الشهري يجب أن يكون أكبر من صفر")
        try:
            starts_on=date.fromisoformat((request.form.get("starts_on") or "").strip())
        except ValueError:
            raise ValueError("حدد تاريخ بداية صحيحًا للعقد")
        end_value=(request.form.get("ends_on") or "").strip()
        try:
            ends_on=date.fromisoformat(end_value) if end_value else None
        except ValueError:
            raise ValueError("تاريخ نهاية العقد غير صحيح")
        if ends_on and ends_on<starts_on:
            raise ValueError("تاريخ نهاية العقد لا يمكن أن يسبق تاريخ بدايته")
        try:
            due_day=int(request.form.get("due_day") or 1)
        except (TypeError,ValueError):
            raise ValueError("يوم الاستحقاق يجب أن يكون رقمًا من 1 إلى 31")
        if not 1<=due_day<=31:
            raise ValueError("يوم الاستحقاق يجب أن يكون بين 1 و31")

        recorded_months=[r.rent_month for r in recorded_rents]
        if recorded_months and starts_on.replace(day=1)>min(recorded_months):
            raise ValueError("لا يمكن نقل بداية العقد إلى ما بعد شهر استحقاق مسجل؛ الاستحقاقات والقيود السابقة محفوظة كما سُجلت.")
        if recorded_months and ends_on and ends_on.replace(day=1)<max(recorded_months):
            raise ValueError("لا يمكن إنهاء العقد قبل آخر شهر استحقاق مسجل؛ عدّل العقد دون استبعاد الاستحقاقات السابقة.")

        old_values=f"{lease.agent.name}|{lease.name}|{lease.monthly_amount}|{lease.starts_on}|{lease.ends_on}|{lease.due_day}"
        lease.agent=agent
        ensure_agent_account(agent)
        lease.name=name
        lease.monthly_amount=monthly_amount
        lease.starts_on=starts_on
        lease.ends_on=ends_on
        lease.due_day=due_day
        if ends_on and ends_on.replace(day=1)<date.today().replace(day=1):
            lease.active=False
        audit("update_lease","agent_lease",lease.id,
              f"{old_values} -> {lease.agent.name}|{lease.name}|{lease.monthly_amount}|{lease.starts_on}|{lease.ends_on}|{lease.due_day}; الاستحقاقات والقيود السابقة دون تغيير")
        db.session.commit()
        flash("تم تعديل بيانات العقد. لم تتغير الاستحقاقات السابقة أو قيودها المحاسبية.","success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("operations.leases"))

@bp.post("/leases/<int:lease_id>/toggle")
@permission_required("leases.manage")
def toggle_lease(lease_id):
    lease=db.session.get(AgentLease,lease_id)
    if not lease:
        return ("العقد غير موجود",404)
    try:
        if lease.active:
            lease.active=False
            message="تم إيقاف العقد مع إبقاء جميع الاستحقاقات السابقة والقيود المالية كما هي."
        else:
            if lease.ends_on and lease.ends_on.replace(day=1)<date.today().replace(day=1):
                raise ValueError("انتهت مدة العقد؛ استخدم إجراء تجديد العقد بدل إعادة تفعيله.")
            lease.active=True
            message="تم تفعيل العقد. لم تتغير الاستحقاقات السابقة أو قيودها."
        audit("toggle_lease","agent_lease",lease.id,"active="+str(lease.active))
        db.session.commit()
        flash(message,"success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("operations.leases"))

@bp.post("/leases/<int:lease_id>/renew")
@permission_required("leases.manage")
def renew_lease(lease_id):
    lease=db.session.get(AgentLease,lease_id)
    if not lease:
        return ("العقد غير موجود",404)
    try:
        try:
            starts_on=date.fromisoformat((request.form.get("starts_on") or "").strip())
        except ValueError:
            raise ValueError("حدد تاريخ بداية صحيحًا للتجديد")
        current_month=date.today().replace(day=1)
        new_month=starts_on.replace(day=1)
        if starts_on.day!=1 or new_month<=current_month:
            raise ValueError("يبدأ العقد المجدد في اليوم الأول من شهر قادم لتجنب التداخل أو احتساب شهر مرتين.")
        if lease.ends_on and lease.ends_on>=starts_on:
            raise ValueError("تاريخ بداية التجديد يجب أن يكون بعد نهاية العقد الحالي. عدّل تاريخ النهاية أولًا إذا لزم.")
        if AgentRent.query.filter(AgentRent.agent_id==lease.agent_id,AgentRent.rent_month>=new_month).first():
            raise ValueError("يوجد استحقاق مسجل لهذا الوكيل في شهر التجديد أو بعده؛ لن ننشئ عقدًا قد يكرر استحقاق الشهر.")
        try:
            monthly_amount=D(request.form.get("monthly_amount"))
        except Exception:
            raise ValueError("أدخل قيمة إيجار صحيحة")
        if monthly_amount<=0:
            raise ValueError("المبلغ الشهري للتجديد يجب أن يكون أكبر من صفر")
        end_value=(request.form.get("ends_on") or "").strip()
        try:
            ends_on=date.fromisoformat(end_value) if end_value else None
        except ValueError:
            raise ValueError("تاريخ نهاية العقد المجدد غير صحيح")
        if ends_on and ends_on<starts_on:
            raise ValueError("تاريخ نهاية العقد المجدد لا يمكن أن يسبق بدايته")
        name=(request.form.get("name") or f"{lease.name} (تجديد)").strip()
        if not name:
            name=f"{lease.name} (تجديد)"
        if len(name)>120:
            raise ValueError("اسم العقد المجدد يجب ألا يتجاوز 120 حرفًا")
        try:
            due_day=int(request.form.get("due_day") or lease.due_day)
        except (TypeError,ValueError):
            raise ValueError("يوم الاستحقاق يجب أن يكون من 1 إلى 31")
        if not 1<=due_day<=31:
            raise ValueError("يوم الاستحقاق يجب أن يكون من 1 إلى 31")

        previous_end=lease.ends_on
        if lease.ends_on is None:
            lease.ends_on=starts_on-timedelta(days=1)
        lease.active=False
        renewed=AgentLease(agent_id=lease.agent_id,name=name,monthly_amount=monthly_amount,
            starts_on=starts_on,ends_on=ends_on,due_day=due_day,active=True)
        db.session.add(renewed)
        db.session.flush()
        audit("renew_lease","agent_lease",lease.id,
              f"new_lease_id={renewed.id}; previous_end={previous_end}; effective={starts_on}; previous dues/journals preserved")
        audit("create_lease_renewal","agent_lease",renewed.id,
              f"previous_lease_id={lease.id}; {renewed.name}|{renewed.monthly_amount}|{renewed.starts_on}")
        db.session.commit()
        flash("تم تجديد العقد بإنشاء عقد جديد مرتبط بالوكيل. بقيت جميع استحقاقات وقيود العقد السابق دون تغيير.","success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("operations.leases"))

@bp.post("/leases/<int:lease_id>/charge")
@permission_required("leases.manage")
def charge_lease(lease_id):
    try:
        lease=db.session.get(AgentLease,lease_id)
        if not lease:
            raise ValueError("العقد غير موجود")
        month_value=(request.form.get("rent_month") or "").strip()
        if len(month_value)==7:
            rent_month=date.fromisoformat(month_value+"-01")
        else:
            rent_month=date.fromisoformat(month_value).replace(day=1)
        rent,entry=charge_rent(lease=lease,rent_month=rent_month,user_id=current_user.id,
            base_amount=request.form.get("base_amount") or None,discount=request.form.get("discount","0"),addition=request.form.get("addition","0"))
        audit("charge_rent","agent_rent",rent.id,entry.number)
        db.session.commit()
        flash(f"تم إثبات استحقاق الإيجار عن {rent.rent_month:%Y-%m} بنجاح","success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("operations.rents",lease_id=lease_id,status="unpaid"))

@bp.get("/rents")
@permission_required("leases.view")
def rents():
    selected_lease_id=request.args.get("lease_id",type=int)
    selected_status=(request.args.get("status") or "all").strip()
    if selected_status not in {"all","unpaid","paid"}:
        selected_status="all"
    rent_query=AgentRent.query
    if selected_lease_id:
        rent_query=rent_query.filter_by(lease_id=selected_lease_id)
    if selected_status in {"unpaid","paid"}:
        rent_query=rent_query.filter_by(status=selected_status)
    rows=rent_query.order_by(AgentRent.rent_month.desc(),AgentRent.id.desc()).all()
    all_rents=AgentRent.query.all()
    unpaid_rows=[r for r in all_rents if r.status!="paid"]
    paid_count=sum(1 for r in all_rents if r.status=="paid")
    unpaid_amount=sum((D(r.amount) for r in unpaid_rows),D("0"))
    leases=AgentLease.query.filter_by(active=True).order_by(AgentLease.id.desc()).all()
    lease_filters=AgentLease.query.order_by(AgentLease.id.desc()).all()
    current_month=date.today().strftime("%Y-%m")
    return render_template("operations/rents.html",rows=rows,leases=leases,lease_filters=lease_filters,
        cash=get_system_account("main_cash"),selected_lease_id=selected_lease_id,
        selected_status=selected_status,current_month=current_month,form_open=request.args.get("new")=="1",
        unpaid_count=len(unpaid_rows),paid_count=paid_count,unpaid_amount=unpaid_amount)

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
