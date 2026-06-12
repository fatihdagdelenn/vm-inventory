"""
Platform yönetimi: vCenter / Proxmox bağlantıları (sadece admin).
- Kimlik bilgileri kaydedilirken Fernet ile şifrelenir, API yanıtlarında ASLA dönmez.
- Bağlantı testi endpoint'i kaydetmeden önce doğrulama yapar.
- Manuel senkronizasyon arka plan görevi olarak tetiklenir.
"""
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Platform, SyncLog, User, AuditLog
from ..core.security import (require_role, get_current_user, encrypt_secret,
                             decrypt_secret, validate_csrf)
from ..collectors.vmware_collector import VMwareCollector
from ..collectors.proxmox_collector import ProxmoxCollector
from ..services.sync_service import sync_platform, sync_all_platforms

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


def _platform_to_dict(p: Platform) -> dict:
    """Kimlik bilgileri HARİÇ platform bilgisi."""
    return {"id": p.id, "name": p.name, "type": p.type, "host": p.host,
            "port": p.port, "verify_ssl": p.verify_ssl, "auth_method": p.auth_method,
            "username": p.username, "token_name": p.token_name,
            "location": p.location, "environment": p.environment,
            "enabled": p.enabled,
            "last_sync": p.last_sync.isoformat() if p.last_sync else None,
            "last_sync_status": p.last_sync_status,
            "last_sync_error": p.last_sync_error}


@router.get("")
def list_platforms(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """API bağlantı durum ekranı için platform listesi (tüm roller görebilir)."""
    return {"items": [_platform_to_dict(p) for p in db.query(Platform).all()]}


@router.post("")
def create_platform(request: Request, payload: dict = Body(...),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    if payload.get("type") not in ("vcenter", "proxmox"):
        raise HTTPException(400, "type 'vcenter' veya 'proxmox' olmalı")

    p = Platform(
        name=payload["name"], type=payload["type"], host=payload["host"],
        port=int(payload.get("port") or (443 if payload["type"] == "vcenter" else 8006)),
        verify_ssl=bool(payload.get("verify_ssl", True)),
        auth_method=payload.get("auth_method", "password"),
        username=payload.get("username"),
        password_encrypted=encrypt_secret(payload.get("password", "")),
        token_name=payload.get("token_name"),
        token_value_encrypted=encrypt_secret(payload.get("token_value", "")),
        location=payload.get("location", ""),
        environment=payload.get("environment", "production"),
    )
    db.add(p)
    db.add(AuditLog(username=user.username, action="create_platform",
                    detail=f"{p.type}:{p.name}"))
    db.commit()
    return _platform_to_dict(p)


@router.put("/{platform_id}")
def update_platform(platform_id: int, request: Request, payload: dict = Body(...),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    p = db.get(Platform, platform_id)
    if not p:
        raise HTTPException(404, "Platform bulunamadı")
    for field in ("name", "host", "username", "token_name", "location",
                  "environment", "auth_method"):
        if field in payload:
            setattr(p, field, payload[field])
    if "port" in payload:
        p.port = int(payload["port"])
    if "verify_ssl" in payload:
        p.verify_ssl = bool(payload["verify_ssl"])
    if "enabled" in payload:
        p.enabled = bool(payload["enabled"])
    if payload.get("password"):  # boşsa eski parola korunur
        p.password_encrypted = encrypt_secret(payload["password"])
    if payload.get("token_value"):
        p.token_value_encrypted = encrypt_secret(payload["token_value"])
    db.add(AuditLog(username=user.username, action="update_platform", detail=p.name))
    db.commit()
    return _platform_to_dict(p)


@router.delete("/{platform_id}")
def delete_platform(platform_id: int, request: Request,
                    db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    validate_csrf(request, None)
    p = db.get(Platform, platform_id)
    if not p:
        raise HTTPException(404, "Platform bulunamadı")
    # İlişkili tüm kayıtları sırayla temizle.
    # NOT: ChangeHistory'nin platform_id FK'sı temizlenmezse PostgreSQL'de
    # foreign key ihlali oluşur ve silme 500 ile başarısız olur.
    from ..models import VirtualMachine, Network, Datastore, ChangeHistory
    from ..models.inventory import vm_tags
    vm_ids = [r[0] for r in db.query(VirtualMachine.id)
                             .filter_by(platform_id=p.id).all()]
    if vm_ids:  # etiket ilişkilerini elle sil (bulk delete ORM cascade'i atlar)
        db.execute(vm_tags.delete().where(vm_tags.c.vm_id.in_(vm_ids)))
    db.query(ChangeHistory).filter_by(platform_id=p.id).delete()
    db.query(VirtualMachine).filter_by(platform_id=p.id).delete()
    db.query(Network).filter_by(platform_id=p.id).delete()
    db.query(Datastore).filter_by(platform_id=p.id).delete()
    db.add(AuditLog(username=user.username, action="delete_platform", detail=p.name))
    db.delete(p)   # host'lar ve sync log'ları ORM cascade ile silinir
    db.commit()
    return {"ok": True}


@router.post("/test")
def test_connection(request: Request, payload: dict = Body(...),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    """
    Bağlantı testi ekranı: kaydetmeden önce verilen bilgilerle bağlantıyı dener.
    Mevcut platform için id verilirse kayıtlı (şifreli) bilgiler kullanılır.
    """
    validate_csrf(request, payload.pop("csrf_token", None))
    pid = payload.get("id")
    if pid:
        p = db.get(Platform, pid)
        if not p:
            raise HTTPException(404, "Platform bulunamadı")
        payload = {"type": p.type, "host": p.host, "port": p.port,
                   "verify_ssl": p.verify_ssl, "username": p.username,
                   "password": decrypt_secret(p.password_encrypted),
                   "token_name": p.token_name,
                   "token_value": decrypt_secret(p.token_value_encrypted)}

    if payload.get("type") == "vcenter":
        collector = VMwareCollector(host=payload["host"],
                                    port=int(payload.get("port") or 443),
                                    verify_ssl=bool(payload.get("verify_ssl", True)),
                                    username=payload.get("username"),
                                    password=payload.get("password"))
    else:
        collector = ProxmoxCollector(host=payload["host"],
                                     port=int(payload.get("port") or 8006),
                                     verify_ssl=bool(payload.get("verify_ssl", True)),
                                     username=payload.get("username"),
                                     password=payload.get("password"),
                                     token_name=payload.get("token_name"),
                                     token_value=payload.get("token_value"))
    return collector.test_connection()


@router.post("/{platform_id}/sync")
def trigger_sync(platform_id: int, request: Request, background: BackgroundTasks,
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role("operator"))):
    """Tek platform için manuel senkronizasyon (arka planda çalışır)."""
    validate_csrf(request, None)
    if not db.get(Platform, platform_id):
        raise HTTPException(404, "Platform bulunamadı")
    background.add_task(sync_platform, platform_id)
    db.add(AuditLog(username=user.username, action="manual_sync",
                    detail=f"platform_id={platform_id}"))
    db.commit()
    return {"ok": True, "message": "Senkronizasyon arka planda başlatıldı"}


@router.post("/sync-all")
def trigger_sync_all(request: Request, background: BackgroundTasks,
                     db: Session = Depends(get_db),
                     user: User = Depends(require_role("operator"))):
    """Toplu veri yenileme: tüm platformları arka planda senkronize et."""
    validate_csrf(request, None)
    background.add_task(sync_all_platforms)
    db.add(AuditLog(username=user.username, action="manual_sync_all"))
    db.commit()
    return {"ok": True, "message": "Tüm platformlar için senkronizasyon başlatıldı"}


@router.get("/{platform_id}/logs")
def sync_logs(platform_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """API hata/senkronizasyon logları."""
    logs = db.query(SyncLog).filter_by(platform_id=platform_id)\
             .order_by(SyncLog.started_at.desc()).limit(50).all()
    return {"items": [{"started_at": l.started_at.isoformat() if l.started_at else None,
                       "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                       "status": l.status, "hosts_found": l.hosts_found,
                       "vms_found": l.vms_found, "message": l.message} for l in logs]}
