"""
VMware vCenter data collector (pyVmomi - the official vSphere SDK, NO SSH).

Collected:
- Host: name, mgmt IP, ESXi version, CPU model/cores, RAM, cluster, status
- VM: name, MoRef ID, IP/MAC, OS, CPU/RAM/disk, power state, datastore, VLAN,
  creation date, last boot, VMware Tools status
- Network: Port Group, vSwitch, VLAN
- Datastore: capacity/usage

Performance: PropertyCollector-based bulk views (ContainerView); at 500+ VMs
data is pulled in one pass instead of per-object queries.
"""
import ssl
import json
import re
import logging
from datetime import datetime, timedelta, timezone

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

logger = logging.getLogger("collector.vmware")

# guestInfo.detailed.data format: key='value' pairs, space-separated
_DETAILED_RE = re.compile(r"(\w+)='([^']*)'")


def _parse_detailed(raw: str) -> str:
    """
    Parses vSphere 8.0 U2+ detailed guest data ('guestInfo.detailed.data' or
    guest.guestDetailedData) and returns the best full name.
    E.g. prettyName='Ubuntu 24.04.1 LTS'  ->  "Ubuntu 24.04.1 LTS".
    """
    if not raw:
        return ""
    d = dict(_DETAILED_RE.findall(raw))
    pretty = (d.get("prettyName") or "").strip()
    if pretty:
        return pretty
    name, ver = d.get("distroName", "").strip(), d.get("distroVersion", "").strip()
    return (f"{name} {ver}".strip()) if name else ""


def _best_guest_os(vm, guest, summary_config) -> str:
    """
    Find the most detailed OS name, layered:
      1) guest.guestDetailedData              (VM on, Tools 11.2+ - full version)
      2) config.extraConfig['guestInfo.detailed.data']  (persistent; even when off)
      3) config.guestFullName                 (catalog name in the VM config)
      4) guest.guestFullName                  (running OS reported by Tools)
    Version requirement: vSphere 8.0 U2+ and VMware Tools 11.2+ (for steps 1-2).
    NOTE: the 3-4 order is deliberate - the catalog name (e.g. "VMware Photon OS")
    is usually more specific than the generic runtime name Tools reports
    ("Other 3.x Linux"), so the catalog name wins when detailed data is absent.
    """
    # 1) Live detailed data (full version)
    detailed = _parse_detailed(getattr(guest, "guestDetailedData", None) or "")
    if detailed:
        return detailed
    # 2) Persistent detailed data (extraConfig) - even while the VM is off
    #    The key appears as guestinfo/guestInfo in sources -> case-insensitive
    try:
        full_cfg = vm.config
        if full_cfg and getattr(full_cfg, "extraConfig", None):
            for opt in full_cfg.extraConfig:
                if (opt.key or "").lower() == "guestinfo.detailed.data":
                    detailed = _parse_detailed(opt.value or "")
                    if detailed:
                        return detailed
                    break
    except Exception:
        pass
    # 3) Catalog name (config)  4) OS reported by Tools - old (non-regressing) order
    return (summary_config.guestFullName if summary_config else "") or \
           (getattr(guest, "guestFullName", "") if guest else "") or ""


def _fetch_vcenter_tags(host, port, username, password, verify_ssl) -> dict:
    """
    MoRef -> "tag1,tag2" mapping from the vCenter REST (vAPI) tagging service.
    pyVmomi/SOAP does not expose tags, so a separate REST session is opened.
    Fully defensive: any error returns an empty dict and never affects the
    rest of the sync. (Endpoint: legacy /rest, still works on 8.0.)
    """
    import requests
    base = f"https://{host}:{port}"
    s = requests.Session()
    s.verify = verify_ssl
    if not verify_ssl:
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass
    try:
        r = s.post(f"{base}/rest/com/vmware/cis/session",
                   auth=(username, password), timeout=15)
        r.raise_for_status()
        s.headers["vmware-api-session-id"] = r.json()["value"]

        tag_ids = s.get(f"{base}/rest/com/vmware/cis/tagging/tag",
                        timeout=15).json().get("value", [])
        if not tag_ids:
            return {}
        names = {}
        for tid in tag_ids:
            try:
                names[tid] = s.get(
                    f"{base}/rest/com/vmware/cis/tagging/tag/id:{tid}",
                    timeout=15).json()["value"]["name"]
            except Exception:
                names[tid] = tid

        r = s.post(f"{base}/rest/com/vmware/cis/tagging/tag-association",
                   params={"~action": "list-attached-objects-on-tags"},
                   json={"tag_ids": tag_ids}, timeout=30)
        r.raise_for_status()
        result = {}
        for entry in r.json().get("value", []):
            tname = names.get(entry.get("tag_id"), "")
            for obj in entry.get("object_ids", []):
                if obj.get("type") == "VirtualMachine":
                    result.setdefault(obj["id"], []).append(tname)
        return {mo: ",".join(sorted(set(t for t in tags if t)))
                for mo, tags in result.items()}
    except Exception as exc:
        logger.warning("Could not fetch vCenter tags (REST): %s", exc)
        return {}
    finally:
        try:
            s.delete(f"{base}/rest/com/vmware/cis/session", timeout=10)
        except Exception:
            pass


class VMwareCollector:
    def __init__(self, host: str, username: str, password: str,
                 port: int = 443, verify_ssl: bool = True):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.si = None  # ServiceInstance

    # ---------- Connection ----------
    def connect(self):
        """Connect to vCenter. With verify_ssl=False certificate checks are skipped."""
        context = ssl.create_default_context()
        if not self.verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.si = SmartConnect(host=self.host, user=self.username,
                               pwd=self.password, port=self.port, sslContext=context)
        return self.si

    def disconnect(self):
        if self.si:
            Disconnect(self.si)
            self.si = None

    def test_connection(self) -> dict:
        """For the connection-test screen: returns the result with version info."""
        try:
            self.connect()
            about = self.si.content.about
            info = {"success": True,
                    "message": f"Connection successful: {about.fullName}",
                    "version": about.version}
            self.disconnect()
            return info
        except Exception as exc:
            return {"success": False, "message": f"Connection error: {exc}"}

    # ---------- Helpers ----------
    def _get_objects(self, vimtype):
        """Fetch all objects of the given type via ContainerView."""
        content = self.si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
        objs = list(view.view)
        view.Destroy()
        return objs

    # ---------- Cluster mapping ----------
    def _cluster_map(self) -> dict:
        """
        host MoRef ID -> cluster name mapping.

        Cluster names are read straight from ClusterComputeResource objects;
        faster than walking each host/VM parent chain (matters on remote,
        high-latency vCenters) and more reliable:
        even if one host's parent read fails, the cluster name is not lost.
        """
        mapping = {}
        try:
            for cl in self._get_objects([vim.ClusterComputeResource]):
                try:
                    cname = cl.name
                    for h in cl.host:
                        mapping[h._moId] = cname
                except Exception as exc:
                    logger.warning("Could not read cluster %s: %s",
                                   getattr(cl, "name", "?"), exc)
        except Exception as exc:
            logger.warning("Could not build cluster mapping: %s", exc)
        return mapping

    def _pool_map(self) -> dict:
        """VM MoRef -> resource pool name (bulk; no per-VM queries).
        The root 'Resources' pool is noise, so it is left blank."""
        mapping = {}
        try:
            for rp in self._get_objects([vim.ResourcePool]):
                try:
                    name = rp.name
                    if name == "Resources":   # hidden root pool
                        continue
                    for vm in rp.vm:
                        mapping[vm._moId] = name
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("Could not build pool mapping: %s", exc)
        return mapping

    @staticmethod
    def _vm_folder(vm) -> str:
        """Name of the folder the VM sits in directly (vm.parent).
        Canonical: the VM's inventory parent is a folder. The root 'vm'
        folder is hidden, so blank is returned when the VM is at root."""
        try:
            parent = vm.parent
            if isinstance(parent, vim.Folder):
                name = parent.name
                if name and name != "vm":
                    return name
        except Exception:
            pass
        return ""

    # ---------- Host'lar ----------
    def collect_hosts(self) -> list[dict]:
        hosts = []
        cluster_map = self._cluster_map()
        for h in self._get_objects([vim.HostSystem]):
            try:
                summary = h.summary
                hw = summary.hardware
                # Management IP: vmk interfaces sorted by device name (vmk0
                # first) for a DETERMINISTIC pick; the full candidate list lets
                # sync_service keep the stored IP while it still exists on the
                # host (no flip records from ordering changes). On fetch
                # failure the keys are omitted so stored values are preserved.
                mgmt_ip = ""
                mgmt_cands = []
                try:
                    if h.config and h.config.network and h.config.network.vnic:
                        vnics = sorted(h.config.network.vnic,
                                       key=lambda v: str(getattr(v, "device", "")))
                        for v in vnics:
                            try:
                                ip = v.spec.ip.ipAddress or ""
                            except Exception:
                                ip = ""
                            if ip:
                                mgmt_cands.append(ip)
                        mgmt_ip = mgmt_cands[0] if mgmt_cands else ""
                except Exception:
                    pass
                cluster = cluster_map.get(h._moId, "")
                # Disk capacity: sum of attached datastores.
                # An unreachable datastore must not drop the whole host record.
                disk_total = disk_free = 0
                try:
                    disk_total = sum((ds.summary.capacity or 0)
                                     for ds in h.datastore) / 1024**3
                    disk_free = sum((ds.summary.freeSpace or 0)
                                    for ds in h.datastore) / 1024**3
                except Exception:
                    pass
                entry = {
                    "external_id": h._moId,
                    "name": h.name,
                    "os_version": summary.config.product.fullName if summary.config.product else "",
                    "cpu_model": hw.cpuModel or "",
                    "hw_model": " ".join(x for x in (hw.vendor, hw.model) if x),
                    "cpu_cores": hw.numCpuCores or 0,
                    "ram_total_mb": int((hw.memorySize or 0) / 1024**2),
                    "ram_used_mb": int(summary.quickStats.overallMemoryUsage or 0),
                    "cpu_usage_pct": round(
                        100 * (summary.quickStats.overallCpuUsage or 0) /
                        max(1, (hw.cpuMhz or 1) * (hw.numCpuCores or 1)), 1),
                    "disk_total_gb": round(disk_total, 1),
                    "disk_used_gb": round(disk_total - disk_free, 1),
                    "cluster": cluster,
                    "status": "online" if summary.runtime.connectionState == "connected" else "offline",
                    "last_boot": getattr(summary.runtime, "bootTime", None),
                }
                # Only include mgmt_ip when actually read (disconnected hosts /
                # None config): an omitted key preserves the stored value.
                if mgmt_ip:
                    entry["mgmt_ip"] = mgmt_ip
                    entry["mgmt_ip_candidates"] = mgmt_cands
                hosts.append(entry)
            except Exception as exc:
                logger.warning("Could not read host %s: %s", getattr(h, "name", "?"), exc)
        return hosts

    # ---------- Sanal makineler ----------
    def collect_vms(self) -> list[dict]:
        vms = []
        cluster_map = self._cluster_map()   # host MoRef -> cluster name
        pool_map = self._pool_map()         # VM MoRef -> resource pool
        tag_map = _fetch_vcenter_tags(      # VM MoRef -> "etiket1,etiket2" (REST)
            self.host, self.port, self.username, self.password, self.verify_ssl)
        for vm in self._get_objects([vim.VirtualMachine]):
            try:
                summary = vm.summary
                config = summary.config
                guest = vm.guest

                # IPs come from VMware Tools; MACs are collected BELOW from the device
                # CONFIG (live/virtual interfaces in guest.net are noisy for change
                # tracking - Docker/Hyper-V etc. interfaces come and go).
                ips, macs = [], []
                if guest and guest.net:
                    for nic in guest.net:
                        if nic.ipAddress:
                            ips.extend(ip for ip in nic.ipAddress if ":" not in ip)  # IPv4 first
                if not ips and guest and guest.ipAddress:
                    ips.append(guest.ipAddress)
                # DNS servers reported by Tools (guest.ipStack dnsConfig)
                dns = []
                try:
                    for st in (guest.ipStack or []) if guest else []:
                        cfgd = getattr(st, "dnsConfig", None)
                        for a in (getattr(cfgd, "ipAddress", None) or []):
                            if a and a not in dns:
                                dns.append(a)
                except Exception:
                    pass

                # Disk details + network/VLAN info (from the hardware list)
                disks, networks, vlans = [], [], []
                if vm.config and vm.config.hardware:
                    for dev in vm.config.hardware.device:
                        if isinstance(dev, vim.vm.device.VirtualDisk):
                            disks.append({"label": dev.deviceInfo.label,
                                          "size_gb": round((dev.capacityInKB or 0) / 1024**2, 1)})
                        elif isinstance(dev, vim.vm.device.VirtualEthernetCard):
                            if dev.macAddress and dev.macAddress not in macs:
                                macs.append(dev.macAddress)
                            backing = dev.backing
                            # Standart vSwitch port group
                            if isinstance(backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                                networks.append(backing.deviceName or "")
                            # Distributed vSwitch portgroup -> VLAN
                            elif isinstance(backing,
                                            vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo):
                                pg_key = backing.port.portgroupKey
                                networks.append(pg_key or "")

                # Resolve VLANs from port group names
                for net in vm.network:
                    if isinstance(net, vim.dvs.DistributedVirtualPortgroup):
                        vlan_cfg = net.config.defaultPortConfig.vlan
                        if hasattr(vlan_cfg, "vlanId") and isinstance(vlan_cfg.vlanId, int):
                            vlans.append(str(vlan_cfg.vlanId))
                        if net.name not in networks:
                            networks.append(net.name)

                host_name = summary.runtime.host.name if summary.runtime.host else ""
                # Cluster: from the prebuilt map (walking each VM's parent
                # chain is slow and fragile on remote vCenters)
                cluster = cluster_map.get(
                    summary.runtime.host._moId, "") if summary.runtime.host else ""

                power_map = {"poweredOn": "running", "poweredOff": "stopped",
                             "suspended": "suspended"}

                vms.append({
                    "external_id": vm._moId,
                    "vmid": vm._moId,
                    "name": config.name if config else vm.name,
                    "ip_addresses": ",".join(sorted(set(ips))),
                    "dns_servers": ",".join(dns),
                    "mac_addresses": ",".join(sorted(set(macs))),
                    "guest_os": _best_guest_os(vm, guest, config),
                    "arch": ("x86_64" if config and "64" in (config.guestId or "")
                             else "x86" if config else ""),
                    "cpu_count": config.numCpu if config else 0,
                    "ram_mb": config.memorySizeMB if config else 0,
                    "disk_total_gb": round(sum(d["size_gb"] for d in disks), 1),
                    "disks_json": json.dumps(disks, ensure_ascii=False),
                    "power_state": power_map.get(str(summary.runtime.powerState), "unknown"),
                    "host_name": host_name,
                    "cluster": cluster,
                    "datastore": ",".join(ds.name for ds in vm.datastore),
                    "vlans": ",".join(sorted(set(vlans))),
                    "networks": ",".join(n for n in sorted(set(networks)) if n),
                    "created_date": vm.config.createDate if vm.config and
                                    hasattr(vm.config, "createDate") else None,
                    "last_boot": summary.runtime.bootTime,
                    "tools_status": str(guest.toolsRunningStatus) if guest else "unknown",
                    "guest_notes": (config.annotation if config and
                                    getattr(config, "annotation", None) else "") or "",
                    "pool": pool_map.get(vm._moId, ""),
                    "folder": self._vm_folder(vm),
                    "platform_tags": tag_map.get(vm._moId, ""),
                    "is_template": bool(config.template) if config else False,
                })
            except Exception as exc:
                logger.warning("Could not read VM %s: %s", getattr(vm, "name", "?"), exc)
        return vms

    # ---------- Networks ----------
    def collect_networks(self) -> list[dict]:
        nets = []
        # Standard vSwitch port groups (per host)
        for h in self._get_objects([vim.HostSystem]):
            try:
                if not h.config or not h.config.network:
                    continue
                for pg in h.config.network.portgroup or []:
                    nets.append({"name": pg.spec.name,
                                 "vlan": str(pg.spec.vlanId),
                                 "vswitch": pg.spec.vswitchName,
                                 "portgroup": pg.spec.name,
                                 "host_name": h.name,
                                 "kind": "portgroup"})
                # Physical NICs (vmnicX) - the host's own uplinks
                for pnic in h.config.network.pnic or []:
                    speed = ""
                    ls = getattr(pnic, "linkSpeed", None)
                    if ls and getattr(ls, "speedMb", None):
                        speed = f"{ls.speedMb} Mb/s"
                    nets.append({"name": pnic.device, "host_name": h.name,
                                 "kind": "pnic", "mac": pnic.mac or "",
                                 "link_speed": speed})
            except Exception as exc:
                logger.warning("Could not read host network: %s", exc)
        # Distributed port group'lar
        for dpg in self._get_objects([vim.dvs.DistributedVirtualPortgroup]):
            try:
                vlan_cfg = dpg.config.defaultPortConfig.vlan
                vlan = str(vlan_cfg.vlanId) if hasattr(vlan_cfg, "vlanId") and \
                       isinstance(vlan_cfg.vlanId, int) else ""
                nets.append({"name": dpg.name, "vlan": vlan,
                             "vswitch": dpg.config.distributedVirtualSwitch.name,
                             "portgroup": dpg.name, "host_name": "",
                             "kind": "portgroup"})
            except Exception as exc:
                logger.warning("Could not read DVS portgroups: %s", exc)
        return nets

    # ---------- Datastore'lar ----------
    def collect_datastores(self) -> list[dict]:
        result = []
        cluster_map = self._cluster_map()   # host MoRef -> cluster name
        for ds in self._get_objects([vim.Datastore]):
            try:
                s = ds.summary
                cap = (s.capacity or 0) / 1024**3
                free = (s.freeSpace or 0) / 1024**3
                maint = getattr(s, "maintenanceMode", "normal") or "normal"
                status = ("maintenance" if maint != "normal"
                          else "active" if getattr(s, "accessible", True) else "inactive")
                hosts = getattr(ds, "host", []) or []
                mount_names = []
                for hm in hosts:
                    try:
                        hn = hm.key.name or ""
                        if hn:
                            mount_names.append(hn)
                    except Exception:
                        pass
                # Local datastore (single host) -> host name. Shared (multi-host) ->
                # cluster name if attached hosts share one cluster (blank if several).
                node = ""
                if len(hosts) == 1:
                    try:
                        node = hosts[0].key.name or ""
                    except Exception:
                        node = ""
                elif len(hosts) > 1:
                    clusters = set()
                    for hm in hosts:
                        try:
                            clusters.add(cluster_map.get(hm.key._moId, ""))
                        except Exception:
                            pass
                    clusters.discard("")
                    if len(clusters) == 1:
                        node = next(iter(clusters))
                result.append({"name": s.name, "type": s.type,
                               "node": node,
                               "shared": len(hosts) > 1,
                               "capacity_gb": round(cap, 1),
                               "used_gb": round(cap - free, 1),
                               "free_gb": round(free, 1),
                               "host_count": len(hosts),
                               "host_names": ",".join(sorted(set(mount_names))),
                               "status": status})
            except Exception as exc:
                logger.warning("Could not read datastores: %s", exc)
        return result

    def collect_snapshots(self) -> list[dict]:
        """Flatten the VM snapshot tree (vm.snapshot.rootSnapshotList)."""
        result = []
        for vm in self._get_objects([vim.VirtualMachine]):
            try:
                snap = getattr(vm, "snapshot", None)
                if not snap or not snap.rootSnapshotList:
                    continue
                current = getattr(snap, "currentSnapshot", None)
                moid, vmname = vm._moId, vm.name

                def _walk(nodes, parent_name=""):
                    for n in nodes:
                        created = n.createTime
                        if created and created.tzinfo:
                            created = created.astimezone(timezone.utc).replace(tzinfo=None)
                        result.append({
                            "vm_external_id": moid, "vm_name": vmname,
                            "name": n.name, "description": (n.description or "").strip(),
                            "created_at": created,
                            "is_current": bool(current and n.snapshot == current),
                            "parent": parent_name,
                        })
                        if n.childSnapshotList:
                            _walk(n.childSnapshotList, n.name)

                _walk(snap.rootSnapshotList)
            except Exception as exc:
                logger.warning("Could not read snapshots (%s): %s",
                               getattr(vm, "name", "?"), exc)
        return result

    def collect_backups(self) -> list[dict]:
        # vCenter has no backup-management API; backups exist only on Proxmox.
        return []

    # vCenter event type -> (category, direction).
    _EVENT_CATEGORY = {
        "VmReconfiguredEvent": ("config", None),
        "VmCreatedEvent": ("lifecycle", "create"),
        "VmBeingDeployedEvent": ("lifecycle", "create"),
        "VmDeployedEvent": ("lifecycle", "create"),
        "VmClonedEvent": ("lifecycle", "clone"),
        "VmBeingClonedEvent": ("lifecycle", "clone"),
        "VmRegisteredEvent": ("lifecycle", "register"),
        "VmRemovedEvent": ("lifecycle", "destroy"),
        "MarkAsTemplateEvent": ("lifecycle", "template"),
        "MarkAsVirtualMachineEvent": ("lifecycle", "untemplate"),
        "VmRenamedEvent": ("config", "rename"),
        "VmMigratedEvent": ("migrate", "migrate"),
        "VmRelocatedEvent": ("migrate", "migrate"),
        "DrsVmMigratedEvent": ("migrate", "migrate"),
        "VmResourcePoolMovedEvent": ("migrate", "move"),
        "VmPoweredOnEvent": ("power", "on"),
        "DrsVmPoweredOnEvent": ("power", "on"),
        "VmPoweredOffEvent": ("power", "off"),
        "VmGuestShutdownEvent": ("power", "off"),
        "VmSuspendedEvent": ("power", "suspend"),
        "VmResettingEvent": ("power", "reboot"),
        "VmGuestRebootEvent": ("power", "reboot"),
        "VmAcquiredTicketEvent": ("console", "open"),
        "VmAcquiredMksTicketEvent": ("console", "open"),
        "VmRemoteConsoleConnectedEvent": ("console", "open"),
    }

    def collect_recent_actors(self) -> dict:
        """'Who changed what, and when' - an operation list per VM.

        Returns {moId: [op, ...]}; each op:
          {ts, op, category, direction, actor, actor_ip, host, detail}
        The list is sorted newest to oldest. sync_service matches every detected
        field change to the right event BY CATEGORY, so a RAM change is credited
        to the right user rather than a later 'powered on' event.

        vCenter events usually carry no client IP / User-Agent -> actor_ip empty.
        For migrations the source->target host is written into the detail.
        """
        from datetime import datetime, timedelta, timezone
        ops: dict[str, list] = {}
        wanted = list(self._EVENT_CATEGORY.keys())
        try:
            em = self.si.content.eventManager
            spec = vim.event.EventFilterSpec()
            spec.time = vim.event.EventFilterSpec.ByTime()
            spec.time.beginTime = datetime.now(timezone.utc) - timedelta(days=3)
            spec.eventTypeId = wanted
            # QueryEvents returns a SINGLE page (~1000 events): on a busy
            # vCenter the 3-day window easily exceeds that and reconfigure
            # events silently fall outside the page -> the change loses its
            # user. An EventHistoryCollector pages through the full window
            # (newest first, capped at 8000 events as a safety valve).
            events = []
            try:
                coll = em.CreateCollectorForEvents(spec)
                try:
                    coll.SetCollectorPageSize(1000)
                    events = list(coll.latestPage or [])
                    while len(events) < 8000:
                        batch = coll.ReadPreviousEvents(1000)
                        if not batch:
                            break
                        events.extend(batch)
                finally:
                    try:
                        coll.DestroyCollector()
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Event collector paging failed (%s); falling "
                               "back to single-page QueryEvents", exc)
                events = em.QueryEvents(spec) or []
        except Exception as exc:
            logger.warning("Could not fetch vCenter events: %s", exc)
            return ops

        def moid(e):
            vmarg = getattr(e, "vm", None)
            ref = getattr(vmarg, "vm", None) if vmarg else None
            return getattr(ref, "_moId", None) if ref else None

        def etype(e):
            return type(e).__name__.split(".")[-1]

        def host_name(ref):
            h = getattr(ref, "name", None) if ref else None
            return h or ""

        try:    # newest event first
            events = sorted(events, key=lambda e: getattr(e, "createdTime", None)
                            or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        except Exception:
            pass

        scanned = 0
        for e in events:
            mo = moid(e)
            user = getattr(e, "userName", "") or ""
            et = etype(e)
            cat = self._EVENT_CATEGORY.get(et)
            if not mo or not cat:
                continue
            category, direction = cat
            scanned += 1
            ts = getattr(e, "createdTime", None)
            try:
                ts = ts.timestamp() if ts else 0
            except Exception:
                ts = 0
            # Host it happened on; source->target for migrations
            host = host_name(getattr(getattr(e, "host", None), "host", None)) \
                or host_name(getattr(e, "host", None))
            detail = None
            if category == "migrate":
                src = host_name(getattr(getattr(e, "sourceHost", None), "host", None)) \
                    or host_name(getattr(e, "sourceHost", None))
                if src and host and src != host:
                    detail = f"{src} → {host}"
            ops.setdefault(mo, []).append({
                "ts": ts,
                "op": et,
                "category": category,
                "direction": direction,
                "actor": user or None,
                "actor_ip": None,    # vCenter events carry no client IP
                "actor_agent": None,
                "host": host or None,
                "detail": detail,
            })
        logger.info("vCenter actors: %d VMs mapped (%d events)",
                    len(ops), scanned)
        return ops

    # vCenter entity events -> (entity_type, op). Used to attribute datastore /
    # network / host add-remove changes to the acting user.
    _ENTITY_EVENTS = {
        "DatastoreDiscoveredEvent": ("datastore", "created"),
        "DatastoreDestroyedEvent": ("datastore", "deleted"),
        "DatastoreRemovedOnHostEvent": ("datastore", "deleted"),
        "DatastoreRenamedEvent": ("datastore", "updated"),
        "HostAddedEvent": ("host", "created"),
        "HostRemovedEvent": ("host", "deleted"),
        "DVPortgroupCreatedEvent": ("network", "created"),
        "DVPortgroupDestroyedEvent": ("network", "deleted"),
        "DVPortgroupRenamedEvent": ("network", "updated"),
    }

    def collect_entity_actors(self, days: int = 3):
        """Who added/removed datastores, networks and hosts.

        Returns {(entity_type, name): {"actor", "ts", "op"}} (newest wins).
        Machine accounts (vpxd, com.vmware.*) stay as-is; the frontend renders
        them with a "system" badge. Fully defensive - errors return {}.
        """
        out = {}
        try:
            em = self.si.content.eventManager
            fspec = vim.event.EventFilterSpec()
            fspec.time = vim.event.EventFilterSpec.ByTime(
                beginTime=datetime.now() - timedelta(days=days))
            fspec.eventTypeId = list(self._ENTITY_EVENTS.keys())
            for e in (em.QueryEvents(fspec) or []):
                etype = type(e).__name__.split(".")[-1]
                ent, op = self._ENTITY_EVENTS.get(etype, (None, None))
                if not ent:
                    continue
                name = ""
                for attr in ("datastore", "net", "host"):
                    arg = getattr(e, attr, None)
                    if arg is not None and getattr(arg, "name", ""):
                        name = arg.name
                        break
                if not name:
                    continue
                key = (ent, name)
                ts = int(e.createdTime.timestamp()) if e.createdTime else 0
                if key not in out or ts > out[key]["ts"]:
                    out[key] = {"actor": getattr(e, "userName", "") or "",
                                "ts": ts, "op": etype}
        except Exception as exc:
            logger.warning("Could not fetch vCenter entity events: %s", exc)
        return out

    # ---------- Lightweight usage sync ----------
    def collect_usage(self) -> dict:
        """
        Instant CPU/RAM usage - a lightweight read via quickStats.

        quickStats are near-realtime metrics vCenter already keeps in memory;
        far cheaper than the performance-chart API. Runs frequently,
        independent of the full sync.
        """
        vms, hosts = [], []

        for vm in self._get_objects([vim.VirtualMachine]):
            try:
                qs = vm.summary.quickStats
                max_mhz = (vm.runtime.maxCpuUsage or 0) if vm.runtime else 0
                cpu_pct = round(100 * (qs.overallCpuUsage or 0) / max_mhz, 1) \
                    if max_mhz else None
                # Real RAM usage: guestMemoryUsage = memory ACTIVELY used by the guest
                # (needs Tools; this is the ~%usage vCenter shows).
                # hostMemoryUsage (consumed/granted) approaches the allocation on
                # long-running VMs and reads "full" -> used ONLY when Tools absent (guest=0).
                ram_used = qs.guestMemoryUsage or qs.hostMemoryUsage or 0
                # Real disk usage: guest filesystem (Tools) - far more accurate than the
                # datastore footprint (committed) on thin disks (e.g. 40 GB vs 80 GB).
                disk_used = None
                try:
                    gdisks = vm.guest.disk if vm.guest else None
                    if gdisks:
                        tot = sum((d.capacity or 0) for d in gdisks)
                        free = sum((d.freeSpace or 0) for d in gdisks)
                        if tot > 0:
                            disk_used = round((tot - free) / 1024**3, 1)
                except Exception:
                    pass
                if disk_used is None:   # No Tools -> fall back to the datastore footprint
                    committed = vm.summary.storage.committed if vm.summary.storage else 0
                    disk_used = round((committed or 0) / 1024**3, 1)
                vms.append({
                    "external_id": vm._moId,
                    "cpu_pct": cpu_pct,
                    "ram_used_mb": ram_used,
                    "disk_used_gb": disk_used,
                })
            except Exception:
                continue

        for h in self._get_objects([vim.HostSystem]):
            try:
                qs = h.summary.quickStats
                hw = h.summary.hardware
                total_mhz = (hw.cpuMhz or 0) * (hw.numCpuCores or 0)
                hosts.append({
                    "name": h.name,
                    "cpu_pct": round(100 * (qs.overallCpuUsage or 0) / total_mhz, 1)
                        if total_mhz else None,
                    "ram_used_mb": qs.overallMemoryUsage or 0,
                    "disk_used_gb": None,   # host diski tam senkronizasyonda gelir
                })
            except Exception:
                continue
        return {"vms": vms, "hosts": hosts}
