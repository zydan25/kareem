from flask import Blueprint, flash, redirect, render_template, request, url_for
from ..extensions import db
from ..models import Setting, VehicleType
from ..permissions import can, permission_required
from ..services.audit import audit

bp=Blueprint("settings",__name__,url_prefix="/settings")

@bp.route("",methods=["GET","POST"])
@permission_required("settings.view")
def index():
    types=VehicleType.query.order_by(VehicleType.active.desc(),VehicleType.name).all()
    settings=Setting.query.order_by(Setting.key).all()
    if request.method=="POST":
        if not can("settings.manage"): return ("Forbidden",403)
        try:
            name=request.form.get("vehicle_type_name","").strip()
            if name and not VehicleType.query.filter_by(name=name).first():
                row=VehicleType(name=name,is_system=False,active=True); db.session.add(row); db.session.flush()
                audit("create","vehicle_type",row.id,row.name)
            for key in request.form:
                if key.startswith("setting_"):
                    skey=key[8:]; value=request.form.get(key)
                    row=Setting.query.filter_by(key=skey).first()
                    if not row: row=Setting(key=skey); db.session.add(row)
                    row.value=value
            db.session.commit(); flash("تم حفظ الإعدادات","success")
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("settings/index.html",vehicle_types=types,settings=settings,can_manage=can("settings.manage"))

@bp.post("/vehicle-types/<int:type_id>/toggle")
@permission_required("settings.manage")
def toggle_type(type_id):
    row=db.session.get(VehicleType,type_id)
    if row.is_system:
        flash("لا يمكن تعطيل نوع نظامي","warning")
    else:
        row.active=not row.active; audit("toggle","vehicle_type",row.id,row.name); db.session.commit()
    return redirect(url_for("settings.index"))
