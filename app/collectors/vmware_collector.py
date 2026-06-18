"""
VMware vCenter veri toplayıcısı (pyVmomi - resmi vSphere SDK, SSH KULLANILMAZ).

Toplananlar:
- Host: ad, yönetim IP, ESXi sürümü, CPU modeli/çekirdek, RAM, cluster, durum
- VM: ad, MoRef ID, IP/MAC, OS, CPU/RAM/disk, güç durumu, datastore, VLAN,
  oluşturulma tarihi, son açılış, VMware Tools durumu
- Network: Port Group, vSwitch, VLAN
- Datastore: kapasite/kullanım

Performans: PropertyCollector tabanlı toplu görünüm (ContainerView) kullanılır;
500+ VM ortamında nesne nesne sorgu yerine tek geçişte veri çekilir.
"""
import ssl
import json
import re
import logging
from datetime import datetime

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

logger = logging.getLogger("collector.vmware")

# guestInfo.detailed.data biçimi: anahtar='değer' çiftleri, boşlukla ayrık
_DETAILED_RE = re.compile(r"(\w+)='([^']*)'")


def _parse_detailed(raw: str) -> str:
    """
    vSphere 8.0 U2+ ayrıntılı guest verisini ('guestInfo.detailed.data' veya
    guest.guestDetailedData) çözüp en iyi tam adı döndürür.
    Örn: prettyName='Ubuntu 24.04.1 LTS'  ->  "Ubuntu 24.04.1 LTS".
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
    En ayrıntılı işletim sistemi adını katmanlı olarak bul:
      1) guest.guestDetailedData              (VM açık, Tools 11.2+ — tam sürüm)
      2) config.extraConfig['guestInfo.detailed.data']  (kalıcı; VM kapalı olsa da)
      3) config.guestFullName                 (VM ayarındaki katalog adı)
      4) guest.guestFullName                  (Tools'un bildirdiği çalışan OS)
    Sürüm gereksinimi: vSphere 8.0 U2+ ve VMware Tools 11.2+ (1-2. adımlar için).
    NOT: 3-4 sırası bilinçli — katalog adı (örn. "VMware Photon OS") çoğu zaman
    Tools'un çalışma anında bildirdiği jenerik addan ("Other 3.x Linux") daha
    belirgindir; bu yüzden ayrıntılı veri yoksa önce katalog adı kullanılır.
    """
    # 1) Canlı ayrıntılı veri (tam sürüm)
    detailed = _parse_detailed(getattr(guest, "guestDetailedData", None) or "")
    if detailed:
        return detailed
    # 2) Kalıcı ayrıntılı veri (extraConfig) — VM kapalıyken bile
    #    Anahtar adı kaynaklarda guestinfo/guestInfo olarak geçebiliyor → harf duyarsız
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
    # 3) Katalog adı (config)  4) Tools'un bildirdiği OS  — eski (gerilemeyen) sıra
    return (summary_config.guestFullName if summary_config else "") or \
           (getattr(guest, "guestFullName", "") if guest else "") or ""


def _fetch_vcenter_tags(host, port, username, password, verify_ssl) -> dict:
    """
    vCenter REST (vAPI) tagging servisinden  MoRef -> "etiket1,etiket2"  eşlemesi.
    pyVmomi/SOAP etiketleri vermediği için ayrı bir REST oturumu açılır.
    Tamamen defensive: herhangi bir hata olursa boş sözlük döner, sync'in
    geri kalanını etkilemez. (Endpoint sürümü: legacy /rest, 8.0'da da çalışır.)
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
        logger.warning("vCenter etiketleri (REST) alınamadı: %s", exc)
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

    # ---------- Bağlantı ----------
    def connect(self):
        """vCenter'a bağlan. verify_ssl=False ise sertifika doğrulaması atlanır."""
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
        """Bağlantı testi ekranı için: sürüm bilgisiyle birlikte sonuç döner."""
        try:
            self.connect()
            about = self.si.content.about
            info = {"success": True,
                    "message": f"Bağlantı başarılı: {about.fullName}",
                    "version": about.version}
            self.disconnect()
            return info
        except Exception as exc:
            return {"success": False, "message": f"Bağlantı hatası: {exc}"}

    # ---------- Yardımcılar ----------
    def _get_objects(self, vimtype):
        """ContainerView ile belirtilen tipteki tüm nesneleri getir."""
        content = self.si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
        objs = list(view.view)
        view.Destroy()
        return objs

    # ---------- Cluster eşlemesi ----------
    def _cluster_map(self) -> dict:
        """
        host MoRef ID -> cluster adı eşlemesi.

        Cluster adları doğrudan ClusterComputeResource nesnelerinden okunur;
        bu, her host/VM için parent zincirini gezmekten hem daha hızlıdır
        (uzak/yüksek gecikmeli vCenter'larda önemli) hem de daha güvenilirdir:
        tek bir host'un parent okuması hata verse bile cluster adı kaybolmaz.
        """
        mapping = {}
        try:
            for cl in self._get_objects([vim.ClusterComputeResource]):
                try:
                    cname = cl.name
                    for h in cl.host:
                        mapping[h._moId] = cname
                except Exception as exc:
                    logger.warning("Cluster okunamadı %s: %s",
                                   getattr(cl, "name", "?"), exc)
        except Exception as exc:
            logger.warning("Cluster eşlemesi kurulamadı: %s", exc)
        return mapping

    def _pool_map(self) -> dict:
        """VM MoRef -> resource pool adı (toplu; her VM için ayrı sorgu yok).
        Kök 'Resources' havuzu gürültü olduğu için boş bırakılır."""
        mapping = {}
        try:
            for rp in self._get_objects([vim.ResourcePool]):
                try:
                    name = rp.name
                    if name == "Resources":   # gizli kök havuz
                        continue
                    for vm in rp.vm:
                        mapping[vm._moId] = name
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("Pool eşlemesi kurulamadı: %s", exc)
        return mapping

    @staticmethod
    def _vm_folder(vm) -> str:
        """VM'in doğrudan içinde bulunduğu klasör adı (vm.parent).
        Kanonik yöntem: VM'in envanterdeki üst öğesi klasördür. Kök 'vm'
        klasörü gizli olduğundan boş döndürülür (VM doğrudan kökteyse)."""
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
                # Yönetim IP'si: vmk arayüzlerinden ilki
                # (bağlantısı kopuk host'larda config None olabilir)
                mgmt_ip = ""
                try:
                    if h.config and h.config.network and h.config.network.vnic:
                        mgmt_ip = h.config.network.vnic[0].spec.ip.ipAddress or ""
                except Exception:
                    pass
                cluster = cluster_map.get(h._moId, "")
                # Disk kapasitesi: bağlı datastore'ların toplamı.
                # Erişilemeyen datastore tüm host kaydını düşürmesin.
                disk_total = disk_free = 0
                try:
                    disk_total = sum((ds.summary.capacity or 0)
                                     for ds in h.datastore) / 1024**3
                    disk_free = sum((ds.summary.freeSpace or 0)
                                    for ds in h.datastore) / 1024**3
                except Exception:
                    pass
                hosts.append({
                    "external_id": h._moId,
                    "name": h.name,
                    "mgmt_ip": mgmt_ip,
                    "os_version": summary.config.product.fullName if summary.config.product else "",
                    "cpu_model": hw.cpuModel or "",
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
                })
            except Exception as exc:
                logger.warning("Host okunamadı %s: %s", getattr(h, "name", "?"), exc)
        return hosts

    # ---------- Sanal makineler ----------
    def collect_vms(self) -> list[dict]:
        vms = []
        cluster_map = self._cluster_map()   # host MoRef -> cluster adı
        pool_map = self._pool_map()         # VM MoRef -> resource pool
        tag_map = _fetch_vcenter_tags(      # VM MoRef -> "etiket1,etiket2" (REST)
            self.host, self.port, self.username, self.password, self.verify_ssl)
        for vm in self._get_objects([vim.VirtualMachine]):
            try:
                summary = vm.summary
                config = summary.config
                guest = vm.guest

                # IP ve MAC adresleri (VMware Tools üzerinden)
                ips, macs = [], []
                if guest and guest.net:
                    for nic in guest.net:
                        if nic.ipAddress:
                            ips.extend(ip for ip in nic.ipAddress if ":" not in ip)  # IPv4 öncelik
                        if nic.macAddress:
                            macs.append(nic.macAddress)
                if not ips and guest and guest.ipAddress:
                    ips.append(guest.ipAddress)

                # Disk detayları + ağ/VLAN bilgisi (donanım listesinden)
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

                # Port group adlarından VLAN çözümleme
                for net in vm.network:
                    if isinstance(net, vim.dvs.DistributedVirtualPortgroup):
                        vlan_cfg = net.config.defaultPortConfig.vlan
                        if hasattr(vlan_cfg, "vlanId") and isinstance(vlan_cfg.vlanId, int):
                            vlans.append(str(vlan_cfg.vlanId))
                        if net.name not in networks:
                            networks.append(net.name)

                host_name = summary.runtime.host.name if summary.runtime.host else ""
                # Cluster: önceden kurulan eşlemeden (her VM için parent
                # zincirini gezmek uzak vCenter'larda hem yavaş hem kırılgan)
                cluster = cluster_map.get(
                    summary.runtime.host._moId, "") if summary.runtime.host else ""

                power_map = {"poweredOn": "running", "poweredOff": "stopped",
                             "suspended": "suspended"}

                vms.append({
                    "external_id": vm._moId,
                    "vmid": vm._moId,
                    "name": config.name if config else vm.name,
                    "ip_addresses": ",".join(sorted(set(ips))),
                    "mac_addresses": ",".join(sorted(set(macs))),
                    "guest_os": _best_guest_os(vm, guest, config),
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
                logger.warning("VM okunamadı %s: %s", getattr(vm, "name", "?"), exc)
        return vms

    # ---------- Ağlar ----------
    def collect_networks(self) -> list[dict]:
        nets = []
        # Standart vSwitch port group'ları (host bazında)
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
                # Fiziksel ağ kartları (vmnicX) — host'un kendi uplink'leri
                for pnic in h.config.network.pnic or []:
                    speed = ""
                    ls = getattr(pnic, "linkSpeed", None)
                    if ls and getattr(ls, "speedMb", None):
                        speed = f"{ls.speedMb} Mb/s"
                    nets.append({"name": pnic.device, "host_name": h.name,
                                 "kind": "pnic", "mac": pnic.mac or "",
                                 "link_speed": speed})
            except Exception as exc:
                logger.warning("Host ağı okunamadı: %s", exc)
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
                logger.warning("DVS portgroup okunamadı: %s", exc)
        return nets

    # ---------- Datastore'lar ----------
    def collect_datastores(self) -> list[dict]:
        result = []
        for ds in self._get_objects([vim.Datastore]):
            try:
                s = ds.summary
                cap = (s.capacity or 0) / 1024**3
                free = (s.freeSpace or 0) / 1024**3
                result.append({"name": s.name, "type": s.type,
                               "capacity_gb": round(cap, 1),
                               "used_gb": round(cap - free, 1),
                               "free_gb": round(free, 1)})
            except Exception as exc:
                logger.warning("Datastore okunamadı: %s", exc)
        return result

    # ---------- Hafif kullanım senkronizasyonu ----------
    def collect_usage(self) -> dict:
        """
        Anlık CPU/RAM kullanımı — quickStats üzerinden hafif okuma.

        quickStats, vCenter'ın zaten bellekte tuttuğu yaklaşık-anlık
        metriklerdir; performans grafiği API'sine göre çok ucuzdur.
        Tam senkronizasyondan bağımsız, sık aralıkla çalıştırılır.
        """
        vms, hosts = [], []

        for vm in self._get_objects([vim.VirtualMachine]):
            try:
                qs = vm.summary.quickStats
                max_mhz = (vm.runtime.maxCpuUsage or 0) if vm.runtime else 0
                cpu_pct = round(100 * (qs.overallCpuUsage or 0) / max_mhz, 1) \
                    if max_mhz else None
                # Gerçek disk kullanımı: datastore'da fiilen yazılı alan
                # (thin-provisioned disklerde tahsisten çok daha anlamlı)
                committed = vm.summary.storage.committed if vm.summary.storage else 0
                vms.append({
                    "external_id": vm._moId,
                    "cpu_pct": cpu_pct,
                    "ram_used_mb": qs.guestMemoryUsage or 0,   # Tools yoksa 0 gelir
                    "disk_used_gb": round((committed or 0) / 1024**3, 1),
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
