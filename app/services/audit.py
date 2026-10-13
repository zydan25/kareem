"""Utilities for recording security- and business-sensitive actions."""
from flask import has_request_context, request
from flask_login import current_user

from ..extensions import db
from ..models import AuditLog


def audit(action, entity_type, entity_id=None, details=""):
    """Add an audit event to the current transaction.

    The event intentionally shares the caller's transaction: if the business
    action rolls back, its audit record rolls back as well. IP information is
    taken from the server-observed peer address; client-supplied forwarding
    headers are not trusted here because they can be forged unless a trusted
    proxy middleware has already normalized the request.
    """
    user_id = None
    actor_username = None
    actor_name = None
    request_method = None
    request_path = None
    user_agent = None
    ip_address = None

    if has_request_context():
        if current_user.is_authenticated:
            user_id = current_user.id
            actor_username = (current_user.username or "")[:80] or None
            actor_name = (current_user.full_name or "")[:160] or None
        request_method = (request.method or "")[:12] or None
        # Store only the path, not the query string which could contain tokens
        # or other sensitive values.
        request_path = (request.path or "")[:255] or None
        user_agent = (request.headers.get("User-Agent") or "")[:255] or None
        ip_address = (request.remote_addr or "")[:64] or None

    action_value = str(action or "unknown")[:80]
    entity_type_value = str(entity_type or "unknown")[:80]
    details_value = "" if details is None else str(details)

    db.session.add(
        AuditLog(
            user_id=user_id,
            actor_username=actor_username,
            actor_name=actor_name,
            action=action_value,
            entity_type=entity_type_value,
            entity_id=entity_id,
            details=details_value,
            ip_address=ip_address,
            request_method=request_method,
            request_path=request_path,
            user_agent=user_agent,
        )
    )
