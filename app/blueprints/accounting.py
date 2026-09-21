from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..models import Account, JournalEntry, JournalLine
from ..permissions import can, permission_required
from ..services.accounting import account_balance, create_posted_entry, reverse_entry
from ..services.audit import audit

bp=Blueprint("accounting",__name__,url_prefix="/accounting")

ACCOUNT_TYPE_LABELS={"asset":"أصول","liability":"خصوم","equity":"حقوق ملكية","revenue":"إيرادات","expense":"مصروفات","memo":"مذكرة"}

def _depth(account):
    depth=0
    seen=set()
    parent=account.parent
    while parent and parent.id not in seen:
        seen.add(parent.id); depth+=1; parent=parent.parent
    return depth

@bp.get("/accounts")
@permission_required("accounting.view")
def accounts():
    all_accounts=Account.query.order_by(Account.code).all()
    rows=[{"account":a,"depth":_depth(a),"balance":account_balance(a.id) if not a.is_group else None} for a in all_accounts]
    return render_template("accounting/accounts.html",rows=rows,account_type_labels=ACCOUNT_TYPE_LABELS,
                           can_manage=can("accounting.post"))

@bp.route("/accounts/new",methods=["GET","POST"])
@permission_required("accounting.post")
def account_new():
    parents=Account.query.filter_by(is_group=True,active=True).order_by(Account.code).all()
    if request.method=="POST":
        try:
            parent=db.session.get(Account,int(request.form["parent_id"]))
            if not parent or not parent.is_group: raise ValueError("الحساب الأب يجب أن يكون مجموعة")
            code=request.form["code"].strip()
            if Account.query.filter_by(code=code).first(): raise ValueError("كود الحساب مستخدم مسبقًا")
            is_group=request.form.get("is_group")=="1"
            account=Account(code=code,name=request.form["name"].strip(),account_type=parent.account_type,
                parent_id=parent.id,is_group=is_group,active=True,allow_manual_posting=not is_group)
            db.session.add(account); db.session.flush()
            audit("create","account",account.id,account.code); db.session.commit(); flash("تم إنشاء الحساب","success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("accounting/account_form.html",parents=parents)

@bp.route("/accounts/<int:account_id>/edit",methods=["GET","POST"])
@permission_required("accounting.post")
def account_edit(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key: flash("الحساب النظامي محمي ولا يمكن تعديل كوده أو بنيته","warning")
    if request.method=="POST":
        try:
            if account.system_key: raise ValueError("لا يمكن تعديل الحسابات النظامية")
            code=request.form["code"].strip()
            other=Account.query.filter(Account.code==code,Account.id!=account.id).first()
            if other: raise ValueError("كود الحساب مستخدم مسبقًا")
            parent=db.session.get(Account,int(request.form["parent_id"]))
            if not parent or not parent.is_group: raise ValueError("الحساب الأب يجب أن يكون مجموعة")
            account.code=code; account.name=request.form["name"].strip(); account.parent_id=parent.id
            account.active=request.form.get("active")=="1"
            if not account.is_group: account.allow_manual_posting=request.form.get("allow_manual_posting")=="1"
            audit("update","account",account.id,account.code); db.session.commit(); flash("تم تحديث الحساب","success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    parents=Account.query.filter(Account.is_group.is_(True),Account.active.is_(True),Account.id!=account.id).order_by(Account.code).all()
    return render_template("accounting/account_edit.html",account=account,parents=parents)

@bp.post("/accounts/<int:account_id>/toggle")
@permission_required("accounting.post")
def account_toggle(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key: flash("الحساب النظامي محمي","warning")
    elif account.children: flash("لا يمكن إيقاف حساب له فروع ضمن هذه الشاشة","warning")
    else:
        account.active=not account.active; audit("toggle","account",account.id,str(account.active)); db.session.commit()
    return redirect(url_for("accounting.accounts"))

@bp.get("/journal")
@permission_required("accounting.view")
def journal():
    entries=JournalEntry.query.order_by(JournalEntry.entry_date.desc(),JournalEntry.id.desc()).limit(500).all()
    return render_template("accounting/journal.html",entries=entries)

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
