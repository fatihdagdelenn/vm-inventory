"""Dashboard özet API'si: sayılar ve grafik verileri (tamamı lokal DB'den)."""
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
    Ana ekran kartları ve grafikler için tüm özet veriler.
    GİZLİ cluster'lardaki VM ve host'lar sayılara/grafiklere DAHİL EDİLMEZ;
    böylece dashboard yalnızca takip etmek istediğiniz ortamı yansıtır.
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

    # Host bazında CPU/RAM kullanımı (grafikler için)
    hosts = host_q().with_entities(Host.name, Host.cpu_usage_pct, Host.ram_total_mb,
                                   Host.ram_used_mb).all()
    host_usage = [{"name": h.name,
                   "cpu_pct": h.cpu_usage_pct or 0,
                   "ram_pct": round(100 * (h.ram_used_mb or 0) /
                                    max(1, h.ram_total_mb or 1), 1)} for h in hosts]

    # Datastore kullanımı
    datastores = db.query(Datastore.name, Datastore.capacity_gb,
                          Datastore.used_gb).order_by(Datastore.capacity_gb.desc()).limit(15).all()
    storage = [{"name": d.name, "capacity_gb": d.capacity_gb or 0,
                "used_gb": d.used_gb or 0} for d in datastores]

    # İşletim sistemi dağılımı (pasta grafik) — ayrıntılı aile sınıflandırması
    os_rows = db.query(VirtualMachine.guest_os, func.count(VirtualMachine.id))\
                .filter_by(is_template=False).group_by(VirtualMachine.guest_os).all()
    os_dist = os_family_distribution(os_rows)

    # Kullanım verisinin en son ne zaman tazelendiği (arayüzde gösterilir)
    usage_times = [p.last_usage_sync for p in db.query(Platform).all()
                   if p.last_usage_sync]
    usage_updated = to_iso(max(usage_times)) if usage_times else None

    last_syncs = [{"name": p.name, "type": p.type,
                   "last_sync": to_iso(p.last_sync),
                   "status": p.last_sync_status or "-"}
                  for p in db.query(Platform).all()]

    # ---- Kaynak toplamları ----
    base = vm_q()
    totals = base.with_entities(
        func.coalesce(func.sum(VirtualMachine.cpu_count), 0),
        func.coalesce(func.sum(VirtualMachine.ram_mb), 0),
        func.coalesce(func.sum(VirtualMachine.disk_total_gb), 0)).one()
    vm_suspended = vm_q().filter(VirtualMachine.power_state == "suspended").count()

    # ---- Dikkat gerektirenler (tıklanınca VM listesine filtreli gider) ----
    no_ip = base.filter(func.coalesce(VirtualMachine.ip_addresses, "") == "").count()
    no_tools = base.filter(
        (func.coalesce(VirtualMachine.tools_status, "") == "") |
        VirtualMachine.tools_status.ilike("%NotRunning%") |
        VirtualMachine.tools_status.ilike("%unknown%")).count()
    no_owner = base.filter(func.coalesce(VirtualMachine.owner, "") == "").count()

    # 30 günden eski snapshot'lar (temizlik adayı)
    from datetime import datetime as _dt, timedelta as _td
    from ..models import Snapshot
    old_snapshots = db.query(Snapshot).filter(
        Snapshot.created_at.isnot(None),
        Snapshot.created_at < _dt.utcnow() - _td(days=30)).count()

    # Yedeği hiç olmayan çalışan VM'ler (yalnızca Proxmox; vCenter'da yedek API'si yok)
    from ..models import Backup
    backed_up = {r[0] for r in db.query(Backup.vm_id).distinct().all() if r[0]}
    no_backup = base.filter(VirtualMachine.power_state == "running") \
        .join(Platform, VirtualMachine.platform_id == Platform.id) \
        .filter(Platform.type == "proxmox",
                ~VirtualMachine.id.in_(backed_up) if backed_up else True).count()

    # ---- Ortam ve cluster dağılımları ----
    env_dist = {r[0] or "—": r[1] for r in base.with_entities(
        VirtualMachine.environment, func.count(VirtualMachine.id))
        .group_by(VirtualMachine.environment).all()}
    cluster_rows = base.with_entities(
        VirtualMachine.cluster, func.count(VirtualMachine.id))\
        .group_by(VirtualMachine.cluster)\
        .order_by(func.count(VirtualMachine.id).desc()).limit(10).all()
    cluster_dist = [{"key": r[0] or "—", "count": r[1]} for r in cluster_rows]

    # ---- En çok kullanılan işletim sistemleri (detaylı, ilk 8) ----
    top_os = [{"key": r[0] or "Bilinmiyor", "count": r[1]} for r in
              base.with_entities(VirtualMachine.guest_os,
                                 func.count(VirtualMachine.id))
              .group_by(VirtualMachine.guest_os)
              .order_by(func.count(VirtualMachine.id).desc()).limit(8).all()]

    # ---- En çok kaynak tüketen VM'ler (çalışanlar, ilk 8) — büyükten küçüğe ----
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

    # Disk: agent'sız Proxmox'ta kullanılan disk (disk_used_gb) 0 gelir; o yüzden
    # kullanılan yoksa AYRILAN diske (disk_total_gb) düşeriz — kart hiç boş kalmaz.
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

    # ---- Host bazında VM dağılımı (büyükten küçüğe, ilk 12) ----
    host_vm_dist = [{"name": r[0] or "—", "count": r[1]} for r in
                    base.outerjoin(Host, VirtualMachine.host_id == Host.id)
                    .with_entities(Host.name, func.count(VirtualMachine.id))
                    .group_by(Host.name)
                    .order_by(func.count(VirtualMachine.id).desc()).limit(12).all()]

    # ---- Cluster bazında kaynak kullanımı (vCPU/RAM, ilk 10) ----
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

    # ---- Datastore doluluk (%) — büyükten küçüğe, ilk 12 ----
    datastore_fill = [{"name": d.name + (f" ({d.node})" if d.node else ""),
                       "usage_pct": d.usage_pct, "used_gb": round(d.used_gb or 0, 1),
                       "capacity_gb": round(d.capacity_gb or 0, 1)}
                      for d in db.query(Datastore)
                      .order_by((Datastore.used_gb /
                                 func.nullif(Datastore.capacity_gb, 0)).desc().nullslast())
                      .limit(12).all()]

    # ---- Son envanter değişiklikleri (10 kayıt) ----
    from ..models import ChangeHistory
    changes = db.query(ChangeHistory)\
                .order_by(ChangeHistory.changed_at.desc()).limit(10).all()
    recent_changes = [{"changed_at": to_iso(c.changed_at),
                       "entity_type": c.entity_type, "entity_name": c.entity_name,
                       "change_type": c.change_type, "field": c.field,
                       "old_value": c.old_value, "new_value": c.new_value}
                      for c in changes]

    return {"vcenter_count": vcenter_count, "proxmox_count": proxmox_count,
            "host_count": host_count, "vm_total": vm_total,
            "vm_running": vm_running, "vm_stopped": vm_stopped,
            "vm_suspended": vm_suspended,
            "total_vcpu": int(totals[0]),
            "total_ram_gb": round(totals[1] / 1024, 1),
            "total_disk_tb": round(totals[2] / 1024, 2),
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
