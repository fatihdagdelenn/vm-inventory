"""Yönetim API'si: kullanıcılar, audit log, değişiklik geçmişi (admin)."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, AuditLog, ChangeHistory
from ..core.timezone import to_iso
from ..core.audit import log_audit
from ..core.security import (require_role, get_current_user, hash_password,
                             validate_csrf)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    return {"items": [{"id": u.id, "username": u.username, "full_name": u.full_name,
                       "email": u.email, "role": u.role, "is_ldap": u.is_ldap,
                       "is_active": u.is_active,
                       "last_login": to_iso(u.last_login)}
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
    log_audit(db, user, "create_user", target=u.username, new=f"rol={u.role}",
              request=request)
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
    old_role, old_active = u.role, u.is_active
    if "role" in payload and payload["role"] in ("admin", "operator", "viewer"):
        u.role = payload["role"]
    if "is_active" in payload:
        u.is_active = bool(payload["is_active"])
    if payload.get("password"):
        u.password_hash = hash_password(payload["password"])
    for f in ("full_name", "email"):
        if f in payload:
            setattr(u, f, payload[f])
    changes = []
    if u.role != old_role:
        changes.append(("rol", old_role, u.role))
    if u.is_active != old_active:
        changes.append(("durum", "aktif" if old_active else "pasif",
                        "aktif" if u.is_active else "pasif"))
    if payload.get("password"):
        changes.append(("parola", "***", "*** (değişti)"))
    log_audit(db, user, "update_user", target=u.username,
              old=", ".join(f"{k}={o}" for k, o, _ in changes) or None,
              new=", ".join(f"{k}={n}" for k, _, n in changes) or None,
              detail=f"alanlar={list(payload.keys())}", request=request)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_logs(limit: int = 200, q: str = "", action: str = "",
               db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(AuditLog.username.ilike(like),
                                 AuditLog.target.ilike(like),
                                 AuditLog.detail.ilike(like)))
    logs = query.order_by(AuditLog.timestamp.desc()).limit(min(limit, 1000)).all()
    actions = [r[0] for r in db.query(AuditLog.action).distinct().all() if r[0]]
    return {"items": [{"timestamp": to_iso(l.timestamp), "username": l.username,
                       "role": l.role or "", "action": l.action,
                       "target": l.target or "", "detail": l.detail or "",
                       "old_value": l.old_value, "new_value": l.new_value,
                       "ip_address": l.ip_address} for l in logs],
            "actions": sorted(actions)}


@router.get("/changes")
def change_history(entity: str = "", q: str = "", category: str = "",
                   limit: int = 200,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Envanter değişiklik geçmişi (tüm roller görebilir)."""
    query = db.query(ChangeHistory)
    if entity in ("vm", "host"):
        query = query.filter_by(entity_type=entity)
    if category:
        query = query.filter(ChangeHistory.category == category)
    if q:
        query = query.filter(ChangeHistory.entity_name.ilike(f"%{q}%"))
    rows = query.order_by(ChangeHistory.changed_at.desc()).limit(min(limit, 1000)).all()
    return {"items": [{"changed_at": to_iso(r.changed_at),
                       "entity_type": r.entity_type, "entity_name": r.entity_name,
                       "change_type": r.change_type, "field": r.field,
                       "old_value": r.old_value, "new_value": r.new_value,
                       "actor": r.actor or "", "category": r.category or "",
                       "op_type": r.op_type or "", "platform_type": r.platform_type or "",
                       "cluster": r.cluster or "", "host": r.host or "",
                       "vm_external_id": r.vm_external_id or "",
                       "actor_ip": r.actor_ip or "", "actor_agent": r.actor_agent or ""}
                      for r in rows]}


@router.get("/sync-settings")
def get_sync_settings(db: Session = Depends(get_db),
                      user: User = Depends(require_role("admin"))):
    from ..config import get_settings
    from ..core.app_settings import get_int_setting, get_bool_setting
    env = get_settings()
    return {
        "sync_interval_minutes": get_int_setting(
            db, "sync_interval_minutes", env.sync_interval_minutes),
        "usage_sync_interval_minutes": get_int_setting(
            db, "usage_sync_interval_minutes", env.usage_sync_interval_minutes),
        "track_console_access": get_bool_setting(db, "track_console_access", False),
        "defaults": {"sync": env.sync_interval_minutes,
                     "usage": env.usage_sync_interval_minutes},
    }


@router.put("/sync-settings")
def update_sync_settings(request: Request, payload: dict = Body(...),
                         db: Session = Depends(get_db),
                         user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    from ..core.app_settings import get_int_setting, set_setting
    try:
        full = int(payload.get("sync_interval_minutes"))
        usage = int(payload.get("usage_sync_interval_minutes"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Geçersiz aralık değeri")
    if not (1 <= full <= 1440) or not (1 <= usage <= 1440):
        raise HTTPException(400, "Aralıklar 1–1440 dakika arasında olmalıdır")
    old = f"{get_int_setting(db, 'sync_interval_minutes', 0)}/" \
          f"{get_int_setting(db, 'usage_sync_interval_minutes', 0)} dk"
    set_setting(db, "sync_interval_minutes", full)
    set_setting(db, "usage_sync_interval_minutes", usage)
    console = bool(payload.get("track_console_access"))
    set_setting(db, "track_console_access", "1" if console else "0")
    log_audit(db, user, "update", target="sync-settings",
              old=old, new=f"{full}/{usage} dk, konsol={console}", request=request)
    db.commit()
    try:
        from ..core.scheduler import reschedule_sync
        reschedule_sync(full, usage)
    except Exception:
        pass   # ayar kaydedildi; yeniden zamanlama olmazsa sonraki açılışta geçerli olur
    return {"ok": True, "sync_interval_minutes": full,
            "usage_sync_interval_minutes": usage,
            "track_console_access": console}
