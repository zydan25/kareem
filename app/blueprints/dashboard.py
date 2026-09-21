from datetime import datetime,timedelta,timezone
from flask import Blueprint,render_template
from sqlalchemy import func
from ..extensions import db
from ..models import GateTransaction,Agent,User,Vehicle
from ..permissions import permission_required

bp=Blueprint("dashboard",__name__)

@bp.route("/")
@bp.route("/dashboard")
@permission_required("dashboard.view")
def index():
    today=datetime.now(timezone.utc).date()
    start=datetime.combine(today,datetime.min.time(),tzinfo=timezone.utc); end=start+timedelta(days=1)
    total=db.session.query(func.coalesce(func.sum(GateTransaction.amount),0)).filter(GateTransaction.transaction_date>=start,GateTransaction.transaction_date<end).scalar()
    count=db.session.query(func.count(GateTransaction.id)).filter(GateTransaction.transaction_date>=start,GateTransaction.transaction_date<end).scalar()
    worked=db.session.query(GateTransaction.collector_id).filter(GateTransaction.transaction_date>=start,GateTransaction.transaction_date<end,
        GateTransaction.counted_for_work.is_(True)).distinct().count()
    return render_template("dashboard/index.html",today=today,total=total,count=count,worked=worked,
        agents=db.session.query(Agent).filter_by(active=True).count(),vehicles=db.session.query(Vehicle).filter_by(active=True).count(),
        employees=db.session.query(User).filter_by(active=True).count())
