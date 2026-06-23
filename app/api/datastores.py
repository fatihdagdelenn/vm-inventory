"""Datastore (depolama) listesi API'si — arama, filtre, sıralama.

Veriler senkronizasyonda toplanır ve mükerrer kayıt önlenir:
paylaşımlı depolar (NFS/Ceph/PBS, vCenter VMFS) tek satırda birleşir;
yerel Proxmox depoları node bazında ayrılır.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Datastore, Platform
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
