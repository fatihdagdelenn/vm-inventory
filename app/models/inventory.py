"""
Envanter modelleri: Host, Sanal Makine, Ağ, Datastore, Etiket ve Değişiklik Geçmişi.

Performans notu: Tüm veriler arka planda zamanlanmış görevlerle toplanır ve bu
tablolarda saklanır. Kullanıcı aramaları SADECE bu lokal tablolara gider;
hiçbir kullanıcı isteği canlı vCenter/Proxmox API çağrısı tetiklemez.
500+ VM için kritik alanlar indekslidir.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Text,
                        Float, BigInteger, ForeignKey, Table, Index)
from sqlalchemy.orm import relationship
from ..database import Base

# VM <-> Etiket çoktan-çoğa ilişki tablosu (manuel gruplama için)
vm_tags = Table(
    "vm_tags", Base.metadata,
    Column("vm_id", Integer, ForeignKey("virtual_machines.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Host(Base):
    """Fiziksel host (ESXi veya Proxmox node) bilgileri."""
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    external_id = Column(String(128), index=True)   # Platform tarafındaki benzersiz kimlik
    name = Column(String(255), index=True)          # Host adı
    mgmt_ip = Column(String(64), index=True)        # Yönetim IP adresi
    os_version = Column(String(255))                # İşletim sistemi / hypervisor sürümü
    cpu_model = Column(String(255))                 # CPU modeli
    cpu_cores = Column(Integer)                     # Çekirdek sayısı
    ram_total_mb = Column(BigInteger)               # Toplam RAM (MB)
    ram_used_mb = Column(BigInteger)                # Kullanılan RAM (MB)
    cpu_usage_pct = Column(Float)                   # CPU kullanım yüzdesi
    disk_total_gb = Column(Float)                   # Toplam disk kapasitesi (GB)
    disk_used_gb = Column(Float)                    # Kullanılan disk (GB)
    cluster = Column(String(128), index=True)       # Cluster adı
    status = Column(String(16), index=True)         # online | offline | maintenance
    last_boot = Column(DateTime)                     # Son açılış zamanı (uptime hesabı için)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = relationship("Platform", back_populates="hosts")
    vms = relationship("VirtualMachine", back_populates="host_ref")


class VirtualMachine(Base):
    """Sanal makine envanter kaydı."""
    __tablename__ = "virtual_machines"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    host_id = Column(Integer, ForeignKey("hosts.id"), index=True)
    external_id = Column(String(128), index=True)   # vCenter MoRef veya Proxmox VMID
    vmid = Column(String(64), index=True)           # Görünen VM ID
    name = Column(String(255), index=True)
    ip_addresses = Column(Text)                     # Virgülle ayrılmış IP listesi
    mac_addresses = Column(Text)                    # Virgülle ayrılmış MAC listesi
    guest_os = Column(String(255), index=True)      # İşletim sistemi
    kernel = Column(String(128))                     # Çekirdek sürümü (Proxmox agent / —)
    arch = Column(String(32))                        # Mimari: x86_64 / aarch64 …
    cpu_count = Column(Integer)
    ram_mb = Column(BigInteger)
    disk_total_gb = Column(Float)
    disks_json = Column(Text)                       # Disk detayları (JSON)
    power_state = Column(String(16), index=True)    # running | stopped | suspended
    cluster = Column(String(128), index=True)
    datastore = Column(String(255), index=True)     # Virgülle ayrılmış datastore listesi
    vlans = Column(String(255), index=True)         # Virgülle ayrılmış VLAN listesi
    networks = Column(Text)                         # Bağlı ağ/portgroup adları
    created_date = Column(DateTime)                 # VM oluşturulma tarihi
    last_boot = Column(DateTime)                    # Son açılış zamanı
    tools_status = Column(String(64))               # VMware Tools / QEMU Agent durumu
    owner = Column(String(128))                     # Manuel: VM sahibi
    notes = Column(Text)                            # Manuel: notlar
    guest_notes = Column(Text)                      # Platformdan: vCenter annotation / Proxmox description
    platform_tags = Column(Text)                    # Platform etiketleri (vCenter tag / Proxmox tags), virgülle
    pool = Column(String(255), index=True)          # Resource pool (vCenter) / pool (Proxmox)
    folder = Column(String(512))                    # VM klasörü (vCenter); Proxmox'ta yok
    environment = Column(String(32), index=True)    # production | test | development
    is_template = Column(Boolean, default=False)
    cpu_usage_pct = Column(Float)                   # Anlık CPU kullanımı (%) — hafif senkr. günceller
    ram_usage_mb = Column(BigInteger)               # Anlık RAM kullanımı (MB) — hafif senkr. günceller
    disk_used_gb = Column(Float)                    # Gerçek disk kullanımı (GB) — vCenter committed / PX agent
    first_seen = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    host_ref = relationship("Host", back_populates="vms")
    platform = relationship("Platform")
    tags = relationship("Tag", secondary=vm_tags, back_populates="vms")

    # Sık kullanılan birleşik aramalar için kompozit indeks
    __table_args__ = (
        Index("ix_vm_power_cluster", "power_state", "cluster"),
        Index("ix_vm_platform_name", "platform_id", "name"),
    )


class Network(Base):
    """Ağ envanteri: VLAN, vSwitch/Bridge, Port Group bilgileri."""
    __tablename__ = "networks"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    name = Column(String(255), index=True)          # Network / Port Group adı
    vlan = Column(String(32), index=True)           # VLAN ID
    vswitch = Column(String(128))                   # vSwitch veya Linux Bridge adı
    portgroup = Column(String(128))                 # Port Group (vCenter)
    subnet = Column(String(64))                     # IP Subnet (CIDR) - manuel/öğrenilmiş
    host_name = Column(String(255))                 # Hangi host üzerinde tanımlı
    kind = Column(String(16), index=True)           # portgroup | bridge | vnet | pnic
    mac = Column(String(64))                         # Fiziksel kart (pnic) MAC adresi
    link_speed = Column(String(32))                  # Fiziksel kart bağlantı hızı
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Datastore(Base):
    """Depolama alanları (Datastore / Proxmox Storage)."""
    __tablename__ = "datastores"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    name = Column(String(255), index=True)
    type = Column(String(64))                       # VMFS, NFS, ZFS, LVM, Ceph...
    node = Column(String(128))                      # Proxmox yerel depo için node; paylaşımlı/vCenter'da boş
    shared = Column(Boolean, default=False)         # birden çok host/node tarafından paylaşılıyor mu
    capacity_gb = Column(Float)
    used_gb = Column(Float)
    free_gb = Column(Float)
    host_count = Column(Integer, default=0)         # bağlı host/node sayısı
    vm_count = Column(Integer, default=0)           # bu depoyu kullanan VM sayısı
    status = Column(String(32))                     # active | inactive | maintenance
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = relationship("Platform")

    @property
    def usage_pct(self) -> int:
        return round(100 * (self.used_gb or 0) / self.capacity_gb) if self.capacity_gb else 0

    @property
    def platform_name(self) -> str:
        return self.platform.name if self.platform else ""


class Snapshot(Base):
    """VM anlık görüntüleri (vCenter snapshot ağacı / Proxmox qemu+lxc snapshot)."""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id"), index=True)
    vm_external_id = Column(String(128), index=True)  # eşleştirme için
    vm_name = Column(String(255), index=True)
    name = Column(String(255))
    description = Column(Text)
    created_at = Column(DateTime, index=True)         # snapshot oluşturulma zamanı (UTC)
    is_current = Column(Boolean, default=False)       # aktif/çalışılan snapshot mı
    parent = Column(String(255))                      # üst snapshot adı (zincir)
    size_gb = Column(Float)                           # API çoğunlukla vermez → None ("—")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = relationship("Platform")
    vm = relationship("VirtualMachine")

    @property
    def platform_name(self) -> str:
        return self.platform.name if self.platform else ""

    @property
    def age_days(self):
        if not self.created_at:
            return None
        return (datetime.utcnow() - self.created_at).days


class Backup(Base):
    """Proxmox yedekleri (vzdump dosyaları + PBS anlık görüntüleri).

    Yalnızca Proxmox: vCenter'ın yedek API'si yoktur. Depo içeriğinden
    (content=backup) toplanır; PBS bağlı depolar da yedek içeriği döndürür.
    """
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id"), index=True)
    vmid = Column(String(32), index=True)        # Proxmox sayısal VM id
    vm_name = Column(String(255), index=True)
    storage = Column(String(128), index=True)
    volid = Column(String(512))                  # depo:backup/vzdump-...
    fmt = Column(String(48))                     # vma.zst, tar.zst, pbs...
    created_at = Column(DateTime, index=True)
    size_gb = Column(Float)
    protected = Column(Boolean, default=False)   # silinmeye karşı korumalı
    notes = Column(String(512))
    source = Column(String(32))                  # vzdump | pbs
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = relationship("Platform")
    vm = relationship("VirtualMachine")

    @property
    def platform_name(self) -> str:
        return self.platform.name if self.platform else ""

    @property
    def age_days(self):
        if not self.created_at:
            return None
        return (datetime.utcnow() - self.created_at).days


class Tag(Base):
    """Manuel etiketler (gruplama için)."""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    color = Column(String(16), default="#6c757d")

    vms = relationship("VirtualMachine", secondary=vm_tags, back_populates="tags")


class ChangeHistory(Base):
    """
    Envanter değişiklik geçmişi.
    Her senkronizasyonda eski ve yeni değerler karşılaştırılır,
    farklılıklar bu tabloya yazılır (örn: RAM artırıldı, IP değişti, VM silindi).
    """
    __tablename__ = "change_history"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(16), index=True)    # vm | host
    entity_name = Column(String(255), index=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"))
    change_type = Column(String(16))                # created | updated | deleted
    field = Column(String(64))                      # Değişen alan adı
    old_value = Column(Text)
    new_value = Column(Text)
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)


class ClusterSetting(Base):
    """
    Cluster görünürlük ayarı.

    Cluster'lar envanterden türetilir (VM/Host üzerindeki string alan);
    bu tablo yalnızca GİZLENEN cluster'ları ve tercihlerini tutar.
    Gizli cluster'lar dashboard sayılarına/grafiklerine girmez ve VM
    listesinde varsayılan olarak görünmez (istenirse dahil edilebilir).
    """
    __tablename__ = "cluster_settings"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    visible = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSetting(Base):
    """Genel anahtar-değer uygulama ayarları (senkronizasyon aralıkları vb.).

    Çalışma zamanında arayüzden değiştirilebilen, .env varsayılanlarını
    geçersiz kılan ayarlar burada tutulur.
    """
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(512))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledReport(Base):
    """
    Zamanlanmış rapor tanımı (KALICI).

    Eskiden zamanlanmış raporlar yalnızca APScheduler'ın bellek-içi
    jobstore'unda tutuluyordu; uygulama yeniden başlayınca tümü kayboluyordu
    ("oluşturdum ama yerinde yok"). Artık tanım bu tabloda saklanır ve her
    açılışta scheduler'a yeniden kaydedilir. Cron saati uygulama zaman
    dilimine (APP_TIMEZONE) göre yorumlanır.
    """
    __tablename__ = "scheduled_reports"

    id = Column(Integer, primary_key=True)
    name = Column(String(128))                       # Görünen ad (opsiyonel)
    target = Column(String(16), default="vms")       # vms | hosts
    fmt = Column(String(8), default="xlsx")          # xlsx | csv | pdf
    query = Column(Text, default="")                 # Arama filtresi (q)
    hour = Column(Integer, default=7)                # Çalışma saati (yerel TZ)
    minute = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    created_by = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run = Column(DateTime)                      # Son çalışma (UTC)
    last_status = Column(String(16))                 # success | error
    last_path = Column(String(512))                  # Son üretilen dosya yolu
    last_error = Column(Text)

    @property
    def job_id(self) -> str:
        return f"report_{self.id}"
