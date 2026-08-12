"""
Physical inventory: manually-entered devices that are NOT auto-discovered
(bare-metal servers, storage arrays, SAN switches, backup appliances).

Single table with type-aware fields: CPU/RAM/OS only apply to servers; storage
and switches leave them blank. A lightweight history table records who
created / edited / deleted each device (this data has no sync source).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from ..database import Base

# Device types (value stored in DB -> UI renders the label via i18n)
DEVICE_TYPES = ("server", "storage", "san_switch", "backup")
# Fields shown ONLY for physical servers (hidden for storage/switch/backup)
SERVER_ONLY_FIELDS = ("cpu", "ram_gb", "os")


class PhysicalDevice(Base):
    __tablename__ = "physical_devices"

    id = Column(Integer, primary_key=True)
    device_type = Column(String(24), nullable=False, index=True)  # DEVICE_TYPES
    name = Column(String(128), nullable=False, index=True)        # label / hostname
    location = Column(String(128))                                # site / rack
    status = Column(String(24), default="active")                 # active|passive|faulty|retired|spare
    mgmt_ip = Column(String(64))                                  # management IP
    ilo_ip = Column(String(64))                                   # iLO / iDRAC / BMC IP
    brand = Column(String(64))                                    # Dell / HPE / NetApp ...
    model = Column(String(128))                                   # PowerEdge R750 ...
    serial_no = Column(String(128))                               # service tag / serial
    # Server-only (blank for storage / san_switch / backup)
    cpu = Column(String(128))                                     # e.g. "2x Xeon Gold 6338 (64c)"
    ram_gb = Column(Integer)                                      # total RAM in GB
    os = Column(String(128))                                      # ESXi 8.0 / PVE 8.2 ...
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PhysicalDeviceHistory(Base):
    """Who created / edited / deleted a physical device, and what changed."""
    __tablename__ = "physical_device_history"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, index=True)          # not a FK: survives device deletion
    device_name = Column(String(128), index=True)
    device_type = Column(String(24))
    action = Column(String(16))                      # created | updated | deleted
    actor = Column(String(128))                      # app username who did it
    changes = Column(Text)                           # JSON: {field: [old, new], ...}
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)
