"""Denetim (audit) logları - kim, ne zaman, ne yaptı."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from ..database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), index=True)
    action = Column(String(64), index=True)   # login, logout, create_platform, export, ...
    detail = Column(Text)
    ip_address = Column(String(64))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
