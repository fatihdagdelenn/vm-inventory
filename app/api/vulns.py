"""Kernel vulnerabilities: CVE list, summary, and the data administration
(online sync, file upload, offline bundle download). Reading needs a login,
changing data needs admin - like the OS lifecycle endpoints."""
import os
import tempfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
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
              vm: Optional[int] = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = vs.cve_list(db, q=q, kev_only=kev, severity=severity, fix=fix, vm_id=vm)
    vm_row = db.get(VirtualMachine, vm) if vm else None
    return {"items": items, "total": len(items), "summary": vs.summary(db),
            "vm": {"id": vm_row.id, "name": vm_row.name, "reason": vm_row.vuln_reason}
            if vm_row else None}


@router.get("/summary")
def vuln_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return vs.summary(db)


@router.get("/status")
def vuln_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Data status (Administration -> Vulnerabilities) + the running job."""
    return {**vs.meta(db), **vs.summary(db)}


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


@router.post("/import")
async def vuln_import(request: Request, file: UploadFile = File(...),
                      db: Session = Depends(get_db),
                      user: User = Depends(require_role("admin"))):
    """Upload: offline bundle (.json.gz), OSV all.zip, OSV JSON or CISA KEV
    JSON. Imported and matched in the background; poll /status."""
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
    name = (file.filename or "dosya")[:120]

    def job(d):
        try:
            res = vs.import_file(d, path)
            res["match"] = vs.recompute(d)
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


@router.get("/bundle")
def vuln_bundle(request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    """Compact kernel-only data package for servers without internet."""
    blob = vs.export_bundle(db)
    stamp = datetime.utcnow().strftime("%Y%m%d")
    log_audit(db, user, "vuln_bundle", target=f"{len(blob)} bytes", request=request)
    db.commit()
    return Response(blob, media_type="application/gzip", headers={
        "Content-Disposition": f'attachment; filename="vm-inventory-vuln-{stamp}.json.gz"'})
