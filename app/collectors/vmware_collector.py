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
import logging
from datetime import datetime

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

logger = logging.getLogger("collector.vmware")


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
                })
            except Exception as exc:
                logger.warning("Host okunamadı %s: %s", getattr(h, "name", "?"), exc)
        return hosts

    # ---------- Sanal makineler ----------
    def collect_vms(self) -> list[dict]:
        vms = []
        cluster_map = self._cluster_map()   # host MoRef -> cluster adı
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
                                          "capacity_gb": round(dev.capacityInKB / 1024**2, 1)})
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
                    "guest_os": (config.guestFullName if config else "") or
                                (guest.guestFullName if guest else "") or "",
                    "cpu_count": config.numCpu if config else 0,
                    "ram_mb": config.memorySizeMB if config else 0,
                    "disk_total_gb": round(sum(d["capacity_gb"] for d in disks), 1),
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
                                 "host_name": h.name})
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
                             "portgroup": dpg.name, "host_name": ""})
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
