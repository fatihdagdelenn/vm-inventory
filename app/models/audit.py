"""Audit logs - who did what, when."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from ..database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), index=True)
    role = Column(String(32))                  # the user's role at the time of the action
    action = Column(String(64), index=True)    # login, logout, create_platform, export, ...
    target = Column(String(255), index=True)   # target of the action (VM/user/platform name...)
    detail = Column(Text)
    old_value = Column(Text)                   # value before the change
    new_value = Column(Text)                   # value after the change
    ip_address = Column(String(64))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
