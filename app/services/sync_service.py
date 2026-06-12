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
import logging
from datetime import datetime

from ..database import SessionLocal
from ..models import (Platform, SyncLog, Host, VirtualMachine,
                      Network, Datastore, ChangeHistory)
from ..core.security import decrypt_secret
from ..collectors.vmware_collector import VMwareCollector
from ..collectors.proxmox_collector import ProxmoxCollector

logger = logging.getLogger("sync")

# Değişiklik geçmişinde izlenen VM alanları
TRACKED_VM_FIELDS = ["name", "ip_addresses", "guest_os", "cpu_count", "ram_mb",
                     "disk_total_gb", "power_state", "cluster", "datastore", "vlans"]
TRACKED_HOST_FIELDS = ["name", "mgmt_ip", "cpu_cores", "ram_total_mb", "cluster", "status"]


def _record_change(db, entity_type, entity_name, platform_id, change_type,
                   field=None, old=None, new=None):
    db.add(ChangeHistory(entity_type=entity_type, entity_name=entity_name,
                         platform_id=platform_id, change_type=change_type,
                         field=field, old_value=str(old) if old is not None else None,
                         new_value=str(new) if new is not None else None))


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
            vm = existing_vms.get(vd["external_id"])
            if vm is None:
                vm = VirtualMachine(platform_id=platform.id,
                                    host_id=host_obj.id if host_obj else None,
                                    environment=platform.environment, **vd)
                db.add(vm)
                _record_change(db, "vm", vd["name"], platform.id, "created")
            else:
                for f in TRACKED_VM_FIELDS:
                    if getattr(vm, f) != vd.get(f) and vd.get(f) is not None:
                        _record_change(db, "vm", vm.name, platform.id,
                                       "updated", f, getattr(vm, f), vd[f])
                for k, v in vd.items():
                    setattr(vm, k, v)
                vm.host_id = host_obj.id if host_obj else None
        for ext_id, vm in existing_vms.items():
            if ext_id not in seen_vms:
                _record_change(db, "vm", vm.name, platform.id, "deleted")
                db.delete(vm)

        # ---------- Ağ ve datastore: basit yenileme (sil-yaz) ----------
        db.query(Network).filter_by(platform_id=platform.id).delete()
        for nd in nets_data:
            db.add(Network(platform_id=platform.id, **nd))
        db.query(Datastore).filter_by(platform_id=platform.id).delete()
        for dd in ds_data:
            db.add(Datastore(platform_id=platform.id, **dd))

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
