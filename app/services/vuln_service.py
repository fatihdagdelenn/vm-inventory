"""Kernel vulnerability matching (OSV + CISA KEV).

Data
----
- OSV (osv.dev) per-ecosystem dumps: <bucket>/<Ecosystem>/all.zip for Ubuntu,
  Debian, AlmaLinux, Rocky Linux, Red Hat. Only KERNEL source packages are
  kept (KERNEL_FILTERS) - an Ubuntu kernel record alone is ~0.7-1 MB because of
  its per-package binary/version lists, the stored rows are a few hundred bytes.
- CISA KEV catalogue (known_exploited_vulnerabilities.json).
- Prod has no internet: a server that has it (the test machine) downloads the
  dumps and exports a compact BUNDLE (Administration -> Vulnerabilities ->
  Download bundle, kernel rows only, a few MB gzip) which is uploaded on prod.
  Raw all.zip / OSV JSON / KEV JSON uploads work too.
- Newest OSV record wins (its 'modified'); KEV: newest catalogVersion wins.

Formats verified against real records (2026-11-03): Ubuntu "Ubuntu:24.04:LTS"
/ "Ubuntu:Pro:18.04:LTS", package "linux" / "linux-hwe-6.8" / "linux-aws"...,
fixed "6.8.0-136.136", HWE "6.8.0-136.136~22.04.1"; Debian "Debian:12",
"linux", "6.1.153-1"; AlmaLinux "AlmaLinux:9", "kernel",
"5.14.0-427.13.1.el9_4"; Red Hat "Red Hat:enterprise_linux:9::baseos",
"kernel", "0:5.14.0-...". CVE ids sit in 'upstream' (Ubuntu/Debian/RH/Alma).
Rocky Linux could not be checked (no reachable copy); it is parsed like Alma.

Matching (only VMs whose OS is supported / ending soon / extended)
--------
- Ubuntu: flavor (-generic, -aws, ...) + kernel series pick the source package
  (GA "linux" vs HWE "linux-hwe-6.8", "linux-aws" vs "linux-aws-6.14").
  uname -r has no upload number, so the ABI is compared; equal ABI is resolved
  when the fix is the FIRST upload of that ABI ("6.8.0-136.136") or when the
  Proxmox agent reported uname -v ("#136-Ubuntu"), otherwise it is uncertain.
  Extended (Ubuntu Pro exception) uses the "Ubuntu:Pro:<ver>:LTS" ecosystem.
- Debian: package version from uname -v ("Debian 6.1.153-1"), dpkg compare;
  without it the VM is 'unknown' (no per-CVE guesses).
- RHEL family: uname -r without the arch = package version-release, rpm
  compare. RHEL / Rocky fall back to AlmaLinux data (same kernel NVRs).
- A record without a 'fixed' event = no fix published yet -> affected.
"""
import gzip
import io
import json
import logging
import os
import re
import tempfile
import threading
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

from sqlalchemy import and_, func

from ..core.os_identity import identify
from ..core.pkgversion import cvss3_score, dpkg_cmp, rpm_cmp, severity_of_score
from ..models import (ChangeHistory, VirtualMachine, VmVuln, VulnAdvisory, VulnCve,
                      VulnKev)

logger = logging.getLogger("vuln")

OSV_URL = "https://osv-vulnerabilities.storage.googleapis.com/{}/all.zip"
OSV_ECOSYSTEMS = ("Ubuntu", "Debian", "AlmaLinux", "Rocky Linux", "Red Hat")
KEV_URLS = ("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
            "https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json")
ELIGIBLE = ("supported", "soon", "extended")
SEV_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "negligible": 1, "unknown": 0, "none": 0}
BUNDLE_KIND = "vm-inventory-vuln-bundle"

_UBUNTU_ECO = re.compile(r"^Ubuntu:(?:Pro:)?\d{2}\.\d{2}(?::LTS)?$")
# VM kernels only: GA "linux", HWE "linux-hwe[-X.Y]", 14.04's "linux-lts-xenial",
# "linux-kvm", "linux-lowlatency[-hwe-X.Y]". Cloud / OEM / board kernels (aws,
# azure, gcp, raspi, nvidia...) are left out on purpose: they are not used on
# vCenter / Proxmox guests and would make the data ~5x larger (measured on
# UBUNTU-CVE-2026-43040: 147 kernel rows -> 34).
_UBUNTU_PKG = re.compile(r"^linux(?:-(?:hwe|lowlatency(?:-hwe)?|kvm|lts-(?:xenial|trusty|utopic|vivid|wily)))?"
                         r"(?:-\d+\.\d+)?$")
_DEBIAN_PKG = re.compile(r"^linux(?:-\d+\.\d+)?$")
_ARCH = re.compile(r"\.(x86_64|aarch64|ppc64le|s390x|i686|noarch)$")


# =================================================================== parsing
def norm_ecosystem(eco: str) -> Optional[str]:
    eco = (eco or "").strip()
    if _UBUNTU_ECO.match(eco):
        return eco
    if re.fullmatch(r"(Debian|AlmaLinux|Rocky Linux):\d+", eco):
        return eco
    m = re.fullmatch(r"Red Hat:enterprise_linux:(\d+)::(?:baseos|appstream)", eco)
    return f"Red Hat:{m.group(1)}" if m else None


def is_kernel_package(eco: str, name: str) -> bool:
    if eco.startswith("Ubuntu:"):
        return bool(_UBUNTU_PKG.match(name))
    if eco.startswith("Debian:"):
        return bool(_DEBIAN_PKG.match(name))
    return name == "kernel"


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def severity_of(rec: dict):
    """(severity, cvss score, specific) - Ubuntu priority, else CVSS v3, else
    the 'Important:' prefix of RH / Alma summaries. specific=False for that
    last one: it is the level of the whole advisory, not of each CVE in it."""
    score, ubuntu = None, None
    for s in rec.get("severity") or []:
        if s.get("type") == "Ubuntu":
            ubuntu = str(s.get("score", "")).lower()
        elif str(s.get("type", "")).startswith("CVSS_V3"):
            score = cvss3_score(str(s.get("score", ""))) or score
    if ubuntu in ("negligible", "low", "medium", "high", "critical"):
        return ubuntu, score, True
    if score is not None:
        return severity_of_score(score), score, True
    m = re.match(r"\s*(Critical|Important|Moderate|Low):", rec.get("summary") or "")
    if m:
        return {"Critical": "critical", "Important": "high", "Moderate": "medium",
                "Low": "low"}[m.group(1)], None, False
    return "unknown", None, False


_KERNEL_INTRO = re.compile(r"^In the Linux kernel, the following vulnerability has been resolved:\s*")
_RH_LINE = re.compile(r"^\s*\*\s*(.+?)\s*\(((?:CVE-\d+-\d+(?:,\s*)?)+)\)\s*$", re.M)


def summaries_of(rec: dict, cves) -> dict:
    """{cve: short description}. RH / Alma advisories list one line per CVE
    ("* kernel: ... (CVE-2024-1086, CVE-...)") - those lines are used; one-CVE
    records (Ubuntu / Debian) use their details text."""
    details = rec.get("details") or ""
    out = {}
    for m in _RH_LINE.finditer(details):
        for c in re.findall(r"CVE-\d+-\d+", m.group(2)):
            out.setdefault(c, re.sub(r"^kernel:\s*", "", m.group(1), flags=re.I)[:400])
    if out or len(cves) != 1:
        return out
    s = " ".join(_KERNEL_INTRO.sub("", (details or rec.get("summary") or "").strip()).split())
    return {cves[0]: s[:400]} if s else {}


def parse_osv(rec: dict) -> list:
    """OSV record -> kernel rows [{cve, ecosystem, package, introduced, fixed}]."""
    ids = [rec.get("id")] + list(rec.get("aliases") or []) + list(rec.get("upstream") or [])
    cves = sorted({x for x in ids if isinstance(x, str) and x.startswith("CVE-")})
    if not cves:
        return []
    out = []
    for a in rec.get("affected") or []:
        pkg = a.get("package") or {}
        eco = norm_ecosystem(pkg.get("ecosystem", ""))
        name = pkg.get("name", "")
        if not eco or not is_kernel_package(eco, name):
            continue
        for r in a.get("ranges") or []:
            if r.get("type") not in (None, "ECOSYSTEM"):
                continue
            intro, pairs = None, []
            for e in r.get("events") or []:
                if "introduced" in e:
                    if intro is not None:
                        pairs.append((intro, None))
                    intro = str(e["introduced"])
                elif "fixed" in e:
                    fx = re.sub(r"^0:", "", str(e["fixed"]))
                    pairs.append((intro or "0", fx))
                    intro = None
            if intro is not None:
                pairs.append((intro, None))
            for i, f in pairs:
                for cve in cves:
                    out.append({"cve": cve, "ecosystem": eco, "package": name,
                                "introduced": i, "fixed": f})
    # one row per (cve, ecosystem, package, introduced, fixed) - Red Hat lists
    # baseos and appstream separately, both normalise to "Red Hat:N"
    seen, uniq = set(), []
    for r in out:
        k = (r["cve"], r["ecosystem"], r["package"], r["introduced"], r["fixed"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


# =================================================================== storing
def _store(db, records, source: str) -> dict:
    """records: iterable of dicts {id, modified, severity, score, specific,
    summaries{cve: text}, rows}. A record's rows are replaced only by a NEWER
    version of it; CVE descriptions / severities go to vuln_cve."""
    have = dict(db.query(VulnAdvisory.osv_id, func.max(VulnAdvisory.modified))
                .group_by(VulnAdvisory.osv_id).all())
    cves = {c.cve: c for c in db.query(VulnCve).all()}
    out = {"records": 0, "replaced": 0, "kept": 0, "rows": 0}
    replace_ids, inserts = [], []

    def flush():
        for i in range(0, len(replace_ids), 500):
            db.query(VulnAdvisory).filter(VulnAdvisory.osv_id.in_(replace_ids[i:i + 500])) \
                .delete(synchronize_session=False)
        if inserts:
            db.bulk_insert_mappings(VulnAdvisory, inserts)
        replace_ids.clear()
        inserts.clear()

    for rec in records:
        oid, modified, rows = rec["id"], rec["modified"], rec["rows"]
        if not oid:
            continue
        old = have.get(oid, "missing")
        if old != "missing" and old and modified and old >= modified:
            out["kept"] += 1
            continue
        if old != "missing":
            replace_ids.append(oid)
            out["replaced"] += 1
        if not rows and old == "missing":
            continue
        out["records"] += 1
        have[oid] = modified
        sev, score, specific = rec["severity"], rec["score"], rec["specific"]
        for r in rows:
            inserts.append(dict(osv_id=oid, cve=r["cve"], ecosystem=r["ecosystem"],
                                package=r["package"], introduced=r.get("introduced") or "0",
                                fixed=r.get("fixed"), severity=sev, score=score,
                                modified=modified, source=source))
        for cve in {r["cve"] for r in rows}:
            c = cves.get(cve)
            if c is None:
                c = cves[cve] = VulnCve(cve=cve)
                db.add(c)
            text = (rec["summaries"] or {}).get(cve)
            if text and len(text) > len(c.summary or ""):
                c.summary = text
            # a CVE-specific level (Ubuntu priority / CVSS) beats an
            # advisory-wide one; among equals the worse one is kept
            if specific and (not c.specific or SEV_RANK.get(sev, 0) > SEV_RANK.get(c.severity, 0)):
                c.severity, c.specific = sev, True
            elif not c.specific and SEV_RANK.get(sev, 0) > SEV_RANK.get(c.severity, 0):
                c.severity = sev
            if score is not None and (c.score is None or score > c.score):
                c.score = score
            if modified and (c.modified is None or modified > c.modified):
                c.modified = modified
        out["rows"] += len(rows)
        if len(inserts) > 5000 or len(replace_ids) > 2000:
            flush()
    flush()
    db.commit()
    return out


def _osv_records(recs):
    for rec in recs:
        rows = parse_osv(rec)
        sev, score, specific = severity_of(rec)
        cves = sorted({r["cve"] for r in rows})
        yield {"id": rec.get("id"), "modified": _ts(rec.get("modified")), "severity": sev,
               "score": score, "specific": specific,
               "summaries": summaries_of(rec, cves) if rows else {}, "rows": rows}


def import_osv_zip(db, path: str, source: str = "osv") -> dict:
    """Stream an OSV all.zip: only members that mention a kernel package are
    parsed (cheap byte pre-filter before json.loads)."""
    def gen():
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                raw = zf.read(name)
                if b'"linux' not in raw and b'"kernel"' not in raw:
                    continue
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue
    return _store(db, _osv_records(gen()), source)


def import_kev(db, doc: dict) -> dict:
    """CISA KEV JSON; replaced only by a newer catalogVersion."""
    from ..core.app_settings import set_setting
    from ..models import AppSetting
    ver = str(doc.get("catalogVersion") or "")
    cur = db.query(AppSetting).filter_by(key="vuln_kev_version").first()
    if cur and cur.value and ver and cur.value >= ver:
        return {"kev": 0, "kept": True, "version": cur.value}
    rows = []
    for v in doc.get("vulnerabilities") or []:
        cve = v.get("cveID")
        if not cve:
            continue
        rows.append(dict(cve=cve, date_added=_d(v.get("dateAdded")), due_date=_d(v.get("dueDate")),
                         ransomware=(v.get("knownRansomwareCampaignUse") or "")[:16],
                         name=(v.get("vulnerabilityName") or "")[:255], updated_at=datetime.utcnow()))
    db.query(VulnKev).delete(synchronize_session=False)
    db.bulk_insert_mappings(VulnKev, rows)
    set_setting(db, "vuln_kev_version", ver)
    db.commit()
    return {"kev": len(rows), "kept": False, "version": ver}


def _d(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _iso(v):
    return v.isoformat(timespec="seconds") + "Z" if v else None


def export_bundle(db) -> bytes:
    """Compact gzip JSON of every stored kernel row + CVE descriptions + KEV,
    for servers without internet."""
    recs = {}
    for a in db.query(VulnAdvisory).order_by(VulnAdvisory.osv_id, VulnAdvisory.id).yield_per(5000):
        r = recs.get(a.osv_id)
        if r is None:
            r = recs[a.osv_id] = {"id": a.osv_id, "modified": _iso(a.modified),
                                  "severity": a.severity, "score": a.score, "rows": []}
        r["rows"].append([a.cve, a.ecosystem, a.package, a.introduced, a.fixed])
    doc = {"kind": BUNDLE_KIND, "schema": 1, "generated_at": _iso(datetime.utcnow()),
           "records": list(recs.values()),
           "cves": [[c.cve, c.summary, c.severity, bool(c.specific), c.score, _iso(c.modified)]
                    for c in db.query(VulnCve).all()],
           "kev_version": _setting(db, "vuln_kev_version"),
           "kev": [[k.cve, k.date_added.isoformat() if k.date_added else None,
                    k.due_date.isoformat() if k.due_date else None, k.ransomware, k.name]
                   for k in db.query(VulnKev).all()]}
    return gzip.compress(json.dumps(doc, separators=(",", ":")).encode())


def import_bundle(db, doc: dict) -> dict:
    if doc.get("schema") != 1:
        raise ValueError(f"desteklenmeyen paket sürümü: {doc.get('schema')}")
    keys = ("cve", "ecosystem", "package", "introduced", "fixed")
    res = _store(db, ({"id": r.get("id"), "modified": _ts(r.get("modified")),
                       "severity": r.get("severity") or "unknown", "score": r.get("score"),
                       "specific": False, "summaries": {},
                       "rows": [dict(zip(keys, x)) for x in r.get("rows") or []]}
                      for r in doc.get("records") or []), "bundle")
    # CVE descriptions: the bundle's copy wins when it is not older
    have = {c.cve: c for c in db.query(VulnCve).all()}
    for cve, summary, sev, specific, score, modified in doc.get("cves") or []:
        c = have.get(cve)
        if c is None:
            c = have[cve] = VulnCve(cve=cve)
            db.add(c)
        m = _ts(modified)
        if c.modified is None or (m and m >= c.modified) or not c.summary:
            c.summary, c.severity, c.specific = summary, sev, bool(specific)
            c.score, c.modified = score, m or c.modified
    db.commit()
    if doc.get("kev"):
        res["kev"] = import_kev(db, {"catalogVersion": doc.get("kev_version") or "",
                                     "vulnerabilities": [
                                         {"cveID": c, "dateAdded": a, "dueDate": du,
                                          "knownRansomwareCampaignUse": rw, "vulnerabilityName": n}
                                         for c, a, du, rw, n in doc["kev"]]})
    return res


def import_file(db, path: str) -> dict:
    """Detect and import an uploaded file: OSV all.zip, bundle (.json.gz /
    .json), KEV JSON, one OSV record or a list of them."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:4] == b"PK\x03\x04":
        return {"type": "osv-zip", **import_osv_zip(db, path, "upload")}
    opener = gzip.open if head[:2] == b"\x1f\x8b" else open
    with opener(path, "rb") as f:
        try:
            doc = json.load(f)
        except ValueError:
            raise ValueError("JSON okunamadı")
    if isinstance(doc, dict) and doc.get("kind") == BUNDLE_KIND:
        return {"type": "bundle", **import_bundle(db, doc)}
    if isinstance(doc, dict) and "vulnerabilities" in doc and "catalogVersion" in doc:
        return {"type": "kev", **import_kev(db, doc)}
    recs = doc if isinstance(doc, list) else [doc]
    if recs and all(isinstance(r, dict) and "affected" in r and "id" in r for r in recs):
        return {"type": "osv-json", **_store(db, _osv_records(recs), "upload")}
    raise ValueError("tanınmayan dosya")


def _setting(db, key):
    from ..models import AppSetting
    row = db.query(AppSetting).filter_by(key=key).first()
    return row.value if row and row.value else None


def _meta_set(db, key, value):
    from ..core.app_settings import set_setting
    set_setting(db, key, "" if value is None else str(value)[:500])


# ================================================================ online sync
def sync_kev(db, timeout: int = 20) -> dict:
    import requests
    last = None
    for url in KEV_URLS:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "vm-inventory"})
            r.raise_for_status()
            return import_kev(db, r.json())
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(last or "KEV download failed")


def sync_osv(db) -> dict:
    """Download every ecosystem dump. The first connection error ends the
    round (offline server: one short failure, not five)."""
    import requests
    done = {}
    for i, eco in enumerate(OSV_ECOSYSTEMS):
        tmp = tempfile.NamedTemporaryFile(prefix="osv-", suffix=".zip", delete=False)
        try:
            with requests.get(OSV_URL.format(quote(eco)), stream=True, timeout=(10, 300),
                              headers={"User-Agent": "vm-inventory"}) as r:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 20):
                    tmp.write(chunk)
            tmp.close()
            done[eco] = import_osv_zip(db, tmp.name, "osv")
        except Exception as exc:
            msg = f"{eco}: {type(exc).__name__}: {exc}"
            if not done:
                raise RuntimeError(msg)
            logger.warning("OSV download failed (%s) - other ecosystems kept", msg)
            done[eco] = {"error": msg}
        finally:
            try:
                tmp.close()
                os.unlink(tmp.name)
            except OSError:
                pass
    return done


# ================================================================== matching
class _Data:
    """Advisory rows grouped by (ecosystem, package), loaded lazily."""

    def __init__(self, db):
        self.db = db
        self.pairs = set(db.query(VulnAdvisory.ecosystem, VulnAdvisory.package).distinct().all())
        self.ecos = {e for e, _ in self.pairs}
        self.kev = {k for (k,) in db.query(VulnKev.cve).all()}
        self.cve_sev = {c: s for c, s in db.query(VulnCve.cve, VulnCve.severity)
                        .filter(VulnCve.specific == True).all()}  # noqa: E712
        self._rows = {}
        self._series = {}

    def rows(self, eco, pkg):
        """{cve: (fixed or None, introduced, osv_id, severity)} - for several
        records of one CVE the EARLIEST fix wins (the first advisory that
        fixed it is enough)."""
        key = (eco, pkg)
        if key not in self._rows:
            cmp_ = dpkg_cmp if eco.startswith(("Ubuntu", "Debian")) else rpm_cmp
            out = {}
            for a in self.db.query(VulnAdvisory).filter_by(ecosystem=eco, package=pkg).all():
                cur = out.get(a.cve)
                if cur is None:
                    out[a.cve] = (a.fixed, a.introduced, a.osv_id, a.severity)
                elif a.fixed and (cur[0] is None or cmp_(a.fixed, cur[0]) < 0):
                    out[a.cve] = (a.fixed, a.introduced, a.osv_id, _worse(a.severity, cur[3]))
            self._rows[key] = out
        return self._rows[key]

    def series(self, eco, pkg):
        """Most common kernel series ("6.8") among a package's fixed versions."""
        key = (eco, pkg)
        if key not in self._series:
            c = Counter(m.group(1) for f, *_ in self.rows(eco, pkg).values() if f
                        for m in [re.match(r"(\d+\.\d+)\.", f)] if m)
            self._series[key] = c.most_common(1)[0][0] if c else None
        return self._series[key]


def _worse(a, b):
    return a if SEV_RANK.get(a or "unknown", 0) >= SEV_RANK.get(b or "unknown", 0) else b


_UB_KERNEL = re.compile(r"^(\d+)\.(\d+)\.(\d+)-(\d+)-([a-z][a-z0-9-]*)$")
_UB_FIXED = re.compile(r"^(\d+\.\d+\.\d+)-(\d+)\.(\d+)(.*)$")
_UB_UPLOAD = re.compile(r"#(\d+(?:\.\d+)*)(~\d+\.\d+(?:\.\d+)?)?-Ubuntu")


def _ubuntu_package(eco, data, flavor, mm):
    """Source package of an Ubuntu kernel flavor + series in one ecosystem."""
    if flavor == "generic":
        cands = [f"linux-hwe-{mm}", "linux-hwe"] + \
            sorted(p for e, p in data.pairs if e == eco and p.startswith("linux-lts-")) + ["linux"]
    elif flavor == "lowlatency":
        cands = [f"linux-lowlatency-hwe-{mm}", "linux-lowlatency"]
    elif flavor == "kvm":
        cands = ["linux-kvm"]
    else:
        return None
    for p in cands:
        if (eco, p) not in data.pairs:
            continue
        if p.endswith(f"-{mm}") or data.series(eco, p) in (mm, None):
            return p
    return None


def _ubuntu_sources(vm, ident, data, extended):
    """-> ([(eco, pkg)], running match, None) or (None, None, reason).
    Extended support (Ubuntu Pro) reads the Pro ecosystem first and the
    standard one for older CVEs (fixed before the standard support ended)."""
    rel = ident.version
    m = _UB_KERNEL.match((vm.kernel or "").strip())
    if not m:
        return None, None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    ecos = [e for e in ([f"Ubuntu:Pro:{rel}:LTS"] if extended else []) +
            [f"Ubuntu:{rel}:LTS", f"Ubuntu:{rel}"] if e in data.ecos]
    if not ecos:
        return None, None, f"Ubuntu {rel}{' Pro' if extended else ''} zafiyet verisi yüklenmemiş"
    mm, flavor = f"{m.group(1)}.{m.group(2)}", m.group(5)
    src = [(e, p) for e in ecos for p in [_ubuntu_package(e, data, flavor, mm)] if p]
    if not src:
        if flavor not in ("generic", "lowlatency", "kvm"):
            return None, None, (f"-{flavor} çekirdeği kapsam dışı (yalnızca generic / HWE / "
                                f"kvm / lowlatency çekirdekleri eşleştirilir)")
        return None, None, f"Çekirdek paketi eşleşmedi ({flavor}, {mm})"
    return src, m, None


def _ubuntu_check(m, build, fixed):
    """'affected' | 'ok' | 'uncertain' for one fixed version.
    uname -r ("6.8.0-124-generic") carries the ABI but not the upload number
    of the package ("6.8.0-124.124"); uname -v ("#124-Ubuntu", Proxmox agent
    only) carries it."""
    base = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    abi = int(m.group(4))
    up = _UB_UPLOAD.search(build or "")
    if up:
        full = f"{base}-{abi}.{up.group(1)}{up.group(2) or ''}"
        return "affected" if dpkg_cmp(full, fixed) < 0 else "ok"
    fm = _UB_FIXED.match(fixed)
    if not fm:
        return "affected" if dpkg_cmp(f"{base}-{abi}", fixed) < 0 else "ok"
    c = dpkg_cmp(base, fm.group(1))
    if c:
        return "affected" if c < 0 else "ok"
    fabi, fup, rest = int(fm.group(2)), int(fm.group(3)), fm.group(4)
    if abi != fabi:
        return "affected" if abi < fabi else "ok"
    # Same ABI. "6.8.0-136.136" (upload == ABI, optional "~22.04.1") is the
    # FIRST upload of ABI 136, so every kernel reporting ABI 136 has the fix.
    # "6.8.0-136.138" / "6.8.0-136.136.2" may be a later upload -> unknown.
    if fup == fabi and re.fullmatch(r"(~\d+\.\d+\.1)?", rest):
        return "ok"
    return "uncertain"


def _ubuntu_shown(m, build):
    s = f"{m.group(1)}.{m.group(2)}.{m.group(3)}-{m.group(4)}"
    up = _UB_UPLOAD.search(build or "")
    return s + (f".{up.group(1)}{up.group(2) or ''}" if up else "")


def _debian_source(vm, ident, data):
    eco = f"Debian:{ident.version}"
    if eco not in data.ecos:
        return None, f"Debian {ident.version} zafiyet verisi yüklenmemiş"
    km = re.match(r"(\d+\.\d+)\.", vm.kernel or "")
    if not km:
        return None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    mm = km.group(1)
    pkg = next((p for p in ("linux", f"linux-{mm}") if (eco, p) in data.pairs and
                (p.endswith(f"-{mm}") or data.series(eco, p) in (mm, None))), None)
    if not pkg:
        return None, f"Çekirdek paketi eşleşmedi (linux {mm})"
    bm = re.search(r"Debian (\d[^\s)]*)", vm.kernel_build or "")
    if not bm:
        return None, ("Debian paket sürümü bilinmiyor: uname -r paket sürümünü vermez, "
                      "uname -v gerekli (yalnızca Proxmox QEMU agent bildirir)")
    return (eco, pkg, bm.group(1)), None


_RH_DATA = {"almalinux": ["AlmaLinux"], "rocky-linux": ["Rocky Linux", "Red Hat", "AlmaLinux"],
            "rhel": ["Red Hat", "AlmaLinux"]}
_RH_NAME = {"almalinux": "AlmaLinux", "rocky-linux": "Rocky Linux", "rhel": "Red Hat"}


def _rh_source(vm, ident, data):
    eco = next((f"{o}:{ident.version}" for o in _RH_DATA[ident.distro]
                if (f"{o}:{ident.version}", "kernel") in data.pairs), None)
    if not eco:
        return None, f"{ident.label} çekirdek zafiyet verisi yüklenmemiş"
    running = _ARCH.sub("", (vm.kernel or "").strip())
    if not re.match(r"\d+\.\d+\.\d+-\S+\.el\d", running):
        return None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    return (eco, "kernel", running), None


def evaluate(vm, data):
    """-> (vm_status, vm_reason, findings{cve: dict}).
    vm_status: evaluated | skipped (not supported) | unknown (cannot tell)."""
    if vm.is_template:
        return "skipped", "Şablon - değerlendirilmez", {}
    if "windows" in (vm.guest_os or "").lower() or (vm.kernel or "").startswith("NT "):
        return "skipped", "Kapsam dışı: yalnızca Linux çekirdekleri eşleştirilir", {}
    if (vm.support_status or "unknown") not in ELIGIBLE:
        return "skipped", ("İşletim sistemi desteği bitmiş (EOL) - değerlendirilmedi"
                           if vm.support_status == "eol" else
                           "İşletim sistemi desteği bilinmiyor - değerlendirilmedi"), {}
    if not vm.kernel:
        return "unknown", "Çekirdek sürümü bilinmiyor (agent / Tools bildirmiyor)", {}
    ident = identify(vm.guest_os, vm.kernel)
    extended = vm.support_status == "extended"
    if ident.distro == "ubuntu" and ident.version:
        src, m, why = _ubuntu_sources(vm, ident, data, extended)
        if src is None:
            return "unknown", why, {}
        shown = _ubuntu_shown(m, vm.kernel_build)
        pro = any(":Pro:" in e for e, _ in src)
        head = f"{ident.label}{' Pro' if pro else ''} · {src[0][1]} {shown}"

        def check(eco, fixed):
            return _ubuntu_check(m, vm.kernel_build, fixed)
        cmp_running = None
    elif extended and ident.distro != "debian":       # Debian LTS fixes are in Debian:N
        return "unknown", f"Uzatılmış destek: {ident.label} için ELS/ESU çekirdek verisi yok", {}
    elif ident.distro in ("debian", "rhel", "almalinux", "rocky-linux") and ident.version:
        tgt, why = (_debian_source if ident.distro == "debian" else _rh_source)(vm, ident, data)
        if tgt is None:
            return "unknown", why, {}
        eco, pkg, running = tgt
        src, shown = [(eco, pkg)], running
        cmp_ = dpkg_cmp if ident.distro == "debian" else rpm_cmp
        other = eco.split(":")[0]
        head = f"{ident.label} · {pkg} {shown}"
        if ident.distro != "debian" and other != _RH_NAME[ident.distro]:
            head += f" ({other} verisiyle - aynı çekirdek sürümleri)"

        def check(eco, fixed):
            return "affected" if cmp_(running, fixed) < 0 else "ok"
        cmp_running = (cmp_, running)
    else:
        return "unknown", (f"Bu dağıtım için çekirdek zafiyet verisi yok "
                           f"({ident.label or vm.guest_os or '?'})"), {}

    findings = {}
    for eco, pkg in src:
        for cve, (fixed, intro, osv_id, sev) in data.rows(eco, pkg).items():
            if cve in findings:
                continue                      # an earlier (Pro) source decided
            # introduced after the running version -> not affected (Debian /
            # RH; Ubuntu kernel records always start at 0)
            if cmp_running and intro and intro != "0" and cmp_running[0](cmp_running[1], intro) < 0:
                continue
            if fixed is None:
                st, why = "affected", "düzeltme yayımlanmadı -> etkileniyor"
            else:
                st = check(eco, fixed)
                if st == "ok":
                    findings[cve] = None      # decided: not affected
                    continue
                why = (f"düzeltme {fixed} -> etkileniyor" if st == "affected" else
                       f"düzeltme {fixed} · ABI aynı, yükleme numarası bilinmiyor -> belirsiz")
            findings[cve] = {"osv_id": osv_id, "package": pkg, "fixed": fixed, "status": st,
                             "fix_available": fixed is not None,
                             "severity": data.cve_sev.get(cve) or sev or "unknown",
                             "kev": cve in data.kev,
                             "reason": f"{ident.label}{' Pro' if ':Pro:' in eco else ''} · "
                                       f"{pkg} {shown} · {why}"}
    return "evaluated", head, {c: f for c, f in findings.items() if f}


def recompute(db, platform_id: Optional[int] = None, vm_ids=None) -> dict:
    """Evaluate VMs, open / update / close findings, refresh VM summaries."""
    data = _Data(db)
    q = db.query(VirtualMachine)
    if platform_id is not None:
        q = q.filter(VirtualMachine.platform_id == platform_id)
    if vm_ids is not None:
        q = q.filter(VirtualMachine.id.in_(list(vm_ids)))
    vms = q.all()
    ids = [v.id for v in vms]
    existing = defaultdict(dict)
    for i in range(0, len(ids), 500):
        for r in db.query(VmVuln).filter(VmVuln.vm_id.in_(ids[i:i + 500])).all():
            existing[r.vm_id][r.cve] = r
    now = datetime.utcnow()
    memo = {}
    tot = {"evaluated": 0, "skipped": 0, "unknown": 0, "new": 0, "closed": 0, "open": 0}
    for vm in vms:
        was_evaluated = vm.vuln_status == "evaluated"
        # VMs on the same OS + kernel share one evaluation
        key = (bool(vm.is_template), vm.support_status, vm.guest_os, vm.kernel, vm.kernel_build)
        if key not in memo:
            memo[key] = evaluate(vm, data)
        status, reason, found = memo[key]
        tot[status] += 1
        mine = existing.get(vm.id, {})
        new_cves, closed_cves = [], []
        for cve, f in found.items():
            row = mine.get(cve)
            if row is None:
                row = VmVuln(vm_id=vm.id, cve=cve, first_seen=now)
                db.add(row)
                new_cves.append(cve)
            elif row.closed_at is not None:
                row.closed_at, row.closed_reason, row.first_seen = None, None, now
                new_cves.append(cve)
            row.osv_id, row.package, row.fixed = f["osv_id"], f["package"], f["fixed"]
            row.status, row.fix_available, row.kev = f["status"], f["fix_available"], f["kev"]
            row.severity, row.reason, row.last_seen = f["severity"], f["reason"], now
        for cve, row in mine.items():
            if cve not in found and row.closed_at is None:
                row.closed_at = now
                row.closed_reason = "patched" if status == "evaluated" else "not_evaluated"
                if status == "evaluated":
                    closed_cves.append(cve)
        opened = list(found.values())
        vm.vuln_status, vm.vuln_reason = status, (reason or None)
        vm.vuln_total = len(opened) if status == "evaluated" else None
        vm.vuln_open = sum(1 for f in opened if f["status"] == "affected" and f["fix_available"]) \
            if status == "evaluated" else None
        vm.vuln_kev = sum(1 for f in opened if f["kev"]) if status == "evaluated" else None
        vm.vuln_max_sev = (max((f["severity"] for f in opened), key=lambda s: SEV_RANK.get(s, 0))
                           if opened else None)
        tot["open"] += len(opened)
        tot["new"] += len(new_cves)
        tot["closed"] += len(closed_cves)
        # Change History: only for a VM that had been evaluated before, so the
        # first data import does not write thousands of rows
        if was_evaluated and (new_cves or closed_cves):
            if new_cves:
                kev_new = [c for c in new_cves if found[c]["kev"]]
                db.add(ChangeHistory(
                    entity_type="vm", entity_name=vm.name, platform_id=vm.platform_id,
                    change_type="updated", field="vuln", category="security",
                    old_value=None, vm_external_id=vm.external_id, cluster=vm.cluster,
                    new_value=_cve_list(new_cves, kev_new, "yeni")))
            if closed_cves:
                db.add(ChangeHistory(
                    entity_type="vm", entity_name=vm.name, platform_id=vm.platform_id,
                    change_type="updated", field="vuln", category="security",
                    old_value=_cve_list(closed_cves, [], "kapandı"), new_value=None,
                    vm_external_id=vm.external_id, cluster=vm.cluster))
    if platform_id is None and vm_ids is None:          # findings of deleted VMs
        db.query(VmVuln).filter(~VmVuln.vm_id.in_(db.query(VirtualMachine.id))) \
            .delete(synchronize_session=False)
    db.commit()
    if tot["new"]:
        try:
            from ..core import events
            events.publish({"kind": "vuln", "new": tot["new"], "closed": tot["closed"],
                            "ts": now.isoformat() + "Z"})
        except Exception:
            pass
    return tot


def _cve_list(cves, kev, word):
    shown = ", ".join(c + (" (KEV)" if c in kev else "") for c in sorted(cves)[:12])
    more = f" +{len(cves) - 12}" if len(cves) > 12 else ""
    return f"{len(cves)} CVE {word}: {shown}{more}"


# =============================================================== background
_job_lock = threading.Lock()
JOB = {"running": False, "kind": None, "started": None, "finished": None,
       "ok": None, "message": None}


def run_background(kind: str, fn) -> bool:
    """Run fn(db) in a thread (one job at a time). False if one is running."""
    if not _job_lock.acquire(blocking=False):
        return False
    JOB.update(running=True, kind=kind, started=datetime.utcnow().isoformat() + "Z",
               finished=None, ok=None, message=None)

    def work():
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            msg = fn(db)
            JOB.update(ok=True, message=msg)
        except Exception as exc:
            db.rollback()
            logger.info("Vulnerability job '%s' failed: %s", kind, exc)
            JOB.update(ok=False, message=f"{type(exc).__name__}: {exc}"[:400])
        finally:
            db.close()
            JOB.update(running=False, finished=datetime.utcnow().isoformat() + "Z")
            _job_lock.release()
    threading.Thread(target=work, name=f"vuln-{kind}", daemon=True).start()
    return True


def job_sync(db, osv: bool = True):
    """Download KEV (+ OSV dumps), then recompute. Each source fails on its own
    (KEV may be reachable through a mirror while OSV storage is not); matching
    runs when at least one of them brought data. Offline -> one short error."""
    out, errors = {}, []
    now = lambda: datetime.utcnow().isoformat(timespec="seconds")  # noqa: E731
    try:
        out["kev"] = sync_kev(db)
    except Exception as exc:
        errors.append(f"KEV: {exc}")
    if osv:
        try:
            out["osv"] = sync_osv(db)
            _meta_set(db, "vuln_last_osv", now())
        except Exception as exc:
            errors.append(f"OSV {exc}")
    _meta_set(db, "vuln_last_attempt", now())
    _meta_set(db, "vuln_last_error", " | ".join(errors)[:500])
    if out:
        _meta_set(db, "vuln_last_sync", now())
    db.commit()
    if errors:
        logger.info("Vulnerability data partly / not reachable (%s) - keeping the stored data",
                    " | ".join(errors)[:300])
    if not out:
        raise RuntimeError(" | ".join(errors))
    out["match"] = recompute(db)
    if errors:
        out["errors"] = errors
    return out


def scheduled_kev():
    run_background("kev", lambda db: job_sync(db, osv=False))


def scheduled_osv():
    run_background("osv", lambda db: job_sync(db, osv=True))


def scheduled_boot():
    """Shortly after start: KEV always, OSV too when there is no data yet or
    the last full download is older than a week."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        last = _setting(db, "vuln_last_osv")
        empty = not db.query(VulnAdvisory.id).first()
    finally:
        db.close()
    stale = not last or (datetime.utcnow() - datetime.fromisoformat(last)).days >= 7
    run_background("boot", lambda d: job_sync(d, osv=empty or stale))


def meta(db) -> dict:
    n = db.query(func.count(VulnAdvisory.id)).scalar() or 0
    by_eco = dict(db.query(VulnAdvisory.ecosystem, func.count(func.distinct(VulnAdvisory.cve)))
                  .group_by(VulnAdvisory.ecosystem).all())
    newest = db.query(func.max(VulnAdvisory.modified)).scalar()
    return {"rows": n, "cves": db.query(func.count(func.distinct(VulnAdvisory.cve))).scalar() or 0,
            "by_ecosystem": by_eco, "data_date": newest.isoformat(timespec="seconds") if newest else None,
            "kev": db.query(func.count(VulnKev.cve)).scalar() or 0,
            "kev_version": _setting(db, "vuln_kev_version"),
            "last_sync": _setting(db, "vuln_last_sync"), "last_attempt": _setting(db, "vuln_last_attempt"),
            "last_error": _setting(db, "vuln_last_error"), "job": dict(JOB)}


# ==================================================================== views
def _sev_key(s):
    return -SEV_RANK.get(s or "unknown", 0)


def vm_findings(db, vm_id: int) -> list:
    """Open findings of one VM, KEV / severity first (VM detail)."""
    rows = db.query(VmVuln).filter(VmVuln.vm_id == vm_id, VmVuln.closed_at.is_(None)).all()
    cves = {c.cve: c for c in db.query(VulnCve).filter(VulnCve.cve.in_([r.cve for r in rows]))} \
        if rows else {}
    kev = {k.cve: k for k in db.query(VulnKev).filter(VulnKev.cve.in_([r.cve for r in rows]))} \
        if rows else {}
    out = [{"cve": r.cve, "status": r.status, "fix_available": bool(r.fix_available),
            "fixed": r.fixed, "package": r.package, "severity": r.severity or "unknown",
            "score": cves[r.cve].score if r.cve in cves else None,
            "summary": cves[r.cve].summary if r.cve in cves else None,
            "kev": bool(r.kev), "kev_due": kev[r.cve].due_date.isoformat()
            if r.cve in kev and kev[r.cve].due_date else None,
            "ransomware": (kev[r.cve].ransomware == "Known") if r.cve in kev else False,
            "reason": r.reason, "osv_id": r.osv_id,
            "first_seen": r.first_seen.isoformat(timespec="seconds") + "Z" if r.first_seen else None}
           for r in rows]
    out.sort(key=lambda f: (not f["kev"], f["status"] != "affected", not f["fix_available"],
                            _sev_key(f["severity"]), -(f["score"] or 0), f["cve"]))
    return out


def cve_list(db, q: str = "", kev_only: bool = False, severity: str = "",
             fix: str = "", vm_id: Optional[int] = None) -> list:
    """CVEs with at least one open finding, with affected VM counts."""
    from sqlalchemy import case
    fq = db.query(VmVuln.cve,
                  func.count(VmVuln.id),
                  func.sum(case((and_(VmVuln.status == "affected",
                                      VmVuln.fix_available == True), 1), else_=0)),  # noqa: E712
                  func.sum(case((VmVuln.status == "uncertain", 1), else_=0)),
                  func.sum(case((VmVuln.fix_available == False, 1), else_=0)),  # noqa: E712
                  func.max(VmVuln.severity), func.max(VmVuln.first_seen)) \
        .filter(VmVuln.closed_at.is_(None))
    if q:
        fq = fq.filter(VmVuln.cve.ilike(f"%{q.strip()}%"))
    if kev_only:
        fq = fq.filter(VmVuln.kev == True)  # noqa: E712
    if vm_id:
        fq = fq.filter(VmVuln.vm_id == vm_id)
    agg = fq.group_by(VmVuln.cve).all()
    names = [a[0] for a in agg]
    cves, kev, sev_by = {}, {}, defaultdict(set)
    for i in range(0, len(names), 500):
        part = names[i:i + 500]
        cves.update({c.cve: c for c in db.query(VulnCve).filter(VulnCve.cve.in_(part))})
        kev.update({k.cve: k for k in db.query(VulnKev).filter(VulnKev.cve.in_(part))})
        for c, s in db.query(VmVuln.cve, VmVuln.severity).filter(
                VmVuln.cve.in_(part), VmVuln.closed_at.is_(None)).distinct():
            sev_by[c].add(s or "unknown")
    out = []
    for cve, n, fixable, uncertain, nofix, _s, first in agg:
        sev = max(sev_by.get(cve) or {"unknown"}, key=lambda s: SEV_RANK.get(s, 0))
        if severity and sev != severity:
            continue
        if fix == "fixable" and not fixable:
            continue
        if fix == "nofix" and not nofix:
            continue
        c, k = cves.get(cve), kev.get(cve)
        out.append({"cve": cve, "vms": n, "fixable": int(fixable or 0),
                    "uncertain": int(uncertain or 0), "nofix": int(nofix or 0),
                    "severity": sev, "score": c.score if c else None,
                    "summary": c.summary if c else None, "kev": bool(k),
                    "kev_added": k.date_added.isoformat() if k and k.date_added else None,
                    "kev_due": k.due_date.isoformat() if k and k.due_date else None,
                    "kev_name": k.name if k else None,
                    "ransomware": bool(k and k.ransomware == "Known"),
                    "first_seen": first.isoformat(timespec="seconds") + "Z" if first else None})
    out.sort(key=lambda r: (not r["kev"], _sev_key(r["severity"]), -(r["score"] or 0),
                            -r["fixable"], r["cve"]))
    return out


def summary(db) -> dict:
    """Counts for the dashboard and the Vulnerabilities page header."""
    vm_counts = dict(db.query(func.coalesce(VirtualMachine.vuln_status, "unknown"),
                              func.count(VirtualMachine.id))
                     .group_by(func.coalesce(VirtualMachine.vuln_status, "unknown")).all())
    open_q = db.query(VmVuln).filter(VmVuln.closed_at.is_(None))
    return {
        "vms_evaluated": vm_counts.get("evaluated", 0),
        "vms_skipped": vm_counts.get("skipped", 0),
        "vms_unknown": vm_counts.get("unknown", 0),
        "vms_open": db.query(func.count(VirtualMachine.id)).filter(VirtualMachine.vuln_open > 0).scalar() or 0,
        "vms_kev": db.query(func.count(VirtualMachine.id)).filter(VirtualMachine.vuln_kev > 0).scalar() or 0,
        "cves_open": open_q.with_entities(func.count(func.distinct(VmVuln.cve))).scalar() or 0,
        "cves_kev": open_q.filter(VmVuln.kev == True)  # noqa: E712
        .with_entities(func.count(func.distinct(VmVuln.cve))).scalar() or 0,
        "has_data": bool(db.query(VulnAdvisory.id).first()),
    }
