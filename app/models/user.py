"""User model - role-based authorization (admin / operator / viewer)."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
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
