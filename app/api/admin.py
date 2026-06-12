"""Yönetim API'si: kullanıcılar, audit log, değişiklik geçmişi (admin)."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, AuditLog, ChangeHistory
from ..core.security import (require_role, get_current_user, hash_password,
                             validate_csrf)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    return {"items": [{"id": u.id, "username": u.username, "full_name": u.full_name,
                       "email": u.email, "role": u.role, "is_ldap": u.is_ldap,
                       "is_active": u.is_active,
                       "last_login": u.last_login.isoformat() if u.last_login else None}
                      for u in db.query(User).all()]}


@router.post("/users")
def create_user(request: Request, payload: dict = Body(...),
                db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    if payload.get("role") not in ("admin", "operator", "viewer"):
        raise HTTPException(400, "Rol admin, operator veya viewer olmalı")
    if db.query(User).filter_by(username=payload["username"]).first():
        raise HTTPException(400, "Bu kullanıcı adı zaten var")
    u = User(username=payload["username"], full_name=payload.get("full_name", ""),
             email=payload.get("email", ""), role=payload["role"],
             password_hash=hash_password(payload["password"]))
    db.add(u)
    db.add(AuditLog(username=user.username, action="create_user", detail=u.username))
    db.commit()
    return {"ok": True, "id": u.id}


@router.patch("/users/{user_id}")
def update_user(user_id: int, request: Request, payload: dict = Body(...),
                db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if "role" in payload and payload["role"] in ("admin", "operator", "viewer"):
        u.role = payload["role"]
    if "is_active" in payload:
        u.is_active = bool(payload["is_active"])
    if payload.get("password"):
        u.password_hash = hash_password(payload["password"])
    for f in ("full_name", "email"):
        if f in payload:
            setattr(u, f, payload[f])
    db.add(AuditLog(username=user.username, action="update_user", detail=u.username))
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_logs(limit: int = 200, db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc())\
             .limit(min(limit, 1000)).all()
    return {"items": [{"timestamp": l.timestamp.isoformat(), "username": l.username,
                       "action": l.action, "detail": l.detail,
                       "ip_address": l.ip_address} for l in logs]}


@router.get("/changes")
def change_history(entity: str = "", q: str = "", limit: int = 200,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Envanter değişiklik geçmişi (tüm roller görebilir)."""
    query = db.query(ChangeHistory)
    if entity in ("vm", "host"):
        query = query.filter_by(entity_type=entity)
    if q:
        query = query.filter(ChangeHistory.entity_name.ilike(f"%{q}%"))
    rows = query.order_by(ChangeHistory.changed_at.desc()).limit(min(limit, 1000)).all()
    return {"items": [{"changed_at": r.changed_at.isoformat(),
                       "entity_type": r.entity_type, "entity_name": r.entity_name,
                       "change_type": r.change_type, "field": r.field,
                       "old_value": r.old_value, "new_value": r.new_value}
                      for r in rows]}
