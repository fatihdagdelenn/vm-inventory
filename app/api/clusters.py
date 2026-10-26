"""
Cluster management API.

Clusters are derived from the inventory (a string field on VM/Host); this
module only manages their visibility.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import VirtualMachine, Host, ClusterSetting, AuditLog
from ..models.user import User
from ..core.security import get_current_user, require_role, validate_csrf
from ..core.audit import log_audit

router = APIRouter(prefix="/api/clusters", tags=["clusters"])

# Virtual group id for VMs/hosts with an empty cluster.
# VMs on standalone hosts naturally have a blank cluster; this sentinel
# lets them be hidden/shown as a single group too.
NONE_SENTINEL = "__none__"


def hidden_cluster_names(db: Session) -> list[str]:
    """
        Returns hidden cluster names (used by the dashboard and VM list).
        If the list contains NONE_SENTINEL, blank-cluster records are hidden too.
        """
    rows = db.query(ClusterSetting.name)\
             .filter(ClusterSetting.visible == False).all()  # noqa: E712
    return [r[0] for r in rows]


def hidden_vm_filter(db: Session, model):
    """
        Builds a SQLAlchemy condition excluding hidden clusters (for VM or Host).
        A None return means nothing is hidden.
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
        List all clusters with VM/host counts and visibility. Clusters that left
        the inventory but still have a setting are listed too (marked accordingly).
        """
    vm_counts = dict(db.query(VirtualMachine.cluster,
                              func.count(VirtualMachine.id))
                     .filter(VirtualMachine.is_template == False)  # noqa: E712
                     .group_by(VirtualMachine.cluster).all())
    host_counts = dict(db.query(Host.cluster, func.count(Host.id))
                       .group_by(Host.cluster).all())
    settings = {s.name: s.visible for s in db.query(ClusterSetting).all()}

    # Collect empty clusters under the virtual "(No cluster)" group
    none_vm = vm_counts.pop(None, 0) + vm_counts.pop("", 0)
    none_host = host_counts.pop(None, 0) + host_counts.pop("", 0)

    names = set(vm_counts) | set(host_counts) | set(settings)
    names.discard(None)
    names.discard("")
    names.discard(NONE_SENTINEL)   # handled separately

    items = [{
        "name": n,
        "vm_count": vm_counts.get(n, 0),
        "host_count": host_counts.get(n, 0),
        "visible": settings.get(n, True),       # no setting -> considered visible
        "in_inventory": n in vm_counts or n in host_counts,
        "is_none": False,
    } for n in sorted(names)]

    # The "(No cluster)" group: listed when the inventory has blank-cluster
    # records or the hide setting was made at least once
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


def _set_one(db, name: str, visible: bool) -> bool:
    """Upsert one visibility row; True when the value actually changed."""
    setting = db.query(ClusterSetting).filter_by(name=name).first()
    if setting is None:
        if visible:
            return False            # no row = visible already
        setting = ClusterSetting(name=name)
        db.add(setting)
    elif bool(setting.visible) == visible:
        return False
    setting.visible = visible
    return True


def _display(name: str) -> str:
    return "(Cluster'sız)" if name == NONE_SENTINEL else name


@router.post("/visibility")
def set_visibility(payload: VisibilityPayload, request: Request,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_role("operator"))):
    """Show/hide a cluster. Operator and above. Global: affects every user."""
    # CSRF was not checked here before phase 148 (every other write endpoint does).
    validate_csrf(request, None)
    if not payload.name.strip():
        raise HTTPException(400, "Cluster adı boş olamaz")
    # NONE_SENTINEL is a valid name: represents the virtual "(No cluster)" group
    if _set_one(db, payload.name, payload.visible):
        log_audit(db, user, "cluster_visibility", target=_display(payload.name),
                  new=("görünür" if payload.visible else "gizli"), request=request)
    db.commit()
    return {"ok": True, "name": payload.name, "visible": payload.visible}


class BulkVisibilityPayload(BaseModel):
    visible: bool
    names: list[str] = []
    all: bool = False          # apply to every known cluster (incl. the blank group)
    only: str | None = None    # "show only this one": it becomes visible, all others hidden


@router.post("/visibility/bulk")
def set_visibility_bulk(payload: BulkVisibilityPayload, request: Request,
                        db: Session = Depends(get_db),
                        user: User = Depends(require_role("operator"))):
    """Several clusters at once: "show all", "show only X", or an explicit list.

    One audit row per changed cluster, so the log reads the same as single toggles.
    """
    validate_csrf(request, None)
    known = [i["name"] for i in list_clusters(db=db, user=user)["items"]]
    if payload.only is not None:
        if payload.only not in known:
            raise HTTPException(404, "Cluster bulunamadı")
        plan = [(n, n == payload.only) for n in known]
    elif payload.all:
        plan = [(n, payload.visible) for n in known]
    else:
        plan = [(n, payload.visible) for n in payload.names if n.strip()]
    changed = []
    for name, vis in plan:
        if _set_one(db, name, vis):
            changed.append(name)
            log_audit(db, user, "cluster_visibility", target=_display(name),
                      new=("görünür" if vis else "gizli"), request=request)
    db.commit()
    return {"ok": True, "changed": changed}
