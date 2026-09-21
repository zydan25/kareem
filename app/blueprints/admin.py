from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import Employee, Permission, User, UserPermission, Role
from ..permissions import can, permission_required
from ..services.audit import audit

bp=Blueprint("admin",__name__,url_prefix="/admin")

@bp.route("/users",methods=["GET","POST"])
@permission_required("users.manage")
def users():
    employees=Employee.query.filter_by(active=True).order_by(Employee.full_name).all()
    rows=User.query.order_by(User.active.desc(),User.full_name).all()
    if request.method=="POST":
        try:
            u=User(username=request.form["username"].strip(),full_name=request.form["full_name"].strip(),
                phone=request.form.get("phone"),role=request.form.get("role","collector"),
                employee_id=int(request.form["employee_id"]) if request.form.get("employee_id") else None,active=True)
            u.set_password(request.form["password"])
            db.session.add(u); audit("create","user",None,u.username); db.session.commit(); flash("تم إنشاء المستخدم","success")
            return redirect(url_for("admin.users"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("admin/users.html",users=rows,employees=employees,roles=[r.value for r in Role],can_manage=True)

@bp.route("/users/<int:user_id>/edit",methods=["GET","POST"])
@permission_required("users.manage")
def edit_user(user_id):
    u=db.session.get(User,user_id); employees=Employee.query.filter_by(active=True).order_by(Employee.full_name).all()
    if request.method=="POST":
        try:
            u.username=request.form["username"].strip(); u.full_name=request.form["full_name"].strip(); u.phone=request.form.get("phone")
            u.role=request.form.get("role","collector"); u.employee_id=int(request.form["employee_id"]) if request.form.get("employee_id") else None
            if request.form.get("password"): u.set_password(request.form["password"])
            audit("update","user",u.id,u.username); db.session.commit(); flash("تم تحديث المستخدم","success"); return redirect(url_for("admin.users"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("admin/user_form.html",user=u,employees=employees,roles=[r.value for r in Role])

@bp.post("/users/<int:user_id>/toggle")
@permission_required("users.manage")
def toggle_user(user_id):
    u=db.session.get(User,user_id)
    if u.id==current_user.id: flash("لا يمكن إيقاف المستخدم الحالي","warning"); return redirect(url_for("admin.users"))
    u.active=not u.active; audit("toggle","user",u.id,u.username); db.session.commit(); return redirect(url_for("admin.users"))

@bp.route("/users/<int:user_id>/permissions",methods=["GET","POST"])
@permission_required("permissions.manage")
def permissions(user_id):
    user=db.session.get(User,user_id); perms=Permission.query.filter_by(active=True).order_by(Permission.group_name,Permission.name).all()
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
            audit("update_permissions","user",user.id,user.username); db.session.commit(); flash("تم حفظ الصلاحيات","success")
            return redirect(url_for("admin.permissions",user_id=user.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    grants={x.permission_id:x.granted for x in UserPermission.query.filter_by(user_id=user.id).all()}
    return render_template("admin/permissions.html",user=user,permissions=perms,grants=grants)


@bp.get("/audit")
@permission_required("audit.view")
def audit_logs():
    from ..models import AuditLog
    rows=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("admin/audit.html",rows=rows)
