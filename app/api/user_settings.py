"""Per-user UI settings (key-value): dashboard layout, topology positions...

Any authenticated user reads/writes ONLY their own settings. The value is an
opaque string (usually JSON) owned by the frontend; the backend only stores it.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserSetting
from ..core.security import get_current_user, validate_csrf

router = APIRouter(prefix="/api/user-settings", tags=["user-settings"])

_KEY_MAX = 64
_VALUE_MAX = 512 * 1024   # 512 KB is plenty for layout JSON


@router.get("/{key}")
def get_setting(key: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    row = db.query(UserSetting).filter_by(user_id=user.id, key=key).first()
    return {"key": key, "value": row.value if row else None}


@router.put("/{key}")
def put_setting(key: str, request: Request, payload: dict = Body(...),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    validate_csrf(request, payload.pop("csrf_token", None))
    if len(key) > _KEY_MAX:
        raise HTTPException(400, "Anahtar çok uzun")
    value = payload.get("value")
    if value is not None and not isinstance(value, str):
        raise HTTPException(400, "value bir metin olmalı")
    if value and len(value) > _VALUE_MAX:
        raise HTTPException(400, "Değer çok büyük")
    row = db.query(UserSetting).filter_by(user_id=user.id, key=key).first()
    if value is None or value == "":
        if row:
            db.delete(row)
    elif row:
        row.value = value
    else:
        db.add(UserSetting(user_id=user.id, key=key, value=value))
    db.commit()
    return {"ok": True}
