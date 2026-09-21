from flask import Blueprint,render_template
from ..models import VehicleType,User
from ..permissions import permission_required

bp=Blueprint("settings",__name__,url_prefix="/settings")

@bp.get("")
@permission_required("settings.view")
def index():
    return render_template("settings/index.html",vehicle_types=VehicleType.query.order_by(VehicleType.name).all(),
        users=User.query.order_by(User.full_name).all())
