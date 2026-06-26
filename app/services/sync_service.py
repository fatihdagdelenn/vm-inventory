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
from datetime import datetime, date, timedelta

from sqlalchemy import func
from ..database import SessionLocal
from ..models import (Platform, SyncLog, Host, VirtualMachine,
                      Network, Datastore, Snapshot, Backup, ChangeHistory,
                      CapacitySnapshot, VmUsageDaily)
from ..core.security import decrypt_secret
from ..collectors.vmware_collector import VMwareCollector
from ..collectors.proxmox_collector import ProxmoxCollector

logger = logging.getLogger("sync")

# Değişiklik geçmişinde izlenen VM alanları
TRACKED_VM_FIELDS = ["name", "ip_addresses", "guest_os", "cpu_count", "ram_mb",
                     "disk_total_gb", "power_state", "cluster", "datastore", "vlans",
                     "networks"]
# NOT: mac_addresses bilerek İZLENMEZ — sık MAC oynaması (geçici/otomatik MAC,
# guest.net gürültüsü) Değişiklik Geçmişi'ni kirletiyordu. MAC değeri VM kaydında
# saklanmaya/gösterilmeye devam eder; yalnızca değişiklik kaydı tutulmaz.
TRACKED_HOST_FIELDS = ["name", "mgmt_ip", "cpu_cores", "ram_total_mb", "cluster", "status"]

# Misafir agent'ı / config sorgusu geçici başarısız olunca bu alanlar "iyi" değerden
# jenerik/boş değere düşebilir. Geçmiş'i (ChangeHistory) gürültüden korumak için
# bu düşüşlerde eski (iyi) değeri koruruz.
_ENRICH_FIELDS = ("guest_os", "ip_addresses", "datastore", "vlans", "networks",
                  "mac_addresses", "kernel", "arch", "disk_total_gb", "ram_mb",
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
    if field in ("ip_addresses", "datastore", "vlans", "disk_total_gb",
                 "networks", "mac_addresses"):
        return (not new) and bool(old)   # eski doluyken yeni boş/0 → geçici düşüş
    return False


def _record_change(db, entity_type, entity_name, platform_id, change_type,
                   field=None, old=None, new=None, actor=None, *,
                   category=None, op_type=None, platform_type=None,
                   cluster=None, host=None, vm_external_id=None,
                   actor_ip=None, actor_agent=None):
    db.add(ChangeHistory(
        entity_type=entity_type, entity_name=entity_name,
        platform_id=platform_id, change_type=change_type,
        field=field, old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
        actor=actor or None, category=category, op_type=op_type,
        platform_type=platform_type, cluster=cluster, host=host,
        vm_external_id=vm_external_id, actor_ip=actor_ip, actor_agent=actor_agent))


# Saptanan alan değişimi → kabul edilebilir işlem kategorileri (öncelik sırası).
# Bir değişimi YALNIZ uygun kategorideki işlemle eşleriz; böylece bir kullanıcının
# işlemi (ör. 'açtı') başka bir kullanıcının değişikliğine (ör. 'RAM artırdı')
# atfedilmez. Uygun işlem yoksa aktör BOŞ bırakılır (yanlış kişi yazmaktansa).
_FIELD_OP_CATEGORIES = {
    "cpu_count":     ["config"],
    "ram_mb":        ["config"],
    "guest_os":      ["config"],            # zayıf; genelde agent kaynaklı → boş kalabilir
    "disk_total_gb": ["disk", "config", "lifecycle"],
    "datastore":     ["migrate", "disk", "config"],
    "vlans":         ["config"],
    "networks":      ["config"],
    "mac_addresses": ["config"],
    "name":          ["config"],            # rename de 'config' kategorisinde
    "cluster":       ["migrate"],
    "power_state":   ["power"],
    "ip_addresses":  [],                    # misafir içi (agent) → operatör işlemi değil
}
# Alanın görsel kategorisi (eşleşen işlem bulunamasa bile UI gruplaması için).
_FIELD_CATEGORY = {
    "cpu_count": "hardware", "ram_mb": "hardware", "guest_os": "os",
    "disk_total_gb": "disk", "datastore": "disk",
    "vlans": "network", "ip_addresses": "network",
    "networks": "network", "mac_addresses": "network",
    "name": "other", "cluster": "migrate", "power_state": "power",
}
# Yeni power_state değeri → beklenen işlem yönü.
_POWER_DIRECTION = {
    "running": "on", "poweredOn": "on", "on": "on",
    "stopped": "off", "poweredOff": "off", "off": "off",
    "suspended": "suspend", "paused": "suspend",
}


def _match_op(ops, categories, direction=None):
    """VM'in işlem listesinden (en yeni → en eski) kategoriye uyan ilk işlem.

    direction verildiyse önce yön+kategori eşleşmesi aranır, bulunamazsa yalnız
    kategori. Hiç uygun işlem yoksa None döner (aktör boş kalır)."""
    if not ops or not categories:
        return None
    for op in ops:
        if op.get("category") in categories and \
                (direction is None or op.get("direction") == direction):
            return op
    if direction is not None:
        for op in ops:
            if op.get("category") in categories:
                return op
    return None


def _epoch(dt):
    """Naive-UTC datetime (collector utcfromtimestamp ile üretir) → epoch saniye."""
    if not dt:
        return 0
    try:
        from datetime import timezone
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def _find_op_by_vid(vm_ops, vid, categories, directions=None, min_ts=0):
    """vmid'e göre TÜM op listelerinde (node bağımsız) en yeni uygun işlemi bul.

    Proxmox'ta bazı görevler beklenmedik node/anahtarda olabilir (ör. klon işlemi
    kaynak node'a yazılır, qmigrate kaynak node'da kayıtlıdır). '/{vid}' ile biten
    tüm anahtarları tarar; kategori (+ varsa yön) eşleşen, aktörü dolu ve min_ts'ten
    yeni işlemlerden en yenisini döner. min_ts genelde VM'in oluşturulma zamanıdır
    (vmid yeniden kullanıldığında eski VM'in işlemleri elensin diye)."""
    best = None
    suffix = "/" + str(vid)
    for ext, ops in vm_ops.items():
        if not ext.endswith(suffix):
            continue
        for op in ops:
            if op.get("category") not in categories:
                continue
            if directions and op.get("direction") not in directions:
                continue
            if (op.get("ts") or 0) < min_ts:
                continue
            if not op.get("actor"):
                continue
            if best is None or (op.get("ts") or 0) > (best.get("ts") or 0):
                best = op
    return best


# Yaşam döngüsü yönleri: "Eklendi" yalnız oluşturma-yönlü işlemlerle eşleşmeli,
# ASLA "destroy" ile (vmid yeniden kullanımında eski VM'in silme görevine bulaşmasın).
_CREATE_DIRECTIONS = {"create", "clone", "restore", "register"}
_DESTROY_DIRECTIONS = {"destroy"}


def _nearest_clone_op(clone_ops, ctime, window=900):
    """Zaman yakınlığıyla klon işlemini bul.

    Proxmox klon görevinin UPID'i KAYNAK vmid'i taşır (yeni vmid'i değil), bu yüzden
    yeni VM kendi klon işlemini vmid anahtarıyla bulamaz. Yeni VM'in oluşturulma
    zamanı (ctime) ≈ klon görevinin zamanı olduğundan, ctime'a en yakın klon
    işlemini (pencere içinde) eşleriz → klonu yapan kullanıcı doğru bulunur."""
    if not ctime:
        return None
    best, best_d = None, None
    for op in clone_ops:
        d = abs((op.get("ts") or 0) - ctime)
        if d <= window and (best_d is None or d < best_d):
            best, best_d = op, d
    return best


def _record_console_ops(db, platform, vm, ops, ext_id, host_name, window=1800, cap=8):
    """VM konsoluna erişen kullanıcıları bilgi satırı olarak işle.

    Konsol erişimi bir envanter DEĞİŞİMİ değildir; ayrı satır (change_type='access')
    olarak yazılır. Proxmox'ta her noVNC açılışı/yeniden bağlanışı ayrı bir
    'vncproxy' görevi ürettiğinden geçmiş bunlarla dolabilir. Bu yüzden aynı
    kullanıcının erişimleri 'window' saniyelik pencerelere (varsayılan 30 dk)
    toplanır: kullanıcı başına pencere başına EN FAZLA bir satır. Pencere başlangıcı
    new_value'ya yazılır → hem deterministik tekilleştirme hem sade görünüm.
    """
    console = [o for o in ops if o.get("category") == "console" and o.get("actor")]
    if not console:
        return
    # Mevcut konsol satırlarının (aktör, pencere-ISO) anahtarları
    seen = set()
    for r in db.query(ChangeHistory.actor, ChangeHistory.new_value).filter(
            ChangeHistory.vm_external_id == ext_id,
            ChangeHistory.category == "console").order_by(
            ChangeHistory.changed_at.desc()).limit(500):
        seen.add((r.actor, r.new_value))
    added = 0
    for o in console:                     # en yeni → en eski
        if added >= cap:
            break
        ts = o.get("ts") or 0
        if not ts:
            continue
        bucket = int(ts) - (int(ts) % window)   # pencere başlangıcı (epoch)
        try:
            iso = datetime.utcfromtimestamp(bucket).isoformat(timespec="seconds")
        except Exception:
            continue
        actor = o.get("actor")
        if (actor, iso) in seen:
            continue
        seen.add((actor, iso))
        added += 1
        _record_change(db, "vm", vm.name, platform.id, "access",
                       field="console", old=None, new=iso,
                       actor=actor, category="console",
                       op_type=o.get("op"), platform_type=platform.type,
                       cluster=vm.cluster, host=host_name or o.get("host"),
                       vm_external_id=ext_id, actor_ip=o.get("actor_ip"),
                       actor_agent=o.get("actor_agent"))


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
            vm_ops = collector.collect_recent_actors() or {}
        except Exception as exc:
            vm_ops = {}
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
        # Göç tespiti için host id → ad eşlemesi (flush sonrası id'ler hazır).
        host_name_by_id = {h.id: h.name for h in host_by_name.values() if h.id}
        ptype = platform.type
        from ..core.app_settings import get_bool_setting
        track_console = get_bool_setting(db, "track_console_access", False)
        # Proxmox klon işlemleri (yön='clone') — klon görevi kaynak vmid'e yazıldığı
        # için yeni VM'e zaman-yakınlığıyla eşlenir.
        pmx_clone_ops = []
        if ptype == "proxmox":
            for _lst in vm_ops.values():
                for _op in _lst:
                    if _op.get("direction") == "clone" and _op.get("actor"):
                        pmx_clone_ops.append(_op)

        def _meta(op):
            """Eşleşen işlemden aktör/IP/op meta sözlüğü (None-güvenli)."""
            op = op or {}
            return dict(actor=op.get("actor"), op_type=op.get("op"),
                        actor_ip=op.get("actor_ip"), actor_agent=op.get("actor_agent"))

        existing_vms = {v.external_id: v for v in
                        db.query(VirtualMachine).filter_by(platform_id=platform.id)}

        # --- faz36: Proxmox node-arası göç tespiti ---
        # Proxmox'ta external_id = node/vmid olduğundan, bir VM başka node'a göç
        # edince eski external_id "silindi", yeni external_id "eklendi" görünür.
        # Aynı vmid'in farklı node'a taşınmasını TEK bir göç olayı olarak tanırız.
        migrated_pmx = {}   # vmid -> (old_ext, old_node, new_ext, new_node)
        if ptype == "proxmox":
            def _vid(ext): return ext.split("/", 1)[1] if "/" in ext else ext
            def _nod(ext): return ext.split("/", 1)[0] if "/" in ext else ""
            incoming_exts = {vd["external_id"] for vd in vms_data}
            existing_by_vid = {}
            for ext in existing_vms:
                existing_by_vid.setdefault(_vid(ext), ext)
            for vd in vms_data:
                ext = vd["external_id"]
                old_ext = existing_by_vid.get(_vid(ext))
                if old_ext and old_ext != ext and old_ext not in incoming_exts:
                    migrated_pmx[_vid(ext)] = (old_ext, _nod(old_ext), ext, _nod(ext))
        migrated_old_exts = {m[0] for m in migrated_pmx.values()}

        seen_vms = set()
        for vd in vms_data:
            seen_vms.add(vd["external_id"])
            host_name = vd.pop("host_name", "")
            host_obj = host_by_name.get(host_name)
            enrich_failed = vd.pop("enrich_failed", False)
            os_from_agent = vd.pop("os_from_agent", True)   # vCenter/LXC için varsayılan: güven
            ip_from_agent = vd.pop("ip_from_agent", True)
            vm = existing_vms.get(vd["external_id"])
            ext_id = vd["external_id"]
            vid = ext_id.split("/", 1)[1] if "/" in ext_id else ext_id
            # ctime filtresi: VM'in oluşturulma zamanından ÖNCEKİ işlemleri ele.
            # vmid yeniden kullanıldığında (eski VM silinip aynı id ile yeni VM)
            # eski VM'in görevleri (destroy/konsol/config) yeni VM'e bulaşmasın.
            ctime = _epoch(vd.get("created_date"))
            min_ts = (ctime - 300) if ctime else 0      # 5 dk pay
            ops = [o for o in (vm_ops.get(ext_id) or [])
                   if (o.get("ts") or 0) >= min_ts]
            if vm is None:
                vm = VirtualMachine(platform_id=platform.id,
                                    host_id=host_obj.id if host_obj else None,
                                    environment=platform.environment, **vd)
                db.add(vm)
                mig = migrated_pmx.get(vid) \
                    if (ptype == "proxmox" and "/" in ext_id) else None
                if mig and mig[2] == ext_id:
                    # Bu "yeni" kayıt aslında bir göçün hedef tarafı (node değişti).
                    old_ext, old_node, _new_ext, new_node = mig
                    # qmigrate görevini vmid'e göre tüm op listelerinde ara
                    # (kaynak/hedef node anahtarından bağımsız → aktör boş kalmasın).
                    op = _find_op_by_vid(vm_ops, vid, ["migrate"]) \
                        or _match_op(vm_ops.get(old_ext) or [], ["migrate"])
                    if not (op and op.get("actor")):
                        logger.info("Goc aktoru bulunamadi vmid=%s; ops=%s", vid,
                                    [(o.get("op"), o.get("actor")) for o in
                                     (vm_ops.get(old_ext) or []) + (vm_ops.get(ext_id) or [])])
                    _record_change(db, "vm", vd["name"], platform.id, "migrated",
                                   "host", old_node, new_node, category="migrate",
                                   platform_type=ptype, cluster=vd.get("cluster"),
                                   host=f"{old_node} → {new_node}",
                                   vm_external_id=ext_id, **_meta(op))
                else:
                    # "Eklendi" yalnız oluşturma-yönlü işlemle (create/clone/restore);
                    # klon işlemi farklı node/anahtarda olabileceğinden vmid bazlı ara,
                    # bulunamazsa ctime'a en yakın klon işlemiyle eşle (klon görevi
                    # kaynak vmid'e yazıldığından yeni VM kendi anahtarında bulamaz).
                    op = _find_op_by_vid(vm_ops, vid, ["lifecycle"],
                                         _CREATE_DIRECTIONS, min_ts) \
                        or (_nearest_clone_op(pmx_clone_ops, ctime) if ptype == "proxmox" else None) \
                        or _match_op(ops, ["lifecycle"], None)
                    if op and op.get("direction") == "destroy":
                        op = None      # güvenlik: created'a destroy eşleşmesin
                    if not (op and op.get("actor")):
                        logger.info("Olusturma aktoru bulunamadi vmid=%s; ops=%s", vid,
                                    [(o.get("op"), o.get("actor"), o.get("direction"))
                                     for o in ops])
                    _record_change(db, "vm", vd["name"], platform.id, "created",
                                   category="lifecycle", platform_type=ptype,
                                   cluster=vd.get("cluster"), host=host_name,
                                   vm_external_id=ext_id, **_meta(op))
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
                        # Değişimi YALNIZ uygun kategorideki işlemle eşle (yanlış kişi engeli)
                        cats = _FIELD_OP_CATEGORIES.get(f, [])
                        direction = _POWER_DIRECTION.get(str(new)) if f == "power_state" else None
                        op = _match_op(ops, cats, direction)
                        # Görsel kategori ALANDAN gelir (op kategorisi yalnız eşleştirme
                        # içindir; ör. RAM değişimi op'u 'qmconfig'/'config' olsa da
                        # kullanıcıya 'Donanım' olarak gösterilir).
                        cat = _FIELD_CATEGORY.get(f) or (op or {}).get("category") or "other"
                        _record_change(db, "vm", vm.name, platform.id, "updated",
                                       f, old, new, category=cat, platform_type=ptype,
                                       cluster=vd.get("cluster") or vm.cluster,
                                       host=host_name or host_name_by_id.get(vm.host_id),
                                       vm_external_id=ext_id, **_meta(op))
                # Göç (host değişimi): aynı external_id'de host değiştiyse — vMotion.
                # Proxmox'ta external_id=node/vmid olduğundan göç create+delete görünür
                # (bu yüzden burada yalnız host_id sabit kalan platformlarda tetiklenir).
                old_host = host_name_by_id.get(vm.host_id)
                new_host = host_name
                if old_host and new_host and old_host != new_host:
                    op = _match_op(ops, ["migrate"])
                    detail = (op or {}).get("detail")
                    _record_change(db, "vm", vm.name, platform.id, "migrated",
                                   "host", old_host, detail or new_host,
                                   category="migrate", platform_type=ptype,
                                   cluster=vd.get("cluster") or vm.cluster,
                                   host=f"{old_host} → {new_host}",
                                   vm_external_id=ext_id, **_meta(op))
                for k, v in vd.items():
                    setattr(vm, k, v)
                vm.host_id = host_obj.id if host_obj else None
            # Konsol erişimleri: yalnız ayar açıksa (varsayılan kapalı; gürültülü).
            if track_console:
                _record_console_ops(db, platform, vm, ops, ext_id, host_name)
        for ext_id, vm in existing_vms.items():
            if ext_id not in seen_vms:
                if ext_id in migrated_old_exts:
                    db.delete(vm)   # göçün kaynak tarafı; "Göç" satırı zaten yazıldı
                    continue
                vid = ext_id.split("/", 1)[1] if "/" in ext_id else ext_id
                op = _find_op_by_vid(vm_ops, vid, ["lifecycle"], _DESTROY_DIRECTIONS) \
                    or _match_op([o for o in (vm_ops.get(ext_id) or [])
                                  if o.get("direction") == "destroy"], ["lifecycle"])
                _record_change(db, "vm", vm.name, platform.id, "deleted",
                               category="lifecycle", platform_type=ptype,
                               cluster=vm.cluster,
                               host=host_name_by_id.get(vm.host_id),
                               vm_external_id=ext_id, **_meta(op))
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
        # Tarihsel örnekleme (kapasite öngörüsü + zombi tespiti). Asla
        # usage sync'i düşürmesin diye ayrı try; hata yalnız loglanır.
        try:
            record_samples(db)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Ornekleme (snapshot/usage-daily) basarisiz: %s", exc)
    finally:
        db.close()


def record_samples(db):
    """
    Günlük tarihsel örnekleme — sync_usage_all her çalıştığında çağrılır.
    1) VmUsageDaily: her çalışan VM için bugünün gün içi CPU ortalaması/tepesi
       ve RAM ortalaması (running average ile güncellenir).
    2) CapacitySnapshot: tüm ortam geneli tahsisli/kullanılan/kapasite toplamları
       (günde bir satır, upsert).
    Eski kayıtlar budanır. Bu veriler insights endpoint'inde DOĞRUSAL REGRESYON
    (forecast) ve 7 GÜNLÜK pencere (zombi) için kullanılır.
    """
    today = date.today()

    # 1) VM günlük kullanım toplulaştırma (yalnız kullanım örneği olanlar)
    vms = db.query(VirtualMachine.id, VirtualMachine.cpu_usage_pct,
                   VirtualMachine.ram_usage_mb).filter_by(is_template=False).all()
    existing = {r.vm_id: r for r in db.query(VmUsageDaily).filter_by(day=today).all()}
    for vm_id, cpu, ram in vms:
        if cpu is None:
            continue                      # kullanım örneği yok → atla
        ram = ram or 0
        row = existing.get(vm_id)
        if row is None:
            db.add(VmUsageDaily(vm_id=vm_id, day=today, cpu_avg=cpu,
                                cpu_max=cpu, ram_avg_mb=ram, samples=1))
        else:
            n = row.samples or 0
            row.cpu_avg = (((row.cpu_avg or 0) * n) + cpu) / (n + 1)
            row.ram_avg_mb = int((((row.ram_avg_mb or 0) * n) + ram) / (n + 1))
            row.cpu_max = max(row.cpu_max or 0, cpu)
            row.samples = n + 1

    # 2) Kapasite snapshot (tüm ortam geneli; gizli cluster filtresi yok)
    t = db.query(
        func.coalesce(func.sum(VirtualMachine.disk_total_gb), 0),
        func.coalesce(func.sum(VirtualMachine.ram_mb), 0),
        func.coalesce(func.sum(VirtualMachine.disk_used_gb), 0),
        func.coalesce(func.sum(VirtualMachine.ram_usage_mb), 0),
        func.count(VirtualMachine.id)).filter(
        VirtualMachine.is_template == False).one()  # noqa: E712
    ds = db.query(func.coalesce(func.sum(Datastore.capacity_gb), 0),
                  func.coalesce(func.sum(Datastore.used_gb), 0)).one()
    ds_cap = ds[0] or 0
    ds_used = ds[1] or 0
    host_ram = db.query(func.coalesce(func.sum(Host.ram_total_mb), 0)).scalar() or 0

    snap = db.query(CapacitySnapshot).filter_by(snap_date=today).first()
    if snap is None:
        snap = CapacitySnapshot(snap_date=today)
        db.add(snap)
    snap.alloc_disk_gb = float(t[0] or 0)
    snap.alloc_ram_mb = int(t[1] or 0)
    snap.used_disk_gb = float(t[2] or 0)
    snap.used_ram_mb = int(t[3] or 0)
    snap.datastore_capacity_gb = float(ds_cap)
    snap.datastore_used_gb = float(ds_used)
    snap.host_ram_mb = int(host_ram)
    snap.vm_count = int(t[4] or 0)

    # 3) Budama (depo şişmesin)
    db.query(VmUsageDaily).filter(VmUsageDaily.day < today - timedelta(days=35)).delete()
    db.query(CapacitySnapshot).filter(
        CapacitySnapshot.snap_date < today - timedelta(days=120)).delete()
