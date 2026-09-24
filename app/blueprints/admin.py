from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import Employee, Permission, User, UserPermission, Role
from ..permissions import can, permission_required
from ..services.audit import audit
from ..services.accounts import ensure_employee_account, ensure_employee_payroll_account

ROLE_LABELS={"admin":"مدير النظام","manager":"مدير","accountant":"محاسب","collector":"متحصل","auditor":"مراجع"}

bp=Blueprint("admin",__name__,url_prefix="/admin")

@bp.get("/users")
@permission_required("users.manage")
def users():
    rows=User.query.order_by(User.active.desc(),User.full_name).all()
    return render_template("admin/users.html",users=rows,role_labels=ROLE_LABELS)

@bp.route("/users/<int:user_id>/edit",methods=["GET","POST"])
@permission_required("users.manage")
def edit_user(user_id):
    u=db.session.get(User,user_id)
    if not u: return ("غير موجود",404)
    employees=Employee.query.filter_by(active=True).order_by(Employee.full_name).all()
    if request.method=="POST":
        try:
            username=request.form["username"].strip()
            other=User.query.filter(User.username==username,User.id!=u.id).first()
            if other: raise ValueError("اسم المستخدم مستخدم مسبقًا")
            u.username=username; u.full_name=request.form["full_name"].strip(); u.phone=request.form.get("phone")
            u.role=request.form.get("role","collector"); u.employee_id=int(request.form["employee_id"]) if request.form.get("employee_id") else None
            if request.form.get("password"): u.set_password(request.form["password"])
            if u.employee:
                u.employee.full_name=u.full_name
                u.employee.phone=u.phone
                u.employee.active=u.active
                u.employee.job_title={"admin":"مدير النظام","manager":"مدير","collector":"متحصل","accountant":"محاسب","auditor":"مراجع"}.get(u.role,u.employee.job_title or "موظف")
                ensure_employee_account(u.employee)
                ensure_employee_payroll_account(u.employee)
            else:
                last=Employee.query.order_by(Employee.id.desc()).first()
                next_id=(last.id+1) if last else 1
                emp=Employee(code=f"EMP-{next_id:05d}",full_name=u.full_name,phone=u.phone,
                    job_title={"admin":"مدير النظام","manager":"مدير","collector":"متحصل","accountant":"محاسب","auditor":"مراجع"}.get(u.role,"موظف"),
                    monthly_salary=0,hire_date=date.today(),active=u.active)
                db.session.add(emp); db.session.flush(); u.employee_id=emp.id
                ensure_employee_account(emp); ensure_employee_payroll_account(emp)
            audit("update","user",u.id,u.username); db.session.commit(); flash("تم تحديث المستخدم وملفه المالي","success"); return redirect(url_for("admin.users"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("admin/user_form.html",user=u,employees=employees,roles=[r.value for r in Role],role_labels=ROLE_LABELS)

@bp.post("/users/<int:user_id>/toggle")
@permission_required("users.manage")
def toggle_user(user_id):
    u=db.session.get(User,user_id)
    if not u: return ("غير موجود",404)
    if u.id==current_user.id: flash("لا يمكن إيقاف المستخدم الحالي","warning"); return redirect(url_for("admin.users"))
    u.active=not u.active; audit("toggle","user",u.id,u.username); db.session.commit(); return redirect(url_for("admin.users"))

@bp.route("/users/<int:user_id>/permissions",methods=["GET","POST"])
@permission_required("permissions.manage")
def permissions(user_id):
    user=db.session.get(User,user_id)
    if not user: return ("غير موجود",404)
    perms=Permission.query.filter_by(active=True).order_by(Permission.group_name,Permission.name).all()
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
            audit("update_permissions","user",user.id,user.username); db.session.commit(); flash("تم حفظ الصلاحيات التفصيلية","success")
            return redirect(url_for("admin.permissions",user_id=user.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    grants={x.permission_id:x.granted for x in UserPermission.query.filter_by(user_id=user.id).all()}
    role_defaults=__import__("app.permissions",fromlist=["ROLE_DEFAULTS"]).ROLE_DEFAULTS.get(user.role,set())
    effective={}
    for p in perms:
        if user.role in {"admin","manager"}:
            effective[p.key]=True
        elif p.key in grants:
            effective[p.key]=bool(grants[p.id])
        else:
            effective[p.key]=p.key in role_defaults
    role_locked=user.role in {"admin","manager"}
    return render_template("admin/permissions.html",user=user,permissions=perms,grants=grants,
                           effective=effective,role_defaults=role_defaults,role_locked=role_locked,
                           role_labels=ROLE_LABELS)

@bp.get("/guide")
@permission_required("users.manage")
def guide():
    return render_template("admin/guide.html", role_labels=ROLE_LABELS)

@bp.get("/guide")
@permission_required("users.manage")
def guide():
    return render_template("admin/guide.html", role_labels=ROLE_LABELS)

@bp.get("/audit")
@permission_required("audit.view")
def audit_logs():
    from ..models import AuditLog
    rows=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("admin/audit.html",rows=rows)
