"""OS lifecycle (end-of-life) data and operator exceptions.

OsLifecycle mirrors endoflife.date release cycles for the products in
services/lifecycle_service.PRODUCTS. Data comes from the bundled seed file,
the weekly endoflife.date sync (only where the server has internet) or a JSON
file uploaded in Administration; for each (distro, version) the NEWEST data
wins, whatever its source (updated_at = the date of the data, not of the write).

LifecycleOverride records "this VM / these VMs have a paid extended-support
subscription" (Ubuntu Pro / ESM, RHEL ELS, Windows ESU, Debian ELTS ...).
Scope: all VMs (optionally only one product), every VM with a tag, or one VM.
The most specific match wins (vm > tag > all), so a VM rule can also switch
extended support OFF for a VM inside a tagged group.
"""
from datetime import datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text, UniqueConstraint
from ..database import Base

OVERRIDE_SCOPES = ("all", "tag", "vm")


class OsLifecycle(Base):
    __tablename__ = "os_lifecycle"
    __table_args__ = (UniqueConstraint("distro", "version", name="uq_os_lifecycle_cycle"),)

    id = Column(Integer, primary_key=True)
    distro = Column(String(48), index=True, nullable=False)   # endoflife.date product id
    version = Column(String(48), nullable=False)              # release-cycle id
    release_date = Column(Date)
    eol_standard = Column(Date)      # end of free security support (endoflife.date 'eol')
    eol_extended = Column(Date)      # end of paid extended support ('eoes'): ESM / ELS / ESU
    eol_reached = Column(Boolean, default=False)  # EOL announced without a date
    source = Column(String(24))      # seed | endoflife.date | manual
    updated_at = Column(DateTime)    # date of the DATA (newest wins)


class LifecycleOverride(Base):
    __tablename__ = "lifecycle_overrides"

    id = Column(Integer, primary_key=True)
    scope = Column(String(8), nullable=False)   # all | tag | vm
    target = Column(String(255))                # tag name | "<platform_id>:<vmid>" | None
    target_label = Column(String(255))          # VM name at creation time (display only)
    distro = Column(String(48))                 # optional: only this product
    extended = Column(Boolean, default=True)    # paid extended support in place?
    note = Column(Text)
    created_by = Column(String(128))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
