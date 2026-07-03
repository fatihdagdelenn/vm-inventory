"""Datastore (storage) list API - search, filter, sort.
Data is collected during sync with duplicate prevention."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Datastore, Platform, VirtualMachine, Host
from ..core.security import get_current_user

router = APIRouter(prefix="/api/datastores", tags=["datastores"])

SORTABLE = {
    "name": Datastore.name, "type": Datastore.type, "node": Datastore.node,
    "capacity_gb": Datastore.capacity_gb, "used_gb": Datastore.used_gb,
    "free_gb": Datastore.free_gb, "host_count": Datastore.host_count,
    "vm_count": Datastore.vm_count, "status": Datastore.status,
    "usage": Datastore.used_gb / func.nullif(Datastore.capacity_gb, 0),
    "platform": Platform.name,
}
CASE_INSENSITIVE = {"name", "type", "node", "status", "platform"}


def _to_dict(d: Datastore, pname: str, ptype: str) -> dict:
    return {
        "id": d.id, "name": d.name, "type": d.type or "", "node": d.node or "",
        "shared": bool(d.shared),
        "capacity_gb": round(d.capacity_gb or 0, 1),
        "used_gb": round(d.used_gb or 0, 1),
        "free_gb": round(d.free_gb or 0, 1),
        "usage_pct": d.usage_pct,
        "host_count": d.host_count or 0,
        "vm_count": d.vm_count or 0,
        "status": d.status or "",
        "platform": pname or "",
        "platform_type": ptype or "",
    }


@router.get("")
def list_datastores(q: str = "", sort: str = "name", order: str = "asc",
                    db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    query = (db.query(Datastore, Platform.name, Platform.type)
               .outerjoin(Platform, Datastore.platform_id == Platform.id))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Datastore.name.ilike(like), Datastore.type.ilike(like),
            Datastore.node.ilike(like), Platform.name.ilike(like)))
    col = SORTABLE.get(sort, Datastore.name)
    if sort in CASE_INSENSITIVE:
        col = func.lower(col)
    query = query.order_by(col.desc() if order == "desc" else col.asc())
    return {"items": [_to_dict(d, pn, pt) for d, pn, pt in query.all()]}


@router.get("/{ds_id}")
def datastore_detail(ds_id: int, db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    """VMs + hosts using a datastore (for drill-down modals).
        VM matching uses the same logic as list/sync: the VM's comma-separated
        'datastore' field (node-aware for local Proxmox stores)."""
    d = db.query(Datastore).filter_by(id=ds_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Datastore bulunamadı")
    rows = (db.query(VirtualMachine, Host.name)
              .outerjoin(Host, VirtualMachine.host_id == Host.id)
              .filter(VirtualMachine.platform_id == d.platform_id,
                      VirtualMachine.is_template == False,            # noqa: E712
                      VirtualMachine.datastore.ilike(f"%{d.name}%")).all())
    vms, host_names = [], set()
    for vm, hname in rows:
        tokens = [t.strip() for t in (vm.datastore or "").split(",") if t.strip()]
        if d.name not in tokens:
            continue                       # avoid substring mismatches (ds1 != ds10)
        if not (d.shared or not d.node or hname == d.node):
            continue
        ext = vm.external_id or ""
        vms.append({
            "id": vm.id, "name": vm.name,
            "vmid": ext.split("/", 1)[1] if "/" in ext else ext,
            "ip_addresses": vm.ip_addresses or "",
            "power_state": vm.power_state,
            "cpu_count": vm.cpu_count, "cpu_usage_pct": vm.cpu_usage_pct,
            "ram_mb": vm.ram_mb, "ram_usage_mb": vm.ram_usage_mb,
            "host": hname or "",
        })
        if hname:
            host_names.add(hname)
    hosts = [{"id": h.id, "name": h.name}
             for h in db.query(Host).filter(
                 Host.platform_id == d.platform_id,
                 Host.name.in_(host_names)).all()] if host_names else []
    vms.sort(key=lambda v: (v["name"] or "").lower())
    return {"id": d.id, "name": d.name, "vms": vms, "hosts": hosts}
