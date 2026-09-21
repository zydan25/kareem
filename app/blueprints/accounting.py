from flask import Blueprint,render_template
from ..models import Account,JournalEntry
from ..permissions import permission_required

bp=Blueprint("accounting",__name__,url_prefix="/accounting")

@bp.get("/accounts")
@permission_required("accounting.view")
def accounts():
    return render_template("accounting/accounts.html",accounts=Account.query.order_by(Account.code).all())

@bp.get("/journal")
@permission_required("accounting.view")
def journal():
    entries=JournalEntry.query.order_by(JournalEntry.entry_date.desc(),JournalEntry.id.desc()).limit(100).all()
    return render_template("accounting/journal.html",entries=entries)
