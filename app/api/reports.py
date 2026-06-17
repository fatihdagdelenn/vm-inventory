"""
Raporlama API'si: Excel / CSV / PDF dışa aktarma + zamanlanmış raporlar.
Arama parametresi (q) aynen uygulanır -> filtrelenmiş sonuçlar dışa aktarılır.
"""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import VirtualMachine, Host, User, AuditLog, ScheduledReport
from ..core.security import get_current_user, require_role, validate_csrf
from ..core.search import apply_vm_search
from ..core.scheduler import scheduler
from ..services import report_service as rs
from ..core.timezone import to_iso, now_local
from ..config import get_settings

router = APIRouter(prefix="/api/reports", tags=["reports"])

MEDIA = {
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "csv": ("text/csv; charset=utf-8", "csv"),
    "pdf": ("application/pdf", "pdf"),
}


def _export(items, columns, fmt: str, title: str) -> Response:
    if fmt not in MEDIA:
        raise HTTPException(400, "Format xlsx, csv veya pdf olmalı")
    if fmt == "xlsx":
        content = rs.export_excel(items, columns, title)
    elif fmt == "csv":
        content = rs.export_csv(items, columns)
    else:
        content = rs.export_pdf(items, columns, title)
    media, ext = MEDIA[fmt]
    filename = f"{title.lower().replace(' ', '_')}_{now_local():%Y%m%d_%H%M}.{ext}"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/vms/export")
def export_vms(fmt: str = "xlsx", q: str = "", db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """VM raporu - q parametresiyle filtrelenmiş sonuçlar dışa aktarılır."""
    query = db.query(VirtualMachine).options(
        joinedload(VirtualMachine.host_ref)).filter_by(is_template=False)
    items = apply_vm_search(query, q).order_by(VirtualMachine.name).all()
    db.add(AuditLog(username=user.username, action="export",
                    detail=f"vms fmt={fmt} q='{q}' count={len(items)}"))
    db.commit()
    return _export(items, rs.VM_COLUMNS, fmt, "VM Envanteri")


@router.get("/hosts/export")
def export_hosts(fmt: str = "xlsx", db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    items = db.query(Host).order_by(Host.name).all()
    db.add(AuditLog(username=user.username, action="export",
                    detail=f"hosts fmt={fmt} count={len(items)}"))
    db.commit()
    return _export(items, rs.HOST_COLUMNS, fmt, "Host Envanteri")


# ---------- Zamanlanmış raporlar (KALICI) ----------
# Tanımlar DB'de (ScheduledReport) saklanır ve her açılışta scheduler'a
# yeniden kaydedilir; böylece uygulama yeniden başlasa da kaybolmazlar.
# Cron saati uygulama zaman dilimine (APP_TIMEZONE) göre yorumlanır.
import os


def _report_dir() -> str:
    """Raporların yazılacağı klasör (env REPORT_DIR > ayar > varsayılan)."""
    d = os.environ.get("REPORT_DIR") or get_settings().report_dir
    os.makedirs(d, exist_ok=True)
    return d


def _build_items(db: Session, target: str, q: str):
    """Hedefe göre rapor satırlarını ve kolon setini üret."""
    if target == "hosts":
        return db.query(Host).order_by(Host.name).all(), rs.HOST_COLUMNS, "Host"
    query = db.query(VirtualMachine).options(
        joinedload(VirtualMachine.host_ref)).filter_by(is_template=False)
    items = apply_vm_search(query, q).order_by(VirtualMachine.name).all()
    return items, rs.VM_COLUMNS, "VM"


def run_scheduled_report(report_id: int):
    """Zamanlayıcı veya 'şimdi çalıştır' tarafından çağrılır: raporu diske yazar."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        rep = db.get(ScheduledReport, report_id)
        if not rep or not rep.enabled:
            return
        try:
            items, columns, label = _build_items(db, rep.target, rep.query or "")
            title = f"Zamanlanmış {label} Raporu"
            content = (rs.export_excel(items, columns, title) if rep.fmt == "xlsx"
                       else rs.export_csv(items, columns) if rep.fmt == "csv"
                       else rs.export_pdf(items, columns, title))
            fname = f"{rep.target}_raporu_{now_local():%Y%m%d_%H%M}.{rep.fmt}"
            path = os.path.join(_report_dir(), fname)
            with open(path, "wb") as f:
                f.write(content)
            rep.last_run, rep.last_status = datetime.utcnow(), "success"
            rep.last_path, rep.last_error = path, None
        except Exception as exc:
            rep.last_run, rep.last_status = datetime.utcnow(), "error"
            rep.last_error = str(exc)[:2000]
        db.commit()
    finally:
        db.close()


def _register_job(rep: ScheduledReport):
    """Rapor tanımını scheduler'a cron job olarak kaydet (varsa değiştir)."""
    scheduler.add_job(run_scheduled_report, trigger="cron",
                      hour=rep.hour, minute=rep.minute,
                      args=[rep.id], id=rep.job_id, replace_existing=True)


def register_all_scheduled_reports():
    """Açılışta DB'deki etkin raporları scheduler'a yeniden kaydet (kalıcılık)."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        for rep in db.query(ScheduledReport).filter_by(enabled=True).all():
            try:
                _register_job(rep)
            except Exception:
                pass
    finally:
        db.close()


def _serialize(rep: ScheduledReport):
    """Bir rapor tanımını arayüz için JSON'a çevir (saatler yerel TZ'ye uygun ISO)."""
    job = scheduler.get_job(rep.job_id)
    return {
        "id": rep.id, "name": rep.name or "", "target": rep.target,
        "fmt": rep.fmt, "query": rep.query or "",
        "hour": rep.hour, "minute": rep.minute, "enabled": rep.enabled,
        "next_run": to_iso(job.next_run_time) if job and job.next_run_time else None,
        "last_run": to_iso(rep.last_run), "last_status": rep.last_status,
        "last_file": os.path.basename(rep.last_path) if rep.last_path else None,
        "last_error": rep.last_error,
    }


@router.post("/schedule")
def schedule_report(request: Request, payload: dict = Body(...),
                    user: User = Depends(require_role("operator")),
                    db: Session = Depends(get_db)):
    """
    Zamanlanmış rapor oluştur.
    payload: {"name","target":"vms|hosts","fmt":"xlsx|csv|pdf","q","hour","minute"}
    Cron saati APP_TIMEZONE'a göredir. Rapor _report_dir() klasörüne yazılır.
    """
    validate_csrf(request, payload.pop("csrf_token", None))
    fmt = payload.get("fmt", "xlsx")
    if fmt not in MEDIA:
        raise HTTPException(400, "Format xlsx, csv veya pdf olmalı")
    target = payload.get("target", "vms")
    if target not in ("vms", "hosts"):
        raise HTTPException(400, "Hedef vms veya hosts olmalı")
    rep = ScheduledReport(
        name=payload.get("name", ""), target=target, fmt=fmt,
        query=payload.get("q", ""),
        hour=max(0, min(23, int(payload.get("hour", 7)))),
        minute=max(0, min(59, int(payload.get("minute", 0)))),
        created_by=user.username)
    db.add(rep)
    db.commit()
    db.refresh(rep)
    _register_job(rep)
    db.add(AuditLog(username=user.username, action="schedule_report", detail=rep.job_id))
    db.commit()
    return {"ok": True, "item": _serialize(rep)}


@router.get("/schedule")
def list_scheduled(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    reps = db.query(ScheduledReport).order_by(ScheduledReport.id).all()
    return {"items": [_serialize(r) for r in reps]}


@router.post("/schedule/{report_id}/run")
def run_now(report_id: int, request: Request,
            user: User = Depends(require_role("operator")),
            db: Session = Depends(get_db)):
    """Raporu hemen çalıştır (senkron) — kullanıcı cron saatini beklemesin."""
    validate_csrf(request, None)
    rep = db.get(ScheduledReport, report_id)
    if not rep:
        raise HTTPException(404, "Zamanlanmış rapor bulunamadı")
    run_scheduled_report(report_id)
    db.refresh(rep)
    db.add(AuditLog(username=user.username, action="run_report_now", detail=rep.job_id))
    db.commit()
    return {"ok": True, "item": _serialize(rep)}


@router.delete("/schedule/{report_id}")
def delete_scheduled(report_id: int, request: Request,
                     user: User = Depends(require_role("operator")),
                     db: Session = Depends(get_db)):
    validate_csrf(request, None)
    rep = db.get(ScheduledReport, report_id)
    if not rep:
        raise HTTPException(404, "Zamanlanmış rapor bulunamadı")
    try:
        scheduler.remove_job(rep.job_id)
    except Exception:
        pass  # job zaten yoksa (ör. restart sonrası) sorun değil
    db.delete(rep)
    db.commit()
    return {"ok": True}


# ---------- Üretilmiş rapor dosyaları ----------
@router.get("/files")
def list_report_files(user: User = Depends(get_current_user)):
    """REPORT_DIR içindeki üretilmiş rapor dosyalarını listele."""
    d = _report_dir()
    out = []
    for name in sorted(os.listdir(d), reverse=True):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append({"name": name, "size_kb": round(st.st_size / 1024, 1),
                        "modified": to_iso(datetime.utcfromtimestamp(st.st_mtime))})
    return {"items": out}


@router.get("/files/{name}")
def download_report_file(name: str, user: User = Depends(get_current_user)):
    """Üretilmiş bir rapor dosyasını indir (path traversal korumalı)."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Geçersiz dosya adı")
    path = os.path.join(_report_dir(), name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Dosya bulunamadı")
    ext = name.rsplit(".", 1)[-1].lower()
    media = MEDIA.get(ext, ("application/octet-stream",))[0]
    with open(path, "rb") as f:
        content = f.read()
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"'})
