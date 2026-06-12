"""
Raporlama API'si: Excel / CSV / PDF dışa aktarma + zamanlanmış raporlar.
Arama parametresi (q) aynen uygulanır -> filtrelenmiş sonuçlar dışa aktarılır.
"""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import VirtualMachine, Host, User, AuditLog
from ..core.security import get_current_user, require_role, validate_csrf
from ..core.search import apply_vm_search
from ..core.scheduler import scheduler
from ..services import report_service as rs

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
    filename = f"{title.lower().replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.{ext}"
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


# ---------- Zamanlanmış raporlar ----------
# Rapor dosyaları belirlenen cron zamanında /reports klasörüne yazılır.
import os
REPORT_DIR = os.environ.get("REPORT_DIR", "./data/reports")


def _generate_scheduled_report(fmt: str, q: str):
    """Zamanlayıcı tarafından çağrılır: raporu diske yazar."""
    from ..database import SessionLocal
    os.makedirs(REPORT_DIR, exist_ok=True)
    db = SessionLocal()
    try:
        query = db.query(VirtualMachine).options(
            joinedload(VirtualMachine.host_ref)).filter_by(is_template=False)
        items = apply_vm_search(query, q).order_by(VirtualMachine.name).all()
        content = (rs.export_excel(items, rs.VM_COLUMNS, "Zamanlanmış VM Raporu")
                   if fmt == "xlsx" else rs.export_csv(items, rs.VM_COLUMNS)
                   if fmt == "csv" else rs.export_pdf(items, rs.VM_COLUMNS,
                                                      "Zamanlanmış VM Raporu"))
        path = os.path.join(REPORT_DIR,
                            f"vm_raporu_{datetime.now():%Y%m%d_%H%M}.{fmt}")
        with open(path, "wb") as f:
            f.write(content)
    finally:
        db.close()


@router.post("/schedule")
def schedule_report(request: Request, payload: dict = Body(...),
                    user: User = Depends(require_role("operator")),
                    db: Session = Depends(get_db)):
    """
    Zamanlanmış rapor oluştur.
    payload: {"hour": 7, "minute": 0, "fmt": "xlsx", "q": "cluster:production"}
    Rapor her gün belirtilen saatte REPORT_DIR klasörüne yazılır.
    """
    validate_csrf(request, payload.pop("csrf_token", None))
    fmt = payload.get("fmt", "xlsx")
    if fmt not in MEDIA:
        raise HTTPException(400, "Format xlsx, csv veya pdf olmalı")
    job_id = f"report_{user.username}_{datetime.now():%H%M%S}"
    scheduler.add_job(_generate_scheduled_report, trigger="cron",
                      hour=int(payload.get("hour", 7)),
                      minute=int(payload.get("minute", 0)),
                      args=[fmt, payload.get("q", "")], id=job_id)
    db.add(AuditLog(username=user.username, action="schedule_report", detail=job_id))
    db.commit()
    return {"ok": True, "job_id": job_id}


@router.get("/schedule")
def list_scheduled(user: User = Depends(get_current_user)):
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)}
            for j in scheduler.get_jobs() if j.id.startswith("report_")]
    return {"items": jobs}


@router.delete("/schedule/{job_id}")
def delete_scheduled(job_id: str, request: Request,
                     user: User = Depends(require_role("operator"))):
    validate_csrf(request, None)
    try:
        scheduler.remove_job(job_id)
    except Exception:
        raise HTTPException(404, "Zamanlanmış rapor bulunamadı")
    return {"ok": True}
