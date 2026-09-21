from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Account, JournalEntry
from ..permissions import can, permission_required
from ..services.accounting import account_balance, create_posted_entry, reverse_entry
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
            result.append({"account":account,"depth":depth,"children":build(account.id,depth+1)})
        return result
    return build(None)

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
                           account_type_labels=ACCOUNT_TYPE_LABELS,balance_func=account_balance,can_manage=can("accounting.post"))

@bp.route("/accounts/new",methods=["GET","POST"])
@permission_required("accounting.post")
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
            code=_next_code(parent)
            while Account.query.filter_by(code=code).first():
                code=f"{parent.code}{int(code[len(parent.code):])+1:02d}"
            account=Account(code=code,name=name,account_type=parent.account_type,parent_id=parent.id,is_group=is_group,
                            active=True,allow_manual_posting=not is_group)
            db.session.add(account); db.session.flush()
            audit("create","account",account.id,f"{account.code}|{account.name}")
            db.session.commit(); flash(f"تم إنشاء الحساب {account.name} برمز {account.code}","success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("accounting/account_form.html",parents=parents,selected_parent=selected_parent,auto_code=_next_code(selected_parent) if selected_parent else "—")

@bp.route("/accounts/<int:account_id>/edit",methods=["GET","POST"])
@permission_required("accounting.post")
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

@bp.post("/accounts/<int:account_id>/toggle")
@permission_required("accounting.post")
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
