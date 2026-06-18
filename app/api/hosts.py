"""Host listesi ve detay API'si (lokal DB'den)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Host, User
from ..core.security import get_current_user
from ..core.timezone import to_iso

router = APIRouter(prefix="/api/hosts", tags=["hosts"])


def _host_to_dict(h: Host) -> dict:
    return {"id": h.id, "name": h.name, "mgmt_ip": h.mgmt_ip,
            "os_version": h.os_version, "cpu_model": h.cpu_model,
            "cpu_cores": h.cpu_cores, "ram_total_mb": h.ram_total_mb,
            "ram_used_mb": h.ram_used_mb, "cpu_usage_pct": h.cpu_usage_pct,
            "disk_total_gb": h.disk_total_gb, "disk_used_gb": h.disk_used_gb,
            "cluster": h.cluster, "status": h.status,
            "last_boot": to_iso(h.last_boot),
            "platform": h.platform.name if h.platform else "",
            "platform_type": h.platform.type if h.platform else "",
            "vm_count": len(h.vms)}


@router.get("")
def list_hosts(q: str = "", db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    query = db.query(Host).options(joinedload(Host.platform), joinedload(Host.vms))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Host.name.ilike(like), Host.mgmt_ip.ilike(like),
                                 Host.cluster.ilike(like), Host.cpu_model.ilike(like)))
    return {"items": [_host_to_dict(h) for h in query.order_by(Host.name).all()]}


@router.get("/{host_id}")
def get_host(host_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    h = db.get(Host, host_id)
    if not h:
        raise HTTPException(404, "Host bulunamadı")
    data = _host_to_dict(h)
    data["vms"] = [{"id": v.id, "name": v.name, "power_state": v.power_state}
                   for v in h.vms]
    return data
