"""User model - role-based authorization (admin / operator / viewer)."""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Text,
                        ForeignKey, UniqueConstraint)
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    full_name = Column(String(128))
    email = Column(String(128))
    password_hash = Column(String(255))          # bcrypt hash; may be empty for LDAP users
    role = Column(String(16), default="viewer")  # admin | operator | viewer
    is_ldap = Column(Boolean, default=False)     # authenticated via LDAP/AD?
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)


class UserSetting(Base):
    """Per-user UI settings (dashboard layout, topology positions...).

    Stored server-side so a user's layout follows the ACCOUNT instead of the
    browser: it survives rebuilds, browser cleanups and device changes.
    Value is an opaque string (usually JSON) owned by the frontend."""
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     index=True, nullable=False)
    key = Column(String(64), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_setting"),)
