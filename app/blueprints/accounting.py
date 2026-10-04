from datetime import date
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Account, JournalEntry
from sqlalchemy import or_
from ..permissions import can, permission_required
from ..services.accounting import account_balance, create_posted_entry, get_system_account, reverse_entry
from ..services.audit import audit

bp=Blueprint("accounting",__name__,url_prefix="/accounting")

ACCOUNT_TYPE_LABELS={"asset":"أصول","liability":"خصوم","equity":"حقوق ملكية","revenue":"إيرادات","expense":"مصروفات","memo":"مذكرة"}

def _children_tree(accounts):
    by_parent={}
    for account in accounts:
        by_parent.setdefault(account.parent_id,[]).append(account)
    for values in by_parent.values():
        values.sort(key=lambda x:(x.code or ""))
    def build(parent_id=None, depth=0):
        result=[]
        for account in by_parent.get(parent_id,[]):
            children=build(account.id,depth+1)
            balance=sum((node["balance"] for node in children),0) if children else (account_balance(account.id) if not account.is_group else 0)
            result.append({"account":account,"depth":depth,"children":children,"balance":balance})
        return result
    return build(None)

def _account_references(account_id):
    """Return a human-readable direct reference that prevents safe deletion."""
    from ..models import Agent, Client, Employee, Expense, JournalLine, Settlement, Voucher
    checks=[
        (JournalLine, "account_id", "قيد محاسبي"),
        (Voucher, "from_account_id", "سند"),
        (Voucher, "to_account_id", "سند"),
        (Expense, "expense_account_id", "مصروف"),
        (Expense, "cash_account_id", "مصروف"),
        (Settlement, "source_account_id", "تسوية"),
        (Settlement, "target_account_id", "تسوية"),
        (Agent, "account_id", "وكيل"),
        (Client, "account_id", "عميل"),
        (Employee, "account_id", "حساب موظف"),
        (Employee, "cashbox_account_id", "صندوق موظف"),
        (Employee, "payroll_account_id", "مستحق راتب"),
    ]
    for model,column_name,label in checks:
        column=getattr(model,column_name)
        if db.session.query(model).filter(column==account_id).first():
            return label
    return None

def _next_code(parent):
    existing=[a.code for a in Account.query.filter(Account.parent_id==parent.id).all() if a.code]
    prefix=f"{parent.code}"
    nums=[]
    for code in existing:
        if code.startswith(prefix) and code[len(prefix):].isdigit():
            nums.append(int(code[len(prefix):]))
    width=max([len(code)-len(prefix) for code in existing if code.startswith(prefix) and code[len(prefix):].isdigit()] or [2])
    return f"{prefix}{(max(nums)+1 if nums else 1):0{width}d}"

@bp.get("/accounts")
@permission_required("accounting.view")
def accounts():
    all_accounts=Account.query.order_by(Account.code).all()
    tree=_children_tree(all_accounts)
    stats={
        "count":len(all_accounts),
        "groups":sum(1 for a in all_accounts if a.is_group),
        "leaves":sum(1 for a in all_accounts if not a.is_group),
        "balance":sum((account_balance(a.id) for a in all_accounts if not a.is_group),0),
    }
    return render_template("accounting/accounts.html",tree=tree,flat_accounts=all_accounts,stats=stats,
                           account_type_labels=ACCOUNT_TYPE_LABELS,balance_func=account_balance,can_manage=can("accounting.manage"))

@bp.route("/accounts/new",methods=["GET","POST"])
@permission_required("accounting.manage")
def account_new():
    parents=Account.query.filter_by(is_group=True,active=True).order_by(Account.code).all()
    parent_id=request.form.get("parent_id",type=int) if request.method=="POST" else request.args.get("parent_id",type=int)
    selected_parent=db.session.get(Account,parent_id) if parent_id else (parents[0] if parents else None)
    if request.method=="POST":
        try:
            parent=db.session.get(Account,int(request.form["parent_id"]))
            if not parent or not parent.is_group: raise ValueError("اختر حسابًا أبًا تجميعيًا")
            name=request.form.get("name","").strip()
            if not name: raise ValueError("اسم الحساب مطلوب")
            is_group=request.form.get("is_group")=="1"
            opening_balance=Decimal(str(request.form.get("opening_balance","0") or "0")).quantize(Decimal("0.01"))
            if opening_balance < 0: raise ValueError("الرصيد الافتتاحي لا يمكن أن يكون سالبًا")
            if is_group and opening_balance != 0: raise ValueError("الحساب التجميعي لا يحمل رصيدًا افتتاحيًا؛ استخدم حسابًا تفصيليًا")
            opening_side=request.form.get("opening_side","auto")
            code=_next_code(parent)
            while Account.query.filter_by(code=code).first():
                code=f"{parent.code}{int(code[len(parent.code):])+1:02d}"
            account=Account(code=code,name=name,account_type=parent.account_type,parent_id=parent.id,is_group=is_group,
                            active=True,allow_manual_posting=not is_group)
            db.session.add(account); db.session.flush()

            opening_entry_number=None
            if opening_balance > 0:
                opening_account=get_system_account("opening_balance_equity")
                debit_by_nature=account.account_type in {"asset","expense"}
                is_debit=(debit_by_nature if opening_side=="auto" else opening_side=="debit")
                lines=[
                    {"account":account,"debit":opening_balance if is_debit else Decimal("0"),"credit":opening_balance if not is_debit else Decimal("0"),
                     "description":"الرصيد الافتتاحي"},
                    {"account":opening_account,"debit":opening_balance if not is_debit else Decimal("0"),"credit":opening_balance if is_debit else Decimal("0"),
                     "description":f"مقابل رصيد افتتاحي للحساب {account.code}"},
                ]
                opening_entry=create_posted_entry(
                    description=f"رصيد افتتاحي — {account.name}",
                    entry_date=date.today(),
                    created_by_id=current_user.id,
                    lines=lines,
                    source_type="opening_balance",
                    source_id=account.id,
                    prefix="OPEN",
                    audit=f"الرصيد الافتتاحي للحساب {account.code}: {opening_balance}",
                )
                opening_entry_number=opening_entry.number
            audit("create","account",account.id,f"{account.code}|{account.name}|opening={opening_balance}")
            db.session.commit()
            message=f"تم إنشاء الحساب {account.name} برمز {account.code}"
            if opening_entry_number: message += f" وترحيل الرصيد الافتتاحي في {opening_entry_number}"
            flash(message,"success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    auto_codes={p.id:_next_code(p) for p in parents}
    default_opening_side="debit" if (selected_parent and selected_parent.account_type in {"asset","expense"}) else "credit"
    return render_template("accounting/account_form.html",parents=parents,selected_parent=selected_parent,auto_codes=auto_codes,default_opening_side=default_opening_side)

@bp.route("/accounts/<int:account_id>/edit",methods=["GET","POST"])
@permission_required("accounting.manage")
def account_edit(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key:
        flash("الحساب النظامي محمي ولا يمكن تغيير بنيته","warning")
    if request.method=="POST":
        try:
            if account.system_key: raise ValueError("لا يمكن تعديل الحسابات النظامية")
            name=request.form.get("name","").strip()
            parent=db.session.get(Account,request.form.get("parent_id",type=int))
            if not name or not parent or not parent.is_group: raise ValueError("الاسم والحساب الأب مطلوبان")
            account.name=name
            account.parent_id=parent.id
            account.active=request.form.get("active")=="1"
            account.allow_manual_posting=not account.is_group and request.form.get("allow_manual_posting")=="1"
            audit("update","account",account.id,account.code); db.session.commit(); flash("تم تحديث الحساب","success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    parents=Account.query.filter(Account.is_group.is_(True),Account.active.is_(True),Account.id!=account.id).order_by(Account.code).all()
    return render_template("accounting/account_edit.html",account=account,parents=parents)

@bp.post("/accounts/<int:account_id>/delete")
@permission_required("accounting.manage")
def account_delete(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key:
        flash("الحساب النظامي محمي ولا يمكن حذفه","warning")
        return redirect(url_for("accounting.accounts"))
    if account.children:
        flash("لا يمكن حذف حساب يحتوي على فروع. احذف الفروع أو عطّل الحساب بدلًا من ذلك","warning")
        return redirect(url_for("accounting.accounts"))
    reference=_account_references(account.id)
    if reference:
        flash(f"لا يمكن حذف الحساب لأنه مستخدم في {reference}. يمكن إيقافه بدلًا من الحذف.","warning")
        return redirect(url_for("accounting.accounts"))
    try:
        audit("delete","account",account.id,f"{account.code}|{account.name}")
        db.session.delete(account)
        db.session.commit()
        flash("تم حذف الحساب نهائيًا لأنه لم يُستخدم في أي حركة","success")
    except Exception as exc:
        db.session.rollback()
        flash(f"تعذر حذف الحساب بأمان: {exc}","danger")
    return redirect(url_for("accounting.accounts"))

@bp.post("/accounts/<int:account_id>/toggle")
@permission_required("accounting.manage")
def account_toggle(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key: flash("الحساب النظامي محمي","warning")
    elif account.children: flash("لا يمكن إيقاف حساب له فروع","warning")
    else:
        account.active=not account.active; audit("toggle","account",account.id,str(account.active)); db.session.commit()
    return redirect(url_for("accounting.accounts"))

@bp.get("/journal")
@permission_required("accounting.view")
def journal():
    source=request.args.get("source","").strip()
    query=request.args.get("q","").strip()
    sort=request.args.get("sort","latest")

    q=JournalEntry.query
    if source:
        q=q.filter(JournalEntry.source_type==source)
    if query:
        like=f"%{query}%"
        q=q.filter((JournalEntry.number.ilike(like)) | (JournalEntry.description.ilike(like)))

    if sort=="oldest":
        q=q.order_by(JournalEntry.entry_date.asc(),JournalEntry.id.asc())
    elif sort=="highest":
        rows=q.all()
        rows.sort(key=lambda e:e.totals()[0],reverse=True)
        entries=rows[:500]
    elif sort=="lowest":
        rows=q.all()
        rows.sort(key=lambda e:e.totals()[0])
        entries=rows[:500]
    else:
        q=q.order_by(JournalEntry.entry_date.desc(),JournalEntry.id.desc())
        entries=q.limit(500).all()

    if sort not in {"highest","lowest"}:
        entries=entries[:500]

    source_labels={
        "voucher":"سند",
        "expense":"مصروف",
        "settlement":"تسوية",
        "payroll":"رواتب",
        "rent":"إيجار",
        "rent_payment":"تحصيل إيجار",
        "salary_payment":"صرف راتب",
        "gate":"البوابة",
        "manual":"قيد يدوي",
        "reverse":"قيد عكسي",
        "opening_balance":"رصيد افتتاحي",
    }
    return render_template("accounting/journal.html",
        entries=entries,source=source,query=query,sort=sort,source_labels=source_labels)

@bp.get("/journal/<int:entry_id>")
@permission_required("accounting.view")
def journal_detail(entry_id):
    return render_template("accounting/journal_detail.html",entry=db.session.get(JournalEntry,entry_id),can_reverse=can("accounting.post"))

@bp.post("/journal/<int:entry_id>/reverse")
@permission_required("accounting.post")
def reverse(entry_id):
    try:
        e=db.session.get(JournalEntry,entry_id)
        r=reverse_entry(e,current_user.id,request.form.get("reason","تصحيح"))
        audit("reverse_journal","journal_entry",e.id,r.number); db.session.commit(); flash(f"تم عكس القيد إلى {r.number}","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("accounting.journal_detail",entry_id=entry_id))
