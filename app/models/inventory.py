"""
Inventory models: Host, Virtual Machine, Network, Datastore, Tag and
Change History.
Performance note: all data is collected by the background sync; user
searches only read these local tables.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Date, Text,
                        Float, BigInteger, ForeignKey, Table, Index, UniqueConstraint)
from sqlalchemy.orm import relationship
from ..database import Base

# VM <-> Tag many-to-many table (for manual grouping)
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
    external_id = Column(String(128), index=True)   # Unique id on the platform side
    name = Column(String(255), index=True)          # Host name
    mgmt_ip = Column(String(64), index=True)        # Management IP address
    os_version = Column(String(255))                # OS / hypervisor version
    cpu_model = Column(String(255))                 # CPU modeli
    cpu_cores = Column(Integer)                     # Core count
    ram_total_mb = Column(BigInteger)               # Toplam RAM (MB)
    ram_used_mb = Column(BigInteger)                # Used RAM (MB)
    cpu_usage_pct = Column(Float)                   # CPU usage percent
    disk_total_gb = Column(Float)                   # Toplam disk kapasitesi (GB)
    disk_used_gb = Column(Float)                    # Used disk (GB)
    cluster = Column(String(128), index=True)       # Cluster name
    status = Column(String(16), index=True)         # online | offline | maintenance
    last_boot = Column(DateTime)                     # Last boot time (for uptime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = relationship("Platform", back_populates="hosts")
    vms = relationship("VirtualMachine", back_populates="host_ref")


class VirtualMachine(Base):
    """Virtual machine inventory record."""
    __tablename__ = "virtual_machines"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    host_id = Column(Integer, ForeignKey("hosts.id"), index=True)
    external_id = Column(String(128), index=True)   # vCenter MoRef veya Proxmox VMID
    vmid = Column(String(64), index=True)           # Visible VM ID
    name = Column(String(255), index=True)
    ip_addresses = Column(Text)                     # Comma-separated IP list
    dns_servers = Column(Text)                      # Comma-separated DNS server list
    mac_addresses = Column(Text)                    # Comma-separated MAC list
    guest_os = Column(String(255), index=True)      # Operating system
    kernel = Column(String(128))                     # Kernel version (Proxmox agent / -)
    arch = Column(String(32))                        # Mimari: x86_64 / aarch64 …
    cpu_count = Column(Integer)
    ram_mb = Column(BigInteger)
    disk_total_gb = Column(Float)
    disks_json = Column(Text)                       # Disk details (JSON)
    power_state = Column(String(16), index=True)    # running | stopped | suspended
    cluster = Column(String(128), index=True)
    datastore = Column(String(255), index=True)     # Comma-separated datastore list
    vlans = Column(String(255), index=True)         # Comma-separated VLAN list
    networks = Column(Text)                         # Attached network/portgroup names
    created_date = Column(DateTime)                 # VM creation date
    last_boot = Column(DateTime)                    # Last boot time
    tools_status = Column(String(64))               # VMware Tools / QEMU Agent durumu
    owner = Column(String(128))                     # Manuel: VM sahibi
    notes = Column(Text)                            # Manuel: notlar
    guest_notes = Column(Text)                      # Platformdan: vCenter annotation / Proxmox description
    platform_tags = Column(Text)                    # Platform tags (vCenter tag / Proxmox tags), comma-separated
    pool = Column(String(255), index=True)          # Resource pool (vCenter) / pool (Proxmox)
    folder = Column(String(512))                    # VM folder (vCenter); absent on Proxmox
    environment = Column(String(32), index=True)    # production | test | development
    is_template = Column(Boolean, default=False)
    cpu_usage_pct = Column(Float)                   # Instant CPU usage (%) - updated by the light sync
    ram_usage_mb = Column(BigInteger)               # Instant RAM usage (MB) - updated by the light sync
    disk_used_gb = Column(Float)                    # Real disk usage (GB) - vCenter committed / PX agent
    net_kbps = Column(Float)                        # Instant network traffic (KB/s) - from the netin+netout delta
    diskio_kbps = Column(Float)                     # Instant disk I/O (KB/s) - from the diskread+diskwrite delta
    io_net_bytes = Column(BigInteger)               # Last cumulative netin+netout (for delta computation)
    io_disk_bytes = Column(BigInteger)              # Last cumulative diskread+diskwrite (for delta computation)
    io_ts = Column(DateTime)                        # Last IO sample time (rate = delta / dt)
    first_seen = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    host_ref = relationship("Host", back_populates="vms")
    platform = relationship("Platform")
    tags = relationship("Tag", secondary=vm_tags, back_populates="vms")

    # Composite index for frequent combined searches
    __table_args__ = (
        Index("ix_vm_power_cluster", "power_state", "cluster"),
        Index("ix_vm_platform_name", "platform_id", "name"),
    )


class Network(Base):
    """Network inventory: VLAN, vSwitch/Bridge, Port Group info."""
    __tablename__ = "networks"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    name = Column(String(255), index=True)          # Network / Port Group name
    vlan = Column(String(32), index=True)           # VLAN ID
    vswitch = Column(String(128))                   # vSwitch or Linux Bridge name
    portgroup = Column(String(128))                 # Port Group (vCenter)
    subnet = Column(String(64))                     # IP subnet (CIDR) - manual/learned
    host_name = Column(String(255))                 # The host it is defined on
    kind = Column(String(16), index=True)           # portgroup | bridge | vnet | pnic
    mac = Column(String(64))                         # Fiziksel kart (pnic) MAC adresi
    link_speed = Column(String(32))                  # Physical NIC link speed
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Datastore(Base):
    """Storage areas (Datastore / Proxmox Storage)."""
    __tablename__ = "datastores"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    name = Column(String(255), index=True)
    type = Column(String(64))                       # VMFS, NFS, ZFS, LVM, Ceph...
    node = Column(String(128))                      # Node for local Proxmox stores; blank for shared/vCenter
    shared = Column(Boolean, default=False)         # shared by multiple hosts/nodes?
    capacity_gb = Column(Float)
    used_gb = Column(Float)
    free_gb = Column(Float)
    host_count = Column(Integer, default=0)         # attached host/node count
    vm_count = Column(Integer, default=0)           # VM count using this store
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
    """VM snapshots (vCenter snapshot tree / Proxmox qemu+lxc snapshots)."""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id"), index=True)
    vm_external_id = Column(String(128), index=True)  # for matching
    vm_name = Column(String(255), index=True)
    name = Column(String(255))
    description = Column(Text)
    created_at = Column(DateTime, index=True)         # snapshot creation time (UTC)
    is_current = Column(Boolean, default=False)       # is it the active/current snapshot
    parent = Column(String(255))                      # parent snapshot name (chain)
    size_gb = Column(Float)                           # the API mostly omits it -> None ("-")
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
    """Proxmox backups (vzdump files + PBS snapshots).
        Proxmox only: vCenter has no backup API. Collected from storage content."""
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True, nullable=False)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id"), index=True)
    vmid = Column(String(32), index=True)        # Numeric Proxmox VM id
    vm_name = Column(String(255), index=True)
    storage = Column(String(128), index=True)
    volid = Column(String(512))                  # depo:backup/vzdump-...
    fmt = Column(String(48))                     # vma.zst, tar.zst, pbs...
    created_at = Column(DateTime, index=True)
    size_gb = Column(Float)
    protected = Column(Boolean, default=False)   # protected against deletion
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
    """Manual tags (for grouping)."""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    color = Column(String(16), default="#6c757d")

    vms = relationship("VirtualMachine", secondary=vm_tags, back_populates="tags")


class ChangeHistory(Base):
    """
        Inventory change history. Every sync compares old and new values and
        writes the differences here, enriched with category/actor/source info.
        """
    __tablename__ = "change_history"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(16), index=True)    # vm | host
    entity_name = Column(String(255), index=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"))
    change_type = Column(String(24))                # created|updated|deleted|migrated|access
    field = Column(String(64))                      # Name of the changed field
    old_value = Column(Text)
    new_value = Column(Text)
    actor = Column(String(128))                     # Platform user who performed the action (from the task/event log)
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)

    # --- phase35: enriched provenance / source / actor info ---
    # Bu kolonlar ensure_schema ile mevcut kurulumlara otomatik eklenir.
    category = Column(String(24), index=True)       # hardware|disk|network|power|migrate|lifecycle|console|os|other
    op_type = Column(String(64))                    # Raw type of the platform operation (qmconfig / VmReconfiguredEvent...)
    platform_type = Column(String(16), index=True)  # vcenter | proxmox
    cluster = Column(String(128))                   # Cluster the change happened in
    host = Column(String(255))                       # Host/node the VM lives on (for migrations: source->target)
    vm_external_id = Column(String(128), index=True)  # moId veya node/vmid
    actor_ip = Column(String(64))                    # Client IP of the actor (if any; most platforms omit it)
    actor_agent = Column(String(255))                # Client User-Agent of the actor (if any)


class ClusterSetting(Base):
    """
        Cluster visibility setting. Clusters are derived from the inventory
        (a string field on VM/Host); this table only stores the HIDDEN ones.
        """
    __tablename__ = "cluster_settings"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    visible = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSetting(Base):
    """General key-value app settings (sync intervals etc.).
        Runtime-changeable from the UI; .env provides the defaults."""
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(512))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledReport(Base):
    """
        Scheduled report definition (PERSISTENT). Reports used to live only in
        APScheduler's in-memory jobstore and were lost on restart; now they are
        stored here and re-registered on startup.
        """
    __tablename__ = "scheduled_reports"

    id = Column(Integer, primary_key=True)
    name = Column(String(128))                       # Display name (optional)
    target = Column(String(16), default="vms")       # vms | hosts
    fmt = Column(String(8), default="xlsx")          # xlsx | csv | pdf
    query = Column(Text, default="")                 # Arama filtresi (q)
    hour = Column(Integer, default=7)                # Run hour (local TZ)
    minute = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    created_by = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run = Column(DateTime)                      # Last run (UTC)
    last_status = Column(String(16))                 # success | error
    last_path = Column(String(512))                  # Path of the last generated file
    last_error = Column(Text)

    @property
    def job_id(self) -> str:
        return f"report_{self.id}"


class CapacitySnapshot(Base):
    """
        Daily capacity snapshot (for the capacity forecast).
        sync_usage_all upserts today's row on every run.
        """
    __tablename__ = "capacity_snapshots"

    id = Column(Integer, primary_key=True)
    snap_date = Column(Date, unique=True, index=True)   # one row per day
    alloc_disk_gb = Column(Float)        # tahsisli toplam (sum VM disk_total_gb)
    alloc_ram_mb = Column(BigInteger)    # tahsisli toplam (sum VM ram_mb)
    used_disk_gb = Column(Float)         # real usage (sum VM disk_used_gb)
    used_ram_mb = Column(BigInteger)     # real usage (sum VM ram_usage_mb)
    datastore_capacity_gb = Column(Float)  # physical disk ceiling
    datastore_used_gb = Column(Float)      # real datastore usage (fill)
    host_ram_mb = Column(BigInteger)       # physical RAM ceiling
    host_cpu_cores = Column(Integer)       # physical core ceiling
    alloc_vcpu = Column(Integer)           # allocated vCPU total
    used_cpu_pct = Column(Float)           # core-weighted avg host CPU %
    vm_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class VmUsageDaily(Base):
    """
        DAILY per-VM usage aggregation (for zombie/idle detection).
        sync_usage_all upserts today's row on every run (running averages).
        """
    __tablename__ = "vm_usage_daily"

    id = Column(Integer, primary_key=True)
    vm_id = Column(Integer, ForeignKey("virtual_machines.id", ondelete="CASCADE"), index=True)
    day = Column(Date, index=True)
    cpu_avg = Column(Float)              # intraday average CPU %
    cpu_max = Column(Float)              # intraday peak CPU %
    ram_avg_mb = Column(BigInteger)      # intraday average RAM usage (MB)
    ram_min_mb = Column(BigInteger)      # intraday minimum RAM (flat-line/variance detection)
    ram_max_mb = Column(BigInteger)      # intraday maximum RAM
    net_kbps = Column(Float)             # intraday average net traffic (KB/s)
    diskio_kbps = Column(Float)          # intraday average disk I/O (KB/s)
    samples = Column(Integer, default=0)

    __table_args__ = (UniqueConstraint("vm_id", "day", name="uq_vm_usage_day"),)
