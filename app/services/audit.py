from flask import request
from flask_login import current_user
from ..extensions import db
from ..models import AuditLog

def audit(action, entity_type, entity_id=None, details=""):
    user_id = current_user.id if current_user.is_authenticated else None
    ip = request.headers.get("X-Forwarded-For", request.remote_addr) if request else None
    db.session.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type,
        entity_id=entity_id, details=details, ip_address=ip))
