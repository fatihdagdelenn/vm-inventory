"""
Güvenlik katmanı:
- Parola hashleme (bcrypt)
- Platform kimlik bilgilerinin şifrelenmesi (Fernet / AES-128)
- Oturum yönetimi (imzalı çerez + zaman aşımı)
- Rol bazlı yetkilendirme dependency'leri
- CSRF token üretimi/doğrulaması
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

# Rol hiyerarşisi: admin her şeyi yapabilir, operator düzenleyebilir, viewer sadece görür
ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}


# ---------- Parola ----------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------- Kimlik bilgisi şifreleme ----------
def _get_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY tanımlı değil! .env dosyasına bir Fernet anahtarı ekleyin: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt_secret(plain: str) -> str:
    """Parola/token'ı veritabanında saklamadan önce şifrele."""
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Şifreli kimlik bilgisini API çağrısı için çöz (sadece bellek içinde)."""
    if not encrypted:
        return ""
    return _get_fernet().decrypt(encrypted.encode()).decode()


# ---------- Oturum ----------
def create_session_token(user: User) -> str:
    """İmzalı, zaman damgalı oturum token'ı üret."""
    return session_serializer.dumps({"uid": user.id, "role": user.role})


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Çerezdeki oturum token'ını doğrula.
    Zaman aşımı (SESSION_TIMEOUT_MINUTES) dolmuşsa 401 döner.
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
    return user


def require_role(min_role: str):
    """Belirli bir minimum rol gerektiren dependency üretir."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if ROLE_LEVELS.get(user.role, 0) < ROLE_LEVELS[min_role]:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
        return user
    return checker


# ---------- CSRF ----------
def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def validate_csrf(request: Request, token_from_form: Optional[str]):
    """Çerezdeki CSRF token'ı ile formdan/headerdan gelen token'ı karşılaştır."""
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("X-CSRF-Token") or token_from_form
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF doğrulaması başarısız")
