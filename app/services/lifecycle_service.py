"""OS lifecycle (end-of-life) tracking.

Data flow
---------
- Seed: app/resources/os_lifecycle_seed.json ships with the app (built from
  endoflife.date) and is applied on every startup.
- Weekly sync: endoflife.date API v1 (/api/v1/products/<product>). The prod
  server has no internet, so this simply fails there: the first connection
  error stops the round, is logged once at INFO and stored as the last error -
  the stored data keeps working.
- Manual import: Administration -> OS support -> upload a JSON file (the seed
  format, or raw endoflife.date API v1 responses).
For each (distro, version) the newest DATA wins (updated_at = date of the
data), so an old seed never overwrites a newer API result and vice versa.

Status per VM (recompute): supported | soon | extended | eol | unknown, with
the end date that applies and a reason code (translated in the UI).
"""
import json
import logging
import os
from datetime import date, datetime
from typing import Optional

from ..core.os_identity import KERNEL_PRODUCT, identify, kernel_cycle
from ..models import LifecycleOverride, OsLifecycle, VirtualMachine

logger = logging.getLogger("lifecycle")

PRODUCTS = ("ubuntu", "debian", "rhel", "centos", "centos-stream", "rocky-linux",
            "almalinux", "oracle-linux", "sles", "opensuse", "fedora", "amazon-linux",
            "windows-server", "windows", "freebsd", "photon", "alpine-linux",
            KERNEL_PRODUCT)
# Product ids that were wrong in an earlier seed -> the API id (the API names a
# product by its endoflife.date permalink: /photon, not the file vmware-photon.md)
RENAMED = {"vmware-photon": "photon"}
API_URL = "https://endoflife.date/api/v1/products/{}"
# NOT under app/data/: ".gitignore" ignores every data/ folder (database files)
SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources",
                         "os_lifecycle_seed.json")
STATUSES = ("supported", "soon", "extended", "eol", "unknown")
DEFAULT_SOON_DAYS = 180
SOON_KEY = "lifecycle_soon_days"


# ----------------------------------------------------------------- parsing
def _d(v) -> Optional[date]:
    if not v or v is True:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def rows_from_seed(doc: dict) -> list:
    """Seed / export format: {"products": {product: [{cycle, release_date,
    eol, eol_reached, eol_extended}]}}."""
    rows = []
    for product, cycles in (doc.get("products") or {}).items():
        for c in cycles or []:
            if not c.get("cycle"):
                continue
            rows.append(dict(distro=str(product), version=str(c["cycle"]),
                             release_date=_d(c.get("release_date")),
                             eol_standard=_d(c.get("eol")),
                             eol_extended=_d(c.get("eol_extended")),
                             eol_reached=bool(c.get("eol_reached"))))
    return rows


def rows_from_api_v1(doc: dict) -> list:
    """One endoflife.date API v1 product response:
    {"result": {"name": ..., "releases": [{name, releaseDate, isEol, eolFrom,
    isEoes, eoesFrom, ...}]}}."""
    res = doc.get("result") or {}
    product = res.get("name")
    rows = []
    for r in res.get("releases") or []:
        if not product or not r.get("name"):
            continue
        eol = _d(r.get("eolFrom"))
        rows.append(dict(distro=str(product), version=str(r["name"]),
                         release_date=_d(r.get("releaseDate")),
                         eol_standard=eol, eol_extended=_d(r.get("eoesFrom")),
                         eol_reached=bool(r.get("isEol")) and eol is None))
    return rows


def parse_import(obj):
    """Accepted upload shapes -> (rows, data_date):
    seed format; one API v1 product response; a list of them; or a dict
    {product: API v1 response}. Raises ValueError for anything else."""
    stamp = None
    if isinstance(obj, dict) and "products" in obj:
        return rows_from_seed(obj), _ts(obj.get("generated_at"))
    docs = obj if isinstance(obj, list) else (
        [obj] if isinstance(obj, dict) and "result" in obj else
        list(obj.values()) if isinstance(obj, dict) else None)
    if not docs:
        raise ValueError("unrecognised lifecycle JSON")
    rows = []
    for doc in docs:
        if not isinstance(doc, dict) or "result" not in doc:
            raise ValueError("unrecognised lifecycle JSON")
        rows += rows_from_api_v1(doc)
        t = _ts(doc.get("last_modified") or doc.get("generated_at"))
        stamp = max(stamp, t) if (stamp and t) else (stamp or t)
    if not rows:
        raise ValueError("no release cycles in the file")
    return rows, stamp


# ----------------------------------------------------------------- storing
def upsert_rows(db, rows, source: str, data_date: Optional[datetime]) -> dict:
    """Insert / update cycles; a row is replaced only by NEWER data."""
    data_date = data_date or datetime.utcnow()
    have = {(r.distro, r.version): r for r in db.query(OsLifecycle).all()}
    out = {"added": 0, "updated": 0, "kept": 0}
    for row in rows:
        key = (row["distro"], row["version"])
        cur = have.get(key)
        if cur is None:
            cur = OsLifecycle(distro=row["distro"], version=row["version"])
            db.add(cur)
            have[key] = cur
            out["added"] += 1
        elif cur.updated_at and cur.updated_at >= data_date:
            out["kept"] += 1
            continue
        else:
            out["updated"] += 1
        for k in ("release_date", "eol_standard", "eol_extended", "eol_reached"):
            setattr(cur, k, row[k])
        cur.source, cur.updated_at = source, data_date
    db.flush()
    return out


def ensure_seed(db) -> dict:
    """Apply the bundled seed (idempotent; never replaces newer data)."""
    with open(SEED_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    return upsert_rows(db, rows_from_seed(doc), "seed", _ts(doc.get("generated_at")))


def _meta_set(db, key, value):
    from ..core.app_settings import set_setting
    set_setting(db, key, "" if value is None else value)


def sync_from_api(db, timeout: int = 10) -> dict:
    """Fetch every product from endoflife.date. Stops at the first connection
    error (no internet -> one short failure, not 16 timeouts)."""
    import requests
    rows, stamp, done = [], None, []
    try:
        for product in PRODUCTS:
            r = requests.get(API_URL.format(product), timeout=timeout,
                             headers={"User-Agent": "vm-inventory lifecycle sync"})
            if r.status_code == 404:
                logger.warning("endoflife.date has no product '%s' - skipped", product)
                continue
            r.raise_for_status()
            doc = r.json()
            rows += rows_from_api_v1(doc)
            t = _ts(doc.get("last_modified") or doc.get("generated_at"))
            stamp = max(stamp, t) if (stamp and t) else (stamp or t)
            done.append(product)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"[:400]
        _meta_set(db, "lifecycle_last_error", msg)
        _meta_set(db, "lifecycle_last_attempt", datetime.utcnow().isoformat(timespec="seconds"))
        db.commit()
        logger.info("endoflife.date unreachable (%s) - keeping the stored lifecycle data", msg)
        return {"ok": False, "error": msg, "products": done}
    res = upsert_rows(db, rows, "endoflife.date", stamp or datetime.utcnow())
    now = datetime.utcnow().isoformat(timespec="seconds")
    _meta_set(db, "lifecycle_last_attempt", now)
    _meta_set(db, "lifecycle_last_sync", now)
    _meta_set(db, "lifecycle_last_error", "")
    db.commit()
    logger.info("Lifecycle data synced from endoflife.date: %s", res)
    return {"ok": True, "products": done, **res}


# --------------------------------------------------------------- the status
def soon_days(db) -> int:
    from ..core.app_settings import get_int_setting
    return max(1, min(3650, get_int_setting(db, SOON_KEY, DEFAULT_SOON_DAYS)))


class _Index:
    """Lifecycle rows + overrides loaded once per recompute."""

    def __init__(self, db):
        self.cycles = {(r.distro, r.version): r for r in db.query(OsLifecycle).all()}
        self.by_distro = {}
        for r in self.cycles.values():
            self.by_distro.setdefault(r.distro, []).append(r)
        self.overrides = db.query(LifecycleOverride).all()

    def find(self, ident):
        for v in ident.cycles():
            rec = self.cycles.get((ident.distro, v))
            if rec is not None:
                return rec
        return None

    def override(self, vm, distro):
        """Most specific matching override: vm > tag > all."""
        tags = {t.name for t in (vm.tags or [])}
        key = f"{vm.platform_id}:{vm.vmid or vm.external_id}"
        best, rank = None, 0
        for o in self.overrides:
            if o.distro and o.distro != distro:
                continue
            r = {"vm": 3, "tag": 2, "all": 1}.get(o.scope, 0)
            if o.scope == "vm" and o.target != key:
                continue
            if o.scope == "tag" and o.target not in tags:
                continue
            if r > rank:
                best, rank = o, r
        return best


def _tools_running(ts) -> bool:
    t = (ts or "").lower()
    return "running" in t and "notrunning" not in t


def _unknown_reason(vm, ident) -> str:
    """Why the release could not be identified (UI translates the code)."""
    never = (vm.power_state != "running" and not vm.last_boot and not vm.ip_addresses
             and not vm.kernel and not _tools_running(vm.tools_status))
    if ident.source in ("catalog", "ostype", "none"):
        if never:
            return "never_powered"
        if not _tools_running(vm.tools_status):
            return "no_agent"
        ptype = vm.platform.type if vm.platform else ""
        if ptype == "vcenter" and ident.source == "catalog":
            return "tools_old"            # Tools runs but sends no detailed OS data (< 11.2)
    return "version_unknown"


def _windows_candidates(index, ident):
    """Windows client without a build: cycles of the same major + edition."""
    pre = ident.prefix
    out = []
    for r in index.by_distro.get(ident.distro, []):
        if not r.version.startswith(pre):
            continue
        lts = "lts" in r.version
        if (ident.edition or "").endswith("lts") != lts:
            continue
        out.append(r)
    return out


def compute(vm, index, soon: int, today: date):
    """-> (status, until, reason, os_label, confidence)"""
    ident = identify(vm.guest_os, vm.kernel)
    label, conf = ident.label or None, ident.confidence
    if ident.rolling:
        # No release cycles. A rolling system is supported as long as it is kept
        # updated - the running kernel tells: once its upstream series is out
        # of support, the system has not been updated for a long time.
        kc = kernel_cycle(vm.kernel)
        krec = index.cycles.get((KERNEL_PRODUCT, kc)) if kc else None
        if krec is None:
            return "unknown", None, "rolling_no_kernel", label, conf
        label = f"{label} · kernel {kc}"
        if krec.eol_reached or (krec.eol_standard and krec.eol_standard < today):
            return "eol", krec.eol_standard, "rolling_kernel_eol", label, "estimated"
        return "supported", krec.eol_standard, "rolling_kernel", label, "estimated"
    rec = index.find(ident) if ident.version else None
    if rec is None:
        if ident.distro and ident.version:
            return "unknown", None, "no_data", label, conf
        # Release unknown, but if EVERY release it could be is past EOL the
        # answer does not depend on it (any CentOS; Windows 10 non-LTSC).
        cands = []
        if ident.distro and not ident.version:
            cands = (_windows_candidates(index, ident) if ident.distro == "windows" and ident.prefix
                     else index.by_distro.get(ident.distro, []) if ident.distro == "centos" else [])
        if cands and all(c.eol_reached or (c.eol_standard and c.eol_standard < today)
                         for c in cands):
            last = max((c.eol_standard for c in cands if c.eol_standard), default=None)
            return "eol", last, "all_releases_eol", label, "estimated"
        return "unknown", None, _unknown_reason(vm, ident), label, conf
    std, ext = rec.eol_standard, rec.eol_extended
    ov = index.override(vm, ident.distro)
    has_ext = bool(ov and ov.extended)
    std_over = rec.eol_reached or (std is not None and std < today)
    if not std_over:
        if std is None:
            return "supported", None, "no_end_date", label, conf
        status = "soon" if (std - today).days <= soon else "supported"
        return status, std, "standard", label, conf
    if has_ext and ext and ext >= today:
        status = "soon" if (ext - today).days <= soon else "extended"
        return status, ext, "extended_subscription", label, conf
    if ext and ext >= today:
        return "eol", std, "extended_available", label, conf
    return "eol", std, "ended", label, conf


def recompute(db, platform_id: Optional[int] = None, vm_ids=None) -> dict:
    """Recompute and store the support columns; returns counts per status."""
    index = _Index(db)
    soon, today = soon_days(db), date.today()
    q = db.query(VirtualMachine)
    if platform_id is not None:
        q = q.filter(VirtualMachine.platform_id == platform_id)
    if vm_ids is not None:
        q = q.filter(VirtualMachine.id.in_(list(vm_ids)))
    counts = {s: 0 for s in STATUSES}
    for vm in q.all():
        st, until, reason, label, conf = compute(vm, index, soon, today)
        vm.support_status, vm.support_until, vm.support_reason = st, until, reason
        vm.support_os, vm.support_confidence = (label or None), conf
        counts[st] += 1
    db.commit()
    return counts


def meta(db) -> dict:
    """Data status for Administration -> OS support."""
    from sqlalchemy import func
    from ..models import AppSetting
    vals = {r.key: r.value for r in db.query(AppSetting).filter(
        AppSetting.key.in_(["lifecycle_last_sync", "lifecycle_last_attempt",
                            "lifecycle_last_error"]))}
    by_src = dict(db.query(OsLifecycle.source, func.count(OsLifecycle.id))
                  .group_by(OsLifecycle.source).all())
    newest = db.query(func.max(OsLifecycle.updated_at)).scalar()
    return {"last_sync": vals.get("lifecycle_last_sync") or None,
            "last_attempt": vals.get("lifecycle_last_attempt") or None,
            "last_error": vals.get("lifecycle_last_error") or None,
            "by_source": by_src, "cycles": sum(by_src.values()),
            "data_date": newest.isoformat(timespec="seconds") if newest else None,
            "soon_days": soon_days(db), "products": list(PRODUCTS)}


def scheduled_sync():
    """Weekly APScheduler job: try endoflife.date, then recompute."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        sync_from_api(db)
        recompute(db)
    except Exception:
        logger.exception("Lifecycle sync failed")
    finally:
        db.close()


def apply_renames(db) -> int:
    """Drop cycles stored under a wrong product id and move exceptions to the
    right one (RENAMED). Returns the number of dropped rows."""
    n = 0
    for old, new in RENAMED.items():
        n += db.query(OsLifecycle).filter(OsLifecycle.distro == old).delete(synchronize_session=False)
        db.query(LifecycleOverride).filter(LifecycleOverride.distro == old) \
            .update({LifecycleOverride.distro: new}, synchronize_session=False)
    return n


def startup():
    """App start: apply the seed (newest-wins) and compute every VM once."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        if apply_renames(db):
            logger.info("Lifecycle: product ids renamed %s", RENAMED)
        res = ensure_seed(db)
        db.commit()
        if res["added"] or res["updated"]:
            logger.info("Lifecycle seed applied: %s", res)
        recompute(db)
    except Exception:
        logger.exception("Lifecycle startup failed")
        db.rollback()
    finally:
        db.close()
