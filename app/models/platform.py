"""
Platform connections: vCenter servers and Proxmox clusters.
Credentials are stored Fernet-encrypted.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base


class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)            # Display name, e.g. "Ankara vCenter"
    type = Column(String(16), nullable=False)             # vcenter | proxmox
    host = Column(String(255), nullable=False)            # API adresi (FQDN veya IP)
    port = Column(Integer, default=443)
    verify_ssl = Column(Boolean, default=True)            # Toggle SSL certificate verification
    auth_method = Column(String(16), default="password")  # password | token (Proxmox)
    username = Column(String(128))
    password_encrypted = Column(Text)                     # Fernet-encrypted password
    token_name = Column(String(128))                      # Proxmox API token name (user@realm!tokenid)
    token_value_encrypted = Column(Text)                  # Fernet-encrypted token value
    location = Column(String(128))                        # Location label (for grouping)
    environment = Column(String(32), default="production")# production | test | development
    enabled = Column(Boolean, default=True)
    last_sync = Column(DateTime)                          # Last successful sync
    last_usage_sync = Column(DateTime)                    # Last usage-data refresh
    last_sync_status = Column(String(16))                 # success | error | running
    last_sync_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    hosts = relationship("Host", back_populates="platform", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="platform", cascade="all, delete-orphan")


class SyncLog(Base):
    """Sync and API error logs."""
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    status = Column(String(16))         # success | error
    hosts_found = Column(Integer, default=0)
    vms_found = Column(Integer, default=0)
    message = Column(Text)              # Error message or summary

    platform = relationship("Platform", back_populates="sync_logs")
