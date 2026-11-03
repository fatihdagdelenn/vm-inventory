"""OS lifecycle (EOL) administration: data status, endoflife.date sync, JSON
import, 'soon' threshold and extended-support exceptions. Admin only; every
change recomputes the VMs' support status."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.app_settings import set_setting
from ..core.audit import log_audit
from ..core.os_identity import PRODUCT_NAMES
from ..core.security import get_current_user, require_role, validate_csrf
from ..database import get_db
from ..models import LifecycleOverride, OsLifecycle, Tag, User, VirtualMachine
from ..models.lifecycle import OVERRIDE_SCOPES
from ..services import lifecycle_service as ls

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


def _ov(o: LifecycleOverride) -> dict:
    return {"id": o.id, "scope": o.scope, "target": o.target,
            "target_label": o.target_label or o.target, "distro": o.distro,
            "distro_label": PRODUCT_NAMES.get(o.distro or "", o.distro or ""),
            "extended": bool(o.extended), "note": o.note, "created_by": o.created_by,
            "updated_at": o.updated_at.isoformat(timespec="seconds") if o.updated_at else None}


@router.get("")
def lifecycle_status(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Data status + per-product summary + status counts."""
    agg = {}
    for d, src, n, u in (db.query(OsLifecycle.distro, OsLifecycle.source,
                                  func.count(OsLifecycle.id), func.max(OsLifecycle.updated_at))
                         .group_by(OsLifecycle.distro, OsLifecycle.source).all()):
        a = agg.setdefault(d, {"cycles": 0, "updated_at": None, "sources": []})
        a["cycles"] += n
        a["sources"].append(src)
        if u and (a["updated_at"] is None or u > a["updated_at"]):
            a["updated_at"] = u
    products = [{"distro": d, "label": PRODUCT_NAMES.get(d, d), "cycles": a["cycles"],
                 "updated_at": a["updated_at"].isoformat(timespec="seconds") if a["updated_at"] else None,
                 "sources": sorted(a["sources"])} for d, a in agg.items()]
    products.sort(key=lambda p: p["label"].lower())
    counts = dict(db.query(func.coalesce(VirtualMachine.support_status, "unknown"),
                           func.count(VirtualMachine.id))
                  .filter(VirtualMachine.is_template == False)       # noqa: E712
                  .group_by(func.coalesce(VirtualMachine.support_status, "unknown")).all())
    return {"meta": ls.meta(db), "products": products,
            "counts": {s: counts.get(s, 0) for s in ls.STATUSES},
            "product_names": PRODUCT_NAMES}


@router.post("/sync")
def lifecycle_sync(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    validate_csrf(request, None)
    res = ls.sync_from_api(db)
    counts = ls.recompute(db)
    log_audit(db, user, "lifecycle_sync", target="endoflife.date",
              detail=("ok" if res["ok"] else "offline: " + res.get("error", ""))[:255],
              request=request)
    db.commit()
    return {**res, "counts": counts}


@router.post("/import")
def lifecycle_import(request: Request, payload=Body(...), db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    """Upload lifecycle JSON: the seed format, or endoflife.date API v1
    product responses (one, a list, or {product: response})."""
    validate_csrf(request, None)
    try:
        rows, stamp = ls.parse_import(payload)
    except ValueError as exc:
        raise HTTPException(400, f"Dosya tanınmadı: {exc}. Beklenen: başlangıç verisi "
                                 "biçimi veya endoflife.date API v1 ürün cevabı.")
    res = ls.upsert_rows(db, rows, "manual", stamp)
    db.commit()
    counts = ls.recompute(db)
    log_audit(db, user, "lifecycle_import", target="json",
              detail=f"rows={len(rows)} added={res['added']} updated={res['updated']} "
                     f"kept={res['kept']}", request=request)
    db.commit()
    return {**res, "rows": len(rows), "counts": counts}


@router.put("/settings")
def lifecycle_settings(request: Request, payload: dict = Body(...),
                       db: Session = Depends(get_db),
                       user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    try:
        days = int(payload.get("soon_days"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Gün sayısı bir tam sayı olmalı")
    if not 1 <= days <= 3650:
        raise HTTPException(400, "Gün sayısı 1 ile 3650 arasında olmalı")
    old = ls.soon_days(db)
    set_setting(db, ls.SOON_KEY, days)
    db.commit()
    counts = ls.recompute(db)
    log_audit(db, user, "lifecycle_settings", target="soon_days", old=str(old),
              new=str(days), request=request)
    db.commit()
    return {"soon_days": days, "counts": counts}


@router.get("/overrides")
def list_overrides(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    rows = db.query(LifecycleOverride).order_by(LifecycleOverride.scope,
                                                LifecycleOverride.id).all()
    tags = sorted(t.name for t in db.query(Tag).all())
    return {"items": [_ov(o) for o in rows], "tags": tags}


@router.post("/overrides")
def add_override(request: Request, payload: dict = Body(...), db: Session = Depends(get_db),
                 user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    scope = payload.get("scope")
    if scope not in OVERRIDE_SCOPES:
        raise HTTPException(400, "Kapsam all, tag veya vm olmalı")
    distro = (payload.get("distro") or "").strip() or None
    if distro and distro not in ls.PRODUCTS:
        raise HTTPException(400, "Bilinmeyen işletim sistemi ürünü")
    target = label = None
    if scope == "tag":
        target = (payload.get("target") or "").strip()
        if not target:
            raise HTTPException(400, "Etiket adı gerekli")
        label = target
    elif scope == "vm":
        name = (payload.get("target") or "").strip()
        vms = db.query(VirtualMachine).filter(func.lower(VirtualMachine.name) == name.lower()).all()
        if not vms:
            raise HTTPException(404, f"VM bulunamadı: {name}")
        if len(vms) > 1:
            raise HTTPException(409, f"Bu adla {len(vms)} VM var; adı benzersiz bir VM seçin")
        vm = vms[0]
        # platform + vmid survives a Proxmox live migration (new row, new external_id)
        target, label = f"{vm.platform_id}:{vm.vmid or vm.external_id}", vm.name
    o = LifecycleOverride(scope=scope, target=target, target_label=label, distro=distro,
                          extended=bool(payload.get("extended", True)),
                          note=(payload.get("note") or "").strip()[:1000] or None,
                          created_by=user.username, updated_at=datetime.utcnow())
    db.add(o)
    db.commit()
    counts = ls.recompute(db)
    log_audit(db, user, "lifecycle_override_add", target=f"{scope}:{label or '*'}",
              detail=f"distro={distro or '*'} extended={o.extended}", request=request)
    db.commit()
    return {"item": _ov(o), "counts": counts}


@router.delete("/overrides/{oid}")
def delete_override(oid: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    validate_csrf(request, None)
    o = db.get(LifecycleOverride, oid)
    if not o:
        raise HTTPException(404, "Kayıt bulunamadı")
    desc = f"{o.scope}:{o.target_label or '*'}"
    db.delete(o)
    db.commit()
    counts = ls.recompute(db)
    log_audit(db, user, "lifecycle_override_delete", target=desc, request=request)
    db.commit()
    return {"ok": True, "counts": counts}
