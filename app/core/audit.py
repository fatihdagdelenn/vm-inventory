"""Shared helper for audit records. All endpoints use it; the role comes
from the acting user, the IP/User-Agent from the request."""
from .. models import AuditLog


def log_audit(db, user=None, action="", *, target="", detail="",
              old=None, new=None, request=None, username=None, role=None):
    db.add(AuditLog(
        username=username if username is not None else getattr(user, "username", "") or "",
        role=role if role is not None else (getattr(user, "role", "") or ""),
        action=action,
        target=(target or "")[:255],
        detail=detail or "",
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        ip_address=(request.client.host if request and request.client else ""),
    ))
