from flask import Blueprint,render_template
from ..models import Agent,Client,Vehicle
from ..permissions import permission_required

bp=Blueprint("master_data",__name__)

@bp.get("/agents")
@permission_required("agents.view")
def agents():
    return render_template("master_data/agents.html",agents=Agent.query.order_by(Agent.name).all())

@bp.get("/clients")
@permission_required("clients.view")
def clients():
    return render_template("master_data/clients.html",clients=Client.query.order_by(Client.name).all())

@bp.get("/vehicles")
@permission_required("vehicles.view")
def vehicles():
    return render_template("master_data/vehicles.html",vehicles=Vehicle.query.order_by(Vehicle.updated_at.desc()).all())
