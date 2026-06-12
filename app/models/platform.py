"""
Platform bağlantıları: vCenter sunucuları ve Proxmox cluster'ları.
Kimlik bilgileri Fernet ile şifrelenerek saklanır (düz metin ASLA tutulmaz).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base


class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)            # Görünen ad, örn: "Ankara vCenter"
    type = Column(String(16), nullable=False)             # vcenter | proxmox
    host = Column(String(255), nullable=False)            # API adresi (FQDN veya IP)
    port = Column(Integer, default=443)
    verify_ssl = Column(Boolean, default=True)            # SSL sertifika doğrulaması aç/kapat
    auth_method = Column(String(16), default="password")  # password | token (Proxmox)
    username = Column(String(128))
    password_encrypted = Column(Text)                     # Fernet ile şifreli parola
    token_name = Column(String(128))                      # Proxmox API token adı (user@realm!tokenid)
    token_value_encrypted = Column(Text)                  # Fernet ile şifreli token değeri
    location = Column(String(128))                        # Lokasyon etiketi (gruplama için)
    environment = Column(String(32), default="production")# production | test | development
    enabled = Column(Boolean, default=True)
    last_sync = Column(DateTime)                          # Son başarılı senkronizasyon
    last_usage_sync = Column(DateTime)                    # Son kullanım-verisi tazelemesi
    last_sync_status = Column(String(16))                 # success | error | running
    last_sync_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    hosts = relationship("Host", back_populates="platform", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="platform", cascade="all, delete-orphan")


class SyncLog(Base):
    """Senkronizasyon ve API hata logları."""
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    status = Column(String(16))         # success | error
    hosts_found = Column(Integer, default=0)
    vms_found = Column(Integer, default=0)
    message = Column(Text)              # Hata mesajı veya özet

    platform = relationship("Platform", back_populates="sync_logs")
