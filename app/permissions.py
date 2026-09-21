from functools import wraps
from flask import abort
from flask_login import current_user, login_required

ROLE_PERMISSIONS = {
    "admin": {"*"},
    "manager": {
        "dashboard.view", "collector.view", "collector.post", "collector.settle",
        "agents.view", "agents.manage", "clients.view", "clients.manage",
        "vehicles.view", "vehicles.manage", "accounting.view", "accounting.post",
        "reports.view", "leases.manage", "payroll.manage", "settings.view",
    },
    "accountant": {"dashboard.view", "accounting.view", "accounting.post", "reports.view", "payroll.manage", "leases.manage"},
    "collector": {"dashboard.view", "collector.view", "collector.post", "collector.settle", "clients.view", "vehicles.view"},
    "auditor": {"dashboard.view", "accounting.view", "reports.view"},
}

def can(permission):
    if not current_user.is_authenticated or not current_user.active:
        return False
    permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    return "*" in permissions or permission in permissions

def permission_required(permission):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not can(permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return deco
