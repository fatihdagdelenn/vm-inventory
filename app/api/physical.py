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
from ..models import (User, PhysicalDevice, PhysicalDeviceHistory,
                      HostSupplement, Host, Platform)
from ..models.physical import DEVICE_TYPES, SERVER_ONLY_FIELDS, SERVER_ROLES
from ..core.security import require_role, get_current_user, validate_csrf
from ..core.audit import log_audit
from ..core.timezone import to_iso, now_local
from ..services import report_service as rs

router = APIRouter(prefix="/api/physical", tags=["physical"])

# Editable fields (device_type handled separately)
_FIELDS = ("name", "location", "status", "role", "mgmt_ip", "ilo_ip", "brand",
           "model", "serial_no", "cpu", "ram_gb", "os", "notes")


def _to_dict(d: PhysicalDevice) -> dict:
    return {
        "id": d.id, "source": "manual", "device_type": d.device_type,
        "name": d.name, "location": d.location, "status": d.status,
        "role": d.role, "mgmt_ip": d.mgmt_ip, "ilo_ip": d.ilo_ip,
        "brand": d.brand, "model": d.model, "serial_no": d.serial_no,
        "cpu": d.cpu, "ram_gb": d.ram_gb, "os": d.os, "notes": d.notes,
        "created_at": to_iso(d.created_at), "updated_at": to_iso(d.updated_at),
    }


def _host_to_dict(h: Host, sup: HostSupplement = None) -> dict:
    """A platform hypervisor host projected as a read-only physical row.

    Auto fields come from sync (name, IP, CPU/RAM, brand/model, OS); manual
    extras (location, iLO IP, serial, role, notes) come from HostSupplement.
    """
    cpu = f"{h.cpu_cores} çekirdek" if h.cpu_cores else ""
    if h.cpu_model:
        cpu = (h.cpu_model + (f" ({h.cpu_cores}c)" if h.cpu_cores else "")).strip()
    ram_gb = int(round((h.ram_total_mb or 0) / 1024)) or None
    brand, model = "", (h.hw_model or "")
    if h.hw_model and " " in h.hw_model:
        brand, model = h.hw_model.split(" ", 1)
    return {
        "id": None, "source": "platform", "host_id": h.id,
        "device_type": "server", "name": h.name,
        "location": (sup.location if sup else None),
        "status": "active" if (h.status == "online") else (h.status or "active"),
        "role": (sup.role if sup and sup.role else "hypervisor"),
        "mgmt_ip": h.mgmt_ip, "ilo_ip": (sup.ilo_ip if sup else None),
        "brand": brand, "model": model,
        "serial_no": (sup.serial_no if sup else None),
        "cpu": cpu, "ram_gb": ram_gb, "os": h.os_version,
        "notes": (sup.notes if sup else None),
        "cluster": h.cluster, "updated_at": to_iso(h.updated_at),
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
    # role: only valid values kept
    if out.get("role") and out["role"] not in SERVER_ROLES:
        out["role"] = None
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
                 location: str = "", role: str = "", include_hosts: int = 1,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Physical inventory: manual devices + (read-only) platform hypervisor
    hosts. Filterable by search / type / status / location / role."""
    query = db.query(PhysicalDevice)
    if device_type in DEVICE_TYPES:
        query = query.filter(PhysicalDevice.device_type == device_type)
    if status:
        query = query.filter(PhysicalDevice.status == status)
    if location:
        query = query.filter(PhysicalDevice.location == location)
    if role:
        query = query.filter(PhysicalDevice.role == role)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            PhysicalDevice.name.ilike(like), PhysicalDevice.location.ilike(like),
            PhysicalDevice.mgmt_ip.ilike(like), PhysicalDevice.ilo_ip.ilike(like),
            PhysicalDevice.brand.ilike(like), PhysicalDevice.model.ilike(like),
            PhysicalDevice.serial_no.ilike(like), PhysicalDevice.notes.ilike(like)))
    manual = [_to_dict(d) for d in
              query.order_by(PhysicalDevice.device_type, PhysicalDevice.name).all()]

    # Platform hypervisor hosts (read-only projection). They count as servers,
    # so they're included unless a non-server type filter is active.
    host_rows = []
    if include_hosts and device_type in ("", "server"):
        sups = {s.host_id: s for s in db.query(HostSupplement).all()}
        for h in db.query(Host).order_by(Host.name).all():
            row = _host_to_dict(h, sups.get(h.id))
            if status and row["status"] != status:
                continue
            if location and (row.get("location") or "") != location:
                continue
            if role and (row.get("role") or "") != role:
                continue
            if q:
                blob = " ".join(str(row.get(k) or "") for k in
                                ("name", "location", "mgmt_ip", "ilo_ip",
                                 "brand", "model", "serial_no", "notes")).lower()
                if q.strip().lower() not in blob:
                    continue
            host_rows.append(row)

    items = manual + host_rows
    # counts per type for the summary chips (hosts add to "server")
    counts = {t: 0 for t in DEVICE_TYPES}
    for d in db.query(PhysicalDevice.device_type).all():
        counts[d[0]] = counts.get(d[0], 0) + 1
    n_hosts = db.query(Host).count()
    counts["server"] += n_hosts
    # distinct, sorted locations (manual + supplements) for filter/datalist
    locs = {r[0] for r in db.query(PhysicalDevice.location).distinct().all()
            if r[0] and r[0].strip()}
    locs |= {s.location for s in db.query(HostSupplement).all()
             if s.location and s.location.strip()}
    return {"items": items, "counts": counts,
            "total": sum(counts.values()), "locations": sorted(locs),
            "host_count": n_hosts}


@router.put("/host/{host_id}")
def upsert_host_supplement(host_id: int, request: Request,
                           payload: dict = Body(...),
                           db: Session = Depends(get_db),
                           user: User = Depends(require_role("operator"))):
    """Save manual extras (location, iLO IP, serial, role, notes) for a
    read-only platform host shown in the physical inventory."""
    validate_csrf(request, payload.pop("csrf_token", None))
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "Host bulunamadı")
    sup = db.query(HostSupplement).filter_by(host_id=host_id).first()
    if not sup:
        sup = HostSupplement(host_id=host_id)
        db.add(sup)
    role = payload.get("role")
    sup.location = (payload.get("location") or "").strip() or None
    sup.ilo_ip = (payload.get("ilo_ip") or "").strip() or None
    sup.serial_no = (payload.get("serial_no") or "").strip() or None
    sup.role = role if role in SERVER_ROLES else "hypervisor"
    sup.notes = (payload.get("notes") or "").strip() or None
    log_audit(db, user, "update", target=f"host-supplement:{h.name}", request=request)
    db.commit()
    return _host_to_dict(h, sup)


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


def physical_export_rows(db):
    """Manual physical devices + read-only platform host projections, as a
    single list suitable for report_service export helpers. Shared by the
    physical page export and the reports page (physical / all scopes)."""
    rows = list(db.query(PhysicalDevice).order_by(
        PhysicalDevice.device_type, PhysicalDevice.name).all())
    sups = {s.host_id: s for s in db.query(HostSupplement).all()}
    for h in db.query(Host).order_by(Host.name).all():
        rows.append(_host_to_dict(h, sups.get(h.id)))
    return rows


@router.get("/export")
def export_devices(fmt: str = "xlsx", q: str = "", device_type: str = "",
                   location: str = "",
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Export filtered physical inventory (Excel / CSV / PDF)."""
    query = db.query(PhysicalDevice)
    if device_type in DEVICE_TYPES:
        query = query.filter(PhysicalDevice.device_type == device_type)
    if location:
        query = query.filter(PhysicalDevice.location == location)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            PhysicalDevice.name.ilike(like), PhysicalDevice.location.ilike(like),
            PhysicalDevice.brand.ilike(like), PhysicalDevice.model.ilike(like),
            PhysicalDevice.serial_no.ilike(like)))
    items = query.order_by(PhysicalDevice.device_type,
                           PhysicalDevice.name).all()
    # Append read-only platform hosts (as dict rows) unless a non-server
    # type filter is active — same rule as the list view.
    host_rows = []
    if device_type in ("", "server"):
        sups = {s.host_id: s for s in db.query(HostSupplement).all()}
        for h in db.query(Host).order_by(Host.name).all():
            row = _host_to_dict(h, sups.get(h.id))
            if location and (row.get("location") or "") != location:
                continue
            if q and q.strip().lower() not in " ".join(
                    str(row.get(k) or "") for k in
                    ("name", "location", "brand", "model", "serial_no")).lower():
                continue
            host_rows.append(row)
    all_items = list(items) + host_rows
    log_audit(db, user, "export", target=f"physical ({fmt})",
              detail=f"count={len(all_items)}")
    db.commit()

    if fmt not in ("xlsx", "csv", "pdf"):
        raise HTTPException(400, "Format xlsx, csv veya pdf olmalı")
    if fmt == "xlsx":
        content = rs.export_excel(all_items, rs.PHYSICAL_COLUMNS, "Fiziksel Envanter")
        media, ext = ("application/vnd.openxmlformats-officedocument."
                      "spreadsheetml.sheet", "xlsx")
    elif fmt == "csv":
        content = rs.export_csv(all_items, rs.PHYSICAL_COLUMNS)
        media, ext = "text/csv; charset=utf-8", "csv"
    else:
        content = rs.export_pdf(all_items, rs.PHYSICAL_COLUMNS, "Fiziksel Envanter")
        media, ext = "application/pdf", "pdf"
    fname = f"fiziksel_envanter_{now_local():%Y%m%d_%H%M}.{ext}"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})
