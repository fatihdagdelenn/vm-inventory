"""
Physical inventory API: manual CRUD for bare-metal servers, storage arrays,
SAN switches and backup appliances + change history + Excel/CSV/PDF export.

Unlike platform-sourced inventory, these rows are entered by hand, so every
create / update / delete is recorded in PhysicalDeviceHistory with the acting
app user.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, PhysicalDevice, PhysicalDeviceHistory
from ..models.physical import DEVICE_TYPES, SERVER_ONLY_FIELDS
from ..core.security import require_role, get_current_user, validate_csrf
from ..core.audit import log_audit
from ..core.timezone import to_iso, now_local
from ..services import report_service as rs

router = APIRouter(prefix="/api/physical", tags=["physical"])

# Editable fields (device_type handled separately)
_FIELDS = ("name", "location", "status", "mgmt_ip", "ilo_ip", "brand", "model",
           "serial_no", "cpu", "ram_gb", "os", "notes")


def _to_dict(d: PhysicalDevice) -> dict:
    return {
        "id": d.id, "device_type": d.device_type, "name": d.name,
        "location": d.location, "status": d.status, "mgmt_ip": d.mgmt_ip,
        "ilo_ip": d.ilo_ip, "brand": d.brand, "model": d.model,
        "serial_no": d.serial_no, "cpu": d.cpu, "ram_gb": d.ram_gb,
        "os": d.os, "notes": d.notes,
        "created_at": to_iso(d.created_at), "updated_at": to_iso(d.updated_at),
    }


def _clean(payload: dict) -> dict:
    """Extract editable fields; blank server-only fields for non-servers."""
    dtype = payload.get("device_type")
    if dtype not in DEVICE_TYPES:
        raise HTTPException(400, "Geçersiz cihaz tipi")
    out = {"device_type": dtype}
    for f in _FIELDS:
        if f in payload:
            out[f] = payload[f]
    if not out.get("name"):
        raise HTTPException(400, "Ad zorunludur")
    # ram_gb -> int or None
    if "ram_gb" in out:
        try:
            out["ram_gb"] = int(out["ram_gb"]) if str(out["ram_gb"]).strip() else None
        except (ValueError, TypeError):
            out["ram_gb"] = None
    # server-only fields cleared for storage / san_switch / backup
    if dtype != "server":
        for f in SERVER_ONLY_FIELDS:
            out[f] = None
    return out


def _record(db, device, action, actor, changes=None):
    db.add(PhysicalDeviceHistory(
        device_id=device.id, device_name=device.name,
        device_type=device.device_type, action=action, actor=actor,
        changes=json.dumps(changes, ensure_ascii=False) if changes else None))


@router.get("")
def list_devices(q: str = "", device_type: str = "", status: str = "",
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """All physical devices (filterable). Visible to every role."""
    query = db.query(PhysicalDevice)
    if device_type in DEVICE_TYPES:
        query = query.filter(PhysicalDevice.device_type == device_type)
    if status:
        query = query.filter(PhysicalDevice.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            PhysicalDevice.name.ilike(like), PhysicalDevice.location.ilike(like),
            PhysicalDevice.mgmt_ip.ilike(like), PhysicalDevice.ilo_ip.ilike(like),
            PhysicalDevice.brand.ilike(like), PhysicalDevice.model.ilike(like),
            PhysicalDevice.serial_no.ilike(like), PhysicalDevice.notes.ilike(like)))
    items = query.order_by(PhysicalDevice.device_type, PhysicalDevice.name).all()
    # counts per type for the summary chips
    counts = {t: 0 for t in DEVICE_TYPES}
    for d in db.query(PhysicalDevice.device_type).all():
        counts[d[0]] = counts.get(d[0], 0) + 1
    return {"items": [_to_dict(d) for d in items], "counts": counts,
            "total": sum(counts.values())}


@router.post("")
def create_device(request: Request, payload: dict = Body(...),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_role("operator"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    data = _clean(payload)
    d = PhysicalDevice(**data)
    db.add(d)
    db.flush()
    _record(db, d, "created", user.username,
            {k: [None, v] for k, v in data.items() if v not in (None, "")})
    log_audit(db, user, "create", target=f"physical:{d.name}", request=request)
    db.commit()
    return _to_dict(d)


@router.put("/{device_id}")
def update_device(device_id: int, request: Request, payload: dict = Body(...),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_role("operator"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    d = db.get(PhysicalDevice, device_id)
    if not d:
        raise HTTPException(404, "Cihaz bulunamadı")
    data = _clean(payload)
    changes = {}
    for k, v in data.items():
        old = getattr(d, k)
        if (old or None) != (v or None):
            changes[k] = [old, v]
            setattr(d, k, v)
    if changes:
        _record(db, d, "updated", user.username, changes)
        log_audit(db, user, "update", target=f"physical:{d.name}", request=request)
    db.commit()
    return _to_dict(d)


@router.delete("/{device_id}")
def delete_device(device_id: int, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_role("operator"))):
    validate_csrf(request, payload.pop("csrf_token", None) if payload else
                 request.headers.get("X-CSRF-Token"))
    d = db.get(PhysicalDevice, device_id)
    if not d:
        raise HTTPException(404, "Cihaz bulunamadı")
    _record(db, d, "deleted", user.username)
    log_audit(db, user, "delete", target=f"physical:{d.name}", request=request)
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.get("/history")
def device_history(device_id: int = 0, limit: int = 200,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Change history (all devices, or one when device_id is given)."""
    query = db.query(PhysicalDeviceHistory)
    if device_id:
        query = query.filter(PhysicalDeviceHistory.device_id == device_id)
    rows = query.order_by(PhysicalDeviceHistory.changed_at.desc()).limit(limit).all()
    return {"items": [{
        "id": r.id, "device_id": r.device_id, "device_name": r.device_name,
        "device_type": r.device_type, "action": r.action, "actor": r.actor,
        "changes": json.loads(r.changes) if r.changes else None,
        "changed_at": to_iso(r.changed_at),
    } for r in rows]}


@router.get("/export")
def export_devices(fmt: str = "xlsx", q: str = "", device_type: str = "",
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Export filtered physical inventory (Excel / CSV / PDF)."""
    query = db.query(PhysicalDevice)
    if device_type in DEVICE_TYPES:
        query = query.filter(PhysicalDevice.device_type == device_type)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            PhysicalDevice.name.ilike(like), PhysicalDevice.location.ilike(like),
            PhysicalDevice.brand.ilike(like), PhysicalDevice.model.ilike(like),
            PhysicalDevice.serial_no.ilike(like)))
    items = query.order_by(PhysicalDevice.device_type,
                           PhysicalDevice.name).all()
    log_audit(db, user, "export", target=f"physical ({fmt})",
              detail=f"count={len(items)}")
    db.commit()

    if fmt not in ("xlsx", "csv", "pdf"):
        raise HTTPException(400, "Format xlsx, csv veya pdf olmalı")
    if fmt == "xlsx":
        content = rs.export_excel(items, rs.PHYSICAL_COLUMNS, "Fiziksel Envanter")
        media, ext = ("application/vnd.openxmlformats-officedocument."
                      "spreadsheetml.sheet", "xlsx")
    elif fmt == "csv":
        content = rs.export_csv(items, rs.PHYSICAL_COLUMNS)
        media, ext = "text/csv; charset=utf-8", "csv"
    else:
        content = rs.export_pdf(items, rs.PHYSICAL_COLUMNS, "Fiziksel Envanter")
        media, ext = "application/pdf", "pdf"
    fname = f"fiziksel_envanter_{now_local():%Y%m%d_%H%M}.{ext}"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})
