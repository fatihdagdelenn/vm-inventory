"""Kernel vulnerabilities: CVE list, summary, and the data administration
(online sync, file upload, offline bundle download). Reading needs a login,
changing data needs admin - like the OS lifecycle endpoints."""
import os
import tempfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..core.audit import log_audit
from ..core.security import get_current_user, require_role, validate_csrf
from ..database import get_db
from ..models import User, VirtualMachine
from ..services import vuln_service as vs

router = APIRouter(prefix="/api/vulns", tags=["vulns"])

MAX_UPLOAD = 2 * 1024 ** 3        # an Ubuntu all.zip is several hundred MB


@router.get("")
def list_cves(q: str = "", kev: bool = False, severity: str = "", fix: str = "",
              vm: Optional[int] = None, page: int = 1, per_page: int = 100,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    per_page = max(10, min(per_page, 500))
    items, total = vs.cve_page(db, q=q, kev_only=kev, severity=severity, fix=fix, vm_id=vm,
                               page=page, per_page=per_page)
    vm_row = db.get(VirtualMachine, vm) if vm else None
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "summary": vs.summary(db),
            "vm": {"id": vm_row.id, "name": vm_row.name, "reason": vm_row.vuln_reason}
            if vm_row else None}


@router.get("/summary")
def vuln_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return vs.summary(db)


@router.get("/status")
def vuln_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Data status (Administration -> Vulnerabilities) + the running job."""
    return {**vs.meta(db), **vs.summary(db)}


@router.get("/bundle-info")
def vuln_bundle_info(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Last package and how much changed since (offline card)."""
    return vs.bundle_info(db)


@router.get("/unverified")
def vuln_unverified(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """VMs that could not be checked, grouped by reason, with what to do."""
    return {"groups": vs.unknown_overview(db)}


@router.get("/sources")
def vuln_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Selectable OSV sources with the VMs that need each and the stored data."""
    return vs.sources_overview(db)


@router.put("/sources")
def vuln_sources_save(request: Request, payload: dict = Body(...), db: Session = Depends(get_db),
                      user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    try:
        sel = vs.set_selection(db, payload.get("mode"), payload.get("manual") or [])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log_audit(db, user, "vuln_sources", target=sel["mode"], detail=",".join(sel["manual"])[:255],
              request=request)
    db.commit()
    return vs.sources_overview(db)


@router.post("/probe")
def vuln_probe(request: Request, user: User = Depends(require_role("admin"))):
    """Which download sources this server can reach (cisa.gov, GitHub hosts,
    osv.dev storage) - reads only the first bytes of each."""
    validate_csrf(request, None)
    return {"items": vs.probe()}


@router.get("/ca")
def ca_status(user: User = Depends(require_role("admin"))):
    """Extra CA certificates trusted for data downloads (TLS inspection)."""
    from ..core import outbound
    return outbound.status()


@router.post("/ca")
async def ca_upload(request: Request, file: UploadFile = File(...),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    """Company root CA (PEM / DER, or a whole bundle) for data downloads only."""
    from ..core import outbound
    validate_csrf(request, None)
    data = await file.read(outbound.MAX_UPLOAD + 1)
    try:
        certs = outbound.save_upload(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    company = [c for c in certs if not c["public"]]
    log_audit(db, user, "vuln_ca_upload", target=(file.filename or "ca")[:120],
              detail=f"certs={len(certs)} company={','.join(c['subject'] for c in company)[:200]}",
              request=request)
    db.commit()
    return {"certs": certs, **outbound.status()}


@router.delete("/ca")
def ca_remove(request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_role("admin"))):
    from ..core import outbound
    validate_csrf(request, None)
    removed = outbound.remove_upload()
    log_audit(db, user, "vuln_ca_remove", target="extra-ca.pem", detail=str(removed), request=request)
    db.commit()
    return outbound.status()


@router.post("/sync")
def vuln_sync(request: Request, kev_only: bool = False, db: Session = Depends(get_db),
              user: User = Depends(require_role("admin"))):
    """Download KEV (+ the OSV dumps) in the background; poll /status."""
    validate_csrf(request, None)
    started = vs.run_background("manual", lambda d: vs.job_sync(d, osv=not kev_only))
    if not started:
        raise HTTPException(409, "Başka bir zafiyet verisi işi sürüyor")
    log_audit(db, user, "vuln_sync", target="osv+kev" if not kev_only else "kev", request=request)
    db.commit()
    return {"started": True}


def _start_import(db, request, user, path: str, name: str, size: int) -> dict:
    """Import an uploaded file in the background (one job at a time)."""
    def job(d):
        try:
            res = vs.import_file(d, path)
            res["match"] = vs.recompute(d)
            # what the operator needs to see: did this help the VMs here?
            ov = vs.sources_overview(d)
            res["missing"] = ov["missing"]
            res["vms_evaluated"] = vs.summary(d)["vms_evaluated"]
            vs._meta_set(d, "vuln_last_import", f"{datetime.utcnow().isoformat(timespec='seconds')} {name}")
            d.commit()
            return res
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    if not vs.run_background("import", job):
        os.unlink(path)
        raise HTTPException(409, "Başka bir zafiyet verisi işi sürüyor")
    log_audit(db, user, "vuln_import", target=name, detail=f"{size} bytes", request=request)
    db.commit()
    return {"started": True, "size": size}


@router.post("/import")
async def vuln_import(request: Request, file: UploadFile = File(...),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_role("admin"))):
    """Upload in one request: offline bundle (.json.gz), OSV all.zip / .tar.gz,
    OSV JSON or CISA KEV JSON. The UI uses the chunked upload below instead
    (reverse proxies often limit a request body to 1 MB)."""
    validate_csrf(request, None)
    fd, path = tempfile.mkstemp(prefix="vuln-upload-")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "Dosya çok büyük (en fazla 2 GB)")
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return _start_import(db, request, user, path, (file.filename or "dosya")[:120], size)


# ---------------------------------------------------------------- chunked upload
# A reverse proxy in front of the app (nginx default client_max_body_size =
# 1 MB) answers "413" to a bundle of a few MB before it reaches the app. The
# browser therefore sends the file in pieces below that limit; each piece is
# appended at its offset (a retried piece is accepted again), and "finish"
# starts the import.
CHUNK_MAX = 900 * 1024
_UP_RE = r"^[0-9a-f]{32}$"


def _upload_dir() -> str:
    from ..core.outbound import cert_dir
    d = os.path.join(os.path.dirname(cert_dir()), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _upload_path(upload_id: str) -> str:
    import re
    if not re.match(_UP_RE, upload_id or ""):
        raise HTTPException(400, "Geçersiz yükleme kimliği")
    return os.path.join(_upload_dir(), upload_id + ".part")


@router.post("/upload")
def upload_start(request: Request, payload: dict = Body(...),
                 user: User = Depends(require_role("admin"))):
    import time
    import uuid
    validate_csrf(request, payload.pop("csrf_token", None))
    size = int(payload.get("size") or 0)
    if size <= 0:
        raise HTTPException(400, "Boş dosya")
    if size > MAX_UPLOAD:
        raise HTTPException(413, "Dosya çok büyük (en fazla 2 GB)")
    d = _upload_dir()
    for f in os.listdir(d):                       # forgotten uploads older than a day
        p = os.path.join(d, f)
        try:
            if time.time() - os.path.getmtime(p) > 86400:
                os.unlink(p)
        except OSError:
            pass
    upload_id = uuid.uuid4().hex
    open(_upload_path(upload_id), "wb").close()
    return {"upload_id": upload_id, "chunk": CHUNK_MAX}


@router.put("/upload/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = 0,
                       user: User = Depends(require_role("admin"))):
    validate_csrf(request, None)
    path = _upload_path(upload_id)
    if not os.path.exists(path):
        raise HTTPException(404, "Yükleme bulunamadı (süresi dolmuş olabilir)")
    data = await request.body()
    if len(data) > CHUNK_MAX:
        raise HTTPException(413, "Parça çok büyük")
    have = os.path.getsize(path)
    if offset > have:
        raise HTTPException(409, f"Eksik parça: sunucuda {have} bayt var")
    if have + len(data) - (have - offset) > MAX_UPLOAD:
        raise HTTPException(413, "Dosya çok büyük (en fazla 2 GB)")
    with open(path, "r+b") as f:                  # offset < have: a retried piece
        f.seek(offset)
        f.write(data)
        f.truncate(offset + len(data))
    return {"received": offset + len(data)}


@router.post("/upload/{upload_id}/finish")
def upload_finish(upload_id: str, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    validate_csrf(request, payload.pop("csrf_token", None))
    path = _upload_path(upload_id)
    if not os.path.exists(path):
        raise HTTPException(404, "Yükleme bulunamadı (süresi dolmuş olabilir)")
    size = os.path.getsize(path)
    expected = int(payload.get("size") or size)
    if size != expected:
        raise HTTPException(409, f"Dosya eksik geldi: {size} / {expected} bayt")
    return _start_import(db, request, user, path, str(payload.get("name") or "dosya")[:120], size)


@router.get("/bundle")
def vuln_bundle(request: Request, mode: str = "full", db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    """Data package for servers without internet; mode=delta = only what
    changed since the last package (phase 173)."""
    delta = mode == "delta"
    blob = vs.export_bundle(db, delta=delta)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    log_audit(db, user, "vuln_bundle", target=f"{'delta' if delta else 'full'} {len(blob)} bytes",
              request=request)
    db.commit()
    name = f"vm-inventory-vuln-{'changes-' if delta else ''}{stamp}.json.gz"
    return Response(blob, media_type="application/gzip", headers={
        "Content-Disposition": f'attachment; filename="{name}"'})
