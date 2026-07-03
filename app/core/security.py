"""
Security layer:
- Password hashing (bcrypt)
- Platform credential encryption (Fernet / AES-128)
- Signed session tokens (itsdangerous) + sliding timeout
- CSRF double-submit verification
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
session_serializer = URLSafeTimedSerializer(settings.secret_key, salt="session")

# Role hierarchy: admin can do everything, operator can edit, viewer read-only
ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}


# ---------- Parola ----------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------- Credential encryption ----------
def _get_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set! Add a Fernet key to your .env: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt_secret(plain: str) -> str:
    """Encrypt a password/token before storing it in the database."""
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a stored credential for an API call (in memory only)."""
    if not encrypted:
        return ""
    return _get_fernet().decrypt(encrypted.encode()).decode()


# ---------- Oturum ----------
SESSION_COOKIE_NAME = "session"


def create_session_token(user: User) -> str:
    """Produce a signed, timestamped session token."""
    return session_serializer.dumps({"uid": user.id, "role": user.role})


def set_session_cookie(response, token: str) -> None:
    """
        Write the session cookie with standard attributes (login + sliding refresh
        in one place). HttpOnly + SameSite=Lax; max_age = idle timeout.
        """
    response.set_cookie(
        SESSION_COOKIE_NAME, token, httponly=True, samesite="lax",
        max_age=settings.session_timeout_minutes * 60)


def refresh_session_token(token: str) -> Optional[str]:
    """
        Re-sign a valid session token with a fresh timestamp.
        Used for sliding sessions: every active request pushes the expiry forward.
        """
    try:
        data = session_serializer.loads(
            token, max_age=settings.session_timeout_minutes * 60)
    except (BadSignature, SignatureExpired):
        return None
    return session_serializer.dumps(data)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
        Verify the session token in the cookie.
        Returns 401 when the timeout (SESSION_TIMEOUT_MINUTES) has passed.
        """
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum bulunamadı")
    try:
        data = session_serializer.loads(token, max_age=settings.session_timeout_minutes * 60)
    except SignatureExpired:
        raise HTTPException(status_code=401, detail="Oturum zaman aşımına uğradı")
    except BadSignature:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")

    user = db.get(User, data["uid"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı veya pasif")
    # Sliding session: verification OK -> middleware refreshes the cookie in the response.
    # (logout doesn't pass through get_current_user, so no flag - logout stays intact)
    request.state.session_refresh = True
    return user


def require_role(min_role: str):
    """Produce a dependency requiring a minimum role."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if ROLE_LEVELS.get(user.role, 0) < ROLE_LEVELS[min_role]:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
        return user
    return checker


# ---------- CSRF ----------
def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def validate_csrf(request: Request, token_from_form: Optional[str]):
    """Compare the CSRF cookie token with the form/header token."""
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("X-CSRF-Token") or token_from_form
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF doğrulaması başarısız")
