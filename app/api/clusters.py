"""
Cluster yönetimi API'si.

Cluster'lar envanterden türetilir (VM/Host üzerindeki alan); burada
görünürlükleri yönetilir. Gizlenen cluster'lar:
- Dashboard sayılarına ve grafiklerine GİRMEZ
- VM listesi ve facets'te varsayılan olarak GÖRÜNMEZ
  (gelişmiş panelden "gizli cluster'ları dahil et" ile veya doğrudan
   cluster: araması yapılarak yine erişilebilir — veri silinmez)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import VirtualMachine, Host, ClusterSetting, AuditLog
from ..models.user import User
from ..core.security import get_current_user, require_role

router = APIRouter(prefix="/api/clusters", tags=["clusters"])

# Cluster'ı boş olan VM/host'lar için sanal grup kimliği.
# Standalone host'lardaki VM'lerin cluster alanı doğal olarak boştur;
# bu sentinel sayesinde onlar da tek grup olarak gizlenip gösterilebilir.
NONE_SENTINEL = "__none__"


def hidden_cluster_names(db: Session) -> list[str]:
    """
    Gizli cluster adlarını döndürür (dashboard ve VM listesi kullanır).
    Liste NONE_SENTINEL içeriyorsa cluster'ı boş kayıtlar da gizlidir.
    """
    rows = db.query(ClusterSetting.name)\
             .filter(ClusterSetting.visible == False).all()  # noqa: E712
    return [r[0] for r in rows]


def hidden_vm_filter(db: Session, model):
    """
    Gizli cluster'ları dışlayan SQLAlchemy koşulu üretir (VM veya Host için).
    Dönüş None ise hiçbir şey gizli değildir.
    """
    from sqlalchemy import func, or_
    hidden = hidden_cluster_names(db)
    if not hidden:
        return None
    names = [h for h in hidden if h != NONE_SENTINEL]
    conds = []
    if names:
        conds.append(func.coalesce(model.cluster, "").in_(names))
    if NONE_SENTINEL in hidden:
        conds.append(func.coalesce(model.cluster, "") == "")
    return ~or_(*conds) if conds else None


@router.get("")
def list_clusters(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """
    Tüm cluster'ları VM/host sayıları ve görünürlük durumuyla listele.
    Envanterde artık bulunmayan ama ayarı kalmış cluster'lar da gösterilir
    (kullanıcı ayarı temizleyebilsin diye).
    """
    vm_counts = dict(db.query(VirtualMachine.cluster,
                              func.count(VirtualMachine.id))
                     .filter(VirtualMachine.is_template == False)  # noqa: E712
                     .group_by(VirtualMachine.cluster).all())
    host_counts = dict(db.query(Host.cluster, func.count(Host.id))
                       .group_by(Host.cluster).all())
    settings = {s.name: s.visible for s in db.query(ClusterSetting).all()}

    # Boş cluster'ları sanal "(Cluster'sız)" grubunda topla
    none_vm = vm_counts.pop(None, 0) + vm_counts.pop("", 0)
    none_host = host_counts.pop(None, 0) + host_counts.pop("", 0)

    names = set(vm_counts) | set(host_counts) | set(settings)
    names.discard(None)
    names.discard("")
    names.discard(NONE_SENTINEL)   # ayrı işlenir

    items = [{
        "name": n,
        "vm_count": vm_counts.get(n, 0),
        "host_count": host_counts.get(n, 0),
        "visible": settings.get(n, True),       # ayar yoksa görünür kabul edilir
        "in_inventory": n in vm_counts or n in host_counts,
        "is_none": False,
    } for n in sorted(names)]

    # "(Cluster'sız)" grubu: envanterde boş cluster'lı kayıt varsa
    # veya gizleme ayarı bir kez yapılmışsa listede yer alır
    if none_vm or none_host or NONE_SENTINEL in settings:
        items.insert(0, {
            "name": NONE_SENTINEL,
            "vm_count": none_vm,
            "host_count": none_host,
            "visible": settings.get(NONE_SENTINEL, True),
            "in_inventory": bool(none_vm or none_host),
            "is_none": True,
        })
    return {"items": items,
            "hidden_count": sum(1 for i in items if not i["visible"])}


class VisibilityPayload(BaseModel):
    name: str
    visible: bool


@router.post("/visibility")
def set_visibility(payload: VisibilityPayload,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_role("operator"))):
    """Bir cluster'ı göster/gizle. Operatör ve üzeri yapabilir."""
    if not payload.name.strip():
        raise HTTPException(400, "Cluster adı boş olamaz")
    # NONE_SENTINEL geçerli bir addır: "(Cluster'sız)" sanal grubunu temsil eder
    setting = db.query(ClusterSetting).filter_by(name=payload.name).first()
    if setting is None:
        setting = ClusterSetting(name=payload.name)
        db.add(setting)
    setting.visible = payload.visible
    display = "(Cluster'sız)" if payload.name == NONE_SENTINEL else payload.name
    db.add(AuditLog(username=user.username,
                    action="cluster_visibility",
                    detail=f"{display} -> "
                           f"{'görünür' if payload.visible else 'gizli'}"))
    db.commit()
    return {"ok": True, "name": payload.name, "visible": payload.visible}
