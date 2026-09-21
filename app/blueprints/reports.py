from datetime import datetime,timedelta,timezone
from flask import Blueprint,render_template
from sqlalchemy import func
from ..extensions import db
from ..models import GateTransaction,User,JournalLine,Account
from ..permissions import permission_required

bp=Blueprint("reports",__name__,url_prefix="/reports")

@bp.get("/collectors")
@permission_required("reports.view")
def collectors():
    today=datetime.now(timezone.utc).date()
    start=datetime.combine(today,datetime.min.time(),tzinfo=timezone.utc); end=start+timedelta(days=1)
    rows=(db.session.query(User.id,User.full_name,User.role,func.count(GateTransaction.id).label("count"),
        func.coalesce(func.sum(GateTransaction.amount),0).label("total"))
        .outerjoin(GateTransaction,(GateTransaction.collector_id==User.id)&(GateTransaction.transaction_date>=start)&(GateTransaction.transaction_date<end))
        .filter(User.role.in_(["collector","manager"])).group_by(User.id,User.full_name,User.role)
        .order_by(func.sum(GateTransaction.amount).desc()).all())
    return render_template("reports/collectors.html",rows=rows,today=today)

@bp.get("/account/<int:account_id>")
@permission_required("reports.view")
def account_statement(account_id):
    account=db.session.get(Account,account_id)
    lines=(db.session.query(JournalLine).join(JournalLine.entry).filter(JournalLine.account_id==account_id,
        JournalLine.entry.has(status="posted")).order_by(JournalLine.id.desc()).limit(300).all())
    return render_template("reports/account_statement.html",account=account,lines=lines)

@bp.get("/trial-balance")
@permission_required("reports.view")
def trial_balance():
    rows=(db.session.query(Account.id,Account.code,Account.name,Account.account_type,
        func.coalesce(func.sum(JournalLine.debit),0).label("debit"),
        func.coalesce(func.sum(JournalLine.credit),0).label("credit"))
        .outerjoin(JournalLine,JournalLine.account_id==Account.id)
        .outerjoin(JournalLine.entry).filter(Account.is_group.is_(False))
        .filter((JournalLine.entry_id.is_(None))|(JournalLine.entry.has(status="posted")))
        .group_by(Account.id,Account.code,Account.name,Account.account_type).order_by(Account.code).all())
    return render_template("reports/trial_balance.html",rows=rows)
