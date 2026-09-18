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
from ..models import (VirtualMachine, Tag, User, AuditLog, Host,
                      ChangeHistory, Platform)
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
            "uptime": VirtualMachine.last_boot, "pool": VirtualMachine.pool}
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
    if sort == "uptime":
        # Uptime is derived from last_boot (older boot = longer uptime), so the
        # direction is inverted: "desc" (longest uptime first) = last_boot asc.
        # VMs without a boot time (powered off) always sort to the end.
        nulls_last = VirtualMachine.last_boot.is_(None)
        if order == "desc":
            query = query.order_by(nulls_last.asc(), VirtualMachine.last_boot.asc())
        else:
            query = query.order_by(nulls_last.asc(), VirtualMachine.last_boot.desc())
    else:
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


def _disk_state(total, disks):
    """Classify a VM's disk data -> (state, disks_sum, human verdict).

    states: ok | mismatch | diskless | detail_missing
    A diskless VM (no disks AND a zero/absent total) is NORMAL, not a fault:
    both sides agree that there is nothing to report.
    """
    dsum = round(sum(float(d.get("size_gb") or 0) for d in disks), 1) if disks else None
    t = round(total, 1) if total is not None else None
    if disks:
        if t is not None and abs(dsum - t) < 0.2:
            return "ok", dsum, f"Tutarlı — {t} GB / {len(disks)} disk"
        return "mismatch", dsum, (f"TUTARSIZ — liste sütunu {t} GB diyor, "
                                  f"disk detayı {dsum} GB ({len(disks)} disk)")
    if not t:
        return "diskless", None, "Disksiz VM — disk tanımlı değil (normal)"
    return "detail_missing", None, (f"Disk detayı okunamadı — toplam "
                                    f"platformdan geliyor ({t} GB)")


@router.get("/disk-diag")
def disk_diagnostics(name: str = "", db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    """Admin-only: check that each VM's disk total agrees with its per-disk
    detail, to diagnose 'the list shows the wrong disk size'.

    Without `name` only the VMs worth looking at are listed (mismatching total,
    or a total with no readable detail); diskless VMs are counted, not listed.
    With `name` every matching VM is listed, including the healthy ones.
    """
    q = db.query(VirtualMachine).filter_by(is_template=False)
    if name:
        q = q.filter(VirtualMachine.name.ilike(f"%{name.strip()}%"))
    ptypes = {p.id: p.type for p in db.query(Platform).all()}
    counts = {"ok": 0, "mismatch": 0, "diskless": 0, "detail_missing": 0}
    items = []
    for vm in q.order_by(VirtualMachine.name).all():
        try:
            disks = json.loads(vm.disks_json or "[]")
        except (ValueError, TypeError):
            disks = []
        state, dsum, verdict = _disk_state(vm.disk_total_gb, disks)
        counts[state] += 1
        if not name and state in ("ok", "diskless"):
            continue                       # nothing to look at
        hist = (db.query(ChangeHistory)
                .filter(ChangeHistory.entity_type == "vm",
                        ChangeHistory.entity_name == vm.name,
                        ChangeHistory.field == "disk_total_gb")
                .order_by(ChangeHistory.changed_at.desc()).limit(3).all())
        items.append({
            "vm": vm.name,
            "durum": verdict,
            "state": state,
            "liste_sutunu_gb": (round(vm.disk_total_gb, 1)
                                if vm.disk_total_gb is not None else None),
            "disk_detayi_gb": dsum,
            "disk_sayisi": len(disks),
            "diskler": "; ".join(
                f"{d.get('label') or d.get('name') or 'disk'}: {d.get('size_gb')} GB"
                for d in disks) or "—",
            "platform": ptypes.get(vm.platform_id, "?"),
            "external_id": vm.external_id,
            "id": vm.id,
            "son_sync": to_iso(vm.updated_at),
            "gecmis": [f"{to_iso(h.changed_at)}: {h.old_value} -> {h.new_value}"
                       for h in hist] or ["disk değişikliği kaydı yok"],
        })
    # Worst first, so the interesting rows are at the top.
    order = {"mismatch": 0, "detail_missing": 1, "diskless": 2, "ok": 3}
    items.sort(key=lambda i: (order.get(i["state"], 9), i["vm"].lower()))

    checked = sum(counts.values())
    problems = []
    if counts["mismatch"]:
        problems.append(f"{counts['mismatch']} tutarsız")
    if counts["detail_missing"]:
        problems.append(f"{counts['detail_missing']} disk detayı okunamadı")
    summary = f"{checked} VM kontrol edildi — " + (
        ", ".join(problems) if problems else "sorun yok")
    if counts["diskless"]:
        summary += f". {counts['diskless']} disksiz VM normal sayıldı"
    return {"ozet": summary + ".", "sayilar": counts,
            "listelenen": len(items), "items": items}


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
