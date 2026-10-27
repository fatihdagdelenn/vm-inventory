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
from ..models import VirtualMachine, Host, ClusterSetting, ClusterAlias, AuditLog, Platform
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

    alias_names = _alias_names(db)
    items = [{
        "name": n,
        "vm_count": vm_counts.get(n, 0),
        "host_count": host_counts.get(n, 0),
        "visible": settings.get(n, True),       # no setting -> considered visible
        "in_inventory": n in vm_counts or n in host_counts,
        "is_none": False,
        "is_alias": n in alias_names,
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
            "is_alias": False,
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


# ---------------------------------------------------------------------------
# Cluster aliases for standalone hosts (phase 148b)
# ---------------------------------------------------------------------------

def _alias_names(db) -> set:
    """Cluster names that currently come from an alias (or are defined as one)."""
    names = {r[0] for r in db.query(ClusterAlias.alias).distinct()}
    names |= {r[0] for r in db.query(VirtualMachine.cluster)
              .filter(VirtualMachine.cluster_is_alias == True).distinct()}  # noqa: E712
    names |= {r[0] for r in db.query(Host.cluster)
              .filter(Host.cluster_is_alias == True).distinct()}  # noqa: E712
    names.discard(None)
    names.discard("")
    return names


def _real_cluster_names(db) -> set:
    """Cluster names reported by a platform (not produced by an alias)."""
    blank = func.coalesce(VirtualMachine.cluster, "") == ""
    vm = {r[0] for r in db.query(VirtualMachine.cluster)
          .filter(~blank, func.coalesce(VirtualMachine.cluster_is_alias, False) == False)  # noqa: E712
          .distinct()}
    hblank = func.coalesce(Host.cluster, "") == ""
    hs = {r[0] for r in db.query(Host.cluster)
          .filter(~hblank, func.coalesce(Host.cluster_is_alias, False) == False)  # noqa: E712
          .distinct()}
    return {n for n in vm | hs if n}


def _aliasable(col_cluster, col_flag):
    """Rows whose cluster may be (re)written by an alias: blank or alias-made."""
    from sqlalchemy import or_
    return or_(func.coalesce(col_cluster, "") == "", col_flag == True)  # noqa: E712


@router.get("/standalone")
def standalone_hosts(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Hosts the platform reports without a cluster, grouped by platform,
    with their VM count and current alias. These make up "(Cluster'sız)"
    unless an alias names them."""
    aliases = {(a.platform_id, a.host_name): a.alias for a in db.query(ClusterAlias)}
    hosts = (db.query(Host).filter(_aliasable(Host.cluster, Host.cluster_is_alias))
               .order_by(Host.name).all())
    vm_counts = dict(db.query(VirtualMachine.host_id, func.count(VirtualMachine.id))
                     .filter(VirtualMachine.is_template == False,  # noqa: E712
                             _aliasable(VirtualMachine.cluster, VirtualMachine.cluster_is_alias))
                     .group_by(VirtualMachine.host_id).all())
    plats = {p.id: p for p in db.query(Platform)}
    groups = {}
    for h in hosts:
        p = plats.get(h.platform_id)
        g = groups.setdefault(h.platform_id, {
            "platform_id": h.platform_id, "platform": p.name if p else "",
            "location": (p.location or "") if p else "", "hosts": []})
        g["hosts"].append({"host": h.name, "vm_count": vm_counts.get(h.id, 0),
                           "alias": aliases.get((h.platform_id, h.name), "")})
    # Blank-cluster VMs with no host at all cannot be named (nothing to key on)
    hostless = db.query(func.count(VirtualMachine.id)).filter(
        VirtualMachine.is_template == False, VirtualMachine.host_id.is_(None),  # noqa: E712
        func.coalesce(VirtualMachine.cluster, "") == "").scalar() or 0
    return {"groups": sorted(groups.values(), key=lambda g: g["platform"].lower()),
            "hostless_vms": hostless}


class AliasItem(BaseModel):
    platform_id: int
    host: str
    alias: str = ""            # "" removes the alias (host goes back to "(Cluster'sız)")


class AliasPayload(BaseModel):
    items: list[AliasItem]


@router.put("/aliases")
def set_aliases(payload: AliasPayload, request: Request,
                db: Session = Depends(get_db),
                user: User = Depends(require_role("operator"))):
    """Name (or un-name) standalone hosts' cluster. Applied to the inventory at
    once - no wait for the next sync - and kept by every later sync until the
    platform reports a real cluster for the host.

    Visibility carries over: a NEW alias name starts hidden when the group its
    VMs came from (the old alias, else "(Cluster'sız)") was hidden, so naming a
    hidden group does not suddenly put it back on the dashboard.
    """
    validate_csrf(request, None)
    real = _real_cluster_names(db)
    settings = {s.name: s for s in db.query(ClusterSetting)}
    done, inherited, dropped = [], [], set()
    for it in payload.items:
        host_name = it.host.strip()
        alias = " ".join(it.alias.split())          # trim + collapse inner whitespace
        if not host_name:
            continue
        if len(alias) > 128:
            raise HTTPException(400, "Takma ad en fazla 128 karakter olabilir")
        if alias == NONE_SENTINEL:
            raise HTTPException(400, "Bu ad kullanılamaz")
        if alias and alias in real:
            raise HTTPException(409, f'"{alias}" platformdan gelen gerçek bir cluster adı; '
                                     "karışmaması için başka bir ad seçin")
        host = db.query(Host).filter_by(platform_id=it.platform_id, name=host_name).first()
        if host is None:
            raise HTTPException(404, f"Host bulunamadı: {host_name}")
        rule = db.query(ClusterAlias).filter_by(platform_id=it.platform_id,
                                                host_name=host_name).first()
        prev = rule.alias if rule else ""
        if prev == alias:
            continue
        if alias:
            if rule is None:
                rule = ClusterAlias(platform_id=it.platform_id, host_name=host_name, alias=alias)
                db.add(rule)
            else:
                rule.alias = alias
            # visibility inheritance (only when the new name has no setting yet)
            if alias not in settings:
                src = settings.get(prev) if prev else None
                src = src or settings.get(NONE_SENTINEL)
                if src is not None and not src.visible:
                    cs = ClusterSetting(name=alias, visible=False)
                    db.add(cs)
                    settings[alias] = cs
                    inherited.append(alias)
        elif rule is not None:
            db.delete(rule)
        # apply now: the host and its VMs, only where the platform gave no cluster
        new_val, flag = (alias, True) if alias else ("", False)
        db.query(Host).filter(Host.id == host.id,
                              _aliasable(Host.cluster, Host.cluster_is_alias)) \
          .update({Host.cluster: new_val, Host.cluster_is_alias: flag}, synchronize_session=False)
        db.query(VirtualMachine).filter(
            VirtualMachine.host_id == host.id,
            _aliasable(VirtualMachine.cluster, VirtualMachine.cluster_is_alias)) \
          .update({VirtualMachine.cluster: new_val, VirtualMachine.cluster_is_alias: flag},
                  synchronize_session=False)
        log_audit(db, user, "cluster_alias", target=host_name,
                  old=prev or None, new=alias or None, request=request)
        done.append({"host": host_name, "alias": alias})
        if prev:
            dropped.add(prev)
    # An alias nobody uses any more leaves no trace: drop its visibility row,
    # otherwise the modal keeps listing it as "envanterde yok".
    db.flush()
    for name in dropped:
        in_use = (db.query(ClusterAlias).filter_by(alias=name).first()
                  or db.query(VirtualMachine.id).filter(VirtualMachine.cluster == name).first()
                  or db.query(Host.id).filter(Host.cluster == name).first())
        if not in_use:
            db.query(ClusterSetting).filter_by(name=name).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "changed": done, "inherited_hidden": inherited}
