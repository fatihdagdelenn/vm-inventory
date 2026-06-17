"""Dashboard özet API'si: sayılar ve grafik verileri (tamamı lokal DB'den)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Platform, Host, VirtualMachine, Datastore, User
from ..core.timezone import to_iso
from ..core.security import get_current_user

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

    # İşletim sistemi dağılımı (pasta grafik)
    os_rows = db.query(VirtualMachine.guest_os, func.count(VirtualMachine.id))\
                .filter_by(is_template=False).group_by(VirtualMachine.guest_os).all()
    os_dist = {}
    for os_name, count in os_rows:
        label = "Windows" if "win" in (os_name or "").lower() else \
                "Linux" if any(x in (os_name or "").lower() for x in
                               ("linux", "ubuntu", "centos", "rhel", "debian", "l26")) else "Diğer"
        os_dist[label] = os_dist.get(label, 0) + count

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
            "attention": {"no_ip": no_ip, "no_tools": no_tools, "no_owner": no_owner},
            "env_distribution": env_dist, "cluster_distribution": cluster_dist,
            "top_os": top_os, "recent_changes": recent_changes,
            "host_usage": host_usage, "storage": storage,
            "os_distribution": os_dist, "platforms": last_syncs,
            "hidden_clusters": len(hidden),
            "usage_updated": usage_updated}
