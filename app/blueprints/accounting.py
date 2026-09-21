from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import Account, JournalEntry
from ..permissions import can, permission_required
from ..services.accounting import create_posted_entry, reverse_entry
from ..services.audit import audit

bp=Blueprint("accounting",__name__,url_prefix="/accounting")

@bp.get("/accounts")
@permission_required("accounting.view")
def accounts():
    return render_template("accounting/accounts.html",accounts=Account.query.order_by(Account.code).all(),can_manage=can("accounting.post"))

@bp.route("/accounts/new",methods=["GET","POST"])
@permission_required("accounting.post")
def account_new():
    parents=Account.query.filter_by(is_group=True,active=True).order_by(Account.code).all()
    if request.method=="POST":
        try:
            parent=db.session.get(Account,int(request.form["parent_id"]))
            if not parent or not parent.is_group: raise ValueError("الحساب الأب يجب أن يكون مجموعة")
            is_group=request.form.get("is_group")=="1"
            account=Account(code=request.form["code"].strip(),name=request.form["name"].strip(),account_type=parent.account_type,
                parent_id=parent.id,is_group=is_group,active=True,allow_manual_posting=not is_group)
            db.session.add(account); db.session.flush()
            audit("create","account",account.id,account.code); db.session.commit(); flash("تم إنشاء الحساب","success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("accounting/account_form.html",parents=parents)

@bp.get("/journal")
@permission_required("accounting.view")
def journal():
    entries=JournalEntry.query.order_by(JournalEntry.entry_date.desc(),JournalEntry.id.desc()).limit(250).all()
    return render_template("accounting/journal.html",entries=entries)

@bp.get("/journal/<int:entry_id>")
@permission_required("accounting.view")
def journal_detail(entry_id):
    return render_template("accounting/journal_detail.html",entry=db.session.get(JournalEntry,entry_id))

@bp.post("/journal/<int:entry_id>/reverse")
@permission_required("accounting.post")
def reverse(entry_id):
    entry=db.session.get(JournalEntry,entry_id)
    try:
        reverse_entry(entry,current_user.id,request.form.get("reason","تصحيح القيد"))
        audit("reverse","journal_entry",entry.id,entry.number)
        db.session.commit(); flash("تم إنشاء القيد العكسي","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("accounting.journal_detail",entry_id=entry.id))
