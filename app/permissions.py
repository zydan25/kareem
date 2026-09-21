from functools import wraps
from flask import abort, g
from flask_login import current_user, login_required
from sqlalchemy import select
from .extensions import db
from .models import Permission, UserPermission

PERMISSIONS=[
("dashboard.view","عرض لوحة التحكم","لوحة التحكم"),
("collector.view","عرض التحصيل","البوابة"),
("collector.post","تسجيل حركات البوابة","البوابة"),
("collector.settle","طلب إخلاء عهدة","العهد"),
("collector.approve_settlement","اعتماد إخلاء العهدة","العهد"),
("agents.view","عرض الوكلاء","البيانات"),("agents.manage","إدارة الوكلاء","البيانات"),
("clients.view","عرض العملاء","البيانات"),("clients.manage","إدارة العملاء","البيانات"),
("vehicles.view","عرض المركبات","البيانات"),("vehicles.manage","إدارة المركبات","البيانات"),
("employees.view","عرض الموظفين","الموارد البشرية"),("employees.manage","إدارة الموظفين","الموارد البشرية"),
("users.manage","إدارة المستخدمين","الموارد البشرية"),("permissions.manage","إدارة الصلاحيات","الموارد البشرية"),
("accounting.view","عرض المحاسبة","المحاسبة"),("accounting.post","ترحيل قيود يدوية","المحاسبة"),("vouchers.post","إصدار السندات","المحاسبة"),
("leases.view","عرض الإيجارات","الإيجارات"),("leases.manage","إدارة الإيجارات","الإيجارات"),("leases.pay","تحصيل الإيجارات","الإيجارات"),
("payroll.view","عرض الرواتب","الرواتب"),("payroll.manage","إعداد وترحيل الرواتب","الرواتب"),("payroll.pay","صرف الرواتب","الرواتب"),
("reports.view","عرض التقارير","التقارير"),("reports.export","طباعة وتصدير التقارير","التقارير"),
("settings.view","عرض الإعدادات","الإعدادات"),("settings.manage","إدارة الإعدادات","الإعدادات"),
("audit.view","عرض سجل التدقيق","الرقابة")]
ROLE_DEFAULTS={
"admin":{"*"},
"manager":{p[0] for p in PERMISSIONS},
"accountant":{"dashboard.view","accounting.view","accounting.post","vouchers.post","leases.view","leases.manage","leases.pay","payroll.view","payroll.manage","payroll.pay","reports.view","reports.export","audit.view"},
"collector":{"dashboard.view","collector.view","collector.post","collector.settle","clients.view","vehicles.view"},
"auditor":{"dashboard.view","accounting.view","reports.view","reports.export","audit.view"}}

def _permission_cache():
    cached=getattr(g,"_permission_cache",None)
    if cached is not None:
        return cached
    defaults=ROLE_DEFAULTS.get(current_user.role,set())
    if "*" in defaults:
        cached={"*"}
    else:
        cached=set(defaults)
        rows=db.session.execute(
            select(Permission.key,UserPermission.granted)
            .join(UserPermission,UserPermission.permission_id==Permission.id)
            .where(UserPermission.user_id==current_user.id,Permission.active.is_(True))
        ).all()
        for key,granted in rows:
            if granted: cached.add(key)
            else: cached.discard(key)
    g._permission_cache=cached
    return cached

def can(permission):
    if not current_user.is_authenticated or not current_user.active:
        return False
    cached=_permission_cache()
    return "*" in cached or permission in cached

def permission_required(permission):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*args,**kwargs):
            if not can(permission): abort(403)
            return view(*args,**kwargs)
        return wrapped
    return deco

def seed_permissions():
    for key,name,group in PERMISSIONS:
        if not db.session.query(Permission).filter_by(key=key).first():
            db.session.add(Permission(key=key,name=name,group_name=group,active=True))
    db.session.flush()
