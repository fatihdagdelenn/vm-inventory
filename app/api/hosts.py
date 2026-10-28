"""Host listesi ve detay API'si (lokal DB'den)."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Host, HostSupplement, User
from ..core.security import get_current_user, require_role, validate_csrf
from ..core.audit import log_audit
from ..core.host_hw import effective_hw, supplements_by_host
from ..core.timezone import to_iso

router = APIRouter(prefix="/api/hosts", tags=["hosts"])


def _host_to_dict(h: Host, sup: HostSupplement = None) -> dict:
    # hw_model = what the UI shows: the manual override when set, else the
    # collector value. hw_auto keeps the collector value visible.
    hw = effective_hw(h, sup)
    return {"id": h.id, "name": h.name, "mgmt_ip": h.mgmt_ip,
            "os_version": h.os_version, "cpu_model": h.cpu_model,
            "hw_model": hw["text"], "hw_brand": hw["brand"], "hw_name": hw["model"],
            "hw_manual": hw["manual"], "hw_auto": hw["auto"],
            "hw_manual_brand": (sup.brand or "") if sup else "",
            "hw_manual_model": (sup.model or "") if sup else "",
            "cpu_cores": h.cpu_cores, "ram_total_mb": h.ram_total_mb,
            "ram_used_mb": h.ram_used_mb, "cpu_usage_pct": h.cpu_usage_pct,
            "disk_total_gb": h.disk_total_gb, "disk_used_gb": h.disk_used_gb,
            "cluster": h.cluster, "status": h.status,
            "last_boot": to_iso(h.last_boot),
            "platform": h.platform.name if h.platform else "",
            "platform_type": h.platform.type if h.platform else "",
            "vm_count": len(h.vms),
            "vm_running": sum(1 for v in h.vms if v.power_state == "running")}


@router.get("")
def list_hosts(q: str = "", db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    query = db.query(Host).options(joinedload(Host.platform), joinedload(Host.vms))
    if q:
        like = f"%{q}%"
        # HostSupplement has no FK to hosts -> explicit outer join; manual
        # brand / model must be searchable like the detected value.
        query = query.outerjoin(HostSupplement, HostSupplement.host_id == Host.id) \
            .filter(or_(Host.name.ilike(like), Host.mgmt_ip.ilike(like),
                        Host.cluster.ilike(like), Host.cpu_model.ilike(like),
                        Host.hw_model.ilike(like), HostSupplement.brand.ilike(like),
                        HostSupplement.model.ilike(like)))
    sups = supplements_by_host(db)
    return {"items": [_host_to_dict(h, sups.get(h.id))
                      for h in query.order_by(Host.name).all()]}


@router.put("/{host_id}/hardware")
def set_host_hardware(host_id: int, request: Request, payload: dict = Body(...),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_role("operator"))):
    """Manual hardware brand / model for a host (Proxmox cannot report the
    exact system model through its API). Both empty = back to the detected
    value. Stored in HostSupplement, shared with the physical inventory."""
    validate_csrf(request, payload.pop("csrf_token", None))
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "Host bulunamadı")
    brand = " ".join(str(payload.get("brand") or "").split())
    model = " ".join(str(payload.get("model") or "").split())
    if len(brand) > 64 or len(model) > 128:
        raise HTTPException(400, "Marka en fazla 64, model en fazla 128 karakter olabilir")
    sup = db.query(HostSupplement).filter_by(host_id=host_id).first()
    old = effective_hw(h, sup)["text"]
    if not sup:
        if not brand and not model:
            return _host_to_dict(h, None)        # nothing to clear
        sup = HostSupplement(host_id=host_id)
        db.add(sup)
    sup.brand = brand or None
    sup.model = model or None
    new = effective_hw(h, sup)["text"]
    log_audit(db, user, "update", target=f"host-hardware:{h.name}",
              detail="manual" if (brand or model) else "cleared (detected value)",
              old=old or None, new=new or None, request=request)
    db.commit()
    return _host_to_dict(h, sup)


@router.get("/{host_id}")
def get_host(host_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "Host bulunamadı")
    data = _host_to_dict(h, db.query(HostSupplement).filter_by(host_id=h.id).first())
    # Rich VM list for the modal mini table: name, IP, power state,
    # instant CPU/RAM usage + id for deep links. Running first, then by name.
    vms = sorted(h.vms, key=lambda v: (v.power_state != "running",
                                       (v.name or "").lower()))
    data["vms"] = [{
        "id": v.id, "name": v.name, "vmid": v.vmid,
        "ip_addresses": v.ip_effective, "power_state": v.power_state,
        "cpu_count": v.cpu_count, "cpu_usage_pct": v.cpu_usage_pct,
        "ram_mb": v.ram_mb, "ram_usage_mb": v.ram_usage_mb,
    } for v in vms]
    return data
