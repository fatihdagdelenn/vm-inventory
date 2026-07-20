"""
Synchronization service.

Flow:
1. The scheduler (or the user's 'Refresh All' button) calls sync_all_platforms().
2. The matching collector runs per platform; data is pulled from the API.
3. The local database is updated with upsert logic.
4. Old/new values are compared -> written to ChangeHistory.
5. VM/Host records no longer on the platform are deleted (and logged).
6. The result is stored in SyncLog.

This keeps user searches always fast, served from local data.
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

# VM fields tracked in the change history
TRACKED_VM_FIELDS = ["name", "ip_addresses", "guest_os", "cpu_count", "ram_mb",
                     "disk_total_gb", "power_state", "cluster", "datastore", "vlans",
                     "networks"]
# NOTE: mac_addresses is deliberately NOT tracked - frequent MAC churn (temporary/auto
# MACs, guest.net noise) polluted the Change History. The MAC value is still stored
# and shown on the VM record; only change records are skipped.
TRACKED_HOST_FIELDS = ["name", "mgmt_ip", "cpu_cores", "ram_total_mb", "cluster", "status"]

# When the guest agent / config query fails transiently, these fields can drop from a
# "good" value to a generic/empty one. To protect ChangeHistory from noise we keep
# the old (good) value on such drops.
_ENRICH_FIELDS = ("guest_os", "ip_addresses", "dns_servers", "datastore", "vlans", "networks",
                  "mac_addresses", "kernel", "arch", "disk_total_gb", "ram_mb",
                  "guest_notes", "platform_tags", "tools_status")
# Generic / vague OS names (from ostype/guestFullName when no agent).
# NOTE: the Turkish words in the regex are intentional - they match data values
# the collectors emit (e.g. "Diğer", "eski çekirdek"); translating them breaks matching.
_GENERIC_OS_RE = re.compile(
    r"çekirdek|kernel\)|\bother\b|^diğer$|^linux$|^windows$|2\.6\+|2\.4 ",
    re.IGNORECASE)


def _is_generic_os(s) -> bool:
    return (not s) or bool(_GENERIC_OS_RE.search(str(s)))


def _preserve_old(field, old, new) -> bool:
    """Should the old good value be kept on a transient agent/enrich drop?"""
    if field == "guest_os":
        return new is not None and _is_generic_os(new) and old and not _is_generic_os(old)
    if field in ("ip_addresses", "datastore", "vlans", "disk_total_gb",
                 "networks", "mac_addresses"):
        return (not new) and bool(old)   # old non-empty, new empty/0 -> transient drop
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


# Detected field change -> acceptable operation categories (priority order).
# A change is matched ONLY to an operation in a fitting category, so one user's
# action (e.g. 'powered on') is never credited with another user's change
# (e.g. 'raised RAM'). With no fitting op the actor stays EMPTY (better than wrong).
_FIELD_OP_CATEGORIES = {
    "cpu_count":     ["config"],
    "ram_mb":        ["config"],
    "guest_os":      ["config"],            # weak; usually agent-driven -> may stay empty
    "disk_total_gb": ["disk", "config", "lifecycle"],
    "datastore":     ["migrate", "disk", "config"],
    "vlans":         ["config"],
    "networks":      ["config"],
    "mac_addresses": ["config"],
    "name":          ["config"],            # rename de 'config' kategorisinde
    "cluster":       ["migrate"],
    "power_state":   ["power"],
    "ip_addresses":  [],                    # in-guest (agent) -> not an operator action
}
# Visual category of the field (for UI grouping even when no op matches).
_FIELD_CATEGORY = {
    "cpu_count": "hardware", "ram_mb": "hardware", "guest_os": "os",
    "disk_total_gb": "disk", "datastore": "disk",
    "vlans": "network", "ip_addresses": "network",
    "networks": "network", "mac_addresses": "network",
    "name": "other", "cluster": "migrate", "power_state": "power",
}
# New power_state value -> expected operation direction.
_POWER_DIRECTION = {
    "running": "on", "poweredOn": "on", "on": "on",
    "stopped": "off", "poweredOff": "off", "off": "off",
    "suspended": "suspend", "paused": "suspend",
}


def _match_op(ops, categories, direction=None, min_ts=0):
    """First op in the VM's op list (newest to oldest) matching the category.

    With direction given, direction+category is tried first, then category only.
    With min_ts, ops OLDER than that are dropped (prevents crediting a fresh
    change to an old setup operation). None when nothing fits.

    ACTOR PREFERENCE (vCenter 'Shut Down Guest' fix): vSphere emits
    VmGuestShutdownEvent (userName SET) immediately followed by
    VmPoweredOffEvent (userName EMPTY, guest-initiated). Picking strictly the
    newest match returned the empty-actor op and the user showed as '-'.
    Now, if the newest match has no actor, a slightly older matching op WITH
    an actor (within 15 min of the newest match) is preferred. The window
    guard prevents crediting today's cron-triggered shutdown to an admin who
    powered off two days ago."""
    if not ops or not categories:
        return None
    cand = [o for o in ops if (o.get("ts") or 0) >= min_ts] if min_ts else ops

    def _pick(pool):
        if not pool:
            return None
        newest = pool[0]
        if newest.get("actor"):
            return newest
        floor = (newest.get("ts") or 0) - 900
        for op in pool[1:]:
            if (op.get("ts") or 0) < floor:
                break
            if op.get("actor"):
                return op
        return newest

    if direction is not None:
        hit = _pick([o for o in cand if o.get("category") in categories
                     and o.get("direction") == direction])
        if hit is not None:
            return hit
    return _pick([o for o in cand if o.get("category") in categories])


def _purge_vm_children(db, vm):
    """Delete rows that reference the VM before deleting the VM itself.

    Backup.vm_id and Snapshot.vm_id have NO ON DELETE CASCADE, so deleting a
    VM that still has backup/snapshot rows raises a ForeignKeyViolation on
    PostgreSQL (seen in test env; prod had simply never deleted a VM with
    backups). VmUsageDaily is cascaded at DB level on fresh schemas but is
    purged explicitly too, to cover databases created before the cascade."""
    db.query(Backup).filter_by(vm_id=vm.id).delete(synchronize_session=False)
    db.query(Snapshot).filter_by(vm_id=vm.id).delete(synchronize_session=False)
    db.query(VmUsageDaily).filter_by(vm_id=vm.id).delete(synchronize_session=False)


def _epoch(dt):
    """Naive-UTC datetime (collectors produce via utcfromtimestamp) -> epoch seconds."""
    if not dt:
        return 0
    try:
        from datetime import timezone
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def _find_op_by_vid(vm_ops, vid, categories, directions=None, min_ts=0):
    """Find the newest fitting op by vmid across ALL op lists (node-independent).

    In Proxmox some tasks live under unexpected nodes/keys (e.g. a clone is
    logged on the source node, qmigrate on the source node). Scans all keys
    ending in '/{vid}'; returns the newest op that matches the category (+
    direction if given), has an actor and is newer than min_ts. min_ts is
    usually the VM's creation time (drops the old VM's ops on vmid reuse)."""
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


# Lifecycle directions: "Added" must only match create-direction ops,
# NEVER "destroy" (avoid picking up the old VM's delete task on vmid reuse).
_CREATE_DIRECTIONS = {"create", "clone", "restore", "register"}
_DESTROY_DIRECTIONS = {"destroy"}


def _nearest_clone_op(clone_ops, ctime, window=900):
    """Find the clone op by time proximity.

    The Proxmox clone task's UPID carries the SOURCE vmid (not the new one),
    so the new VM can't find its clone op by vmid key. Since the new VM's
    creation time (ctime) ~ the clone task time, we match the clone op nearest
    to ctime (within a window) -> the cloning user is found correctly."""
    if not ctime:
        return None
    best, best_d = None, None
    for op in clone_ops:
        d = abs((op.get("ts") or 0) - ctime)
        if d <= window and (best_d is None or d < best_d):
            best, best_d = op, d
    return best


def _record_console_ops(db, platform, vm, ops, ext_id, host_name, window=1800, cap=8):
    """Record users who accessed the VM console as info rows.

    Console access is not an inventory CHANGE; it is written as a separate row
    (change_type='access'). In Proxmox every noVNC open/reconnect spawns its
    own 'vncproxy' task, which could flood the history. So one user's accesses
    are grouped into 'window'-second windows (default 30 min): AT MOST one row
    per user per window. The window start goes into new_value -> deterministic
    dedup and a clean view.
    """
    console = [o for o in ops if o.get("category") == "console" and o.get("actor")]
    if not console:
        return
    # Keys (actor, window-ISO) of existing console rows
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
        bucket = int(ts) - (int(ts) % window)   # window start (epoch)
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
    """Build the right collector from a platform record (decrypting secrets)."""
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
    """Sync a single platform."""
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
            logger.warning("Could not collect snapshots (%s): %s", platform.name, exc)
        try:
            backups_data = collector.collect_backups()
        except Exception as exc:
            backups_data = []
            logger.warning("Could not collect backups (%s): %s", platform.name, exc)
        try:
            vm_ops = collector.collect_recent_actors() or {}
        except Exception as exc:
            vm_ops = {}
            logger.warning("Could not collect actors (%s): %s", platform.name, exc)
        try:
            fn = getattr(collector, "collect_entity_actors", None)
            entity_actors = (fn() or {}) if fn else {}
        except Exception as exc:
            entity_actors = {}
            logger.warning("Could not collect entity actors (%s): %s", platform.name, exc)

        def _ent_actor(etype, name):
            """Actor + op meta for a datastore/network/host entity change."""
            rec = entity_actors.get((etype, name)) or {}
            return {"actor": rec.get("actor"), "op_type": rec.get("op"),
                    "platform_type": platform.type}
        # Field changes detected in this sync happened AFTER the previous sync.
        # Bounding actor matching to that time means that when the change's log
        # record was missed, we do not attribute it to a leftover OLD setup
        # operation (wrong person); it stays '-'. last_sync still holds the old value here.
        prev_sync_ts = _epoch(platform.last_sync) if platform.last_sync else 0
        if hasattr(collector, "disconnect"):
            collector.disconnect()

        # ---------- Host upsert ----------
        # Visual category per host field (mirrors the VM-side _FIELD_CATEGORY).
        _HOST_FIELD_CATEGORY = {"mgmt_ip": "network", "cpu_cores": "hardware",
                                "ram_total_mb": "hardware", "cluster": "other",
                                "status": "power", "name": "other"}
        existing_hosts = {h.external_id: h for h in
                          db.query(Host).filter_by(platform_id=platform.id)}
        seen_hosts = set()
        host_by_name = {}
        for hd in hosts_data:
            # mgmt_ip candidate list (not a model column - pop before upsert).
            # While the STORED IP is still present on the host, a different
            # deterministic pick (bond failover, vmk order) is NOT a change:
            # keep the stored value. Only a real re-IP (old address gone from
            # the host) is recorded - once.
            mgmt_cands = hd.pop("mgmt_ip_candidates", None)
            seen_hosts.add(hd["external_id"])
            host = existing_hosts.get(hd["external_id"])
            if host is not None and mgmt_cands and hd.get("mgmt_ip") \
                    and host.mgmt_ip and hd["mgmt_ip"] != host.mgmt_ip \
                    and host.mgmt_ip in mgmt_cands:
                hd["mgmt_ip"] = host.mgmt_ip
            if host is None:
                host = Host(platform_id=platform.id, **hd)
                db.add(host)
                _record_change(db, "host", hd["name"], platform.id, "created",
                               category="lifecycle", cluster=hd.get("cluster"),
                               host=hd.get("name"), **_ent_actor("host", hd["name"]))
            else:
                for f in TRACKED_HOST_FIELDS:  # write changes into the history
                    if getattr(host, f) != hd.get(f) and hd.get(f) is not None:
                        ea = _ent_actor("host", host.name)
                        _record_change(db, "host", host.name, platform.id,
                                       "updated", f, getattr(host, f), hd[f],
                                       category=_HOST_FIELD_CATEGORY.get(f, "other"),
                                       cluster=hd.get("cluster") or host.cluster,
                                       host=host.name, **ea)
                for k, v in hd.items():
                    setattr(host, k, v)
            host_by_name[hd["name"]] = host
        # Delete hosts no longer visible
        for ext_id, host in existing_hosts.items():
            if ext_id not in seen_hosts:
                _record_change(db, "host", host.name, platform.id, "deleted",
                               category="lifecycle", cluster=host.cluster,
                               host=host.name, **_ent_actor("host", host.name))
                db.delete(host)
        db.flush()

        # ---------- VM upsert ----------
        # host id -> name map for migration detection (ids ready after flush).
        host_name_by_id = {h.id: h.name for h in host_by_name.values() if h.id}
        ptype = platform.type
        from ..core.app_settings import get_bool_setting
        track_console = get_bool_setting(db, "track_console_access", False)
        # Proxmox clone ops (direction='clone') - the clone task is logged on the
        # source vmid, so it is matched to the new VM by time proximity.
        pmx_clone_ops = []
        if ptype == "proxmox":
            for _lst in vm_ops.values():
                for _op in _lst:
                    if _op.get("direction") == "clone" and _op.get("actor"):
                        pmx_clone_ops.append(_op)

        def _meta(op):
            """Actor/IP/op meta dict from a matched op (None-safe)."""
            op = op or {}
            return dict(actor=op.get("actor"), op_type=op.get("op"),
                        actor_ip=op.get("actor_ip"), actor_agent=op.get("actor_agent"))

        existing_vms = {v.external_id: v for v in
                        db.query(VirtualMachine).filter_by(platform_id=platform.id)}

        # --- phase36: Proxmox cross-node migration detection ---
        # In Proxmox external_id = node/vmid, so when a VM migrates to another
        # node the old external_id looks 'deleted' and the new one 'added'.
        # We recognize the same vmid moving to a different node as ONE migration.
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
            os_from_agent = vd.pop("os_from_agent", True)   # default for vCenter/LXC: trust
            ip_from_agent = vd.pop("ip_from_agent", True)
            agent_indeterminate = vd.pop("agent_indeterminate", False)
            vm = existing_vms.get(vd["external_id"])
            ext_id = vd["external_id"]
            vid = ext_id.split("/", 1)[1] if "/" in ext_id else ext_id
            # ctime filter: drop operations from BEFORE the VM's creation time.
            # On vmid reuse (old VM deleted, new VM with the same id) the old VM's
            # tasks (destroy/console/config) must not contaminate the new VM.
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
                    # This 'new' record is actually the target side of a migration (node changed).
                    old_ext, old_node, _new_ext, new_node = mig
                    # search the qmigrate task by vmid across all op lists
                    # (independent of source/target node key -> actor not left empty).
                    op = _find_op_by_vid(vm_ops, vid, ["migrate"]) \
                        or _match_op(vm_ops.get(old_ext) or [], ["migrate"])
                    if not (op and op.get("actor")):
                        logger.info("Migration actor not found vmid=%s; ops=%s", vid,
                                    [(o.get("op"), o.get("actor")) for o in
                                     (vm_ops.get(old_ext) or []) + (vm_ops.get(ext_id) or [])])
                    _record_change(db, "vm", vd["name"], platform.id, "migrated",
                                   "host", old_node, new_node, category="migrate",
                                   platform_type=ptype, cluster=vd.get("cluster"),
                                   host=f"{old_node} → {new_node}",
                                   vm_external_id=ext_id, **_meta(op))
                else:
                    # 'Added' only matches create-direction ops (create/clone/restore);
                    # the clone op may live under a different node/key, so search by vmid,
                    # and if not found match the clone op nearest to ctime (the clone task
                    # is logged on the source vmid, so the new VM can't find it under its own key).
                    op = _find_op_by_vid(vm_ops, vid, ["lifecycle"],
                                         _CREATE_DIRECTIONS, min_ts) \
                        or (_nearest_clone_op(pmx_clone_ops, ctime) if ptype == "proxmox" else None) \
                        or _match_op(ops, ["lifecycle"], None)
                    if op and op.get("direction") == "destroy":
                        op = None      # safety: created must never match destroy
                    if not (op and op.get("actor")):
                        logger.info("Creation actor not found vmid=%s; ops=%s", vid,
                                    [(o.get("op"), o.get("actor"), o.get("direction"))
                                     for o in ops])
                    _record_change(db, "vm", vd["name"], platform.id, "created",
                                   category="lifecycle", platform_type=ptype,
                                   cluster=vd.get("cluster"), host=host_name,
                                   vm_external_id=ext_id, **_meta(op))
            else:
                # If the VM detail query failed entirely this round, pin enrich-dependent
                # fields to their old values (don't overwrite with generic/empty ones).
                if enrich_failed:
                    for f in _ENRICH_FIELDS:
                        if f in vd:
                            vd[f] = getattr(vm, f)
                # Provenance: if the agent gave no OS/IP this round, keep the old
                # (agent-sourced) value. Prevents 'Server 2019' <-> 'Windows 10' flapping
                # (when agent osinfo intermittently fails) from polluting the History.
                if not os_from_agent and vm.guest_os:
                    for f in ("guest_os", "kernel", "arch"):
                        if f in vd:
                            vd[f] = getattr(vm, f)
                if not ip_from_agent and vm.ip_addresses:
                    for f in ("ip_addresses", "mac_addresses", "networks"):
                        if f in vd:
                            vd[f] = getattr(vm, f)
                # Sticky agent state (PVE 8.4.x flap guard): the agent option is on
                # but the probe failed with a timeout/connection-class error. The
                # agent may be alive but busy (backup fsfreeze, boot). Keep the
                # previous 'running' for up to 3 consecutive misses; a PVE-confirmed
                # 'not running' (agent_indeterminate=False) flips immediately.
                if agent_indeterminate and vm.tools_status == "guestToolsRunning":
                    vm.agent_miss_count = (vm.agent_miss_count or 0) + 1
                    if vm.agent_miss_count <= 3 and "tools_status" in vd:
                        vd["tools_status"] = vm.tools_status
                else:
                    vm.agent_miss_count = 0
                for f in TRACKED_VM_FIELDS:
                    old, new = getattr(vm, f), vd.get(f)
                    if _preserve_old(f, old, new):   # transient drop -> keep the old value
                        vd[f] = old
                        continue
                    if old != new and new is not None:
                        # Match the change ONLY to an op in a fitting category (wrong-person guard)
                        cats = _FIELD_OP_CATEGORIES.get(f, [])
                        direction = _POWER_DIRECTION.get(str(new)) if f == "power_state" else None
                        # The change happened after the previous sync -> drop older ops
                        # (e.g. credit a RAM change to the person who actually changed it,
                        #  not to whoever created the VM). A 5-minute margin is left.
                        op = _match_op(ops, cats, direction,
                                       min_ts=max(0, prev_sync_ts - 300))
                        # The visual category comes from the FIELD (the op category is only
                        # for matching; e.g. a RAM change op may be 'qmconfig'/'config' but
                        # is shown to the user as 'Hardware').
                        cat = _FIELD_CATEGORY.get(f) or (op or {}).get("category") or "other"
                        _record_change(db, "vm", vm.name, platform.id, "updated",
                                       f, old, new, category=cat, platform_type=ptype,
                                       cluster=vd.get("cluster") or vm.cluster,
                                       host=host_name or host_name_by_id.get(vm.host_id),
                                       vm_external_id=ext_id, **_meta(op))
                # Migration (host change): host changed under the same external_id - vMotion.
                # In Proxmox external_id=node/vmid so migration shows as create+delete
                # (hence this only triggers on platforms where host_id stays stable).
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
            # Console accesses: only when the setting is on (default off; noisy).
            if track_console:
                _record_console_ops(db, platform, vm, ops, ext_id, host_name)
        for ext_id, vm in existing_vms.items():
            if ext_id not in seen_vms:
                if ext_id in migrated_old_exts:
                    _purge_vm_children(db, vm)
                    db.delete(vm)   # source side of a migration; the 'Migration' row was already written
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
                _purge_vm_children(db, vm)
                db.delete(vm)
        # CRITICAL (autoflush=False): execute the pending VM deletes NOW.
        # Backup/snapshot archives SURVIVE VM deletion on the storage, so the
        # rewrite below re-inserts rows for them; without this flush the
        # vm_id/vmid maps still contain the pending-deleted VM and the fresh
        # rows reference it -> at commit INSERTs run before the DELETE and
        # PostgreSQL raises backups_vm_id_fkey. After the flush the maps
        # reflect reality and orphaned archives are stored with vm_id=NULL.
        db.flush()

        # ---------- Networks and datastores: simple refresh (delete-write) ----------
        # Before rewriting, diff the old rows against the new data and record
        # added/removed datastores and networks (with the acting user when the
        # platform's own log/events reveal one). Distinct names are compared so
        # per-host duplicate rows (portgroups, physical NICs) don't multiply rows.
        old_net_names = {n.name for n in
                         db.query(Network.name).filter_by(platform_id=platform.id)}
        new_net_names = {nd.get("name") for nd in nets_data if nd.get("name")}
        if old_net_names:  # skip on a brand-new platform (initial fill isn't "changes")
            for name in sorted(new_net_names - old_net_names):
                _record_change(db, "network", name, platform.id, "created",
                               category="network", **_ent_actor("network", name))
            for name in sorted(old_net_names - new_net_names):
                _record_change(db, "network", name, platform.id, "deleted",
                               category="network", **_ent_actor("network", name))
        old_ds = {(d.name, d.node or ""): d for d in
                  db.query(Datastore).filter_by(platform_id=platform.id)}
        new_ds_keys = {(dd.get("name"), dd.get("node") or "") for dd in ds_data}
        if old_ds:
            for name, node in sorted(new_ds_keys - set(old_ds)):
                _record_change(db, "datastore", name, platform.id, "created",
                               category="disk", host=node or None,
                               **_ent_actor("datastore", name))
            for (name, node), d in sorted(old_ds.items()):
                if (name, node) not in new_ds_keys:
                    _record_change(db, "datastore", name, platform.id, "deleted",
                                   category="disk", host=node or None,
                                   **_ent_actor("datastore", name))
        db.query(Network).filter_by(platform_id=platform.id).delete()
        for nd in nets_data:
            db.add(Network(platform_id=platform.id, **nd))
        db.query(Datastore).filter_by(platform_id=platform.id).delete()
        # vm_count: cross-computed from this platform's VMs' 'datastore' field
        # (comma-separated store names). For local Proxmox stores the VM's node
        # must additionally match the datastore's node.
        vm_ds_rows = db.query(Host.name, VirtualMachine.datastore)\
                       .outerjoin(Host, VirtualMachine.host_id == Host.id)\
                       .filter(VirtualMachine.platform_id == platform.id,
                               VirtualMachine.is_template == False).all()

        def _ds_vm_count(ds_name, ds_node, shared):
            n = 0
            for host_name, dstr in vm_ds_rows:
                tokens = [t.strip() for t in (dstr or "").split(",") if t.strip()]
                # a shared store is usable by VMs on all hosts; a local store only
                # by VMs on its own node
                if ds_name in tokens and (shared or not ds_node or host_name == ds_node):
                    n += 1
            return n

        for dd in ds_data:
            dd["vm_count"] = _ds_vm_count(dd["name"], dd.get("node", ""),
                                          dd.get("shared", False))
            db.add(Datastore(platform_id=platform.id, **dd))

        # ---------- Snapshots: delete-write, linked to VM by external_id ----------
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

        # ---------- Backups: delete-write, linked to VM by vmid (Proxmox only) ----------
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

        # ---------- Result ----------
        platform.last_sync = datetime.utcnow()
        platform.last_sync_status = "success"
        platform.last_sync_error = None
        log.status = "success"
        log.finished_at = datetime.utcnow()
        log.hosts_found = len(hosts_data)
        log.vms_found = len(vms_data)
        log.message = f"{len(hosts_data)} host, {len(vms_data)} VM senkronize edildi"
        db.commit()
        logger.info("Sync done: %s (%s VMs)", platform.name, len(vms_data))

    except Exception as exc:
        logger.exception("Sync error (platform %s)", platform_id)
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


import threading
# Shared lock preventing the full sync and the lightweight usage refresh
# from running AT THE SAME TIME and clashing in the DB (same VM rows).
# The full sync waits for the lock (priority); if the usage refresh can't get
# it, it SKIPS THAT ROUND (retries next interval) - no queueing/slowdown.
_sync_lock = threading.Lock()


def sync_all_platforms():
    """Sync all enabled platforms in order (scheduler job)."""
    with _sync_lock:
        _t0 = datetime.utcnow()
        db = SessionLocal()
        try:
            ids = [p.id for p in db.query(Platform).filter_by(enabled=True)]
        finally:
            db.close()
        for pid in ids:
            sync_platform(pid)
        logger.info("Full sync finished: %d platforms, %.1f s",
                    len(ids), (datetime.utcnow() - _t0).total_seconds())
        # Keep the topology map fresh live (SSE subscribers get notified).
        try:
            from ..core import events
            events.publish({"kind": "sync",
                            "ts": datetime.utcnow().isoformat() + "Z"})
        except Exception:
            pass


# ==================== Lightweight usage sync ====================
def sync_usage_all():
    """
    Updates ONLY the INSTANT USAGE data across all platforms
    (VM cpu/ram usage, host cpu/ram/disk usage).

    Differences from the full sync:
    - Runs much more often (default 3 min; USAGE_SYNC_INTERVAL_MINUTES)
    - Finishes with one/few API calls, no config-agent queries
    - Produces no ChangeHistory or SyncLog (avoids noise)
    Usage figures on the dashboard and lists stay near-live this way.
    """
    # Skip this round to avoid clashing with a running full sync.
    if not _sync_lock.acquire(blocking=False):
        logger.info("Full sync in progress; usage refresh skipped this round.")
        return
    try:
        _usage_sync_body()
    finally:
        _sync_lock.release()


def _usage_sync_body():
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

                # VM usage: match by external_id, bulk update
                now = datetime.utcnow()
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
                    # Net/Disk I/O rate: cumulative counter delta / elapsed time (KB/s).
                    # Negative delta = VM restarted (counters reset) -> skip.
                    nb, db_ = u.get("net_bytes"), u.get("disk_bytes")
                    if nb is not None and db_ is not None:
                        prev_ts = vm.io_ts
                        if prev_ts and vm.io_net_bytes is not None:
                            dt = (now - prev_ts).total_seconds()
                            if dt >= 1:
                                dn = nb - (vm.io_net_bytes or 0)
                                dd = db_ - (vm.io_disk_bytes or 0)
                                if dn >= 0:
                                    vm.net_kbps = round(dn / dt / 1024, 2)
                                if dd >= 0:
                                    vm.diskio_kbps = round(dd / dt / 1024, 2)
                        vm.io_net_bytes = nb
                        vm.io_disk_bytes = db_
                        vm.io_ts = now

                # Host usage: match by name
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
                logger.warning("Usage sync failed [%s]: %s",
                               platform.name, exc)
        # Historical sampling (capacity forecast + zombie detection). In a separate
        # try so it never breaks the usage sync; errors are only logged.
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
    Daily historical sampling - called on every sync_usage_all run.
    1) VmUsageDaily: today's intraday CPU average/peak and RAM average per
       running VM (updated with a running average).
    2) CapacitySnapshot: environment-wide allocated/used/capacity totals
       (one row per day, upsert).
    Old rows are pruned. The insights endpoint uses this data for LINEAR
    REGRESSION (forecast) and the 7-DAY window (zombie).
    """
    today = date.today()

    # 1) Daily VM usage aggregation (only VMs with a usage sample)
    vms = db.query(VirtualMachine.id, VirtualMachine.cpu_usage_pct,
                   VirtualMachine.ram_usage_mb, VirtualMachine.net_kbps,
                   VirtualMachine.diskio_kbps).filter_by(is_template=False).all()
    existing = {r.vm_id: r for r in db.query(VmUsageDaily).filter_by(day=today).all()}
    for vm_id, cpu, ram, net_kbps, disk_kbps in vms:
        if cpu is None:
            continue                      # no usage sample -> skip
        ram = ram or 0
        row = existing.get(vm_id)
        if row is None:
            db.add(VmUsageDaily(vm_id=vm_id, day=today, cpu_avg=cpu,
                                cpu_max=cpu, ram_avg_mb=ram, ram_min_mb=ram,
                                ram_max_mb=ram, net_kbps=net_kbps,
                                diskio_kbps=disk_kbps, samples=1))
        else:
            n = row.samples or 0
            row.cpu_avg = (((row.cpu_avg or 0) * n) + cpu) / (n + 1)
            row.ram_avg_mb = int((((row.ram_avg_mb or 0) * n) + ram) / (n + 1))
            row.cpu_max = max(row.cpu_max or 0, cpu)
            row.ram_min_mb = min(row.ram_min_mb if row.ram_min_mb is not None else ram, ram)
            row.ram_max_mb = max(row.ram_max_mb or 0, ram)
            if net_kbps is not None:
                row.net_kbps = (((row.net_kbps or 0) * n) + net_kbps) / (n + 1)
            if disk_kbps is not None:
                row.diskio_kbps = (((row.diskio_kbps or 0) * n) + disk_kbps) / (n + 1)
            row.samples = n + 1

    # 2) Capacity snapshot (whole environment; no hidden-cluster filter)
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
    # CPU: physical cores, allocated vCPU, core-weighted average host CPU %.
    host_cpu = db.query(Host.cpu_cores, Host.cpu_usage_pct).all()
    tot_cores = sum(int(c or 0) for c, _ in host_cpu)
    w_used = sum(int(c or 0) * float(u or 0) for c, u in host_cpu)
    used_cpu_pct = round(w_used / tot_cores, 1) if tot_cores else None
    alloc_vcpu = int(db.query(func.coalesce(func.sum(VirtualMachine.cpu_count), 0))
                     .filter(VirtualMachine.is_template == False).scalar() or 0)  # noqa: E712

    snap = db.query(CapacitySnapshot).filter_by(snap_date=today).first()
    if snap is None:
        snap = CapacitySnapshot(snap_date=today)
        db.add(snap)
    snap.alloc_disk_gb = float(t[0] or 0)
    snap.alloc_ram_mb = int(t[1] or 0)
    snap.used_disk_gb = float(t[2] or 0)
    snap.used_ram_mb = int(t[3] or 0)
    snap.host_cpu_cores = tot_cores or None
    snap.alloc_vcpu = alloc_vcpu
    snap.used_cpu_pct = used_cpu_pct
    snap.datastore_capacity_gb = float(ds_cap)
    snap.datastore_used_gb = float(ds_used)
    snap.host_ram_mb = int(host_ram)
    snap.vm_count = int(t[4] or 0)

    # 3) Pruning (keep the tables from bloating)
    db.query(VmUsageDaily).filter(VmUsageDaily.day < today - timedelta(days=35)).delete()
    db.query(CapacitySnapshot).filter(
        CapacitySnapshot.snap_date < today - timedelta(days=120)).delete()
