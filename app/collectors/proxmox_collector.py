"""
Proxmox VE veri toplayıcısı (proxmoxer - resmi REST API istemcisi, SSH KULLANILMAZ).

Kimlik doğrulama: API Token (önerilen) veya kullanıcı/parola.
Toplananlar: node'lar (host), QEMU VM'leri, ağ (bridge/VLAN), storage.
QEMU Guest Agent kuruluysa VM içi IP adresleri de alınır.
"""
import json
import logging
from datetime import datetime

from proxmoxer import ProxmoxAPI

logger = logging.getLogger("collector.proxmox")

# Proxmox'un iç "ostype" kodları -> okunaklı isimler.
# Guest Agent çalışıyorsa gerçek OS adı misafirden alınır ve bu değeri ezer.
OSTYPE_MAP = {
    "l26": "Linux",                  # Proxmox 'l26' = modern Linux ipucu (gerçek dağıtım değil)
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
        token_name biçimi: kullanici@realm!tokenid  (örn: api@pam!envanter)
        Token verilirse parola yöntemi yok sayılır.
        """
        self.host = host
        self.port = port
        self.verify_ssl = verify_ssl
        self.username = username
        self.password = password
        self.token_name = token_name
        self.token_value = token_value
        self.api = None

    # ---------- Bağlantı ----------
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
        """Bağlantı testi: sürüm bilgisini sorgular."""
        try:
            self.connect()
            version = self.api.version.get()
            return {"success": True,
                    "message": f"Bağlantı başarılı: Proxmox VE {version.get('version')}",
                    "version": version.get("version")}
        except Exception as exc:
            return {"success": False, "message": f"Bağlantı hatası: {exc}"}

    # ---------- Cluster adı ----------
    def _cluster_name(self) -> str:
        """
        Proxmox cluster adını döndürür. Cluster kurulu değilse (tek node)
        node adı kullanılır ki arayüzde Cluster kolonu boş kalmasın.
        """
        try:
            for item in self.api.cluster.status.get():
                if item.get("type") == "cluster":
                    return item.get("name", "")
        except Exception:
            pass
        try:  # bağımsız node: ilk node'un adını cluster gibi kullan
            nodes = self.api.nodes.get()
            if len(nodes) == 1:
                return nodes[0]["node"]
        except Exception:
            pass
        return ""

    # ---------- Yönetim IP'si seçimi ----------
    @staticmethod
    def _pick_mgmt_ip(ifaces: list) -> str:
        """
        Node'un yönetim IP'sini DETERMİNİSTİK seç.

        Proxmox API ağ arayüzlerini sabit sırada döndürmez. Önceki sürümde
        'ilk adresli arayüz' alındığı için çok kartlı node'larda her
        senkronizasyonda IP değişebiliyor ve değişiklik geçmişi kirleniyordu.
        Sabit öncelik:
          1) Varsayılan rota (gateway tanımlı) arayüzü — gerçek yönetim IP'si
          2) vmbr0 yönetim köprüsü
          3) Geri düşüş: arayüz adına göre sıralı ilk adresli arayüz
        """
        addressed = [i for i in (ifaces or []) if i.get("address")]
        if not addressed:
            return ""
        ordered = sorted(addressed, key=lambda x: str(x.get("iface", "")))
        for i in ordered:                       # 1) gateway tanımlı arayüz
            if i.get("gateway"):
                return i["address"]
        for i in ordered:                       # 2) vmbr0
            if i.get("iface") == "vmbr0":
                return i["address"]
        return ordered[0]["address"]            # 3) sıralı ilk

    # ---------- Host'lar (node'lar) ----------
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
            # Çevrimiçi node'lardan detay bilgisi al (CPU modeli, sürüm, IP)
            if entry["status"] == "online":
                try:
                    status = self.api.nodes(name).status.get()
                    cpuinfo = status.get("cpuinfo", {})
                    entry["cpu_model"] = cpuinfo.get("model", "")
                    entry["os_version"] = f"Proxmox VE {status.get('pveversion', '')}"
                    # Yönetim IP'si: ağ arayüzlerini DETERMİNİSTİK seç.
                    # API arayüz sırasını garanti etmediğinden, çok kartlı
                    # node'larda eskiden her senkronizasyonda farklı IP seçilip
                    # değişiklik geçmişi gereksiz yere kirleniyordu. Sabit
                    # öncelik uygulanır (bkz. _pick_mgmt_ip).
                    entry["mgmt_ip"] = self._pick_mgmt_ip(
                        self.api.nodes(name).network.get())
                except Exception as exc:
                    logger.warning("Node detayı alınamadı %s: %s", name, exc)
            hosts.append(entry)

        # Cluster adını öğren ve tüm node'lara ata
        cluster = self._cluster_name()
        for h in hosts:
            h["cluster"] = cluster
        return hosts

    # ---------- VLAN eşleme yardımcıları ----------
    @staticmethod
    def _vlan_from_name(iface_name: str) -> str:
        """'bond0.205' veya 'eno1.100' gibi isimden VLAN ID'sini çıkar."""
        if "." in iface_name:
            suffix = iface_name.rsplit(".", 1)[1]
            if suffix.isdigit():
                return suffix
        return ""

    def _bridge_vlan_map(self) -> dict:
        """
        Köprü -> VLAN eşlemesi üretir. Proxmox'ta VLAN üç yerde tanımlı olabilir:
          1) VM ağ kartında tag=  (collect_vms içinde doğrudan okunur)
          2) Node ağ yapısında: vmbr1 köprüsü bond0.205 üzerine kuruluysa
             o köprüye bağlı her VM aslında VLAN 205'tedir
          3) SDN vnet'lerinde: vnet'in tag alanı VLAN ID'sidir
        Dönüş: {"node/köprü": vlan, "vnet_adı": vlan}
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
                # önce vlan tipindeki arayüzleri topla: ad -> vlan id
                vlan_ifaces = {}
                for i in ifaces:
                    if i.get("type") == "vlan":
                        vid = str(i.get("vlan-id") or "") or \
                              self._vlan_from_name(i.get("iface", ""))
                        if vid:
                            vlan_ifaces[i["iface"]] = vid
                # köprüleri tara: portları vlan arayüzüne bağlıysa eşle
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
            logger.warning("Bridge VLAN eşlemesi yapılamadı: %s", exc)

        # SDN vnet'leri (cluster genelinde): vnet adı -> tag
        try:
            for vnet in self.api.cluster.sdn.vnets.get():
                if vnet.get("tag"):
                    mapping[vnet.get("vnet", "")] = str(vnet["tag"])
        except Exception:
            pass  # SDN yapılandırılmamış olabilir, normal durum
        return mapping

    # ---------- Disk boyutu ayrıştırma ----------
    @staticmethod
    def _size_to_gb(size: str) -> float:
        """
        Proxmox disk boyutunu GB (float) değerine çevir.
        Kabul edilen biçimler: '32G', '512M', '1T', '1024K' veya çıplak bayt.
        Çözülemezse 0.0 döner.
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
        cluster = self._cluster_name()           # tüm VM'lere atanacak
        vlan_map = self._bridge_vlan_map()       # köprü/vnet -> VLAN eşlemesi
        # cluster/resources tek çağrıda tüm VM özetini verir (500+ VM için verimli)
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
            # LXC konteynerleri: yapılandırma/IP/disk biçimi qemu'dan farklı,
            # QEMU Guest Agent yoktur → ayrı zenginleştirme.
            if rtype == "lxc":
                try:
                    self._enrich_lxc(entry, node, vmid, vlan_map)
                except Exception as exc:
                    entry["enrich_failed"] = True
                    logger.warning("Konteyner detayı alınamadı %s/%s: %s", node, vmid, exc)
                vms.append(entry)
                continue
            try:
                # VM yapılandırması: OS tipi, ağ kartları, diskler, VLAN
                cfg = self.api.nodes(node).qemu(vmid).config.get()
                ostype = cfg.get("ostype", "")
                entry["guest_os"] = OSTYPE_MAP.get(ostype, ostype)
                # Proxmox "Notlar" alanı (Notes); URL-encode'lu gelebilir
                desc = cfg.get("description", "") or ""
                if desc:
                    try:
                        from urllib.parse import unquote
                        desc = unquote(desc)
                    except Exception:
                        pass
                entry["guest_notes"] = desc
                # Proxmox VM etiketleri (config 'tags' alanı; ';' ile ayrık)
                entry["platform_tags"] = (cfg.get("tags") or "").replace(";", ",")
                if cfg.get("meta"):  # ctime=... oluşturulma zamanı
                    for part in cfg["meta"].split(","):
                        if part.startswith("ctime="):
                            entry["created_date"] = datetime.utcfromtimestamp(int(part[6:]))

                macs, vlans, bridges, disks, stores = [], [], [], [], []
                cloudinit_ips = []   # agent yoksa geri düşüş: cloud-init statik IP'leri
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
                            # NIC'te tag yok: köprünün kendisi bir VLAN'a bağlıysa
                            # (örn. vmbr1 -> bond0.205) veya SDN vnet ise onu kullan
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
                    # Tüm disklerin toplamı; ayrıştırılamazsa maxdisk'e geri düş
                    "disk_total_gb": round(sum(d["size_gb"] for d in disks), 1)
                                     or entry["disk_total_gb"],
                })

                # Çalışan VM'lerde QEMU Guest Agent ile IP adresleri ve uptime
                if entry["power_state"] == "running":
                    status = self.api.nodes(node).qemu(vmid).status.current.get()
                    if status.get("uptime"):
                        entry["last_boot"] = datetime.utcfromtimestamp(
                            int(datetime.utcnow().timestamp()) - int(status["uptime"]))
                    agent_ok = False
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
                        entry["tools_status"] = "guestToolsRunning"
                        agent_ok = True
                    except Exception:
                        entry["tools_status"] = "guestToolsNotRunning"  # Agent kurulu değil

                    # Agent'tan gerçek OS adı (örn: "Ubuntu 22.04.3 LTS").
                    # Ağ çağrısından BAĞIMSIZ denenir: bazı misafirlerde
                    # network-get-interfaces engellidir ama get-osinfo çalışır.
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
                            os_from_agent = True
                        kern = result.get("kernel-release", "") or \
                            result.get("kernel-version", "")
                        if kern:
                            entry["kernel"] = kern
                        if result.get("machine"):
                            entry["arch"] = result.get("machine", "")
                    except Exception:
                        pass  # agent osinfo yanıt vermedi; ostype çevirisi kullanılır
                    # Provenance: guest_os/IP agent'tan mı geldi yoksa fallback mı?
                    # Sync, agent başarısızsa eski (agent kaynaklı) değeri korur.
                    entry["os_from_agent"] = os_from_agent
                    entry["ip_from_agent"] = agent_ok

                # Agent'tan IP gelmediyse cloud-init statik IP'lerine geri düş
                # (kapalı VM'ler ve agent kurulu olmayan misafirler için)
                if not entry["ip_addresses"] and cloudinit_ips:
                    entry["ip_addresses"] = ",".join(sorted(set(cloudinit_ips)))
            except Exception as exc:
                entry["enrich_failed"] = True
                logger.warning("VM detayı alınamadı %s/%s: %s", node, vmid, exc)
            vms.append(entry)
        return vms

    def _enrich_lxc(self, entry, node, vmid, vlan_map):
        """LXC konteyneri detayı: OS tipi, etiketler, not, ağ (IP/MAC/VLAN),
        mount-point diskleri, uptime ve çalışan konteynerde canlı IP'ler.
        Konteynerlerde QEMU Guest Agent yoktur; IP doğrudan yapılandırmadan
        veya çalışırken /lxc/{id}/interfaces ucundan alınır."""
        cfg = self.api.nodes(node).lxc(vmid).config.get()
        ostype = cfg.get("ostype", "") or ""
        entry["guest_os"] = OSTYPE_MAP.get(ostype, ostype.capitalize()) or "Linux"
        desc = cfg.get("description", "") or ""
        if desc:
            try:
                from urllib.parse import unquote
                desc = unquote(desc)
            except Exception:
                pass
        entry["guest_notes"] = desc
        entry["platform_tags"] = (cfg.get("tags") or "").replace(";", ",")

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
            # Çalışan konteynerin canlı IP'leri (agent gerekmez)
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

    # ---------- Ağlar ----------
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
                    # Fiziksel / bağ kartları (host'un kendi NIC'leri)
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
                    # VLAN ID: önce alanın kendisi, sonra isimden (bond0.205),
                    # sonra köprü->VLAN eşlemesinden (vmbr1 -> 205)
                    vlan = str(iface.get("vlan-id", "") or "") or \
                           self._vlan_from_name(iname) or \
                           vlan_map.get(f"{name}/{iname}", "")
                    # VLAN-aware köprüler birden çok VLAN taşır; not olarak belirt
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
                logger.warning("Node ağı alınamadı %s: %s", name, exc)

        # SDN vnet'leri de ağ envanterine ekle
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
            pass  # SDN yapılandırılmamış olabilir
        return nets

    # ---------- Storage ----------
    def collect_datastores(self) -> list[dict]:
        # Paylaşımlı depolar (NFS / Ceph / PBS …) her node'da tekrarlanır → tek satıra
        # indir, host_count'ı artır. Yerel depolar (local, local-lvm …) her node'da
        # AYRI fiziksel depodur (ad aynı olsa bile) → node bazında ayrı satır.
        # 'shared' bayrağı bu ayrımı sağlar (mükerrer kayıt önlenir).
        # Paylaşımlı depoda 'node' yerine cluster adı gösterilir (çoklu cluster ayrımı).
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
        """Her qemu/lxc misafiri için snapshot listesi. 'current' (canlı durum) hariç."""
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
                logger.warning("Snapshot listesi alınamadı %s: %s", ext, exc)
                continue
            # 'current' girdisinin parent'ı = VM'in şu an üstünde olduğu aktif snapshot
            active = ""
            for s in snaps:
                if s.get("name") == "current":
                    active = s.get("parent", "") or ""
                    break
            for s in snaps:
                nm = s.get("name")
                if not nm or nm == "current":   # 'current' gerçek snapshot değil
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

    def collect_backups(self) -> list[dict]:
        """Depo içeriğinden yedekleri topla (vzdump dosyaları + PBS anlık görüntüleri).

        Mümkün olduğunca hoşgörülü: HER depo sorgulanır (status/content ön-filtresi yok),
        içerikten yalnızca yedek olanlar süzülür, volid ile tekilleştirilir.
        content='backup' sorgusu kabul edilmezse filtresiz tekrar denenir.
        """
        result, seen_vol, seen_store = [], set(), set()
        try:
            storages = self.api.cluster.resources.get(type="storage")
        except Exception as exc:
            logger.warning("Depo listesi alınamadı: %s", exc)
            return result
        for s in storages:
            name, node = s.get("storage", ""), s.get("node", "")
            if not name or not node:
                continue
            shared = bool(int(s.get("shared", 0) or 0))
            plugin = s.get("plugintype", "")
            # paylaşımlı depoyu tek kez, yerel depoyu node bazında sorgula
            skey = name if shared else f"{node}/{name}"
            if skey in seen_store:
                continue
            seen_store.add(skey)
            content = None
            last_exc = None
            for kwargs in ({"content": "backup"}, {}):   # önce filtreli, olmazsa filtresiz
                try:
                    content = self.api.nodes(node).storage(name).content.get(**kwargs)
                    break
                except Exception as exc:
                    last_exc = exc
            if content is None:
                logger.warning("İçerik alınamadı %s/%s: %s", node, name, last_exc)
                continue
            found = 0
            for c in content:
                ctype = c.get("content")
                volid = c.get("volid", "")
                # yalnızca yedekler: content alanı 'backup' VEYA volid yedek desenli
                is_backup = (ctype == "backup") or ("/backup/" in volid) \
                    or ("vzdump-" in volid) or (ctype is None and "backup" in volid)
                if not is_backup or not volid or volid in seen_vol:
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
                    "source": "pbs" if plugin == "pbs" else "vzdump",
                })
            logger.info("Yedek tarama: depo=%s node=%s tip=%s içerik=%d yedek=%d",
                        name, node, plugin or "?", len(content), found)
        logger.info("Yedek taraması tamamlandı: toplam %d yedek", len(result))
        return result

    def diagnose_backups(self) -> list[dict]:
        """Yedek toplamanın neden boş döndüğünü teşhis et (UI'da gösterilir).

        Her depo için: ad, node, eklenti, content alanı, içerik sayısı, yedek sayısı,
        örnek volid ve varsa hata mesajı. Hiç istisna fırlatmaz.
        """
        out, seen = [], set()
        try:
            storages = self.api.cluster.resources.get(type="storage")
        except Exception as exc:
            return [{"error": f"cluster/resources okunamadı: {exc}"}]
        for s in storages:
            name, node = s.get("storage", ""), s.get("node", "")
            if not name or not node:
                continue
            shared = bool(int(s.get("shared", 0) or 0))
            skey = name if shared else f"{node}/{name}"
            if skey in seen:
                continue
            seen.add(skey)
            info = {"storage": name, "node": node, "plugin": s.get("plugintype", ""),
                    "content_field": s.get("content", ""), "items": 0, "backups": 0,
                    "sample": "", "error": ""}
            content = None
            for kwargs in ({"content": "backup"}, {}):
                try:
                    content = self.api.nodes(node).storage(name).content.get(**kwargs)
                    break
                except Exception as exc:
                    info["error"] = str(exc)
            if content is None:
                out.append(info)
                continue
            info["error"] = ""
            info["items"] = len(content)
            for c in content:
                volid = c.get("volid", "")
                if c.get("content") == "backup" or "/backup/" in volid or "vzdump-" in volid:
                    info["backups"] += 1
                    if not info["sample"]:
                        info["sample"] = volid
            out.append(info)
        return out

    # ---------- Hafif kullanım senkronizasyonu ----------
    def collect_usage(self) -> dict:
        """
        Anlık CPU/RAM/disk kullanım oranları — TEK API çağrısı (cluster/resources).

        Tam senkronizasyondan bağımsız, çok daha sık (örn. 3 dk'da bir) çalışır.
        Config/agent sorgusu yapılmadığı için 500+ VM'de bile saniyeler sürer
        ve canlı ortama ölçülebilir yük bindirmez.
        """
        vms, hosts = [], []
        for res in self.api.cluster.resources.get():
            if res.get("type") in ("qemu", "lxc") and not res.get("template"):
                disk_used = res.get("disk") or 0   # agent yoksa 0 döner
                vms.append({
                    # VM'ler node/vmid ile kayıtlı (collect_vms ile aynı anahtar)
                    "external_id": f"{res.get('node', '')}/{res.get('vmid', '')}",
                    "cpu_pct": round((res.get("cpu") or 0) * 100, 1),
                    "ram_used_mb": int((res.get("mem") or 0) / (1024 * 1024)),
                    "disk_used_gb": round(disk_used / (1024 ** 3), 1) if disk_used else None,
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
