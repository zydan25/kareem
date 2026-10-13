from datetime import date, datetime, time, timedelta, timezone
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from ..extensions import db
from ..models import Employee, Permission, User, UserPermission, Role
from ..permissions import can, permission_required
from ..services.audit import audit
from ..services.accounts import ensure_employee_account, ensure_employee_cashbox, ensure_employee_payroll_account

ROLE_LABELS={"admin":"مدير النظام","manager":"مدير","accountant":"محاسب","collector":"متحصل","auditor":"مراجع"}

bp=Blueprint("admin",__name__,url_prefix="/admin")

@bp.get("/users")
@permission_required("users.manage")
def users():
    rows=User.query.order_by(User.active.desc(),User.full_name).all()
    return render_template("admin/users.html",users=rows,role_labels=ROLE_LABELS)

PRIVILEGED_ROLES={"admin","manager"}

def _active_admin_count():
    return User.query.filter_by(role=Role.ADMIN.value,active=True).count()

def _guard_privileged_user(target):
    """Only a system admin may edit manager/admin accounts."""
    if current_user.role != Role.ADMIN.value and target.role in PRIVILEGED_ROLES:
        raise ValueError("إدارة حسابات المديرين ومدير النظام متاحة لمدير النظام فقط")

@bp.route("/users/<int:user_id>/edit",methods=["GET","POST"])
@permission_required("users.manage")
def edit_user(user_id):
    u=db.session.get(User,user_id)
    if not u: return ("غير موجود",404)
    try:
        _guard_privileged_user(u)
    except ValueError as exc:
        return (str(exc),403)

    employees=Employee.query.filter_by(active=True).order_by(Employee.full_name).all()
    if request.method=="POST":
        try:
            _guard_privileged_user(u)
            username=request.form.get("username","").strip()
            full_name=request.form.get("full_name","").strip()
            requested_role=request.form.get("role","").strip()
            valid_roles={role.value for role in Role}

            if not username:
                raise ValueError("اسم المستخدم مطلوب")
            if not full_name:
                raise ValueError("الاسم الكامل مطلوب")
            if requested_role not in valid_roles:
                raise ValueError("الدور المحدد غير صالح")

            if current_user.role != Role.ADMIN.value and requested_role in PRIVILEGED_ROLES:
                raise ValueError("لا يمكنك منح صلاحية مدير أو مدير النظام؛ هذه العملية متاحة لمدير النظام فقط")
            if current_user.id==u.id and requested_role!=u.role:
                raise ValueError("لا يمكنك تغيير دور حسابك الحالي لتجنب فقدان صلاحية الإدارة")

            if u.role==Role.ADMIN.value and u.active and requested_role!=Role.ADMIN.value and _active_admin_count()<=1:
                raise ValueError("لا يمكن إزالة دور مدير النظام من آخر مدير نشط")

            other=User.query.filter(User.username==username,User.id!=u.id).first()
            if other: raise ValueError("اسم المستخدم مستخدم مسبقًا")

            old_username=u.username
            old_role=u.role
            old_employee_id=u.employee_id
            u.username=username
            u.full_name=full_name
            u.phone=(request.form.get("phone") or "").strip() or None
            u.role=requested_role
            u.employee_id=int(request.form["employee_id"]) if request.form.get("employee_id") else None
            password_changed=bool(request.form.get("password"))
            if password_changed: u.set_password(request.form["password"])

            if u.employee:
                u.employee.full_name=u.full_name
                u.employee.phone=u.phone
                u.employee.active=u.active
                u.employee.job_title={"admin":"مدير النظام","manager":"مدير","collector":"متحصل","accountant":"محاسب","auditor":"مراجع"}.get(u.role,u.employee.job_title or "موظف")
                ensure_employee_account(u.employee)
                ensure_employee_cashbox(u.employee)
                ensure_employee_payroll_account(u.employee)
            else:
                last=Employee.query.order_by(Employee.id.desc()).first()
                next_id=(last.id+1) if last else 1
                emp=Employee(code=f"EMP-{next_id:05d}",full_name=u.full_name,phone=u.phone,
                    job_title={"admin":"مدير النظام","manager":"مدير","collector":"متحصل","accountant":"محاسب","auditor":"مراجع"}.get(u.role,"موظف"),
                    monthly_salary=0,hire_date=date.today(),active=u.active)
                db.session.add(emp); db.session.flush(); u.employee_id=emp.id
                ensure_employee_account(emp); ensure_employee_cashbox(emp); ensure_employee_payroll_account(emp)

            details=f"username={old_username}->{u.username}|role={old_role}->{u.role}|employee={old_employee_id}->{u.employee_id}|password_changed={int(password_changed)}"
            audit("update_user","user",u.id,details)
            db.session.commit()
            flash("تم تحديث المستخدم وملفه المالي","success")
            return redirect(url_for("admin.users"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc),"danger")

    roles=[r.value for r in Role if current_user.role==Role.ADMIN.value or r.value not in PRIVILEGED_ROLES]
    if current_user.id==u.id:
        roles=[u.role]
    return render_template("admin/user_form.html",user=u,employees=employees,roles=roles,role_labels=ROLE_LABELS)

@bp.post("/users/<int:user_id>/toggle")
@permission_required("users.manage")
def toggle_user(user_id):
    u=db.session.get(User,user_id)
    if not u: return ("غير موجود",404)
    if u.id==current_user.id:
        flash("لا يمكن إيقاف المستخدم الحالي","warning")
        return redirect(url_for("admin.users"))
    if current_user.role != Role.ADMIN.value and u.role in PRIVILEGED_ROLES:
        flash("إدارة حسابات المديرين ومدير النظام متاحة لمدير النظام فقط","danger")
        return redirect(url_for("admin.users"))
    if u.role==Role.ADMIN.value and u.active and _active_admin_count()<=1:
        flash("لا يمكن إيقاف آخر مدير نظام نشط","danger")
        return redirect(url_for("admin.users"))
    u.active=not u.active
    audit("toggle_user","user",u.id,f"username={u.username}|active={int(u.active)}|role={u.role}")
    db.session.commit()
    return redirect(url_for("admin.users"))

@bp.route("/users/<int:user_id>/permissions",methods=["GET","POST"])
@permission_required("permissions.manage")
def permissions(user_id):
    user=db.session.get(User,user_id)
    if not user: return ("غير موجود",404)
    if current_user.role != Role.ADMIN.value and user.role in PRIVILEGED_ROLES:
        return ("إدارة صلاحيات المديرين ومدير النظام متاحة لمدير النظام فقط",403)
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

# Human-readable labels for audit events already stored in the database.
AUDIT_ACTION_LABELS = {
    "create": "إنشاء سجل",
    "update": "تعديل بيانات",
    "delete": "حذف سجل",
    "toggle": "تغيير الحالة",
    "activate": "تفعيل",
    "deactivate": "إيقاف",
    "update_user": "تحديث حساب مستخدم",
    "toggle_user": "تغيير حالة مستخدم",
    "update_permissions": "تحديث الصلاحيات",
    "gate_entry": "تسجيل دخول مركبة",
    "gate_exit": "تسجيل خروج مركبة",
    "reverse_journal": "عكس قيد محاسبي",
    "edit_voucher": "تعديل سند",
    "create_voucher": "إصدار سند",
    "reverse_voucher": "عكس سند",
    "create_expense": "تسجيل مصروف",
    "request_settlement": "طلب تسوية صندوق",
    "approve_settlement": "اعتماد تسوية صندوق",
    "open_shift": "فتح وردية",
    "auto_request_shift_settlement": "طلب تسوية عند إغلاق الوردية",
    "close_shift": "إغلاق وردية",
    "create_lease": "إنشاء عقد إيجار",
    "charge_rent": "إثبات استحقاق إيجار",
    "pay_rent": "تحصيل إيجار",
    "create_payroll": "إنشاء مسير رواتب",
    "post_payroll": "ترحيل مسير رواتب",
    "update_payroll_lines": "تعديل بنود الرواتب",
    "pay_salary": "صرف راتب",
}
AUDIT_ENTITY_LABELS = {
    "account": "حساب",
    "journal_entry": "قيد يومية",
    "user": "مستخدم",
    "gate_transaction": "حركة بوابة",
    "agent": "وكيل",
    "client": "عميل",
    "vehicle": "مركبة",
    "vehicle_type": "نوع مركبة",
    "employee": "موظف",
    "employee_fine": "غرامة موظف",
    "employee_schedule": "جدول دوام موظف",
    "voucher": "سند",
    "expense": "مصروف",
    "settlement": "تسوية صندوق",
    "shift": "وردية",
    "agent_lease": "عقد إيجار",
    "agent_rent": "استحقاق إيجار",
    "payroll_run": "مسير رواتب",
}


@bp.get("/audit")
@permission_required("audit.view")
def audit_logs():
    from ..models import AuditLog

    search = request.args.get("q", "").strip()[:120]
    action = request.args.get("action", "").strip()[:80]
    entity_type = request.args.get("entity_type", "").strip()[:80]
    user_id_value = request.args.get("user_id", "").strip()
    start_value = request.args.get("start_date", "").strip()[:10]
    end_value = request.args.get("end_date", "").strip()[:10]
    filter_error = None

    query = AuditLog.query.outerjoin(User, AuditLog.user_id == User.id)

    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)

    if user_id_value:
        try:
            parsed_user_id = int(user_id_value)
            if parsed_user_id > 0:
                query = query.filter(
                    db.or_(
                        AuditLog.user_id == parsed_user_id,
                        AuditLog.actor_username == db.session.query(User.username).filter(User.id == parsed_user_id).scalar_subquery(),
                    )
                )
        except (TypeError, ValueError):
            filter_error = "معرّف المستخدم المحدد غير صالح."

    start_day = end_day = None
    if start_value:
        try:
            start_day = date.fromisoformat(start_value)
        except ValueError:
            filter_error = "تاريخ البداية غير صالح؛ استخدم تاريخًا صحيحًا."
    if end_value:
        try:
            end_day = date.fromisoformat(end_value)
        except ValueError:
            filter_error = "تاريخ النهاية غير صالح؛ استخدم تاريخًا صحيحًا."
    if start_day and end_day and start_day > end_day:
        filter_error = "تاريخ البداية يجب ألا يتجاوز تاريخ النهاية."
        start_day = end_day = None

    if start_day:
        query = query.filter(
            AuditLog.created_at >= datetime.combine(start_day, time.min, tzinfo=timezone.utc)
        )
    if end_day:
        query = query.filter(
            AuditLog.created_at < datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )

    if search:
        pattern = f"%{search}%"
        search_conditions = [
            AuditLog.action.ilike(pattern),
            AuditLog.entity_type.ilike(pattern),
            AuditLog.details.ilike(pattern),
            AuditLog.ip_address.ilike(pattern),
            AuditLog.request_path.ilike(pattern),
            AuditLog.user_agent.ilike(pattern),
            AuditLog.actor_username.ilike(pattern),
            AuditLog.actor_name.ilike(pattern),
            User.username.ilike(pattern),
            User.full_name.ilike(pattern),
        ]
        if search.isdigit():
            search_conditions.append(AuditLog.entity_id == int(search))
        query = query.filter(db.or_(*search_conditions))

    try:
        per_page = int(request.args.get("per_page", "50"))
    except (TypeError, ValueError):
        per_page = 50
    if per_page not in {25, 50, 100}:
        per_page = 50
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1

    total_count = query.order_by(None).count()
    pages = max(1, (total_count + per_page - 1) // per_page)
    page = min(page, pages)
    rows = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    action_values = [
        value for (value,) in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
    ]
    entity_values = [
        value for (value,) in db.session.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()
    ]
    users = User.query.order_by(User.full_name.asc(), User.id.asc()).all()
    filter_args = {
        key: value
        for key, value in request.args.items()
        if key in {"q", "action", "entity_type", "user_id", "start_date", "end_date", "per_page"} and value
    }
    page_numbers = range(max(1, page - 2), min(pages, page + 2) + 1)
    first_result = ((page - 1) * per_page + 1) if total_count else 0
    last_result = min(page * per_page, total_count)

    return render_template(
        "admin/audit.html",
        rows=rows,
        search=search,
        action=action,
        entity_type=entity_type,
        user_id_value=user_id_value,
        start_value=start_value,
        end_value=end_value,
        per_page=per_page,
        page=page,
        pages=pages,
        page_numbers=page_numbers,
        total_count=total_count,
        first_result=first_result,
        last_result=last_result,
        filter_args=filter_args,
        filter_error=filter_error,
        action_values=action_values,
        entity_values=entity_values,
        users=users,
        action_labels=AUDIT_ACTION_LABELS,
        entity_labels=AUDIT_ENTITY_LABELS,
    )
