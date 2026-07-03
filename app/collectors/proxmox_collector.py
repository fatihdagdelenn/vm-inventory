"""
Proxmox VE data collector (proxmoxer - the official REST API client, NO SSH).

Authentication: API Token (recommended) or user/password.
Collected: nodes (hosts), QEMU VMs, network (bridge/VLAN), storage.
If the QEMU Guest Agent is installed, in-guest IP addresses are read too.
"""
import json
import logging
import re
from datetime import datetime

from proxmoxer import ProxmoxAPI

logger = logging.getLogger("collector.proxmox")

# Proxmox internal "ostype" codes -> readable names.
# If the Guest Agent runs, the real OS name from the guest overrides this.
OSTYPE_MAP = {
    "l26": "Linux",                  # Proxmox 'l26' = modern Linux hint (not the actual distro)
    "l24": "Linux (eski çekirdek)",
    "win11": "Windows 11 / Server 2022+",
    "win10": "Windows 10 / Server 2016-2019",
    "win8": "Windows 8 / Server 2012",
    "win7": "Windows 7 / Server 2008 R2",
    "w2k8": "Windows Server 2008",
    "w2k3": "Windows Server 2003",
    "w2k": "Windows 2000",
    "wxp": "Windows XP",
    "wvista": "Windows Vista",
    "solaris": "Solaris / OpenIndiana",
    "other": "Diğer",
}


class ProxmoxCollector:
    def __init__(self, host: str, port: int = 8006, verify_ssl: bool = True,
                 username: str = None, password: str = None,
                 token_name: str = None, token_value: str = None):
        """
        token_name format: user@realm!tokenid  (e.g. api@pam!inventory)
        If a token is given, the password method is ignored.
        """
        self.host = host
        self.port = port
        self.verify_ssl = verify_ssl
        self.username = username
        self.password = password
        self.token_name = token_name
        self.token_value = token_value
        self.api = None

    # ---------- Connection ----------
    def connect(self):
        if self.token_name and self.token_value:
            # "user@realm!tokenid" -> user="user@realm", token_name="tokenid"
            user_part, _, tokenid = self.token_name.partition("!")
            self.api = ProxmoxAPI(self.host, port=self.port, user=user_part,
                                  token_name=tokenid, token_value=self.token_value,
                                  verify_ssl=self.verify_ssl)
        else:
            self.api = ProxmoxAPI(self.host, port=self.port, user=self.username,
                                  password=self.password, verify_ssl=self.verify_ssl)
        return self.api

    def test_connection(self) -> dict:
        """Connection test: queries version info."""
        try:
            self.connect()
            version = self.api.version.get()
            return {"success": True,
                    "message": f"Bağlantı başarılı: Proxmox VE {version.get('version')}",
                    "version": version.get("version")}
        except Exception as exc:
            return {"success": False, "message": f"Connection error: {exc}"}

    # ---------- Cluster name ----------
    def _cluster_name(self) -> str:
        """
        Returns the Proxmox cluster name. Without a cluster (single node)
        the node name is used so the Cluster column is never empty.
        """
        try:
            for item in self.api.cluster.status.get():
                if item.get("type") == "cluster":
                    return item.get("name", "")
        except Exception:
            pass
        try:  # standalone node: use the first node's name as the cluster
            nodes = self.api.nodes.get()
            if len(nodes) == 1:
                return nodes[0]["node"]
        except Exception:
            pass
        return ""

    # ---------- Management IP selection ----------
    @staticmethod
    def _pick_mgmt_ip(ifaces: list) -> str:
        """
        Pick the node's management IP DETERMINISTICALLY.

        The Proxmox API does not return interfaces in a stable order. The old
        'first interface with an address' approach made the IP flip on every
        sync on multi-NIC nodes, polluting the change history. Fixed priority:
          1) Interface with the default route (gateway) - the real mgmt IP
          2) The vmbr0 management bridge
          3) Fallback: first addressed interface sorted by name
        """
        addressed = [i for i in (ifaces or []) if i.get("address")]
        if not addressed:
            return ""
        ordered = sorted(addressed, key=lambda x: str(x.get("iface", "")))
        for i in ordered:                       # 1) interface with a gateway
            if i.get("gateway"):
                return i["address"]
        for i in ordered:                       # 2) vmbr0
            if i.get("iface") == "vmbr0":
                return i["address"]
        return ordered[0]["address"]            # 3) first in order

    # ---------- Host'lar (node'lar) ----------
    # dmidecode placeholders that mean "no real value"
    _HW_PLACEHOLDER = re.compile(
        r"to be filled|o\.e\.m|default string|system (product name|manufacturer)"
        r"|not specified|unknown|empty", re.IGNORECASE)

    def _node_hw_model(self, node: str) -> str:
        """Physical vendor+model of a node (e.g. 'Dell Inc. PowerEdge R750').

        The PVE REST API has no DMI endpoint, but GET /nodes/{node}/report
        (the GUI "System Report", readable with Sys.Audit) embeds dmidecode
        output - Manufacturer / Product Name are parsed from its System
        Information block. Fallback: the majority subsystem vendor of the
        node's PCI devices (OEM boards report e.g. 'Dell Inc.') gives at
        least the vendor. Fully defensive; failure returns ''.
        """
        if not hasattr(self, "_hw_cache"):
            self._hw_cache = {}
        if node in self._hw_cache:
            return self._hw_cache[node]
        result = ""
        try:
            rep = self.api.nodes(node).report.get()
            text = rep if isinstance(rep, str) else str(rep or "")
            block = re.search(r"System Information([\s\S]{0,400})", text)
            scope = block.group(1) if block else text
            man = re.search(r"Manufacturer:\s*(.+)", scope)
            prod = re.search(r"Product Name:\s*(.+)", scope)
            parts = []
            for m in (man, prod):
                val = (m.group(1).strip() if m else "")
                if val and not self._HW_PLACEHOLDER.search(val):
                    parts.append(val)
            result = " ".join(dict.fromkeys(parts))  # dedupe, keep order
        except Exception as exc:
            logger.info("Node report unavailable (%s): %s", node, exc)
        if not result:
            try:  # fallback: majority PCI subsystem vendor -> at least the OEM
                from collections import Counter
                devs = self.api.nodes(node).hardware.pci.get() or []
                cnt = Counter((d.get("subsystem_vendor_name") or "").strip()
                              for d in devs)
                cnt.pop("", None)
                if cnt:
                    best, n = cnt.most_common(1)[0]
                    if n >= 3 and not self._HW_PLACEHOLDER.search(best):
                        result = best
            except Exception:
                pass
        self._hw_cache[node] = result
        return result

    def collect_hosts(self) -> list[dict]:
        hosts = []
        for node in self.api.nodes.get():
            name = node["node"]
            entry = {
                "external_id": name,
                "name": name,
                "mgmt_ip": "",
                "os_version": "Proxmox VE",
                "cpu_model": "",
                "cpu_cores": node.get("maxcpu", 0),
                "ram_total_mb": int(node.get("maxmem", 0) / 1024**2),
                "ram_used_mb": int(node.get("mem", 0) / 1024**2),
                "cpu_usage_pct": round(100 * node.get("cpu", 0), 1),
                "disk_total_gb": round(node.get("maxdisk", 0) / 1024**3, 1),
                "disk_used_gb": round(node.get("disk", 0) / 1024**3, 1),
                "cluster": "",
                "status": "online" if node.get("status") == "online" else "offline",
                "last_boot": (datetime.utcfromtimestamp(
                    int(datetime.utcnow().timestamp()) - int(node["uptime"]))
                    if node.get("uptime") else None),
            }
            # Fetch details from online nodes (CPU model, version, IP)
            if entry["status"] == "online":
                try:
                    status = self.api.nodes(name).status.get()
                    cpuinfo = status.get("cpuinfo", {})
                    entry["cpu_model"] = cpuinfo.get("model", "")
                    entry["os_version"] = f"Proxmox VE {status.get('pveversion', '')}"
                    # Management IP: pick network interfaces DETERMINISTICALLY.
                    # The API does not guarantee interface order, so multi-NIC
                    # nodes used to get a different IP on every sync, polluting
                    # the change history. A fixed priority is applied
                    # (see _pick_mgmt_ip).
                    entry["mgmt_ip"] = self._pick_mgmt_ip(
                        self.api.nodes(name).network.get())
                except Exception as exc:
                    logger.warning("Could not fetch node details %s: %s", name, exc)
                entry["hw_model"] = self._node_hw_model(name)
            hosts.append(entry)

        # Resolve the cluster name and assign it to all nodes
        cluster = self._cluster_name()
        for h in hosts:
            h["cluster"] = cluster
        return hosts

    # ---------- VLAN mapping helpers ----------
    @staticmethod
    def _vlan_from_name(iface_name: str) -> str:
        """Extract the VLAN ID from a name like 'bond0.205' or 'eno1.100'."""
        if "." in iface_name:
            suffix = iface_name.rsplit(".", 1)[1]
            if suffix.isdigit():
                return suffix
        return ""

    def _bridge_vlan_map(self) -> dict:
        """
        Builds a bridge -> VLAN map. In Proxmox a VLAN can be defined in 3 places:
          1) tag= on the VM NIC (read directly inside collect_vms)
          2) In the node network layout: if bridge vmbr1 sits on bond0.205,
             every VM attached to that bridge is effectively on VLAN 205
          3) In SDN vnets: the vnet's tag field is the VLAN ID
        Returns: {"node/bridge": vlan, "vnet_name": vlan}
        """
        mapping = {}
        try:
            for node in self.api.nodes.get():
                if node.get("status") != "online":
                    continue
                nname = node["node"]
                try:
                    ifaces = self.api.nodes(nname).network.get()
                except Exception:
                    continue
                # first collect vlan-type interfaces: name -> vlan id
                vlan_ifaces = {}
                for i in ifaces:
                    if i.get("type") == "vlan":
                        vid = str(i.get("vlan-id") or "") or \
                              self._vlan_from_name(i.get("iface", ""))
                        if vid:
                            vlan_ifaces[i["iface"]] = vid
                # scan bridges: map ports attached to a vlan interface
                for i in ifaces:
                    if i.get("type") not in ("bridge", "OVSBridge"):
                        continue
                    bridge = i.get("iface", "")
                    vid = ""
                    for port in str(i.get("bridge_ports", "") or
                                    i.get("ovs_ports", "")).split():
                        vid = vlan_ifaces.get(port) or self._vlan_from_name(port)
                        if vid:
                            break
                    if vid:
                        mapping[f"{nname}/{bridge}"] = vid
        except Exception as exc:
            logger.warning("Bridge VLAN mapping failed: %s", exc)

        # SDN vnets (cluster-wide): vnet name -> tag
        try:
            for vnet in self.api.cluster.sdn.vnets.get():
                if vnet.get("tag"):
                    mapping[vnet.get("vnet", "")] = str(vnet["tag"])
        except Exception:
            pass  # SDN may be unconfigured; that's normal
        return mapping

    # ---------- Disk size parsing ----------
    @staticmethod
    def _size_to_gb(size: str) -> float:
        """
        Convert a Proxmox disk size to GB (float).
        Accepted forms: '32G', '512M', '1T', '1024K' or bare bytes.
        Returns 0.0 if unparsable.
        """
        if not size:
            return 0.0
        s = str(size).strip().upper()
        units = {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1.0,
                 "T": 1024.0, "P": 1024**2}
        try:
            if s and s[-1] in units:
                return round(float(s[:-1]) * units[s[-1]], 1)
            return round(float(s) / 1024**3, 1)   # birimsiz = bayt
        except (ValueError, IndexError):
            return 0.0

    # ---------- Sanal makineler ----------
    def collect_vms(self) -> list[dict]:
        vms = []
        cluster = self._cluster_name()           # assigned to all VMs
        vlan_map = self._bridge_vlan_map()       # bridge/vnet -> VLAN mapping
        # cluster/resources returns all VM summaries in one call (efficient for 500+ VMs)
        resources = self.api.cluster.resources.get(type="vm")
        for r in resources:
            rtype = r.get("type")
            if rtype not in ("qemu", "lxc"):
                continue
            node, vmid = r["node"], r["vmid"]
            entry = {
                "external_id": f"{node}/{vmid}",
                "vmid": str(vmid),
                "name": r.get("name", f"vm-{vmid}"),
                "ip_addresses": "",
                "mac_addresses": "",
                "guest_os": "",
                "cpu_count": r.get("maxcpu", 0),
                "ram_mb": int(r.get("maxmem", 0) / 1024**2),
                "disk_total_gb": round(r.get("maxdisk", 0) / 1024**3, 1),
                "disks_json": "[]",
                "power_state": "running" if r.get("status") == "running" else "stopped",
                "host_name": node,
                "cluster": cluster,
                "datastore": "",
                "vlans": "",
                "networks": "",
                "created_date": None,
                "last_boot": None,
                "tools_status": "unknown",
                "guest_notes": "",
                "pool": r.get("pool", "") or "",
                "folder": "",
                "platform_tags": "",
                "is_template": bool(r.get("template", 0)),
            }
            # LXC containers: config/IP/disk format differs from qemu and
            # there is no QEMU Guest Agent -> separate enrichment.
            if rtype == "lxc":
                try:
                    self._enrich_lxc(entry, node, vmid, vlan_map)
                except Exception as exc:
                    entry["enrich_failed"] = True
                    logger.warning("Could not fetch container details %s/%s: %s", node, vmid, exc)
                vms.append(entry)
                continue
            try:
                # VM config: OS type, NICs, disks, VLAN
                cfg = self.api.nodes(node).qemu(vmid).config.get()
                ostype = cfg.get("ostype", "")
                entry["guest_os"] = OSTYPE_MAP.get(ostype, ostype)
                # Configured RAM: config 'memory' (MB) is the STABLE source.
                # cluster/resources.maxmem FLOATS with host pressure on VMs
                # with ballooning (e.g. 12188<->10035) -> produces fake
                # "RAM changed" records every sync. Use config 'memory' instead.
                if cfg.get("memory") not in (None, ""):
                    try:
                        entry["ram_mb"] = int(cfg["memory"])
                    except (TypeError, ValueError):
                        pass
                # Proxmox "Notes" field; may arrive URL-encoded
                desc = cfg.get("description", "") or ""
                if desc:
                    try:
                        from urllib.parse import unquote
                        desc = unquote(desc)
                    except Exception:
                        pass
                entry["guest_notes"] = desc
                # Proxmox VM tags (config 'tags' field; ';'-separated)
                entry["platform_tags"] = (cfg.get("tags") or "").replace(";", ",")
                # DNS servers: cloud-init 'nameserver' (space/comma separated)
                entry["dns_servers"] = ",".join(str(cfg.get("nameserver") or "").split())
                if cfg.get("meta"):  # ctime=... creation time
                    for part in cfg["meta"].split(","):
                        if part.startswith("ctime="):
                            entry["created_date"] = datetime.utcfromtimestamp(int(part[6:]))

                macs, vlans, bridges, disks, stores = [], [], [], [], []
                cloudinit_ips = []   # fallback when no agent: cloud-init static IPs
                for key, val in cfg.items():
                    sval = str(val)
                    if key.startswith("ipconfig"):  # ipconfig0: ip=10.0.0.5/24,gw=10.0.0.1
                        for piece in sval.split(","):
                            if piece.startswith("ip=") and piece != "ip=dhcp":
                                cloudinit_ips.append(piece[3:].split("/")[0])
                    elif key.startswith("net"):       # net0: virtio=AA:BB:..,bridge=vmbr0,tag=100
                        nic_bridge, nic_tag = "", ""
                        for piece in sval.split(","):
                            if "=" in piece:
                                k, v = piece.split("=", 1)
                                if k in ("virtio", "e1000", "rtl8139", "vmxnet3"):
                                    macs.append(v.upper())
                                elif k == "bridge":
                                    nic_bridge = v
                                    bridges.append(v)
                                elif k == "tag":
                                    nic_tag = v
                        if nic_tag:
                            vlans.append(nic_tag)
                        elif nic_bridge:
                            # NIC has no tag: if the bridge itself sits on a VLAN
                            # (e.g. vmbr1 -> bond0.205) or is an SDN vnet, use that
                            mapped = vlan_map.get(f"{node}/{nic_bridge}") or \
                                     vlan_map.get(nic_bridge)
                            if mapped:
                                vlans.append(mapped)
                    elif key.startswith(("scsi", "virtio", "sata", "ide")) and ":" in sval \
                            and not key.endswith("hw"):
                        store = sval.split(":", 1)[0]
                        if store not in ("none", "cdrom") and "media=cdrom" not in sval:
                            stores.append(store)
                            size_raw = ""
                            for piece in sval.split(","):
                                if piece.startswith("size="):
                                    size_raw = piece[5:]
                            disks.append({"label": key,
                                          "size_gb": self._size_to_gb(size_raw)})

                entry.update({
                    "mac_addresses": ",".join(sorted(set(macs))),
                    "vlans": ",".join(sorted(set(vlans))),
                    "networks": ",".join(sorted(set(bridges))),
                    "datastore": ",".join(sorted(set(stores))),
                    "disks_json": json.dumps(disks, ensure_ascii=False),
                    # Sum of all disks; fall back to maxdisk if unparsable
                    "disk_total_gb": round(sum(d["size_gb"] for d in disks), 1)
                                     or entry["disk_total_gb"],
                })

                # IPs and uptime via QEMU Guest Agent on running VMs.
                # IMPORTANT: status/agent calls are in a SEPARATE try - even if
                # they fail transiently, ram_mb/networks/vlans/disk read from
                # config above are NOT lost (enrich_failed is not triggered).
                # Otherwise one agent hiccup hides all config changes that sync.
                if entry["power_state"] == "running":
                    try:
                        status = self.api.nodes(node).qemu(vmid).status.current.get()
                        if status.get("uptime"):
                            entry["last_boot"] = datetime.utcfromtimestamp(
                                int(datetime.utcnow().timestamp()) - int(status["uptime"]))
                    except Exception as exc:
                        logger.debug("Could not fetch status.current %s/%s: %s", node, vmid, exc)
                    agent_ok = False        # network-get-interfaces answered (IPs came)
                    agent_alive = False     # ANY agent command answered (agent runs)
                    try:
                        agent = self.api.nodes(node).qemu(vmid).agent(
                            "network-get-interfaces").get()
                        ips = []
                        for iface in agent.get("result", []):
                            for addr in iface.get("ip-addresses", []):
                                ip = addr.get("ip-address", "")
                                if addr.get("ip-address-type") == "ipv4" and \
                                        not ip.startswith("127."):
                                    ips.append(ip)
                        entry["ip_addresses"] = ",".join(sorted(set(ips)))
                        agent_ok = True
                        agent_alive = True
                    except Exception:
                        pass
                    # Old/limited qemu-guest-agent builds (seen more on PVE 8.4.x) may
                    # reject network-get-interfaces yet still run. Fall back to the
                    # universal probes: 'info' (GET), then 'ping' (POST). Any answer
                    # means the agent is alive -> don't report "not installed".
                    if not agent_alive:
                        try:
                            self.api.nodes(node).qemu(vmid).agent("info").get()
                            agent_alive = True
                        except Exception:
                            try:
                                self.api.nodes(node).qemu(vmid).agent.ping.post()
                                agent_alive = True
                            except Exception:
                                pass
                    entry["tools_status"] = ("guestToolsRunning" if agent_alive
                                             else "guestToolsNotRunning")

                    # Real OS name from the agent (e.g. "Ubuntu 22.04.3 LTS").
                    # Tried INDEPENDENTLY of the network call: some guests block
                    # network-get-interfaces but get-osinfo still works.
                    os_from_agent = False
                    try:
                        osinfo = self.api.nodes(node).qemu(vmid).agent(
                            "get-osinfo").get()
                        result = osinfo.get("result", {}) if isinstance(osinfo, dict) else {}
                        pretty = result.get("pretty-name") or \
                            (str(result.get("name", "")) + " " +
                             str(result.get("version", ""))).strip()
                        if pretty:
                            entry["guest_os"] = pretty
                            entry["tools_status"] = "guestToolsRunning"
                            agent_alive = True
                            os_from_agent = True
                        kern = result.get("kernel-release", "") or \
                            result.get("kernel-version", "")
                        if kern:
                            entry["kernel"] = kern
                        if result.get("machine"):
                            entry["arch"] = result.get("machine", "")
                    except Exception:
                        pass  # agent osinfo did not answer; ostype translation is used
                    # Provenance: did guest_os/IP come from the agent or a fallback?
                    # Sync keeps the old (agent-sourced) value if the agent fails.
                    entry["os_from_agent"] = os_from_agent
                    entry["ip_from_agent"] = agent_ok

                    # REAL used disk - from guest agent filesystem info.
                    # cluster/resources 'disk' is 0 without an agent; on thin disks
                    # the qcow2 footprint exceeds real usage. The guest FS tells the
                    # truth (e.g. 80 GB allocated, 40 GB used). Agent-only.
                    if agent_alive:
                        try:
                            fs = self.api.nodes(node).qemu(vmid).agent(
                                "get-fsinfo").get()
                            used_b = 0
                            seen = False
                            for f in (fs.get("result", []) if isinstance(fs, dict) else []):
                                ub = f.get("used-bytes")
                                tb = f.get("total-bytes")
                                # Skip virtual/special FS (tmpfs etc., total=0)
                                if ub is not None and tb:
                                    used_b += int(ub)
                                    seen = True
                            if seen:
                                entry["disk_used_gb"] = round(used_b / 1024**3, 1)
                        except Exception:
                            pass  # agent does not support fsinfo -> disk_used stays empty

                # If the agent gave no IPs, fall back to cloud-init static IPs
                # (for stopped VMs and guests without an agent)
                if not entry["ip_addresses"] and cloudinit_ips:
                    entry["ip_addresses"] = ",".join(sorted(set(cloudinit_ips)))
            except Exception as exc:
                entry["enrich_failed"] = True
                logger.warning("Could not fetch VM details %s/%s: %s", node, vmid, exc)
            vms.append(entry)
        return vms

    def _enrich_lxc(self, entry, node, vmid, vlan_map):
        """LXC container details: OS type, tags, notes, network (IP/MAC/VLAN),
        mount-point disks, uptime and live IPs on running containers.
        Containers have no QEMU Guest Agent; IPs come straight from the config
        or, while running, from the /lxc/{id}/interfaces endpoint."""
        cfg = self.api.nodes(node).lxc(vmid).config.get()
        ostype = cfg.get("ostype", "") or ""
        entry["guest_os"] = OSTYPE_MAP.get(ostype, ostype.capitalize()) or "Linux"
        # Configured RAM: LXC config 'memory' (MB) - stable source.
        if cfg.get("memory") not in (None, ""):
            try:
                entry["ram_mb"] = int(cfg["memory"])
            except (TypeError, ValueError):
                pass
        desc = cfg.get("description", "") or ""
        if desc:
            try:
                from urllib.parse import unquote
                desc = unquote(desc)
            except Exception:
                pass
        entry["guest_notes"] = desc
        entry["platform_tags"] = (cfg.get("tags") or "").replace(";", ",")
        entry["dns_servers"] = ",".join(str(cfg.get("nameserver") or "").split())

        macs, vlans, bridges, disks, stores = [], [], [], [], []
        static_ips = []
        for key, val in cfg.items():
            sval = str(val)
            if key.startswith("net"):     # name=eth0,bridge=vmbr0,hwaddr=AA:..,ip=10.0.0.5/24,tag=100
                nic_bridge, nic_tag = "", ""
                for piece in sval.split(","):
                    if "=" not in piece:
                        continue
                    k, v = piece.split("=", 1)
                    if k == "hwaddr":
                        macs.append(v.upper())
                    elif k == "bridge":
                        nic_bridge = v
                        bridges.append(v)
                    elif k == "tag":
                        nic_tag = v
                    elif k == "ip" and v not in ("dhcp", "manual", ""):
                        static_ips.append(v.split("/")[0])
                if nic_tag:
                    vlans.append(nic_tag)
                elif nic_bridge:
                    mapped = vlan_map.get(f"{node}/{nic_bridge}") or vlan_map.get(nic_bridge)
                    if mapped:
                        vlans.append(mapped)
            elif (key == "rootfs" or key.startswith("mp")) and ":" in sval:
                store = sval.split(":", 1)[0]
                if store not in ("none",):
                    stores.append(store)
                    size_raw = ""
                    for piece in sval.split(","):
                        if piece.startswith("size="):
                            size_raw = piece[5:]
                    disks.append({"label": key, "size_gb": self._size_to_gb(size_raw)})

        entry.update({
            "mac_addresses": ",".join(sorted(set(macs))),
            "vlans": ",".join(sorted(set(vlans))),
            "networks": ",".join(sorted(set(bridges))),
            "datastore": ",".join(sorted(set(stores))),
            "disks_json": json.dumps(disks, ensure_ascii=False),
            "disk_total_gb": round(sum(d["size_gb"] for d in disks), 1)
                             or entry["disk_total_gb"],
        })

        if entry["power_state"] == "running":
            try:
                status = self.api.nodes(node).lxc(vmid).status.current.get()
                if status.get("uptime"):
                    entry["last_boot"] = datetime.utcfromtimestamp(
                        int(datetime.utcnow().timestamp()) - int(status["uptime"]))
            except Exception:
                pass
            # Live IPs of a running container (no agent needed)
            try:
                live = []
                for iface in (self.api.nodes(node).lxc(vmid).interfaces.get() or []):
                    ip = iface.get("inet", "") or ""
                    if ip and not ip.startswith("127."):
                        live.append(ip.split("/")[0])
                if live:
                    entry["ip_addresses"] = ",".join(sorted(set(live)))
                    entry["tools_status"] = "guestToolsRunning"
            except Exception:
                pass
        if not entry["ip_addresses"] and static_ips:
            entry["ip_addresses"] = ",".join(sorted(set(static_ips)))

    # ---------- Networks ----------
    def collect_networks(self) -> list[dict]:
        nets = []
        vlan_map = self._bridge_vlan_map()
        for node in self.api.nodes.get():
            if node.get("status") != "online":
                continue
            name = node["node"]
            try:
                for iface in self.api.nodes(name).network.get():
                    itype = iface.get("type")
                    iname = iface.get("iface", "")
                    # Physical / bond NICs (the host's own interfaces)
                    if itype in ("eth", "bond"):
                        nets.append({
                            "name": iname, "host_name": name, "kind": "pnic",
                            "mac": iface.get("hwaddr", "") or "",
                            "link_speed": "",
                            "vswitch": "bond" if itype == "bond" else "",
                        })
                        continue
                    if itype not in ("bridge", "vlan", "OVSBridge"):
                        continue
                    # VLAN ID: the field itself first, then from the name (bond0.205),
                    # then from the bridge->VLAN map (vmbr1 -> 205)
                    vlan = str(iface.get("vlan-id", "") or "") or \
                           self._vlan_from_name(iname) or \
                           vlan_map.get(f"{name}/{iname}", "")
                    # VLAN-aware bridges carry multiple VLANs; note it
                    portgroup = ""
                    if str(iface.get("bridge_vlan_aware", "")) in ("1", "True", "true"):
                        portgroup = "VLAN-aware (çoklu VLAN)"
                    nets.append({
                        "name": iname,
                        "vlan": vlan,
                        "vswitch": iname if iface.get("type") != "vlan"
                                   else str(iface.get("vlan-raw-device", "") or
                                            iname.rsplit(".", 1)[0]),
                        "portgroup": portgroup,
                        "subnet": iface.get("cidr", "") or "",
                        "host_name": name,
                        "kind": "bridge",
                    })
            except Exception as exc:
                logger.warning("Could not fetch node network %s: %s", name, exc)

        # Also add SDN vnets to the network inventory
        try:
            for vnet in self.api.cluster.sdn.vnets.get():
                nets.append({
                    "name": vnet.get("vnet", ""),
                    "vlan": str(vnet.get("tag", "") or ""),
                    "vswitch": vnet.get("zone", ""),
                    "portgroup": "SDN vnet",
                    "subnet": "",
                    "host_name": "(cluster)",
                    "kind": "vnet",
                })
        except Exception:
            pass  # SDN may be unconfigured
        return nets

    # ---------- Storage ----------
    def collect_datastores(self) -> list[dict]:
        # Shared stores (NFS / Ceph / PBS ...) repeat on every node -> collapse to
        # one row, bump host_count. Local stores (local, local-lvm ...) are SEPARATE
        # physical stores per node (even with the same name) -> one row per node.
        # The 'shared' flag drives this distinction (prevents duplicates).
        # Shared stores show the cluster name instead of 'node' (multi-cluster).
        cluster = self._cluster_name()
        rows = {}
        for s in self.api.cluster.resources.get(type="storage"):
            name = s.get("storage", "")
            node = s.get("node", "")
            shared = bool(int(s.get("shared", 0) or 0))
            cap = (s.get("maxdisk", 0) or 0) / 1024**3
            used = (s.get("disk", 0) or 0) / 1024**3
            active = s.get("status", "") == "available"
            key = name if shared else f"{name}@{node}"
            if key in rows:
                rows[key]["host_count"] += 1
                continue
            rows[key] = {"name": name, "type": s.get("plugintype", ""),
                         "node": (cluster if shared else node), "shared": shared,
                         "capacity_gb": round(cap, 1), "used_gb": round(used, 1),
                         "free_gb": round(cap - used, 1), "host_count": 1,
                         "status": "active" if active else "inactive"}
        return list(rows.values())

    def collect_snapshots(self) -> list[dict]:
        """Snapshot list per qemu/lxc guest, excluding 'current' (the live state)."""
        result = []
        for r in self.api.cluster.resources.get(type="vm"):
            rtype = r.get("type")
            if rtype not in ("qemu", "lxc"):
                continue
            node, vmid = r["node"], r["vmid"]
            vmname = r.get("name", f"vm-{vmid}")
            ext = f"{node}/{vmid}"
            try:
                endpoint = (self.api.nodes(node).qemu(vmid) if rtype == "qemu"
                            else self.api.nodes(node).lxc(vmid))
                snaps = endpoint.snapshot.get()
            except Exception as exc:
                logger.warning("Could not fetch snapshot list %s: %s", ext, exc)
                continue
            # parent of the 'current' entry = the snapshot the VM currently sits on
            active = ""
            for s in snaps:
                if s.get("name") == "current":
                    active = s.get("parent", "") or ""
                    break
            for s in snaps:
                nm = s.get("name")
                if not nm or nm == "current":   # 'current' is not a real snapshot
                    continue
                st = s.get("snaptime")
                result.append({
                    "vm_external_id": ext, "vm_name": vmname,
                    "name": nm, "description": (s.get("description") or "").strip(),
                    "created_at": datetime.utcfromtimestamp(st) if st else None,
                    "is_current": nm == active,
                    "parent": s.get("parent", "") or "",
                })
        return result

    def _fetch_content(self, node: str, name: str):
        """Fetch storage content. On some PBS versions the unfiltered query is
        empty, on others content=backup is - so BOTH are tried and the result
        with MORE rows wins. Returns (content_list, error)."""
        best, err = None, None
        for kwargs in ({"content": "backup"}, {}):
            try:
                r = self.api.nodes(node).storage(name).content.get(**kwargs)
                if best is None or len(r) > len(best):
                    best = r
            except Exception as exc:
                err = exc
        return best, (None if best is not None else err)

    def _all_storage_configs(self):
        """Read all storage configs once from the /storage list (per-id
        /storage/{name} can come back empty on some setups/permissions).
        Returns ({name: cfg}, error)."""
        try:
            rows = self.api.storage.get() or []
            return {r.get("storage", ""): r for r in rows}, ""
        except Exception as exc:
            return {}, str(exc)

    def _storage_config(self, name: str) -> dict:
        """/storage/{name} config (PBS namespace/datastore/server/user)."""
        try:
            return self.api.storage(name).get() or {}
        except Exception:
            cfg_map, _ = self._all_storage_configs()
            return cfg_map.get(name, {})

    @staticmethod
    def _is_backup(ctype, volid, plugin) -> bool:
        return (ctype == "backup") or ("/backup/" in volid) or ("vzdump-" in volid) \
            or (plugin == "pbs" and ctype in (None, "", "backup"))

    def _storage_groups(self):
        """Group cluster/resources storage rows by name.
        name -> {shared, plugin, content_field, nodes:[(node,status), ...]}."""
        groups = {}
        for s in self.api.cluster.resources.get(type="storage"):
            name, node = s.get("storage", ""), s.get("node", "")
            if not name or not node:
                continue
            g = groups.setdefault(name, {
                "shared": bool(int(s.get("shared", 0) or 0)),
                "plugin": s.get("plugintype", ""),
                "content": s.get("content", "") or "",
                "nodes": []})
            g["nodes"].append((node, s.get("status", "")))
        return groups

    def _online_nodes(self):
        """Online node names in the cluster (shared stores are tried on all nodes)."""
        try:
            return [n.get("node") for n in self.api.nodes.get()
                    if n.get("node") and n.get("status", "online") != "offline"]
        except Exception:
            return []

    def _candidate_nodes(self, g):
        """Node order to query.
        - Local store: only the node(s) it is defined on.
        - Shared store (incl. PBS): ALL online nodes are tried, because the REST
          API only returns PBS content on a node that can actually reach the PBS;
          the cluster/resources 'available' flag can mislead (pvesm list may work
          on one node while REST returns empty on another)."""
        if not g["shared"]:
            return [(n, st) for n, st in g["nodes"]]
        res_avail = [n for n, st in g["nodes"] if st == "available"]
        res_other = [n for n, _ in g["nodes"] if n not in res_avail]
        online = [n for n in self._online_nodes()
                  if n not in res_avail and n not in res_other]
        return [(n, "") for n in (res_avail + res_other + online)]

    def collect_backups(self) -> list[dict]:
        """Collect backups from storage content (vzdump + PBS).

        - Groups by storage NAME; shared stores are tried on multiple nodes
          (active node first, first node returning content wins); local on each node.
        - Fetches content UNFILTERED and filters backups itself (the filtered
          query is empty on some versions/permissions).
        """
        result, seen_vol = [], set()
        try:
            groups = self._storage_groups()
        except Exception as exc:
            logger.warning("Depo listesi alinamadi: %s", exc)
            return result

        for name, g in groups.items():
            # Skip stores that cannot hold backups (speed) - except PBS (all content is backup)
            if g["plugin"] != "pbs" and "backup" not in g["content"]:
                continue
            for node, _status in self._candidate_nodes(g):
                content, err = self._fetch_content(node, name)
                if content is None:
                    logger.warning("Icerik alinamadi %s/%s: %s", node, name, err)
                    continue
                found = 0
                for c in content:
                    ctype, volid = c.get("content"), c.get("volid", "")
                    if not volid or volid in seen_vol:
                        continue
                    if not self._is_backup(ctype, volid, g["plugin"]):
                        continue
                    seen_vol.add(volid)
                    found += 1
                    ctime = c.get("ctime")
                    tail = volid.split("/")[-1]
                    fmt = c.get("format", "") or (tail.split(".", 1)[1] if "." in tail else "")
                    result.append({
                        "vmid": str(c.get("vmid") or ""), "vm_name": "",
                        "storage": name, "volid": volid, "fmt": fmt,
                        "created_at": datetime.utcfromtimestamp(ctime) if ctime else None,
                        "size_gb": round((c.get("size") or 0) / 1024**3, 2),
                        "protected": bool(c.get("protected", 0)),
                        "notes": (c.get("notes") or c.get("comment") or "").strip(),
                        "source": "pbs" if g["plugin"] == "pbs" else "vzdump",
                    })
                logger.info("Yedek tarama: depo=%s node=%s tip=%s icerik=%d yedek=%d",
                            name, node, g["plugin"] or "?", len(content), found)
                # On shared stores the first node returning content is enough; scan all for local
                if g["shared"] and len(content) > 0:
                    break
        logger.info("Yedek taramasi tamamlandi: toplam %d yedek", len(result))
        return result

    def diagnose_backups(self) -> list[dict]:
        """Why are backups empty? For each storage: unfiltered item count + backup
        count + content-type breakdown + sample + tried nodes + a probable-cause code.
        Never raises."""
        out = []
        try:
            groups = self._storage_groups()
        except Exception as exc:
            return [{"error": f"cluster/resources read failed: {exc}"}]
        cfg_map, cfg_err = self._all_storage_configs()   # read all configs once

        for name, g in groups.items():
            info = {"storage": name, "node": "", "plugin": g["plugin"],
                    "content_field": g["content"], "shared": g["shared"],
                    "items": 0, "backups": 0, "sample": "", "ctypes": "",
                    "nodes_tried": 0, "error": "", "note_code": "", "config": ""}
            content, err = None, None
            pernode = []
            for node, _st in self._candidate_nodes(g):
                info["node"] = node
                info["nodes_tried"] += 1
                cc, ce = self._fetch_content(node, name)
                pernode.append(f"{node}:{'err' if cc is None else len(cc)}")
                if cc is not None and len(cc) > 0:
                    content, err = cc, ce
                    break                       # stop at the node that returned content
                if content is None:
                    content, err = cc, ce       # at least keep the last result
            info["pernode"] = ", ".join(pernode)
            # Read config for PBS (namespace + PBS API user are the prime suspects)
            if g["plugin"] == "pbs":
                cfg = cfg_map.get(name) or self._storage_config(name)
                ns = cfg.get("namespace") or "(root)"
                ds = cfg.get("datastore") or "?"
                srv = cfg.get("server") or "?"
                usr = cfg.get("username") or "?"      # PBS API user/token
                info["config"] = f"datastore={ds} · namespace={ns} · server={srv} · PBS-user={usr}"
                if not cfg and cfg_err:
                    info["config"] += f"  (config read failed: {cfg_err})"
                # Storage STATUS (usage): confirms whether there is data or not.
                if info["node"]:
                    try:
                        st = self.api.nodes(info["node"]).storage(name).status.get()
                        used = (st.get("used") or 0) / 1024**3
                        total = (st.get("total") or 0) / 1024**3
                        info["used_gb"] = round(used, 1)
                        info["total_gb"] = round(total, 1)
                        info["active"] = st.get("active", st.get("enabled"))
                        info["config"] += (f" · usage={info['used_gb']}/{info['total_gb']} GB"
                                           f" · active={info['active']}")
                    except Exception as exc:
                        info["config"] += f" · status read failed: {exc}"
                # Separate filtered vs unfiltered counts (to see which one returns)
                if info["node"]:
                    try:
                        nb = self.api.nodes(info["node"]).storage(name).content.get(content="backup")
                        info["n_backup_filter"] = len(nb)
                    except Exception:
                        info["n_backup_filter"] = -1
                    try:
                        na = self.api.nodes(info["node"]).storage(name).content.get()
                        info["n_unfiltered"] = len(na)
                    except Exception:
                        info["n_unfiltered"] = -1
            if content is None:
                info["error"] = str(err)
                out.append(info)
                continue
            info["items"] = len(content)
            ctype_counts = {}
            for c in content:
                ct = c.get("content") or "?"
                ctype_counts[ct] = ctype_counts.get(ct, 0) + 1
                volid = c.get("volid", "")
                if self._is_backup(c.get("content"), volid, g["plugin"]):
                    info["backups"] += 1
                    if not info["sample"]:
                        info["sample"] = volid
            info["ctypes"] = ", ".join(f"{k}:{v}" for k, v in sorted(ctype_counts.items()))
            # Probable-cause code (rendered bilingually on the frontend)
            if info["items"] == 0:
                if g["plugin"] == "pbs":
                    used = info.get("used_gb")
                    if used and used > 1:
                        info["note_code"] = "pbs_data_no_content"
                        info["note_used_gb"] = used
                        info["note_has_token"] = bool(getattr(self, "token_name", None))
                    else:
                        info["note_code"] = "pbs_empty"
                else:
                    info["note_code"] = "storage_empty"
            elif info["backups"] == 0:
                info["note_code"] = "no_backups"
            out.append(info)
        return out

    # Proxmox task type -> (category, direction). Direction only for power operations.
    _TASK_CATEGORY = {
        "qmcreate": ("lifecycle", "create"), "vzcreate": ("lifecycle", "create"),
        "qmclone": ("lifecycle", "clone"),   "vzclone": ("lifecycle", "clone"),
        "qmrestore": ("lifecycle", "restore"), "vzrestore": ("lifecycle", "restore"),
        "qmdestroy": ("lifecycle", "destroy"), "vzdestroy": ("lifecycle", "destroy"),
        "qmtemplate": ("lifecycle", "template"), "vztemplate": ("lifecycle", "template"),
        # Migration: the QEMU migrate task type is 'qmigrate' (single m), CT 'vzmigrate'
        # or 'pctmigrate'. The old 'qmmigrate' (double m) matched NO task ->
        # "who migrated" stayed empty. Cover all:
        "qmigrate": ("migrate", "migrate"), "qmmigrate": ("migrate", "migrate"),
        "vzmigrate": ("migrate", "migrate"), "pctmigrate": ("migrate", "migrate"),
        "qmconfig": ("config", None), "vzconfig": ("config", None),
        "pctconfig": ("config", None),
        "qmresize": ("disk", None),
        "qmsnapshot": ("snapshot", "create"), "vzsnapshot": ("snapshot", "create"),
        "qmdelsnapshot": ("snapshot", "delete"), "vzdelsnapshot": ("snapshot", "delete"),
        "qmrollback": ("snapshot", "rollback"), "vzrollback": ("snapshot", "rollback"),
        "qmstart": ("power", "on"),  "vzstart": ("power", "on"),  "qmresume": ("power", "on"),
        "qmstop": ("power", "off"),  "vzstop": ("power", "off"),
        "qmshutdown": ("power", "off"), "vzshutdown": ("power", "off"),
        "qmsuspend": ("power", "suspend"),
        "qmreboot": ("power", "reboot"), "qmreset": ("power", "reboot"),
        "vzreboot": ("power", "reboot"),
        "vncproxy": ("console", "open"), "qmvncproxy": ("console", "open"),
        "vncshell": ("console", "open"), "termproxy": ("console", "open"),
        "spiceproxy": ("console", "open"), "spiceshell": ("console", "open"),
    }

    def _clone_newid_from_log(self, node, upid):
        """Extract the NEW vmid from a clone task's log.

        qmclone/vzclone task logs contain "... to vm-<NNN>-disk-X" (or
        subvol-<NNN>-...) lines, giving the vmid the clone created. Returns
        None if not found. (Task logs are readable with Sys.Audit.)"""
        try:
            lines = self.api.nodes(node).tasks(upid).log.get(limit=400) or []
        except Exception as exc:
            logger.warning("Could not read clone task log (%s): %s", upid[:40], exc)
            return None
        pat = re.compile(r"\bto (?:vm|subvol|base)-(\d+)-disk")
        for ln in lines:
            txt = ln.get("t") if isinstance(ln, dict) else None
            m = pat.search(txt or "")
            if m:
                return m.group(1)
        return None

    def collect_recent_actors(self) -> dict:
        """'Who changed what, and when' - an operation list per VM.

        Returns {external_id: [op, ...]}; each op:
          {ts, op, category, direction, actor, actor_ip, host, detail}
        The list is sorted newest to oldest. sync_service matches every detected
        field change to the right operation BY CATEGORY (e.g. a RAM change only
        matches 'config', a power_state change only 'power'), so one user's
        action is never attributed to another user.

        Proxmox task records keep no client IP / User-Agent -> actor_ip stays empty.
        UPID: UPID:node:pid:pstart:starttime:type:id:user:
        """
        ops: dict[str, list] = {}
        # /nodes/{node}/tasks supports 'limit' (wide history); /cluster/tasks caps at ~50.
        tasks = []
        try:
            nodes = [r["node"] for r in self.api.cluster.resources.get(type="node")
                     if r.get("node")]
        except Exception as exc:
            logger.warning("Could not fetch node list: %s", exc)
            nodes = []
        for node in nodes:
            try:
                nt = self.api.nodes(node).tasks.get(limit=500) or []
            except Exception as exc:
                logger.warning("Could not fetch tasks of node %s: %s", node, exc)
                continue
            for t in nt:
                t.setdefault("node", node)
            tasks.extend(nt)
        if not tasks:   # fallback: cluster-wide recent tasks (no limit)
            try:
                tasks = self.api.cluster.tasks.get() or []
            except Exception as exc:
                logger.warning("Could not fetch task records (Sys.Audit permission may be required): %s", exc)
                return ops
        tasks.sort(key=lambda t: t.get("starttime", 0) or 0, reverse=True)  # newest first

        def parse(t):
            node = t.get("node") or ""
            ttype = t.get("type") or ""
            vmid = str(t.get("id") or "")
            user = t.get("user") or ""
            upid = t.get("upid") or ""
            if upid and not (node and ttype and vmid and user):
                p = upid.split(":")               # UPID:node:pid:pstart:start:type:id:user:
                if len(p) >= 8:
                    node = node or p[1]
                    ttype = ttype or p[5]
                    vmid = vmid or p[6]
                    user = user or p[7]
            return node, ttype, vmid.split(":")[0], user

        scanned = 0
        clone_tasks = []   # (node, upid, ttype, src_vmid, user, ts) — yeni vmid log'dan
        for t in tasks:                           # en yeniden eskiye
            node, ttype, vmid, user = parse(t)
            if not (node and vmid):
                continue
            cat = self._TASK_CATEGORY.get(ttype)
            if not cat:
                continue
            category, direction = cat
            scanned += 1
            ext = f"{node}/{vmid}"
            ts = t.get("starttime") or 0
            ops.setdefault(ext, []).append({
                "ts": ts,
                "op": ttype,
                "category": category,
                "direction": direction,
                "actor": user or None,
                "actor_ip": None,     # Proxmox task records keep no client IP
                "actor_agent": None,
                "host": node,         # the node the VM lives on
                "detail": None,
            })
            # A clone task's UPID carries the SOURCE vmid, NOT the new one.
            # The new vmid only appears in the task LOG ("... to vm-<NNN>-disk").
            if direction == "clone" and user and t.get("upid"):
                clone_tasks.append((node, t["upid"], ttype, vmid, user, ts))

        # Resolve the new vmid from the task log -> attach the clone op to the NEW
        # vm (node/newid) so the new VM finds its own clone record/cloner.
        clone_resolved = 0
        for node, upid, ttype, src, user, ts in clone_tasks[:40]:   # cap at the last 40 clones
            newid = self._clone_newid_from_log(node, upid)
            if not newid or newid == src:
                continue
            clone_resolved += 1
            ops.setdefault(f"{node}/{newid}", []).append({
                "ts": ts, "op": ttype, "category": "lifecycle", "direction": "clone",
                "actor": user, "actor_ip": None, "actor_agent": None,
                "host": node, "detail": f"kaynak vmid {src}",
            })

        # --- phase36: config operations from /cluster/log ---
        # In Proxmox, config changes made via the web UI/API (RAM, CPU,
        # network, disk add...) usually do NOT land in /nodes/{node}/tasks;
        # they are only written to the cluster log as "update VM <id>: ...".
        # We extract config-actors from those lines (so RAM isn't '-').
        log_scanned = 0
        log_err = False
        try:
            logs = self.api.cluster.log.get(max=1500) or []
        except Exception as exc:
            log_err = True
            logger.warning("Could not fetch cluster log: %s", exc)
            logs = []
        if not logs and not log_err:
            # Empty array (not an error) -> token role lacks Sys.Syslog.
            # /cluster/log returns EMPTY with PVEAuditor/Sys.Audit; Sys.Syslog ('/')
            # is required. Config (RAM/CPU/net) changes produce NO task, so
            # their user can ONLY be read from this source.
            logger.warning("Cluster log BOS dondu — token rolune 'Sys.Syslog' (/) "
                           "ekleyin; aksi halde config degisikliklerinin kullanicisi "
                           "'—' kalir.")
        # "update VM 109: ...", "update CT 110: ..." -> vmid; node is on the line.
        log_re = re.compile(r"\bupdate\s+(?:VM|CT)\s+(\d+)\b", re.IGNORECASE)
        # Migration ops from UPIDs in cluster-log task lines (qmigrate):
        # UPID:node:pid:pstart:start:type:id:user: -> independent/wide source for
        # migrations that fell out of the task window or had an empty user.
        upid_re = re.compile(
            r"UPID:([^:\s]+):[^:]+:[^:]+:[^:]+:(qmigrate|vzmigrate):(\d+):([^:\s]+):")
        for entry in logs:
            msg = str(entry.get("msg") or "")
            mu = upid_re.search(msg)
            if mu:
                m_node, m_type, m_vmid, m_user = mu.groups()
                if m_node and m_vmid and m_user:
                    log_scanned += 1
                    ops.setdefault(f"{m_node}/{m_vmid}", []).append({
                        "ts": entry.get("time") or 0,
                        "op": m_type, "category": "migrate", "direction": "migrate",
                        "actor": m_user, "actor_ip": None, "actor_agent": None,
                        "host": m_node, "detail": None,
                    })
            m = log_re.search(msg)
            if not m:
                continue
            node = entry.get("node") or ""
            user = entry.get("user") or ""
            if not node or not user:
                continue
            vmid = m.group(1)
            log_scanned += 1
            ops.setdefault(f"{node}/{vmid}", []).append({
                "ts": entry.get("time") or 0,
                "op": "update (cluster log)",
                "category": "config",
                "direction": None,
                "actor": user,
                "actor_ip": None,
                "actor_agent": None,
                "host": node,
                "detail": msg[:200],
            })

        # Sort each VM's op list newest -> oldest (tasks + log merged)
        for lst in ops.values():
            lst.sort(key=lambda o: o.get("ts") or 0, reverse=True)

        logger.info("Proxmox actors: %d VMs mapped "
                    "(%d tasks + %d log lines + %d clones resolved)",
                    len(ops), scanned, log_scanned, clone_resolved)
        return ops

    # Cluster-log message pattern for storage / SDN entity changes.
    _ENTITY_LOG_RE = re.compile(
        r"\b(create|add|update|set|delete|remove)\s+"
        r"(storage|vnet|sdn\s*vnet|zone)\s+'?([\w.\-:]+)'?", re.IGNORECASE)

    def collect_entity_actors(self, days: int = 3):
        """Who added/removed storages (datastores) and SDN vnets (networks).

        Parsed from /cluster/log (needs Sys.Syslog, same as config actors).
        Returns {(entity_type, name): {"actor", "ts", "op"}} (newest wins).
        Best-effort: nothing matched -> empty dict, rows just get no actor.
        """
        out = {}
        try:
            entries = self.api.cluster.log.get(max=1000) or []
        except Exception as exc:
            logger.warning("Could not fetch cluster log (entity actors): %s", exc)
            return out
        min_ts = int(datetime.utcnow().timestamp()) - days * 86400
        for en in entries:
            ts = int(en.get("time") or 0)
            if ts < min_ts:
                continue
            user = (en.get("user") or "").strip()
            m = self._ENTITY_LOG_RE.search(str(en.get("msg") or ""))
            if not m or not user:
                continue
            verb, kind, name = m.group(1).lower(), m.group(2).lower(), m.group(3)
            ent = "datastore" if kind == "storage" else "network"
            key = (ent, name)
            if key not in out or ts > out[key]["ts"]:
                out[key] = {"actor": user, "ts": ts, "op": f"{verb} {kind}"}
        return out

    # ---------- Lightweight usage sync ----------
    def collect_usage(self) -> dict:
        """
        Instant CPU/RAM/disk usage ratios - a SINGLE API call (cluster/resources).

        Runs independently of the full sync and much more often (e.g. every
        3 min). With no config/agent queries it takes seconds even at 500+ VMs
        and puts no measurable load on the live environment.
        """
        vms, hosts = [], []
        for res in self.api.cluster.resources.get():
            if res.get("type") in ("qemu", "lxc") and not res.get("template"):
                vms.append({
                    # VMs are keyed by node/vmid (same key as collect_vms)
                    "external_id": f"{res.get('node', '')}/{res.get('vmid', '')}",
                    "cpu_pct": round((res.get("cpu") or 0) * 100, 1),
                    "ram_used_mb": int((res.get("mem") or 0) / (1024 * 1024)),
                    # disk_used_gb is INTENTIONALLY None: cluster/resources 'disk' is 0
                    # without an agent and thin footprints inflate -> wrong. Real usage
                    # comes from guest-agent get-fsinfo in the full sync; usage must NOT overwrite it.
                    "disk_used_gb": None,
                    # Cumulative IO counters (bytes since VM start). The rate (KB/s)
                    # is computed on the sync side from consecutive sample deltas.
                    "net_bytes": int((res.get("netin") or 0) + (res.get("netout") or 0)),
                    "disk_bytes": int((res.get("diskread") or 0) + (res.get("diskwrite") or 0)),
                })
            elif res.get("type") == "node":
                maxmem = res.get("maxmem") or 0
                maxdisk = res.get("maxdisk") or 0
                hosts.append({
                    "name": res.get("node", ""),
                    "cpu_pct": round((res.get("cpu") or 0) * 100, 1),
                    "ram_used_mb": int((res.get("mem") or 0) / (1024 * 1024)),
                    "disk_used_gb": round((res.get("disk") or 0) / (1024 ** 3), 1),
                })
        return {"vms": vms, "hosts": hosts}
