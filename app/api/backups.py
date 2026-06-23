"""Yedek (Proxmox vzdump + PBS) listesi API'si — arama, filtre, sıralama.

Yedekler yalnızca Proxmox platformlarından gelir (vCenter'ın yedek API'si yoktur).
Depo içeriğinden toplanır; PBS bağlı depolar da dahildir.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Backup, Platform, VirtualMachine
from ..core.security import get_current_user
from ..core.timezone import to_iso

router = APIRouter(prefix="/api/backups", tags=["backups"])

SORTABLE = {
    "vm_name": Backup.vm_name, "storage": Backup.storage,
    "created_at": Backup.created_at, "size_gb": Backup.size_gb,
    "source": Backup.source, "platform": Platform.name,
}
CASE_INSENSITIVE = {"vm_name", "storage", "source"}


def _row(b: Backup, pname: str, ptype: str, cluster: str) -> dict:
    return {
        "id": b.id, "vm_name": b.vm_name or b.vmid, "vmid": b.vmid,
        "storage": b.storage or "", "source": b.source or "", "fmt": b.fmt or "",
        "created_at": to_iso(b.created_at), "age_days": b.age_days,
        "size_gb": b.size_gb, "protected": bool(b.protected),
        "notes": b.notes or "", "platform": pname or "", "platform_type": ptype or "",
        "cluster": cluster or "", "volid": b.volid or "",
    }


@router.get("")
def list_backups(q: str = "", sort: str = "created_at", order: str = "desc",
                 storage: str = "", source: str = "",
                 db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    query = (db.query(Backup, Platform.name, Platform.type, VirtualMachine.cluster)
               .outerjoin(Platform, Backup.platform_id == Platform.id)
               .outerjoin(VirtualMachine, Backup.vm_id == VirtualMachine.id))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Backup.vm_name.ilike(like), Backup.vmid.ilike(like),
            Backup.storage.ilike(like), Backup.notes.ilike(like)))
    if storage:
        query = query.filter(Backup.storage == storage)
    if source:
        query = query.filter(Backup.source == source)
    col = SORTABLE.get(sort, Backup.created_at)
    if sort in CASE_INSENSITIVE:
        col = func.lower(col)
    query = query.order_by(col.desc().nullslast() if order == "desc"
                           else col.asc().nullslast())
    rows = query.all()
    storages = sorted(r[0] for r in db.query(Backup.storage).distinct().all() if r[0])
    sources = sorted(r[0] for r in db.query(Backup.source).distinct().all() if r[0])
    return {"items": [_row(b, pn, pt, cl) for b, pn, pt, cl in rows],
            "storages": storages, "sources": sources}


@router.get("/diagnose")
def diagnose_backups(db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    """Yedekler neden boş geliyor? Her Proxmox platformunda depo taramasını
    canlı çalıştırıp ne görüldüğünü döndürür (depo, içerik sayısı, yedek sayısı,
    izin/erişim hatası). Yalnızca yöneticiler."""
    if getattr(user, "role", "") != "admin":
        return {"error": "Bu işlem yalnızca yöneticiler içindir."}
    from ..services.sync_service import _build_collector
    out = []
    for p in db.query(Platform).filter_by(type="proxmox").all():
        entry = {"platform": p.name, "storages": [], "error": ""}
        col = None
        try:
            col = _build_collector(p)
            col.connect()                       # self.api'yi kur (sync ile aynı)
            entry["storages"] = col.diagnose_backups()
        except Exception as exc:
            entry["error"] = str(exc)
        finally:
            if col is not None and hasattr(col, "disconnect"):
                try:
                    col.disconnect()
                except Exception:
                    pass
        out.append(entry)
    if not out:
        return {"platforms": [], "hint": "Proxmox platformu bulunamadı."}
    return {"platforms": out}
