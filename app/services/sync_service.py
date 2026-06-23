"""
Senkronizasyon servisi.

Akış:
1. Zamanlayıcı (veya kullanıcı 'Tümünü Yenile' butonu) sync_all_platforms() çağırır.
2. Her platform için ilgili collector çalışır, veriler API'den çekilir.
3. upsert mantığıyla lokal veritabanı güncellenir.
4. Eski/yeni değer karşılaştırması yapılır -> ChangeHistory'ye yazılır.
5. Artık platformda olmayan VM/Host kayıtları silinir (ve geçmişe işlenir).
6. Sonuç SyncLog'a kaydedilir.

Bu sayede kullanıcı aramaları her zaman hızlı lokal verilerle çalışır.
"""
import re
import logging
from datetime import datetime

from ..database import SessionLocal
from ..models import (Platform, SyncLog, Host, VirtualMachine,
                      Network, Datastore, Snapshot, Backup, ChangeHistory)
from ..core.security import decrypt_secret
from ..collectors.vmware_collector import VMwareCollector
from ..collectors.proxmox_collector import ProxmoxCollector

logger = logging.getLogger("sync")

# Değişiklik geçmişinde izlenen VM alanları
TRACKED_VM_FIELDS = ["name", "ip_addresses", "guest_os", "cpu_count", "ram_mb",
                     "disk_total_gb", "power_state", "cluster", "datastore", "vlans"]
TRACKED_HOST_FIELDS = ["name", "mgmt_ip", "cpu_cores", "ram_total_mb", "cluster", "status"]

# Misafir agent'ı / config sorgusu geçici başarısız olunca bu alanlar "iyi" değerden
# jenerik/boş değere düşebilir. Geçmiş'i (ChangeHistory) gürültüden korumak için
# bu düşüşlerde eski (iyi) değeri koruruz.
_ENRICH_FIELDS = ("guest_os", "ip_addresses", "datastore", "vlans", "networks",
                  "mac_addresses", "kernel", "arch", "disk_total_gb",
                  "guest_notes", "platform_tags")
# Jenerik / belirsiz OS adları (agent yokken ostype/guestFullName'den gelir)
_GENERIC_OS_RE = re.compile(
    r"çekirdek|kernel\)|\bother\b|^diğer$|^linux$|^windows$|2\.6\+|2\.4 ",
    re.IGNORECASE)


def _is_generic_os(s) -> bool:
    return (not s) or bool(_GENERIC_OS_RE.search(str(s)))


def _preserve_old(field, old, new) -> bool:
    """Geçici agent/enrich düşüşünde eski iyi değer korunmalı mı?"""
    if field == "guest_os":
        return new is not None and _is_generic_os(new) and old and not _is_generic_os(old)
    if field in ("ip_addresses", "datastore", "vlans", "disk_total_gb"):
        return (not new) and bool(old)   # eski doluyken yeni boş/0 → geçici düşüş
    return False


def _record_change(db, entity_type, entity_name, platform_id, change_type,
                   field=None, old=None, new=None, actor=None):
    db.add(ChangeHistory(entity_type=entity_type, entity_name=entity_name,
                         platform_id=platform_id, change_type=change_type,
                         field=field, old_value=str(old) if old is not None else None,
                         new_value=str(new) if new is not None else None,
                         actor=actor or None))


def _build_collector(platform: Platform):
    """Platform kaydından uygun collector nesnesi oluştur (şifreleri çözerek)."""
    if platform.type == "vcenter":
        return VMwareCollector(
            host=platform.host, port=platform.port, verify_ssl=platform.verify_ssl,
            username=platform.username,
            password=decrypt_secret(platform.password_encrypted))
    return ProxmoxCollector(
        host=platform.host, port=platform.port or 8006, verify_ssl=platform.verify_ssl,
        username=platform.username,
        password=decrypt_secret(platform.password_encrypted) if platform.password_encrypted else None,
        token_name=platform.token_name,
        token_value=decrypt_secret(platform.token_value_encrypted) if platform.token_value_encrypted else None)


def sync_platform(platform_id: int):
    """Tek bir platformu senkronize et."""
    db = SessionLocal()
    log = None
    try:
        platform = db.get(Platform, platform_id)
        if not platform or not platform.enabled:
            return

        log = SyncLog(platform_id=platform.id, status="running")
        db.add(log)
        platform.last_sync_status = "running"
        db.commit()

        collector = _build_collector(platform)
        collector.connect()
        hosts_data = collector.collect_hosts()
        vms_data = collector.collect_vms()
        nets_data = collector.collect_networks()
        ds_data = collector.collect_datastores()
        try:
            snaps_data = collector.collect_snapshots()
        except Exception as exc:
            snaps_data = []
            logger.warning("Snapshot toplanamadı (%s): %s", platform.name, exc)
        try:
            backups_data = collector.collect_backups()
        except Exception as exc:
            backups_data = []
            logger.warning("Yedek toplanamadı (%s): %s", platform.name, exc)
        try:
            actors = collector.collect_recent_actors() or {}
        except Exception as exc:
            actors = {}
            logger.warning("İşlem yapan kullanıcılar alınamadı (%s): %s", platform.name, exc)
        if hasattr(collector, "disconnect"):
            collector.disconnect()

        # ---------- Host upsert ----------
        existing_hosts = {h.external_id: h for h in
                          db.query(Host).filter_by(platform_id=platform.id)}
        seen_hosts = set()
        host_by_name = {}
        for hd in hosts_data:
            seen_hosts.add(hd["external_id"])
            host = existing_hosts.get(hd["external_id"])
            if host is None:
                host = Host(platform_id=platform.id, **hd)
                db.add(host)
                _record_change(db, "host", hd["name"], platform.id, "created")
            else:
                for f in TRACKED_HOST_FIELDS:  # değişiklikleri geçmişe işle
                    if getattr(host, f) != hd.get(f) and hd.get(f) is not None:
                        _record_change(db, "host", host.name, platform.id,
                                       "updated", f, getattr(host, f), hd[f])
                for k, v in hd.items():
                    setattr(host, k, v)
            host_by_name[hd["name"]] = host
        # Artık görünmeyen host'ları sil
        for ext_id, host in existing_hosts.items():
            if ext_id not in seen_hosts:
                _record_change(db, "host", host.name, platform.id, "deleted")
                db.delete(host)
        db.flush()

        # ---------- VM upsert ----------
        existing_vms = {v.external_id: v for v in
                        db.query(VirtualMachine).filter_by(platform_id=platform.id)}
        seen_vms = set()
        for vd in vms_data:
            seen_vms.add(vd["external_id"])
            host_name = vd.pop("host_name", "")
            host_obj = host_by_name.get(host_name)
            enrich_failed = vd.pop("enrich_failed", False)
            os_from_agent = vd.pop("os_from_agent", True)   # vCenter/LXC için varsayılan: güven
            ip_from_agent = vd.pop("ip_from_agent", True)
            vm = existing_vms.get(vd["external_id"])
            if vm is None:
                vm = VirtualMachine(platform_id=platform.id,
                                    host_id=host_obj.id if host_obj else None,
                                    environment=platform.environment, **vd)
                db.add(vm)
                _record_change(db, "vm", vd["name"], platform.id, "created",
                               actor=actors.get(vd["external_id"]))
            else:
                # Bu turda VM detay sorgusu tümden başarısızsa, enrich'e bağlı
                # alanları eskiye sabitle (jenerik/boş değerlerle ezilmesin).
                if enrich_failed:
                    for f in _ENRICH_FIELDS:
                        if f in vd:
                            vd[f] = getattr(vm, f)
                # Provenance: agent bu turda OS/IP veremediyse, eski (agent kaynaklı)
                # değeri koru. Böylece "Server 2019" ↔ "Windows 10" gibi gidip gelmeler
                # (agent osinfo arada yanıt vermediğinde) Geçmiş'i kirletmez.
                if not os_from_agent and vm.guest_os:
                    for f in ("guest_os", "kernel", "arch"):
                        if f in vd:
                            vd[f] = getattr(vm, f)
                if not ip_from_agent and vm.ip_addresses:
                    for f in ("ip_addresses", "mac_addresses", "networks"):
                        if f in vd:
                            vd[f] = getattr(vm, f)
                for f in TRACKED_VM_FIELDS:
                    old, new = getattr(vm, f), vd.get(f)
                    if _preserve_old(f, old, new):   # geçici düşüş → eskiyi koru
                        vd[f] = old
                        continue
                    if old != new and new is not None:
                        _record_change(db, "vm", vm.name, platform.id,
                                       "updated", f, old, new,
                                       actor=actors.get(vm.external_id))
                for k, v in vd.items():
                    setattr(vm, k, v)
                vm.host_id = host_obj.id if host_obj else None
        for ext_id, vm in existing_vms.items():
            if ext_id not in seen_vms:
                _record_change(db, "vm", vm.name, platform.id, "deleted",
                               actor=actors.get(ext_id))
                db.delete(vm)

        # ---------- Ağ ve datastore: basit yenileme (sil-yaz) ----------
        db.query(Network).filter_by(platform_id=platform.id).delete()
        for nd in nets_data:
            db.add(Network(platform_id=platform.id, **nd))
        db.query(Datastore).filter_by(platform_id=platform.id).delete()
        # vm_count: bu platformdaki VM'lerin 'datastore' alanından (virgülle ayrık
        # depo adları) çapraz hesaplanır. Yerel Proxmox depoları için ayrıca VM'in
        # bulunduğu node, datastore'un node'u ile eşleşmelidir.
        vm_ds_rows = db.query(Host.name, VirtualMachine.datastore)\
                       .outerjoin(Host, VirtualMachine.host_id == Host.id)\
                       .filter(VirtualMachine.platform_id == platform.id,
                               VirtualMachine.is_template == False).all()

        def _ds_vm_count(ds_name, ds_node, shared):
            n = 0
            for host_name, dstr in vm_ds_rows:
                tokens = [t.strip() for t in (dstr or "").split(",") if t.strip()]
                # paylaşımlı depo tüm host'lardaki VM'lerce kullanılabilir; yerel depo
                # yalnızca kendi node'undaki VM'lerce kullanılır
                if ds_name in tokens and (shared or not ds_node or host_name == ds_node):
                    n += 1
            return n

        for dd in ds_data:
            dd["vm_count"] = _ds_vm_count(dd["name"], dd.get("node", ""),
                                          dd.get("shared", False))
            db.add(Datastore(platform_id=platform.id, **dd))

        # ---------- Snapshot'lar: sil-yaz, VM'e external_id ile bağla ----------
        db.query(Snapshot).filter_by(platform_id=platform.id).delete()
        vm_id_map = {ext: vid for ext, vid in
                     db.query(VirtualMachine.external_id, VirtualMachine.id)
                       .filter_by(platform_id=platform.id).all()}
        _snap_cols = {"vm_external_id", "vm_name", "name", "description",
                      "created_at", "is_current", "parent", "size_gb"}
        for sd in snaps_data:
            clean = {k: v for k, v in sd.items() if k in _snap_cols}
            db.add(Snapshot(platform_id=platform.id,
                            vm_id=vm_id_map.get(sd.get("vm_external_id")), **clean))

        # ---------- Yedekler: sil-yaz, VM'e vmid ile bağla (yalnızca Proxmox) ----------
        db.query(Backup).filter_by(platform_id=platform.id).delete()
        vmid_map = {str(vid): (i, nm) for vid, i, nm in
                    db.query(VirtualMachine.vmid, VirtualMachine.id, VirtualMachine.name)
                      .filter_by(platform_id=platform.id).all()}
        _bkp_cols = {"vmid", "vm_name", "storage", "volid", "fmt", "created_at",
                     "size_gb", "protected", "notes", "source"}
        for bd in backups_data:
            link = vmid_map.get(str(bd.get("vmid")))
            clean = {k: v for k, v in bd.items() if k in _bkp_cols}
            if link and not clean.get("vm_name"):
                clean["vm_name"] = link[1]
            db.add(Backup(platform_id=platform.id,
                          vm_id=link[0] if link else None, **clean))

        # ---------- Sonuç ----------
        platform.last_sync = datetime.utcnow()
        platform.last_sync_status = "success"
        platform.last_sync_error = None
        log.status = "success"
        log.finished_at = datetime.utcnow()
        log.hosts_found = len(hosts_data)
        log.vms_found = len(vms_data)
        log.message = f"{len(hosts_data)} host, {len(vms_data)} VM senkronize edildi"
        db.commit()
        logger.info("Senkronizasyon tamam: %s (%s VM)", platform.name, len(vms_data))

    except Exception as exc:
        logger.exception("Senkronizasyon hatası (platform %s)", platform_id)
        db.rollback()
        try:
            platform = db.get(Platform, platform_id)
            if platform:
                platform.last_sync_status = "error"
                platform.last_sync_error = str(exc)[:2000]
            if log:
                log.status = "error"
                log.finished_at = datetime.utcnow()
                log.message = str(exc)[:2000]
                db.add(log)
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def sync_all_platforms():
    """Tüm etkin platformları sırayla senkronize et (zamanlayıcı görevi)."""
    db = SessionLocal()
    try:
        ids = [p.id for p in db.query(Platform).filter_by(enabled=True)]
    finally:
        db.close()
    for pid in ids:
        sync_platform(pid)


# ==================== Hafif kullanım senkronizasyonu ====================
def sync_usage_all():
    """
    Tüm platformlarda yalnızca ANLIK KULLANIM verilerini günceller
    (VM cpu/ram kullanımı, host cpu/ram/disk kullanımı).

    Tam senkronizasyondan farkları:
    - Çok daha sık çalışır (varsayılan 3 dk; USAGE_SYNC_INTERVAL_MINUTES)
    - Tek/az API çağrısıyla biter, config-agent sorgusu yapmaz
    - ChangeHistory ve SyncLog üretmez (gürültü olmasın diye)
    Böylece dashboard ve listelerdeki kullanım oranları neredeyse canlıdır.
    """
    db = SessionLocal()
    try:
        platforms = db.query(Platform).filter_by(enabled=True).all()
        for platform in platforms:
            try:
                collector = _build_collector(platform)
                collector.connect()
                try:
                    usage = collector.collect_usage()
                finally:
                    try:
                        collector.disconnect()
                    except Exception:
                        pass

                # VM kullanımları: external_id ile eşle, toplu güncelle
                vm_rows = {v.external_id: v for v in
                           db.query(VirtualMachine)
                             .filter_by(platform_id=platform.id).all()}
                for u in usage.get("vms", []):
                    vm = vm_rows.get(u["external_id"])
                    if vm is None:
                        continue
                    if u.get("cpu_pct") is not None:
                        vm.cpu_usage_pct = u["cpu_pct"]
                    if u.get("ram_used_mb"):
                        vm.ram_usage_mb = u["ram_used_mb"]
                    if u.get("disk_used_gb"):
                        vm.disk_used_gb = u["disk_used_gb"]

                # Host kullanımları: ada göre eşle
                host_rows = {h.name: h for h in
                             db.query(Host).filter_by(platform_id=platform.id).all()}
                for u in usage.get("hosts", []):
                    h = host_rows.get(u["name"])
                    if h is None:
                        continue
                    if u.get("cpu_pct") is not None:
                        h.cpu_usage_pct = u["cpu_pct"]
                    if u.get("ram_used_mb"):
                        h.ram_used_mb = u["ram_used_mb"]
                    if u.get("disk_used_gb") is not None:
                        h.disk_used_gb = u["disk_used_gb"]

                platform.last_usage_sync = datetime.utcnow()
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("Kullanım senkronizasyonu başarısız [%s]: %s",
                               platform.name, exc)
    finally:
        db.close()
