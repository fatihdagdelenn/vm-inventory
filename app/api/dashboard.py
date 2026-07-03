"""Dashboard summary API: counters and chart data (all from the local DB)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Platform, Host, VirtualMachine, Datastore, User
from ..core.timezone import to_iso
from ..core.security import get_current_user
from ..core.os_family import distribution as os_family_distribution

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
        All summary data for the main-screen cards and charts.
        VMs and hosts in HIDDEN clusters are EXCLUDED from counts/charts.
        """
    from .clusters import hidden_cluster_names, hidden_vm_filter
    hidden = hidden_cluster_names(db)
    vm_cond = hidden_vm_filter(db, VirtualMachine)
    host_cond = hidden_vm_filter(db, Host)

    def vm_q():
        q = db.query(VirtualMachine).filter_by(is_template=False)
        return q.filter(vm_cond) if vm_cond is not None else q

    def host_q():
        q = db.query(Host)
        return q.filter(host_cond) if host_cond is not None else q

    vcenter_count = db.query(Platform).filter_by(type="vcenter").count()
    proxmox_count = db.query(Platform).filter_by(type="proxmox").count()
    host_count = host_q().count()
    vm_total = vm_q().count()
    vm_running = vm_q().filter_by(power_state="running").count()
    vm_stopped = vm_q().filter_by(power_state="stopped").count()

    # Per-host CPU/RAM usage (for charts)
    hosts = host_q().with_entities(Host.name, Host.cpu_usage_pct, Host.ram_total_mb,
                                   Host.ram_used_mb).all()
    host_usage = [{"name": h.name,
                   "cpu_pct": h.cpu_usage_pct or 0,
                   "ram_pct": round(100 * (h.ram_used_mb or 0) /
                                    max(1, h.ram_total_mb or 1), 1)} for h in hosts]

    # Datastore usage
    datastores = db.query(Datastore.name, Datastore.capacity_gb,
                          Datastore.used_gb).order_by(Datastore.capacity_gb.desc()).limit(15).all()
    storage = [{"name": d.name, "capacity_gb": d.capacity_gb or 0,
                "used_gb": d.used_gb or 0} for d in datastores]

    # OS distribution (pie) with detailed family classification
    os_rows = db.query(VirtualMachine.guest_os, func.count(VirtualMachine.id))\
                .filter_by(is_template=False).group_by(VirtualMachine.guest_os).all()
    os_dist = os_family_distribution(os_rows)

    # When usage data was last refreshed (shown in the UI)
    usage_times = [p.last_usage_sync for p in db.query(Platform).all()
                   if p.last_usage_sync]
    usage_updated = to_iso(max(usage_times)) if usage_times else None

    last_syncs = [{"name": p.name, "type": p.type,
                   "last_sync": to_iso(p.last_sync),
                   "status": p.last_sync_status or "-"}
                  for p in db.query(Platform).all()]

    # ---- Resource totals ----
    base = vm_q()
    totals = base.with_entities(
        func.coalesce(func.sum(VirtualMachine.cpu_count), 0),
        func.coalesce(func.sum(VirtualMachine.ram_mb), 0),
        func.coalesce(func.sum(VirtualMachine.disk_total_gb), 0)).one()
    vm_suspended = vm_q().filter(VirtualMachine.power_state == "suspended").count()

    # ---- Needs-attention items (click -> filtered VM list) ----
    no_ip = base.filter(func.coalesce(VirtualMachine.ip_addresses, "") == "").count()
    no_tools = base.filter(
        (func.coalesce(VirtualMachine.tools_status, "") == "") |
        VirtualMachine.tools_status.ilike("%NotRunning%") |
        VirtualMachine.tools_status.ilike("%unknown%")).count()
    no_owner = base.filter(func.coalesce(VirtualMachine.owner, "") == "").count()

    # Snapshots older than 30 days (cleanup candidates)
    from datetime import datetime as _dt, timedelta as _td
    from ..models import Snapshot
    old_snapshots = db.query(Snapshot).filter(
        Snapshot.created_at.isnot(None),
        Snapshot.created_at < _dt.utcnow() - _td(days=30)).count()

    # Running VMs with no backup (Proxmox only; vCenter has no backup API)
    from ..models import Backup
    backed_up = {r[0] for r in db.query(Backup.vm_id).distinct().all() if r[0]}
    no_backup = base.filter(VirtualMachine.power_state == "running") \
        .join(Platform, VirtualMachine.platform_id == Platform.id) \
        .filter(Platform.type == "proxmox",
                ~VirtualMachine.id.in_(backed_up) if backed_up else True).count()

    # ---- Environment and cluster distributions ----
    env_dist = {r[0] or "—": r[1] for r in base.with_entities(
        VirtualMachine.environment, func.count(VirtualMachine.id))
        .group_by(VirtualMachine.environment).all()}
    cluster_rows = base.with_entities(
        VirtualMachine.cluster, func.count(VirtualMachine.id))\
        .group_by(VirtualMachine.cluster)\
        .order_by(func.count(VirtualMachine.id).desc()).limit(10).all()
    cluster_dist = [{"key": r[0] or "—", "count": r[1]} for r in cluster_rows]

    # ---- Most used operating systems (detailed, top 8) ----
    top_os = [{"key": r[0] or "Bilinmiyor", "count": r[1]} for r in
              base.with_entities(VirtualMachine.guest_os,
                                 func.count(VirtualMachine.id))
              .group_by(VirtualMachine.guest_os)
              .order_by(func.count(VirtualMachine.id).desc()).limit(8).all()]

    # ---- Top resource-consuming VMs (running, top 8, desc) ----
    running = base.filter(VirtualMachine.power_state == "running")

    def _running_top(cols, order_col, limit=8):
        return (running.outerjoin(Host, VirtualMachine.host_id == Host.id)
                       .with_entities(*cols)
                       .order_by(order_col.desc()).limit(limit).all())

    top_cpu_vms = [{"name": r[0], "host": r[1] or "", "cluster": r[2] or "",
                    "pct": round(r[3] or 0, 1)}
                   for r in _running_top(
                       [VirtualMachine.name, Host.name, VirtualMachine.cluster,
                        VirtualMachine.cpu_usage_pct], VirtualMachine.cpu_usage_pct)
                   if (r[3] or 0) > 0]

    ram_pct = VirtualMachine.ram_usage_mb * 100.0 / func.nullif(VirtualMachine.ram_mb, 0)
    top_ram_vms = [{"name": r[0], "host": r[1] or "", "cluster": r[2] or "",
                    "pct": round(r[3] or 0, 1), "used_gb": round((r[4] or 0) / 1024, 1)}
                   for r in _running_top(
                       [VirtualMachine.name, Host.name, VirtualMachine.cluster,
                        ram_pct, VirtualMachine.ram_usage_mb], ram_pct)
                   if (r[3] or 0) > 0]

    # Disk: on agentless Proxmox used disk is 0, so fall back to allocated disk
    # (disk_total_gb) when used is missing, so the card is never empty.
    disk_metric = func.coalesce(func.nullif(VirtualMachine.disk_used_gb, 0),
                                VirtualMachine.disk_total_gb)
    top_disk_vms = [{"name": r[0], "host": r[1] or "", "cluster": r[2] or "",
                     "used_gb": round(r[3] or 0, 1), "total_gb": round(r[4] or 0, 1),
                     "value_gb": round((r[3] or r[4] or 0), 1),
                     "is_used": bool(r[3] and r[3] > 0)}
                    for r in _running_top(
                        [VirtualMachine.name, Host.name, VirtualMachine.cluster,
                         VirtualMachine.disk_used_gb, VirtualMachine.disk_total_gb],
                        disk_metric)
                    if (r[3] or r[4] or 0) > 0]

    # ---- VM distribution per host (desc, top 12) ----
    host_vm_dist = [{"name": r[0] or "—", "count": r[1]} for r in
                    base.outerjoin(Host, VirtualMachine.host_id == Host.id)
                    .with_entities(Host.name, func.count(VirtualMachine.id))
                    .group_by(Host.name)
                    .order_by(func.count(VirtualMachine.id).desc()).limit(12).all()]

    # ---- Resource usage per cluster (vCPU/RAM, top 10) ----
    cluster_resource = [{"key": r[0] or "—", "vcpu": int(r[1] or 0),
                         "ram_gb": round((r[2] or 0) / 1024, 1), "vms": r[3]}
                        for r in base.with_entities(
                            VirtualMachine.cluster,
                            func.coalesce(func.sum(VirtualMachine.cpu_count), 0),
                            func.coalesce(func.sum(VirtualMachine.ram_mb), 0),
                            func.count(VirtualMachine.id))
                        .group_by(VirtualMachine.cluster)
                        .order_by(func.coalesce(func.sum(VirtualMachine.cpu_count), 0).desc())
                        .limit(10).all()]

    # ---- Datastore usage (%) (desc, top 12) ----
    datastore_fill = [{"name": d.name + (f" ({d.node})" if d.node else ""),
                       "usage_pct": d.usage_pct, "used_gb": round(d.used_gb or 0, 1),
                       "capacity_gb": round(d.capacity_gb or 0, 1)}
                      for d in db.query(Datastore)
                      .order_by((Datastore.used_gb /
                                 func.nullif(Datastore.capacity_gb, 0)).desc().nullslast())
                      .limit(12).all()]

    # ---- Recent inventory changes (10 rows) ----
    from ..models import ChangeHistory
    changes = db.query(ChangeHistory)\
                .order_by(ChangeHistory.changed_at.desc()).limit(10).all()
    recent_changes = [{"changed_at": to_iso(c.changed_at),
                       "entity_type": c.entity_type, "entity_name": c.entity_name,
                       "change_type": c.change_type, "field": c.field,
                       "old_value": c.old_value, "new_value": c.new_value}
                      for c in changes]

    # Physical ceilings (allocated vs total on the mini cards)
    _hc = host_q().with_entities(func.coalesce(func.sum(Host.cpu_cores), 0),
                                 func.coalesce(func.sum(Host.ram_total_mb), 0)).one()
    _dc = db.query(func.coalesce(func.sum(Datastore.capacity_gb), 0)).scalar() or 0
    phys = {"cores": int(_hc[0] or 0),
            "ram_gb": round(float(_hc[1] or 0) / 1024, 1),
            "disk_tb": round(float(_dc) / 1024, 2)}
    # Oldest 30d+ snapshots (widget)
    from datetime import datetime as _dt2, timedelta as _td2
    _cut = _dt2.utcnow() - _td2(days=7)   # widget filters 7+/14+/30+ client-side
    old_snapshot_items = [
        {"vm": r.vm_name, "name": r.name,
         "days": (_dt2.utcnow() - r.created_at).days if r.created_at else None}
        for r in db.query(Snapshot).filter(Snapshot.created_at != None,  # noqa: E711
                                           Snapshot.created_at < _cut)
                   .order_by(Snapshot.created_at.asc()).limit(40).all()]

    return {"vcenter_count": vcenter_count, "proxmox_count": proxmox_count,
            "host_count": host_count, "vm_total": vm_total,
            "vm_running": vm_running, "vm_stopped": vm_stopped,
            "vm_suspended": vm_suspended,
            "total_vcpu": int(totals[0]),
            "total_ram_gb": round(totals[1] / 1024, 1),
            "total_disk_tb": round(totals[2] / 1024, 2),
            "phys": phys, "old_snapshot_items": old_snapshot_items,
            "attention": {"no_ip": no_ip, "no_tools": no_tools, "no_owner": no_owner,
                          "old_snapshots": old_snapshots, "no_backup": no_backup},
            "env_distribution": env_dist, "cluster_distribution": cluster_dist,
            "top_os": top_os, "recent_changes": recent_changes,
            "top_cpu_vms": top_cpu_vms, "top_ram_vms": top_ram_vms,
            "top_disk_vms": top_disk_vms, "host_vm_dist": host_vm_dist,
            "cluster_resource": cluster_resource, "datastore_fill": datastore_fill,
            "host_usage": host_usage, "storage": storage,
            "os_distribution": os_dist, "platforms": last_syncs,
            "hidden_clusters": len(hidden),
            "usage_updated": usage_updated}


def _to_float(v):
    """ChangeHistory old/new values are raw numbers (ram_mb=MB,
        disk_total_gb=GB); safely parse the first number out of the text."""
    try:
        return float(str(v).strip().split()[0].replace(",", "."))
    except (TypeError, ValueError, IndexError):
        return None


@router.get("/insights")
def insights(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
        Premium 'smart' metrics: capacity forecast, zombie (idle) VMs, small trend
        series (sparklines) and liveness/sync info.
        """
    from datetime import datetime as _dt, timedelta as _td
    from .clusters import hidden_cluster_names, hidden_vm_filter
    from ..models import ChangeHistory
    from ..core.app_settings import get_int_setting

    vm_cond = hidden_vm_filter(db, VirtualMachine)
    host_cond = hidden_vm_filter(db, Host)

    def vm_q():
        q = db.query(VirtualMachine).filter_by(is_template=False)
        return q.filter(vm_cond) if vm_cond is not None else q

    def host_q():
        q = db.query(Host)
        return q.filter(host_cond) if host_cond is not None else q

    now = _dt.utcnow()
    from ..models import CapacitySnapshot, VmUsageDaily

    # ===== Capacity Forecast =====
    # Two SEPARATE concepts (kept distinct on purpose):
    #   - USAGE      = actually USED / physical capacity -> the thing that runs out.
    #                  Disk: datastore used/capacity. RAM: consumed RAM / physical RAM.
    #   - ALLOCATION = provisioned to VMs / physical capacity. May exceed 100%
    #                  (overcommit) which is normal and NOT the same as usage.
    #   The forecast (days left) is based only on the daily growth of USAGE.

    # Allocation + consumed RAM (whole environment)
    g = db.query(
        func.coalesce(func.sum(VirtualMachine.ram_mb), 0),
        func.coalesce(func.sum(VirtualMachine.disk_total_gb), 0),
        func.coalesce(func.sum(VirtualMachine.ram_usage_mb), 0)).filter(
        VirtualMachine.is_template == False).one()  # noqa: E712
    alloc_ram_gb = round(float(g[0] or 0) / 1024, 1)
    alloc_disk_gb = round(float(g[1] or 0), 1)
    used_ram_gb = round(float(g[2] or 0) / 1024, 1)        # real consumed RAM

    ram_cap_gb = round(float(db.query(func.coalesce(func.sum(Host.ram_total_mb), 0)).scalar() or 0) / 1024, 1)
    host_cpu_rows = db.query(Host.cpu_cores, Host.cpu_usage_pct).all()
    cpu_cores_total = sum(int(c or 0) for c, _ in host_cpu_rows)
    _w = sum(int(c or 0) * float(u or 0) for c, u in host_cpu_rows)
    used_cpu_cores = round(_w / 100.0, 1) if cpu_cores_total else 0.0
    alloc_vcpu_total = int(db.query(func.coalesce(func.sum(VirtualMachine.cpu_count), 0))
                           .filter(VirtualMachine.is_template == False).scalar() or 0)  # noqa: E712
    ds = db.query(func.coalesce(func.sum(Datastore.capacity_gb), 0),
                  func.coalesce(func.sum(Datastore.used_gb), 0)).one()
    disk_cap_gb = round(float(ds[0] or 0), 1)
    used_disk_gb = round(float(ds[1] or 0), 1)             # real datastore fill

    try:
        snaps = db.query(CapacitySnapshot).filter(
            CapacitySnapshot.snap_date >= (now.date() - _td(days=30))).order_by(
            CapacitySnapshot.snap_date).all()
    except Exception:
        snaps = []

    def _slope(points):
        """Least-squares slope (unit: y / day). points=[(day_index, y)]."""
        n = len(points)
        if n < 2:
            return None
        sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
        sxx = sum(p[0] ** 2 for p in points); sxy = sum(p[0] * p[1] for p in points)
        denom = n * sxx - sx * sx
        return (n * sxy - sx * sy) / denom if denom else None

    # Threshold intentionally high: >=4 points + >=4 day span, else "collecting".
    MIN_PTS, MIN_SPAN = 4, 4
    span = (snaps[-1].snap_date - snaps[0].snap_date).days if len(snaps) >= 2 else 0
    reg_ok = len(snaps) >= MIN_PTS and span >= MIN_SPAN
    per_day_disk_gb = per_day_ram_gb = 0.0
    if reg_ok:
        base = snaps[0].snap_date
        # Slope of the USAGE series, not allocation. On old snapshots
        # datastore_used_gb NULL olabilir → o noktalar elenir (kirletmesin).
        slope_disk = _slope([((s.snap_date - base).days, float(s.datastore_used_gb))
                             for s in snaps if s.datastore_used_gb is not None])
        slope_ram = _slope([((s.snap_date - base).days, float(s.used_ram_mb) / 1024)
                            for s in snaps if s.used_ram_mb is not None])
        per_day_disk_gb = max(0.0, slope_disk or 0)
        per_day_ram_gb = max(0.0, slope_ram or 0)
        slope_cpu = _slope([(i, (s.used_cpu_pct or 0) * (s.host_cpu_cores or 0) / 100.0)
                            for i, s in enumerate(snaps) if s.used_cpu_pct is not None
                            and s.host_cpu_cores])
        per_day_cpu_cores = max(0.0, slope_cpu or 0)
        fc_method = "trend"
    else:
        fc_method = "collecting"
        per_day_cpu_cores = 0.0
    fc_window = span
    days_collected = len(snaps)
    days_needed = MIN_SPAN + 1

    def _forecast(cap_gb, used_gb, alloc_gb, per_day_gb):
        cap_gb = float(cap_gb); used_gb = float(used_gb)
        alloc_gb = float(alloc_gb); per_day_gb = float(per_day_gb)
        remaining = round(cap_gb - used_gb, 1)
        used_pct = round(100 * used_gb / cap_gb, 1) if cap_gb > 0 else None
        alloc_pct = round(100 * alloc_gb / cap_gb, 1) if cap_gb > 0 else None
        days = None
        if fc_method == "trend" and cap_gb > 0 and per_day_gb > 0.01 and remaining > 0:
            days = int(remaining / per_day_gb)
        if fc_method == "collecting":
            status = "collecting"
        elif days is not None:
            status = "crit" if days < 30 else "warn" if days < 90 else "ok"
        elif cap_gb > 0 and remaining <= 0:
            status = "crit"
        else:
            status = "stable"
        return {"capacity_gb": cap_gb, "used_gb": used_gb, "used_pct": used_pct,
                "allocated_gb": alloc_gb, "alloc_pct": alloc_pct,
                "overcommit": (alloc_pct is not None and alloc_pct > 100),
                "remaining_gb": remaining, "per_day_gb": round(per_day_gb, 2),
                "days_left": days, "status": status}

    forecast = {"window_days": fc_window, "method": fc_method,
                "days_collected": days_collected, "days_needed": days_needed,
                "disk": _forecast(disk_cap_gb, used_disk_gb, alloc_disk_gb, per_day_disk_gb),
                "ram": _forecast(ram_cap_gb, used_ram_gb, alloc_ram_gb, per_day_ram_gb),
                "cpu": _forecast(cpu_cores_total, used_cpu_cores, alloc_vcpu_total,
                                 per_day_cpu_cores)}

    # ===== Zombie (idle) VMs - MULTI-METRIC CORRELATION =====
    # CPU alone is misleading (false positives). Over a 14-30 day window CPU/RAM/Disk/Net
    # are evaluated together (core.zombie.score_vm). Missing metrics are not penalized.
    from ..core import zombie as zlib

    def _f(x):
        return float(x) if x is not None else None

    ZWIN = 30
    zsince = now.date() - _td(days=ZWIN)
    try:
        zrows = db.query(
            VmUsageDaily.vm_id,
            func.avg(VmUsageDaily.cpu_avg), func.max(VmUsageDaily.cpu_max),
            func.avg(VmUsageDaily.ram_avg_mb), func.min(VmUsageDaily.ram_min_mb),
            func.max(VmUsageDaily.ram_max_mb), func.avg(VmUsageDaily.net_kbps),
            func.avg(VmUsageDaily.diskio_kbps), func.count(VmUsageDaily.id),
        ).filter(VmUsageDaily.day >= zsince).group_by(VmUsageDaily.vm_id).all()
    except Exception:
        zrows = []
    wstats = {r[0]: dict(cpu_avg=_f(r[1]), cpu_max=_f(r[2]), ram_avg=_f(r[3]),
                         ram_min=_f(r[4]), ram_max=_f(r[5]), net=_f(r[6]),
                         disk=_f(r[7]), days=int(r[8] or 0)) for r in zrows}

    zombies = []
    if wstats:
        zombie_basis = "14-30d"
        zvms = vm_q().filter(VirtualMachine.power_state == "running").outerjoin(
            Host, VirtualMachine.host_id == Host.id).with_entities(
            VirtualMachine.id, VirtualMachine.name, Host.name,
            VirtualMachine.cpu_count, VirtualMachine.ram_mb,
            VirtualMachine.disk_total_gb).all()
        for vid, name, hname, vcpu, ram_mb, disk_gb in zvms:
            st = wstats.get(vid)
            if not st:
                continue
            res = zlib.score_vm(cpu_avg=st["cpu_avg"], cpu_max=st["cpu_max"],
                                ram_avg_mb=st["ram_avg"], ram_min_mb=st["ram_min"],
                                ram_max_mb=st["ram_max"], net_kbps=st["net"],
                                diskio_kbps=st["disk"], days=st["days"])
            if res["klass"] == "Aktif":
                continue
            zombies.append({"name": name, "host": hname or "", "vcpu": vcpu or 0,
                            "ram_gb": round((ram_mb or 0) / 1024, 1),
                            "disk_gb": round(disk_gb or 0, 1),
                            "score": res["score"], "klass": res["klass"],
                            "klass_code": res["klass_code"],
                            "confidence": res["confidence"],
                            "confidence_code": res["confidence_code"],
                            "reasons": res["reasons"], "reasons_s": res["reasons_s"]})
        zombies.sort(key=lambda z: z["score"], reverse=True)
    else:
        # No historical data (fresh install) -> fall back to instant CPU (temporary).
        zombie_basis = "instant"
        zrows2 = vm_q().filter(VirtualMachine.power_state == "running",
                               VirtualMachine.cpu_usage_pct.isnot(None),
                               VirtualMachine.cpu_usage_pct < 2.0).outerjoin(
            Host, VirtualMachine.host_id == Host.id).with_entities(
            VirtualMachine.name, Host.name, VirtualMachine.cpu_count,
            VirtualMachine.ram_mb, VirtualMachine.disk_total_gb,
            VirtualMachine.cpu_usage_pct).order_by(
            func.coalesce(VirtualMachine.ram_mb, 0).desc()).all()
        zombies = [{"name": r[0], "host": r[1] or "", "vcpu": r[2] or 0,
                    "ram_gb": round((r[3] or 0) / 1024, 1),
                    "disk_gb": round(r[4] or 0, 1),
                    "score": None, "klass": "Şüpheli (Sahibine Sor)",
                    "klass_code": "suspect",
                    "confidence": "düşük", "confidence_code": "low",
                    "reasons": [f"Anlık CPU %{round(r[5] or 0, 1)} (tarihsel veri yok)"],
                    "reasons_s": [{"m": "instant", "cpu": round(r[5] or 0, 1)}]}
                   for r in zrows2]

    zombie_savings = {
        "count": len(zombies),
        "vcpu": sum(z["vcpu"] for z in zombies),
        "ram_gb": round(sum(z["ram_gb"] for z in zombies), 1),
        "disk_gb": round(sum(z["disk_gb"] for z in zombies), 1),
    }

    # ---- Sparkline series (last 14 days) ----
    DAYS = 14
    # Daily new VMs (first_seen) -> cumulative VM count
    fs = [r[0] for r in vm_q().with_entities(VirtualMachine.first_seen).all() if r[0]]
    total_vms = vm_q().count()
    spark_vms = []
    for i in range(DAYS - 1, -1, -1):
        day_end = (now - _td(days=i)).replace(hour=23, minute=59, second=59)
        created_after = sum(1 for d in fs if d > day_end)
        spark_vms.append(max(0, total_vms - created_after))
    # Daily change activity
    spark_activity = []
    for i in range(DAYS - 1, -1, -1):
        d0 = (now - _td(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = d0 + _td(days=1)
        spark_activity.append(db.query(ChangeHistory).filter(
            ChangeHistory.changed_at >= d0, ChangeHistory.changed_at < d1).count())

    # ---- Liveness / sync info ----
    last_syncs = [p.last_sync for p in db.query(Platform).all() if p.last_sync]
    last_sync = to_iso(max(last_syncs)) if last_syncs else None
    sync_interval = get_int_setting(db, "sync_interval_minutes", 15)

    return {"forecast": forecast,
            "zombies": zombies[:10], "zombie_savings": zombie_savings,
            "zombie_basis": zombie_basis,
            "spark": {"vms": spark_vms, "activity": spark_activity},
            "live": {"last_sync": last_sync, "interval_minutes": sync_interval}}
