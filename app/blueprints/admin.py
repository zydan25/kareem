from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import Permission, User, UserPermission
from ..permissions import permission_required
from ..services.audit import audit

bp=Blueprint("admin",__name__,url_prefix="/admin")

@bp.route("/users/<int:user_id>/permissions",methods=["GET","POST"])
@permission_required("permissions.manage")
def permissions(user_id):
    user=db.session.get(User,user_id); perms=Permission.query.filter_by(active=True).order_by(Permission.group_name,Permission.name).all()
    grants={x.permission_id:x.granted for x in UserPermission.query.filter_by(user_id=user.id).all()}
    if request.method=="POST":
        try:
            selected={int(x) for x in request.form.getlist("permission_ids")}
            for p in perms:
                row=UserPermission.query.filter_by(user_id=user.id,permission_id=p.id).first()
                if p.id in selected:
                    if not row: row=UserPermission(user_id=user.id,permission_id=p.id); db.session.add(row)
                    row.granted=True
                elif row:
                    row.granted=False
            audit("update_permissions","user",user.id,user.username)
            db.session.commit(); flash("تم حفظ الصلاحيات","success")
            return redirect(url_for("admin.permissions",user_id=user.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    grants={x.permission_id:x.granted for x in UserPermission.query.filter_by(user_id=user.id).all()}
    return render_template("admin/permissions.html",user=user,permissions=perms,grants=grants)

@bp.get("/users")
@permission_required("users.manage")
def users():
    return render_template("admin/users.html",users=User.query.order_by(User.full_name).all())
