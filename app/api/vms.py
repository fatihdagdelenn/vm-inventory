"""
VM API: server-side paging + search + grouping.
Works with DataTables server-side processing for 500+ VMs; search runs on
the local DB (never against the platforms).
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import VirtualMachine, Tag, User, AuditLog, Host
from ..core.timezone import to_iso
from ..core.audit import log_audit
from ..core.security import get_current_user, require_role, validate_csrf
from ..core.search import apply_vm_search
from ..core.os_family import distribution as os_family_distribution

router = APIRouter(prefix="/api/vms", tags=["vms"])

SORTABLE = {"name": VirtualMachine.name, "power_state": VirtualMachine.power_state,
            "cluster": VirtualMachine.cluster, "guest_os": VirtualMachine.guest_os,
            "agent": VirtualMachine.tools_status,
            "ram_mb": VirtualMachine.ram_mb, "cpu_count": VirtualMachine.cpu_count,
            "disk_total_gb": VirtualMachine.disk_total_gb, "vmid": VirtualMachine.vmid,
            "pool": VirtualMachine.pool}
# Text columns sort case-insensitively (true alphabetical); otherwise the DB
# sorts by byte/ASCII order (uppercase first -> not alphabetical)
CASE_INSENSITIVE = {"name", "cluster", "guest_os", "vmid", "pool"}


def _agent_state(ts, ptype) -> str:
    """3 durumlu agent/Tools durumu: running | stopped | none."""
    t = (ts or "").lower()
    if "running" in t and "notrunning" not in t:
        return "running"                       # installed + running
    if ptype == "vcenter" and "notrunning" in t:
        return "stopped"                       # Tools installed but not running
    return "none"                              # not installed / unknown


def _vm_to_dict(vm: VirtualMachine) -> dict:
    return {
        "id": vm.id, "vmid": vm.vmid, "name": vm.name,
        "ip_addresses": vm.ip_addresses, "mac_addresses": vm.mac_addresses,
        "guest_os": vm.guest_os, "cpu_count": vm.cpu_count, "ram_mb": vm.ram_mb,
        "kernel": vm.kernel, "arch": vm.arch,
        "cpu_usage_pct": vm.cpu_usage_pct, "ram_usage_mb": vm.ram_usage_mb,
        "disk_used_gb": vm.disk_used_gb,
        "disk_total_gb": vm.disk_total_gb,
        "disks": json.loads(vm.disks_json or "[]"),
        "power_state": vm.power_state,
        "host": vm.host_ref.name if vm.host_ref else "",
        "cluster": vm.cluster, "datastore": vm.datastore, "vlans": vm.vlans,
        "networks": vm.networks,
        "created_date": to_iso(vm.created_date),
        "last_boot": to_iso(vm.last_boot),
        "tools_status": vm.tools_status, "owner": vm.owner, "notes": vm.notes,
        "agent_state": _agent_state(vm.tools_status,
                                    vm.platform.type if vm.platform else ""),
        "guest_notes": vm.guest_notes,
        "dns_servers": vm.dns_servers,
        "pool": vm.pool, "folder": vm.folder,
        "platform_tags": vm.platform_tags,
        "environment": vm.environment,
        "platform": vm.platform.name if vm.platform else "",
        "platform_type": vm.platform.type if vm.platform else "",
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in vm.tags],
        "updated_at": to_iso(vm.updated_at),
    }


@router.get("")
def list_vms(q: str = "", page: int = 1, per_page: int = 50,
             sort: str = "name", order: str = "asc", group_by: str = "",
             include_hidden: bool = False,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
        Search + paging. The q parameter supports the 'ip:10.10.10.15 vlan:100'
        syntax. With group_by (cluster/os/vlan/environment/location/tag) the
        matching VMs are returned as groups.
        """
    per_page = min(per_page, 200)  # don't pull excessive data in one request
    query = db.query(VirtualMachine).options(
        joinedload(VirtualMachine.host_ref),
        joinedload(VirtualMachine.platform),
        joinedload(VirtualMachine.tags)).filter_by(is_template=False)

    if not include_hidden and "cluster:" not in (q or "").lower():
        from .clusters import hidden_vm_filter
        cond = hidden_vm_filter(db, VirtualMachine)
        if cond is not None:
            query = query.filter(cond)

    query = apply_vm_search(query, q)

    # ---- Gruplama modu ----
    if group_by:
        col = {"cluster": VirtualMachine.cluster, "os": VirtualMachine.guest_os,
               "vlan": VirtualMachine.vlans, "environment": VirtualMachine.environment,
               }.get(group_by)
        if group_by == "tag":
            rows = db.query(Tag.name, func.count(VirtualMachine.id))\
                     .join(Tag.vms).group_by(Tag.name).all()
        elif group_by == "location":
            from ..models import Platform
            rows = db.query(Platform.location, func.count(VirtualMachine.id))\
                     .join(VirtualMachine, VirtualMachine.platform_id == Platform.id)\
                     .group_by(Platform.location).all()
        elif col is not None:
            rows = query.with_entities(col, func.count(VirtualMachine.id))\
                        .group_by(col).all()
        else:
            raise HTTPException(400, "Geçersiz gruplama alanı")
        return {"groups": [{"key": r[0] or "(boş)", "count": r[1]} for r in rows]}

    total = query.count()
    if sort == "host":
        # Sort by the related host name (case-insensitive)
        query = query.outerjoin(Host, VirtualMachine.host_id == Host.id)
        sort_col = func.lower(func.coalesce(Host.name, ""))
    elif sort == "platform":
        # Sort by the related platform type (VMware/Proxmox)
        from ..models import Platform
        query = query.outerjoin(Platform, VirtualMachine.platform_id == Platform.id)
        sort_col = func.lower(func.coalesce(Platform.type, ""))
    else:
        base_col = SORTABLE.get(sort, VirtualMachine.name)
        sort_col = func.lower(base_col) if sort in CASE_INSENSITIVE else base_col
    query = query.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {"total": total, "page": page, "per_page": per_page,
            "items": [_vm_to_dict(v) for v in items]}


@router.get("/facets")
def vm_facets(include_hidden: bool = False,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """
        Distinct value lists (with counts) for the advanced filter panel.
        One request: cluster, host, platform, environment, status, OS family,
        VLAN, tag, folder.
        """
    base = db.query(VirtualMachine).filter_by(is_template=False)
    from .clusters import hidden_cluster_names, hidden_vm_filter
    hidden = hidden_cluster_names(db)
    if not include_hidden:
        cond = hidden_vm_filter(db, VirtualMachine)
        if cond is not None:
            base = base.filter(cond)

    def counted(col):
        rows = base.with_entities(col, func.count(VirtualMachine.id))\
                   .group_by(col).all()
        return sorted([{"key": r[0], "count": r[1]} for r in rows if r[0]],
                      key=lambda x: x["key"])

    # Host names (join required)
    host_rows = db.query(Host.name, func.count(VirtualMachine.id))\
                  .join(VirtualMachine, VirtualMachine.host_id == Host.id)\
                  .filter(VirtualMachine.is_template == False)\
                  .group_by(Host.name).all()

    # Platformlar
    from ..models import Platform as Pf
    plat_rows = db.query(Pf.name, func.count(VirtualMachine.id))\
                  .join(VirtualMachine, VirtualMachine.platform_id == Pf.id)\
                  .filter(VirtualMachine.is_template == False)\
                  .group_by(Pf.name).all()

    # VLANs are stored comma-separated -> parse in Python
    vlan_counts = {}
    for (vlans,) in base.with_entities(VirtualMachine.vlans).all():
        for v in (vlans or "").split(","):
            v = v.strip()
            if v:
                vlan_counts[v] = vlan_counts.get(v, 0) + 1

    # OS family (detailed: Windows / Ubuntu / Debian / Red Hat / SUSE / ...)
    os_rows = base.with_entities(
        VirtualMachine.guest_os, func.count(VirtualMachine.id))\
        .group_by(VirtualMachine.guest_os).all()
    os_families_facet = os_family_distribution(os_rows)

    # Etiketler
    tag_rows = db.query(Tag.name, func.count(VirtualMachine.id))\
                 .join(Tag.vms).group_by(Tag.name).all()

    # Cluster list: from the full inventory, with a hidden flag
    full_base = db.query(VirtualMachine).filter_by(is_template=False)
    cluster_rows = full_base.with_entities(
        VirtualMachine.cluster, func.count(VirtualMachine.id))\
        .group_by(VirtualMachine.cluster).all()
    clusters_facet = sorted(
        [{"key": r[0], "count": r[1], "hidden": r[0] in hidden}
         for r in cluster_rows if r[0]], key=lambda x: x["key"])

    return {
        "clusters": clusters_facet,
        "environments": counted(VirtualMachine.environment),
        "power_states": counted(VirtualMachine.power_state),
        "hosts": sorted([{"key": r[0], "count": r[1]} for r in host_rows],
                        key=lambda x: x["key"]),
        "platforms": sorted([{"key": r[0], "count": r[1]} for r in plat_rows],
                            key=lambda x: x["key"]),
        "vlans": sorted([{"key": k, "count": v} for k, v in vlan_counts.items()],
                        key=lambda x: (len(x["key"]), x["key"])),
        "os_families": [{"key": o["key"], "label": o["label"], "count": o["count"]}
                        for o in os_families_facet],
        "tags": sorted([{"key": r[0], "count": r[1]} for r in tag_rows],
                       key=lambda x: x["key"]),
        "pools": counted(VirtualMachine.pool),
        "folders": counted(VirtualMachine.folder),
    }


@router.get("/{vm_id}")
def get_vm(vm_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    vm = db.get(VirtualMachine, vm_id)
    if not vm:
        raise HTTPException(404, "VM bulunamadı")
    from ..models import Snapshot
    snaps = (db.query(Snapshot).filter_by(vm_id=vm.id)
               .order_by(Snapshot.created_at.asc().nullslast()).all())
    data = _vm_to_dict(vm)
    data["snapshots"] = [{
        "name": s.name, "created_at": to_iso(s.created_at),
        "age_days": s.age_days, "is_current": bool(s.is_current),
        "parent": s.parent or "", "description": s.description or "",
    } for s in snaps]
    return data


@router.patch("/{vm_id}")
def update_vm_meta(vm_id: int, request: Request, payload: dict = Body(...),
                   db: Session = Depends(get_db),
                   user: User = Depends(require_role("operator"))):
    """Update manual fields: note, owner, environment, tags (operator+)."""
    validate_csrf(request, payload.pop("csrf_token", None))
    vm = db.get(VirtualMachine, vm_id)
    if not vm:
        raise HTTPException(404, "VM bulunamadı")

    old = {"notes": vm.notes or "", "owner": vm.owner or "",
           "environment": vm.environment or "",
           "tags": ", ".join(t.name for t in vm.tags)}

    if "notes" in payload:
        vm.notes = payload["notes"]
    if "owner" in payload:
        vm.owner = payload["owner"]
    if "environment" in payload and payload["environment"] in \
            ("production", "test", "development"):
        vm.environment = payload["environment"]
    if "tags" in payload:  # tag name list; created when missing
        tags = []
        for name in payload["tags"]:
            name = name.strip()
            if not name:
                continue
            tag = db.query(Tag).filter_by(name=name).first() or Tag(name=name)
            db.add(tag)
            tags.append(tag)
        vm.tags = tags

    new = {"notes": vm.notes or "", "owner": vm.owner or "",
           "environment": vm.environment or "",
           "tags": ", ".join(t.name for t in vm.tags)}
    changed = [k for k in new if k in payload and old[k] != new[k]]
    log_audit(db, user, "update_vm", target=vm.name,
              old="; ".join(f"{k}={old[k]}" for k in changed) or None,
              new="; ".join(f"{k}={new[k]}" for k in changed) or None,
              detail=f"alanlar={list(payload.keys())}", request=request)
    db.commit()
    return _vm_to_dict(vm)
