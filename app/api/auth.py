"""Kimlik doğrulama: giriş / çıkış (lokal + opsiyonel LDAP)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, AuditLog
from ..config import get_settings
from ..core.security import (verify_password, create_session_token,
                             generate_csrf_token, hash_password,
                             set_session_cookie)
from ..services.ldap_service import ldap_authenticate

router = APIRouter(tags=["auth"])
settings = get_settings()


def _audit(db: Session, request: Request, username: str, action: str,
           detail: str = "", role: str = ""):
    db.add(AuditLog(username=username, role=role, action=action,
                    target=username, detail=detail,
                    ip_address=request.client.host if request.client else ""))
    db.commit()


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=username).first()
    authenticated = False

    # 1) Lokal kullanıcı + bcrypt doğrulaması
    if user and not user.is_ldap and user.password_hash and \
            verify_password(password, user.password_hash):
        authenticated = True
    # 2) LDAP/AD doğrulaması (etkinse)
    elif settings.ldap_enabled and ldap_authenticate(username, password):
        authenticated = True
        if not user:  # ilk girişte otomatik kullanıcı oluştur
            user = User(username=username, is_ldap=True,
                        role=settings.ldap_default_role)
            db.add(user)
            db.commit()

    if not authenticated or not user or not user.is_active:
        _audit(db, request, username, "login_failed")
        return RedirectResponse("/login?error=1", status_code=303)

    user.last_login = datetime.utcnow()
    db.commit()
    _audit(db, request, username, "login", role=user.role)

    response = RedirectResponse("/", status_code=303)
    # Oturum çerezi: HttpOnly + SameSite (XSS/CSRF'e karşı); kayan zaman aşımı
    set_session_cookie(response, create_session_token(user))
    # CSRF çerezi: JS tarafından okunup X-CSRF-Token header'ına konur
    response.set_cookie("csrf_token", generate_csrf_token(), samesite="lax")
    return response


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    response.delete_cookie("csrf_token")
    return response
