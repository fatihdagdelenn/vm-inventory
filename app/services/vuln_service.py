"""Kernel vulnerability matching (OSV + CISA KEV).

Data
----
- OSV (osv.dev) per-ecosystem dumps: <bucket>/<Ecosystem>/all.zip for Ubuntu,
  Debian, AlmaLinux, Rocky Linux, Red Hat. Only KERNEL source packages are
  kept (KERNEL_FILTERS) - an Ubuntu kernel record alone is ~0.7-1 MB because of
  its per-package binary/version lists, the stored rows are a few hundred bytes.
- CISA KEV catalogue (known_exploited_vulnerabilities.json) from cisa.gov or
  CISA's GitHub repository (KEV_SOURCES); AlmaLinux OSV also from GitHub
  (OSV_GITHUB) when osv.dev storage is blocked.
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
- Windows (phase 168): MSRC monthly CVRF documents give each CVE's fixed
  build per product; the VM's NT build + UBR ("NT 10.0.17763.6775") is
  compared with it. Operating system only (no SQL Server / Exchange / Office).
"""
import gzip
import hashlib
import io
import json
import logging
import os
import re
import tarfile
import tempfile
import threading
import time
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote, urlparse

from sqlalchemy import and_, func

from ..core.os_identity import identify
from ..core.pkgversion import cvss3_score, dpkg_cmp, rpm_cmp, severity_of_score
from ..models import (ChangeHistory, VirtualMachine, VmVuln, VulnAdvisory, VulnCve,
                      VulnCveStat, VulnKernelAbi, VulnKev)

logger = logging.getLogger("vuln")

OSV_URL = "https://osv-vulnerabilities.storage.googleapis.com/{}/all.zip"
OSV_ECOSYSTEMS = ("Ubuntu", "Debian", "AlmaLinux", "Rocky Linux", "Red Hat", "SUSE", "openSUSE")
# Selectable data sources (Administration -> Vulnerability Data). `distros` are
# os_identity ids whose VMs are matched with the source - "auto" mode downloads
# only the sources the inventory needs; `prefix` is the stored ecosystem prefix.
SOURCES = {
    "Ubuntu": {"distros": ("ubuntu",), "prefix": "Ubuntu:", "size": "large"},
    "Debian": {"distros": ("debian",), "prefix": "Debian:", "size": "large"},
    "AlmaLinux": {"distros": ("almalinux", "rocky-linux", "rhel"), "prefix": "AlmaLinux:",
                  "size": "medium"},
    "Rocky Linux": {"distros": ("rocky-linux",), "prefix": "Rocky Linux:", "size": "medium"},
    "Red Hat": {"distros": ("rhel", "rocky-linux"), "prefix": "Red Hat:", "size": "large"},
    "SUSE": {"distros": ("sles",), "prefix": "SUSE:", "size": "large"},
    "openSUSE": {"distros": ("opensuse",), "prefix": "openSUSE:", "size": "large"},
    "Oracle Linux": {"distros": ("oracle-linux",), "prefix": "Oracle Linux:", "size": "medium"},
    "Photon OS": {"distros": ("photon",), "prefix": "Photon OS:", "size": "small"},
    "Windows": {"distros": ("windows-server", "windows"), "prefix": "Windows", "size": "medium"},
}
# Not in OSV: the vendors' own feeds, one file per release.
#  - Oracle: OVAL (ELSA advisories) - UEK ("kernel-uek") and RHCK ("kernel").
#    Format checked against a real file (quay/claircore testdata
#    com.oracle.elsa-2018.xml): <definition> with <affected><platform>Oracle
#    Linux 8</platform>, <reference source="elsa">, <advisory><severity> and
#    <cve cvss3="7.8/CVSS:3.1/...">, criteria comments "kernel-uek is earlier
#    than 0:5.15.0-205.149.5.1.el8uek".
#  - Photon (Broadcom): JSON list {cve_id, pkg, cve_score, aff_ver, res_ver,
#    status} (checked against aquasecurity/vuln-list-update testdata).
VENDOR = {
    "Oracle Linux": {"kind": "oval", "versions": ("7", "8", "9", "10"),
                     "urls": ("https://linux.oracle.com/security/oval/com.oracle.elsa-ol{v}.xml.bz2",),
                     "all": "https://linux.oracle.com/security/oval/com.oracle.elsa-all.xml.bz2"},
    "Photon OS": {"kind": "photon", "versions": ("3.0", "4.0", "5.0"),
                  "urls": ("https://packages.broadcom.com/photon/photon_cve_metadata/cve_data_photon{v}.json",
                           "https://packages.vmware.com/photon/photon_cve_metadata/cve_data_photon{v}.json")},
    # Microsoft: monthly CVRF documents (see "Microsoft (MSRC CVRF)" below)
    "Windows": {"kind": "msrc", "versions": (),
                "urls": ("https://api.msrc.microsoft.com/cvrf/v3.0/cvrf/{v}",),
                "index": "https://api.msrc.microsoft.com/cvrf/v3.0/updates"},
}
CATALOGUE = OSV_ECOSYSTEMS + tuple(VENDOR)
SELECTION_KEY = "vuln_sources"
# CISA KEV, tried in order. cisa.gov is often blocked on corporate networks while
# GitHub is open, so CISA's own GitHub repository (cisagov/kev-data, same file,
# updated with the feed) is reached three ways - each through a different host,
# because firewalls allow them separately:
#   raw.githubusercontent.com  plain file
#   api.github.com             contents API with the raw media type (the API host
#                              answers itself, no redirect; 60 calls/h unauthenticated)
#   github.com -> codeload     branch archive (.tar.gz, ~0.5 MB), file taken out
# VULN_KEV_URLS (comma separated) replaces the list, e.g. with an internal mirror.
KEV_FILE = "known_exploited_vulnerabilities.json"
KEV_SOURCES = (
    ("cisa.gov", "https://www.cisa.gov/sites/default/files/feeds/" + KEV_FILE, "json"),
    ("raw.githubusercontent.com",
     "https://raw.githubusercontent.com/cisagov/kev-data/develop/" + KEV_FILE, "json"),
    ("api.github.com",
     "https://api.github.com/repos/cisagov/kev-data/contents/" + KEV_FILE + "?ref=develop", "json"),
    ("github.com (arşiv)",
     "https://github.com/cisagov/kev-data/archive/refs/heads/develop.tar.gz", "tar"),
)
# OSV fallbacks on GitHub, used for an ecosystem whose osv.dev dump could not be
# downloaded. Only AlmaLinux publishes its OSV data there in a usable size
# (AlmaLinux/osv-database, ~6 MB archive, ~300 kernel advisories); RHEL and
# Rocky VMs are matched with it too. Ubuntu's GitHub copy
# (canonical/ubuntu-security-notices) holds ~66,000 files / many GB and Debian
# has none, so those need osv.dev or an uploaded bundle.
OSV_GITHUB = {
    "AlmaLinux": "https://github.com/AlmaLinux/osv-database/archive/refs/heads/master.tar.gz",
}
_UA = {"User-Agent": "vm-inventory (kernel vulnerability matching)"}
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
# SUSE publishes one ecosystem per product / module; the kernel of SLES 15 SP5
# can come as "Linux Enterprise Server 15 SP5", "... Module for Basesystem 15
# SP5", "... Server for SAP Applications 15 SP5", "... 15 SP5-LTSS" - all
# stored as "SUSE:15.5". openSUSE Leap 15.5 -> "openSUSE:15.5".
_SUSE_ECO = re.compile(r"^SUSE:Linux Enterprise (?:Server|Module for Basesystem|Server for SAP Applications|"
                       r"High Performance Computing|Desktop)(?: LTSS)? (\d+)(?: SP(\d+))?(?:[- ]LTSS.*)?$")
_SUSE_PKG = re.compile(r"^kernel-(?:default|azure|rt|64kb|preempt)$")


def norm_ecosystem(eco: str) -> Optional[str]:
    eco = (eco or "").strip()
    if _UBUNTU_ECO.match(eco):
        return eco
    if re.fullmatch(r"(Debian|AlmaLinux|Rocky Linux):\d+", eco):
        return eco
    m = re.fullmatch(r"Red Hat:enterprise_linux:(\d+)::(?:baseos|appstream)", eco)
    if m:
        return f"Red Hat:{m.group(1)}"
    m = _SUSE_ECO.match(eco)
    if m:
        return f"SUSE:{m.group(1)}.{m.group(2) or 0}"
    m = re.fullmatch(r"openSUSE:Leap (\d+\.\d+)", eco)
    return f"openSUSE:{m.group(1)}" if m else None


def is_kernel_package(eco: str, name: str) -> bool:
    if eco.startswith("Ubuntu:"):
        return bool(_UBUNTU_PKG.match(name))
    if eco.startswith("Debian:"):
        return bool(_DEBIAN_PKG.match(name))
    if eco.startswith(("SUSE:", "openSUSE:")):
        return bool(_SUSE_PKG.match(name))
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


def parse_osv(rec: dict, stats: Optional[Counter] = None) -> list:
    """OSV record -> kernel rows [{cve, ecosystem, package, introduced, fixed}].
    `stats` counts kernel-looking entries that were NOT recognised (unknown
    ecosystem / package name) - shown after an import so a format change of a
    source is visible instead of silently giving no data."""
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
            # the MAIN kernel package under an ecosystem name we do not know =
            # the likely sign of a source's naming change
            if stats is not None and not eco and name in ("kernel", "kernel-default", "linux") and \
                    re.match(r"(Debian|AlmaLinux|Rocky Linux|Red Hat|SUSE|openSUSE)",
                             pkg.get("ecosystem", "")) and not _known_skip(pkg.get("ecosystem", "")):
                stats[f"{pkg.get('ecosystem', '')} / {name}"] += 1
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


def _known_skip(eco: str) -> bool:
    """Ecosystems left out ON PURPOSE (not worth reporting): Red Hat EUS / AUS /
    E4S and add-on streams, SUSE products other than the server / base system
    (Micro, Real Time, Live Patching...)."""
    return bool(re.search(r"Red Hat:(?!enterprise_linux:\d+::)|Micro|Real Time|Live Patching|"
                          r"Development Tools|Legacy|Workstation|Public Cloud|Confidential|"
                          r"Manager|Desktop|Leap Micro|Tumbleweed|Package Hub|Containers|"
                          r"Web and Scripting|Server Applications|HPC|Availability|SAP Business", eco))


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
        per_cve = rec.get("cve_scores") or {}            # Oracle / Photon: CVSS per CVE
        for cve in {r["cve"] for r in rows}:
            c = cves.get(cve)
            if c is None:
                c = cves[cve] = VulnCve(cve=cve)
                db.add(c)
            text = (rec["summaries"] or {}).get(cve)
            if text and len(text) > len(c.summary or ""):
                c.summary = text
            c_sev, c_score, c_spec = sev, score, specific
            if per_cve.get(cve) is not None:
                c_score = per_cve[cve]
                c_sev, c_spec = severity_of_score(c_score), True
            # a CVE-specific level (Ubuntu priority / CVSS) beats an
            # advisory-wide one; among equals the worse one is kept
            if c_spec and (not c.specific or SEV_RANK.get(c_sev, 0) > SEV_RANK.get(c.severity, 0)):
                c.severity, c.specific = c_sev, True
            elif not c.specific and SEV_RANK.get(c_sev, 0) > SEV_RANK.get(c.severity, 0):
                c.severity = c_sev
            if c_score is not None and (c.score is None or c_score > c.score):
                c.score = c_score
            if modified and (c.modified is None or modified > c.modified):
                c.modified = modified
        out["rows"] += len(rows)
        if len(inserts) > 5000 or len(replace_ids) > 2000:
            flush()
    flush()
    db.commit()
    return out


def _osv_records(recs, stats=None):
    for rec in recs:
        rows = parse_osv(rec, stats)
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
                rec = _kernel_json(zf.read(name))
                if isinstance(rec, dict):
                    yield rec
    stats = Counter()
    return _with_stats(_store(db, _osv_records(gen(), stats), source), stats)


def _with_stats(res: dict, stats: Counter) -> dict:
    if stats:
        res["unrecognized"] = [f"{k} ({n})" for k, n in stats.most_common(8)]
        logger.info("Kernel entries not recognised (format change?): %s", res["unrecognized"])
    return res


def _kernel_json(raw: bytes):
    """json.loads only for records that can contain a kernel package."""
    if b'"linux' not in raw and b'"kernel' not in raw:     # "kernel", "kernel-default"
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def import_osv_tar(db, path: str, source: str = "github") -> dict:
    """OSV records inside a .tar.gz (a GitHub branch archive such as
    AlmaLinux/osv-database), streamed member by member."""
    def gen():
        with tarfile.open(path, "r:*") as tf:
            for m in tf:
                if not (m.isfile() and m.name.endswith(".json")):
                    continue
                f = tf.extractfile(m)
                rec = _kernel_json(f.read()) if f else None
                if isinstance(rec, dict) and "affected" in rec and "id" in rec:
                    yield rec
    stats = Counter()
    return _with_stats(_store(db, _osv_records(gen(), stats), source), stats)


# ------------------------------------------------------------ vendor feeds
_OVAL = "{http://oval.mitre.org/XMLSchema/oval-definitions-5}"
_ORA_SEV = {"CRITICAL": "critical", "IMPORTANT": "high", "MODERATE": "medium", "LOW": "low"}
_ORA_CRIT = re.compile(r"^(kernel(?:-uek)?) is earlier than (?:\d+:)?(\S+)$")


def _oracle_package(name: str, fixed: str) -> str:
    """UEK streams (5.4 / 5.15 / 6.12) share the name kernel-uek; each has its
    own advisories, so the stream is part of the stored package name."""
    if name == "kernel-uek":
        m = re.match(r"(\d+\.\d+)\.", fixed)
        return f"kernel-uek-{m.group(1)}" if m else name
    return name


def parse_oracle_oval(fileobj, versions=None):
    """Kernel records from an Oracle OVAL file (streamed). `versions`
    limits to Oracle Linux majors ("8", "9"...)."""
    import xml.etree.ElementTree as ET
    for _, el in ET.iterparse(fileobj, events=("end",)):
        if el.tag != _OVAL + "definition":
            if el.tag in (_OVAL + "tests", _OVAL + "objects", _OVAL + "states"):
                el.clear()
            continue
        try:
            md = el.find(_OVAL + "metadata")
            if md is None:
                continue
            plats = [p.text or "" for p in md.findall(_OVAL + "affected/" + _OVAL + "platform")]
            majors = [m.group(1) for p in plats for m in [re.match(r"Oracle Linux (\d+)", p)] if m]
            if not majors or (versions and not set(majors) & set(versions)):
                continue
            fixes = set()
            for c in el.iter(_OVAL + "criterion"):
                m = _ORA_CRIT.match((c.get("comment") or "").strip())
                if m:
                    fixes.add((m.group(1), m.group(2)))
            if not fixes:
                continue
            ref = next((r.get("ref_id") for r in md.findall(_OVAL + "reference")
                        if r.get("source") == "elsa"), None) or el.get("id")
            adv = md.find(_OVAL + "advisory")
            sev_txt = (adv.findtext(_OVAL + "severity") if adv is not None else "") or ""
            issued = adv.find(_OVAL + "issued") if adv is not None else None
            scores, cves = {}, set()
            for c in (adv.findall(_OVAL + "cve") if adv is not None else []):
                cve = (c.text or "").strip()
                if cve.startswith("CVE-"):
                    cves.add(cve)
                    m = re.match(r"([\d.]+)/CVSS:3", c.get("cvss3") or "")
                    if m:
                        scores[cve] = float(m.group(1))
            cves |= {r.get("ref_id") for r in md.findall(_OVAL + "reference")
                     if r.get("source") == "CVE" and (r.get("ref_id") or "").startswith("CVE-")}
            if not cves:
                continue
            modified = _ts((issued.get("date") if issued is not None else None) or "") or datetime(2000, 1, 1)
            try:                             # a re-issued advisory has a higher version
                from datetime import timedelta
                modified += timedelta(seconds=int(el.get("version") or 0))
            except ValueError:
                pass
            # one UEK advisory often covers OL6 + OL7 with a build per release
            # ("…el6uek" / "…el7uek"): give each release only its own build
            def _for(mj, fx):
                t = re.search(r"\.el(\d+)", fx)
                return not t or t.group(1) == mj
            rows = [{"cve": cve, "ecosystem": f"Oracle Linux:{mj}",
                     "package": _oracle_package(pkg, fx), "introduced": "0", "fixed": fx}
                    for mj in majors if not versions or mj in versions
                    for pkg, fx in sorted(fixes) if _for(mj, fx) for cve in sorted(cves)]
            if not rows:
                continue
            yield {"id": ref, "modified": modified, "severity": _ORA_SEV.get(sev_txt.upper(), "unknown"),
                   "score": None, "specific": False, "summaries": {}, "rows": rows,
                   "cve_scores": scores}
        finally:
            el.clear()


def _open_maybe_bz2(path):
    import bz2
    with open(path, "rb") as f:
        head = f.read(3)
    return bz2.open(path, "rb") if head == b"BZh" else open(path, "rb")


def import_oracle_oval(db, path: str, source: str = "oracle", versions=None) -> dict:
    with _open_maybe_bz2(path) as f:
        return _store(db, parse_oracle_oval(f, versions), source)


_PHOTON_PKG = re.compile(r"^linux(?:-(?:esx|secure|rt|aws))?$")


def parse_photon(doc: list, version: str) -> list:
    """Photon CVE list -> one record per CVE (kernel packages only)."""
    per = defaultdict(list)
    scores = {}
    for x in doc:
        cve, pkg = str(x.get("cve_id") or ""), str(x.get("pkg") or "")
        if not cve.startswith("CVE-") or not _PHOTON_PKG.match(pkg):
            continue
        if str(x.get("status") or "").lower().startswith("not affected"):
            continue
        res = str(x.get("res_ver") or "")
        aff = str(x.get("aff_ver") or "").lower()
        if re.match(r"\d", res):
            fixed = res
        elif aff.startswith("all versions"):
            fixed = None                    # vulnerable, no fixed build yet
        else:
            continue
        per[cve].append({"cve": cve, "ecosystem": f"Photon OS:{version}", "package": pkg,
                         "introduced": "0", "fixed": fixed})
        try:
            scores[cve] = max(scores.get(cve, 0), float(x.get("cve_score")))
        except (TypeError, ValueError):
            pass
    now = datetime.utcnow()
    return [{"id": f"PHOTON-{version}-{cve}", "modified": now,
             "severity": severity_of_score(scores.get(cve)), "score": scores.get(cve),
             "specific": cve in scores, "summaries": {}, "rows": rows,
             "cve_scores": {cve: scores[cve]} if cve in scores else {}}
            for cve, rows in per.items()]


def _photon_version(doc: list, hint: str = "") -> Optional[str]:
    m = re.search(r"photon(\d+\.\d+)", hint or "")
    if m:
        return m.group(1)
    c = Counter(m.group(1) for x in doc for m in [re.search(r"\.ph(\d+)", str(x.get("res_ver") or ""))] if m)
    return f"{c.most_common(1)[0][0]}.0" if c else None


def import_photon(db, doc: list, version: str, source: str = "photon") -> dict:
    """The file is the whole truth for its release: rows of that release are
    replaced (a CVE that disappears from the feed disappears here too)."""
    eco = f"Photon OS:{version}"
    db.query(VulnAdvisory).filter(VulnAdvisory.ecosystem == eco).delete(synchronize_session=False)
    db.commit()
    return {**_store(db, parse_photon(doc, version), source), "version": version}


# ------------------------------------------------------- Microsoft (MSRC CVRF)
# Windows has no package versions: the OS is one cumulative update per month
# and its identity is the NT build + update revision (UBR), "10.0.17763.6893".
# MSRC's CVRF API (api.msrc.microsoft.com/cvrf/v3.0, no key) publishes one
# document per month; every CVE lists, per product, the update that fixes it
# (Remediation "Vendor Fix": KB number, SubType, FixedBuild). Format checked
# against a real document (XML, MaineK00n/vuls-data-update fetch testdata
# 2024-Mar) and the official MSRC PowerShell module (JSON: Remediations[].Type
# 2 = Vendor Fix, .FixedBuild, Threats[].Type 3 = Severity, CVSSScoreSets).
# Stored rows: ecosystem "Windows Server:2019" / "Windows:11-24h2" (the
# os_identity cycle id), package "windows", fixed = FixedBuild, introduced =
# the KB of that fix ("KB5050008" - Windows rows have no introduced version).
# Left out on purpose: hotpatch updates (only Azure Edition / hotpatch-enrolled
# machines take them; a CVE fixed ONLY by a hotpatch does not affect the
# others), CVEs with "Customer Action Required: No" (fixed in the cloud).
MSRC_MONTHS = 24                  # monthly documents downloaded (the data window)
_CVRF_V = "{http://www.icasi.org/CVRF/schema/vuln/1.1}"
_CVRF_P = "{http://www.icasi.org/CVRF/schema/prod/1.1}"
_CVRF_C = "{http://www.icasi.org/CVRF/schema/cvrf/1.1}"
_MS_SEV = {"critical": "critical", "important": "high", "moderate": "medium", "low": "low"}
_MS_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _ms_builds():
    from ..core.os_identity import _CLIENT_BUILDS, _SERVER_BUILDS
    return ({v: k for k, v in _SERVER_BUILDS.items() if k not in (6002,)},
            {v: k for k, v in _CLIENT_BUILDS.items()})


def msrc_product(name: str):
    """MSRC product name -> (ecosystem, NT build) for Windows OS products,
    else None. Server Core installations share the full product's row (the
    inventory cannot tell them apart); 32-bit / x64 / ARM64 share one too."""
    n = re.sub(r"\s*\(Server Core installation\)\s*$", "", (name or "").strip())
    server, client = _ms_builds()
    m = re.fullmatch(r"Windows Server (2012 R2|2012|2016|2019|2022|2025)", n)
    if m:
        cyc = m.group(1).lower().replace(" r2", "-r2")
        return f"Windows Server:{cyc}", server[cyc]
    if n == "Windows Server 2022, 23H2 Edition":
        return "Windows Server:23h2-ac", server["23h2-ac"]
    m = re.fullmatch(r"Windows (10|11)(?: Version (\w+))? for (?:x64-based|32-bit|ARM64-based) Systems", n)
    if m:
        cyc = f"{m.group(1)}-{(m.group(2) or ('1507' if m.group(1) == '10' else '21H2')).lower()}"
        return (f"Windows:{cyc}", client[cyc]) if cyc in client else None
    return None


def _ms_val(x):
    return x.get("Value") if isinstance(x, dict) else x


def _ms_ids(x):
    return [str(i) for i in (x if isinstance(x, list) else [x] if x else [])]


def _msrc_xml(fileobj):
    """(doc, products, vulnerability) from a CVRF XML document, streamed."""
    import xml.etree.ElementTree as ET
    V, P, C = _CVRF_V, _CVRF_P, _CVRF_C
    doc, products = {"id": None, "date": None}, {}
    for _, el in ET.iterparse(fileobj, events=("end",)):
        tag = el.tag
        if tag == P + "FullProductName":
            products[el.get("ProductID")] = (el.text or "").strip()
        elif tag == C + "ID" and doc["id"] is None:
            doc["id"] = (el.text or "").strip()
        elif tag == C + "CurrentReleaseDate":
            doc["date"] = _ts((el.text or "").strip())
        elif tag == V + "Vulnerability":
            v = {"cve": (el.findtext(V + "CVE") or "").strip(),
                 "title": (el.findtext(V + "Title") or "").strip(),
                 "notes": {n.get("Title"): (n.text or "").strip() for n in el.iter(V + "Note")},
                 "threats": [(t.get("Type"), (t.findtext(V + "Description") or "").strip(),
                              [p.text for p in t.findall(V + "ProductID")]) for t in el.iter(V + "Threat")],
                 "scores": [(s.findtext(V + "BaseScore"), [p.text for p in s.findall(V + "ProductID")])
                            for s in el.iter(V + "ScoreSet")],
                 "rems": [(r.get("Type"), (r.findtext(V + "Description") or "").strip(),
                           r.findtext(V + "SubType") or "", (r.findtext(V + "FixedBuild") or "").strip(),
                           [p.text for p in r.findall(V + "ProductID")]) for r in el.iter(V + "Remediation")],
                 "dates": [d.text for r in el.iter(V + "Revision") for d in r if d.tag.endswith("}Date")]}
            yield doc, products, v
            el.clear()


_MS_THREAT = {0: "Impact", 1: "Exploit Status", 2: "Target Set", 3: "Severity"}
_MS_REM = {0: "Workaround", 1: "Mitigation", 2: "Vendor Fix", 3: "None Available", 4: "Will Not Fix"}


def _msrc_json(doc: dict):
    """Same, from the JSON form (Accept: application/json; enumerations are
    numbers there)."""
    tr = doc.get("DocumentTracking") or {}
    meta = {"id": _ms_val((tr.get("Identification") or {}).get("ID")),
            "date": _ts(tr.get("CurrentReleaseDate"))}
    products = {str(p.get("ProductID")): str(_ms_val(p.get("Value")) or "").strip()
                for p in (doc.get("ProductTree") or {}).get("FullProductName") or []}
    for v in doc.get("Vulnerability") or []:
        yield meta, products, {
            "cve": str(v.get("CVE") or "").strip(), "title": str(_ms_val(v.get("Title")) or "").strip(),
            "notes": {n.get("Title"): str(_ms_val(n.get("Value")) or "").strip() for n in v.get("Notes") or []},
            "threats": [(_MS_THREAT.get(t.get("Type"), t.get("Type")), str(_ms_val(t.get("Description")) or ""),
                         _ms_ids(t.get("ProductID"))) for t in v.get("Threats") or []],
            "scores": [(s.get("BaseScore"), _ms_ids(s.get("ProductID"))) for s in v.get("CVSSScoreSets") or []],
            "rems": [(_MS_REM.get(r.get("Type"), r.get("Type")), str(_ms_val(r.get("Description")) or "").strip(),
                      r.get("SubType") or "", str(r.get("FixedBuild") or "").strip(), _ms_ids(r.get("ProductID")))
                     for r in v.get("Remediations") or []],
            "dates": [r.get("Date") for r in v.get("RevisionHistory") or []]}


_MS_FIXED = re.compile(r"^\d+\.\d+\.(\d+)\.(\d+)$")
_MS_UNKNOWN_NAME = re.compile(r"^Windows (?:Server (?:2016|2019|202\d)|1[01] )")


def parse_msrc(items, stats: Optional[Counter] = None):
    """CVRF vulnerabilities -> records (Windows OS products only). `stats`
    counts Windows names / fixed builds that were not understood."""
    for doc, products, v in items:
        cve = v["cve"]
        if not cve.startswith("CVE-"):
            continue
        if (v["notes"].get("Customer Action Required") or "Yes").strip().lower() == "no":
            continue
        prod = {}
        for pid, name in products.items():
            pm = msrc_product(name)
            if pm:
                prod[pid] = pm
        best = {}                                     # eco -> (ubr, fixed, kb)
        for typ, kb, sub, fixed, pids in v["rems"]:
            if typ != "Vendor Fix" or "hotpatch" in sub.lower():
                continue
            for pid in pids:
                pm = prod.get(pid)
                if not pm:
                    if stats is not None and _MS_UNKNOWN_NAME.match(products.get(pid) or ""):
                        stats[products[pid]] += 1
                    continue
                eco, build = pm
                m = _MS_FIXED.match(fixed)
                if not m or int(m.group(1)) != build:
                    if stats is not None:
                        stats[f"{products.get(pid)}: FixedBuild {fixed or '-'}"] += 1
                    continue
                ubr = int(m.group(2))
                if eco not in best or ubr < best[eco][0]:
                    best[eco] = (ubr, fixed, kb)
        if not best:
            continue
        win = {pid for pid, pm in prod.items() if pm[0] in best}
        sev = "unknown"
        for typ, desc, pids in v["threats"]:
            if typ == "Severity" and win & set(pids):
                sev = _worse(_MS_SEV.get(desc.strip().lower(), "unknown"), sev)
        score = None
        for base, pids in v["scores"]:
            try:
                b = float(base)
            except (TypeError, ValueError):
                continue
            if win & set(pids) and (score is None or b > score):
                score = b
        dates = [d for d in (_ts(x) for x in v["dates"]) if d]
        rows = [{"cve": cve, "ecosystem": eco, "package": "windows",
                 "introduced": f"KB{kb}" if kb.isdigit() else "0", "fixed": fixed}
                for eco, (_, fixed, kb) in sorted(best.items())]
        yield {"id": f"MSRC-{cve}", "modified": max(dates) if dates else doc.get("date"),
               "severity": sev, "score": None, "specific": False,
               "summaries": {cve: v["title"][:400]} if v["title"] else {}, "rows": rows,
               "cve_scores": {cve: score} if score is not None else {}}


def _is_cvrf_xml(path: str) -> bool:
    with open(path, "rb") as f:
        return b"cvrfdoc" in f.read(4096)


def import_msrc(db, path: str, source: str = "msrc") -> dict:
    """One monthly CVRF document (XML or JSON)."""
    stats = Counter()
    if _is_cvrf_xml(path):
        with open(path, "rb") as f:
            res = _store(db, parse_msrc(_msrc_xml(f), stats), source)
    else:
        with open(path, "rb") as f:
            res = _store(db, parse_msrc(_msrc_json(json.load(f)), stats), source)
    return _with_stats(res, stats)


def msrc_months(n: int = MSRC_MONTHS, today: Optional[date] = None) -> list:
    """Document ids of the last n months, newest first ("2026-Nov", ...)."""
    d = today or date.today()
    y, m = d.year, d.month
    out = []
    for _ in range(n):
        out.append(f"{y}-{_MS_MONTHS[m - 1]}")
        m -= 1
        if not m:
            y, m = y - 1, 12
    return out


# ------------------------------------------------------- Debian kernel ABI table
ABI_SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "resources", "debian_kernel_abi.json")
# Archive folders listing every signed kernel image still in a suite; file
# names "linux-image-6.1.0-40-amd64_6.1.153-1_amd64.deb" give ABI -> version.
DEBIAN_ABI_URLS = ("https://deb.debian.org/debian/pool/main/l/linux-signed-amd64/",
                   "https://security.debian.org/debian-security/pool/updates/main/l/linux-signed-amd64/")
_ABI_FILE = re.compile(r"linux-image-(\d+\.\d+)\.0-(\d+)-amd64_(\d[^_\"'<>\s]*)_amd64\.deb")
_seed_cache = None


def _abi_seed() -> dict:
    global _seed_cache
    if _seed_cache is None:
        try:
            with open(ABI_SEED) as f:
                _seed_cache = json.load(f).get("debian") or {}
        except (OSError, ValueError):
            logger.warning("Debian ABI seed not readable: %s", ABI_SEED)
            _seed_cache = {}
    return _seed_cache


def abi_table(db) -> dict:
    """{release: {abi number: {versions}}} = seed + stored rows."""
    out = defaultdict(lambda: defaultdict(set))
    for rel, rows in _abi_seed().items():
        for abi, versions in rows.items():
            m = re.match(r"\d+\.\d+\.0-(\d+)$", abi)
            if m:
                out[rel][int(m.group(1))].update(versions)
    for rel, abi, ver in db.query(VulnKernelAbi.release, VulnKernelAbi.abi, VulnKernelAbi.version):
        m = re.match(r"\d+\.\d+\.0-(\d+)$", abi or "")
        if m and ver:
            out[rel][int(m.group(1))].add(ver)
    return {r: dict(v) for r, v in out.items()}


def add_abi_rows(db, rows, source: str) -> int:
    """rows: (release, "6.1.0-40", "6.1.153-1"); only new triples stored."""
    have = {(r, a, v) for r, a, v in db.query(VulnKernelAbi.release, VulnKernelAbi.abi,
                                               VulnKernelAbi.version)}
    seed = {(r, a, v) for r, t in _abi_seed().items() for a, vs in t.items() for v in vs}
    new = [dict(release=r, abi=a, version=v, source=source, updated_at=datetime.utcnow())
           for r, a, v in dict.fromkeys(rows) if (r, a, v) not in have and (r, a, v) not in seed]
    if new:
        db.bulk_insert_mappings(VulnKernelAbi, new)
        db.commit()
    return len(new)


def parse_abi_listing(text: str) -> list:
    """Archive folder listing -> [(release, abi, version)] (Debian 11 / 12)."""
    out = []
    for mm, num, ver in _ABI_FILE.findall(text or ""):
        rel = _DEB_SERIES.get(mm)
        if rel and "~" not in ver:          # "~bpo12+1" / "~deb11u1" = other suites
            out.append((rel, f"{mm}.0-{num}", ver))
    return out


def learn_abi_from_inventory(db) -> int:
    """Proxmox Debian VMs report uname -r AND uname -v: each pair is a fact."""
    rows = []
    q = db.query(VirtualMachine.guest_os, VirtualMachine.kernel, VirtualMachine.kernel_build) \
        .filter(VirtualMachine.kernel_build.like("%Debian %"))
    for g, k, b in q:
        old = _DEB_ABI_OLD.match((k or "").strip())
        bm = re.search(r"Debian (\d[^\s)]*)", b or "")
        if old and bm and _DEB_SERIES.get(old.group(1)) and bm.group(1).startswith(old.group(1) + "."):
            rows.append((_DEB_SERIES[old.group(1)], f"{old.group(1)}.0-{old.group(2)}", bm.group(1)))
    return add_abi_rows(db, rows, "inventory") if rows else 0


def sync_debian_abi(db) -> dict:
    """Refresh the ABI table from the Debian archive (online servers)."""
    found, errors = [], []
    for url in DEBIAN_ABI_URLS:
        try:
            r = _get(url, timeout=(8, 60))
            r.raise_for_status()
            found += parse_abi_listing(r.text)
        except Exception as exc:
            errors.append(urlparse(url).hostname + ": " + _err(exc))
    added = add_abi_rows(db, found, "archive") if found else 0
    if errors and not found:
        logger.info("Debian ABI table not refreshed (%s)", "; ".join(errors))
    return {"seen": len(set(found)), "added": added, **({"errors": errors} if errors else {})}


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
                   for k in db.query(VulnKev).all()],
           "abi": [[a.release, a.abi, a.version] for a in db.query(VulnKernelAbi).all()]}
    return gzip.compress(json.dumps(doc, separators=(",", ":")).encode())


def source_of(ecosystem: str) -> Optional[str]:
    """Stored ecosystem ("Ubuntu:24.04:LTS") -> source name ("Ubuntu")."""
    return next((n for n, m in SOURCES.items() if ecosystem.startswith(m["prefix"])), None)


def bundle_contents(doc: dict) -> dict:
    """{source: distinct CVEs} of a bundle (+ "CISA KEV": entries)."""
    per = defaultdict(set)
    for r in doc.get("records") or []:
        for row in r.get("rows") or []:
            src = source_of(row[1]) if len(row) > 1 else None
            if src:
                per[src].add(row[0])
    out = {k: len(v) for k, v in sorted(per.items())}
    if doc.get("kev"):
        out["CISA KEV"] = len(doc["kev"])
    return out


def import_bundle(db, doc: dict) -> dict:
    if doc.get("schema") != 1:
        raise ValueError(f"desteklenmeyen paket sürümü: {doc.get('schema')}")
    contents = bundle_contents(doc)
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
    if doc.get("abi"):
        res["abi"] = add_abi_rows(db, [tuple(x) for x in doc["abi"] if len(x) == 3], "bundle")
    res["contents"] = contents
    res["generated_at"] = doc.get("generated_at")
    return res


def import_file(db, path: str) -> dict:
    """Detect and import an uploaded file: OSV all.zip, bundle (.json.gz /
    .json), KEV JSON, one OSV record or a list of them, Oracle OVAL, Photon
    JSON, a Microsoft CVRF month (XML or JSON)."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:4] == b"PK\x03\x04":
        return {"type": "osv-zip", **import_osv_zip(db, path, "upload")}
    if head[:1] == b"<" and _is_cvrf_xml(path):
        return {"type": "msrc", **import_msrc(db, path, "upload")}
    if head[:3] == b"BZh" or head[:4] in (b"<?xm", b"<ova"):
        return {"type": "oracle-oval", **import_oracle_oval(db, path, "upload")}
    if head[:2] == b"\x1f\x8b" and tarfile.is_tarfile(path):
        kev = _kev_from_tar(path)
        if kev is not None:                 # cisagov/kev-data archive
            return {"type": "kev", **import_kev(db, kev)}
        return {"type": "osv-tar", **import_osv_tar(db, path, "upload")}
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
    if isinstance(doc, dict) and "Vulnerability" in doc and "ProductTree" in doc:
        stats = Counter()
        return {"type": "msrc", **_with_stats(_store(db, parse_msrc(_msrc_json(doc), stats), "upload"), stats)}
    if isinstance(doc, list) and doc and all(isinstance(r, dict) and "cve_id" in r and "pkg" in r
                                            for r in doc[:50]):
        ver = _photon_version(doc, os.path.basename(path))
        if not ver:
            raise ValueError("Photon sürümü anlaşılamadı (dosya adı cve_data_photon5.0.json gibi olmalı)")
        return {"type": "photon", **import_photon(db, doc, ver, "upload")}
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
def _get(url, stream=False, timeout=(8, 60), headers=None):
    """Single place for outbound HTTP (tests replace it). Extra company CAs
    and VULN_PROXY come from core/outbound."""
    from ..core import outbound
    h = dict(_UA)
    if "api.github.com" in url:
        h["Accept"] = "application/vnd.github.raw"
    elif "api.msrc.microsoft.com" in url:      # index = JSON, monthly documents = XML
        h["Accept"] = "application/json" if url.rstrip("/").endswith("/updates") else "application/xml"
    h.update(headers or {})
    return outbound.get(url, stream=stream, timeout=timeout, headers=h)


def _download(url, suffix, timeout=(8, 300)) -> str:
    """Stream url into a temp file; returns its path (caller deletes it)."""
    tmp = tempfile.NamedTemporaryFile(prefix="vuln-", suffix=suffix, delete=False)
    try:
        with _get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                tmp.write(chunk)
        tmp.close()
        return tmp.name
    except BaseException:
        tmp.close()
        os.unlink(tmp.name)
        raise


def _kev_from_tar(path):
    """The KEV JSON out of a cisagov/kev-data archive, or None."""
    with tarfile.open(path, "r:*") as tf:
        for m in tf:
            if m.isfile() and m.name.endswith("/" + KEV_FILE):
                f = tf.extractfile(m)
                return json.loads(f.read()) if f else None
    return None


def _kev_sources():
    from ..config import get_settings
    settings = get_settings()
    custom = [u.strip() for u in (getattr(settings, "vuln_kev_urls", "") or "").split(",") if u.strip()]
    if custom:
        return [(re.sub(r"^https?://([^/]+).*", r"\1", u),
                 u, "tar" if u.endswith((".tar.gz", ".tgz")) else "json") for u in custom]
    return list(KEV_SOURCES)


_ERR_TEXT = (  # requests' messages are very long; the Administration table shows these
    (r"Tunnel connection failed: (\d{3})", "Proxy engelledi ({})"),
    (r"(?:Name or service not known|nodename nor servname|getaddrinfo failed|"
     r"Temporary failure in name resolution)", "DNS çözülemedi"),
    (r"(?:timed out|Timeout)", "Zaman aşımı"),
    (r"Connection refused", "Bağlantı reddedildi"),
    (r"No route to host|Network is unreachable", "Ağ erişimi yok"),
    (r"certificate verify failed", "Sertifika doğrulanamadı (SSL denetimi)"),
    (r"(\d{3}) (?:Client|Server) Error", "HTTP {}"),
)


def _err(exc) -> str:
    """Short Turkish reason for a failed download."""
    txt = str(exc)
    for pat, out in _ERR_TEXT:
        m = re.search(pat, txt, re.I)
        if m:
            return out.format(*m.groups())
    return f"{type(exc).__name__}: {txt[:160]}"


def sync_kev(db) -> dict:
    """First reachable KEV source wins; every failure is listed."""
    errors = []
    for name, url, kind in _kev_sources():
        try:
            if kind == "tar":
                path = _download(url, ".tar.gz", timeout=(8, 120))
                try:
                    doc = _kev_from_tar(path)
                finally:
                    os.unlink(path)
                if doc is None:
                    raise ValueError("arşivde KEV dosyası yok")
            else:
                r = _get(url)
                r.raise_for_status()
                doc = r.json()
            if not isinstance(doc, dict) or "vulnerabilities" not in doc:
                raise ValueError("KEV biçimi değil")
            res = import_kev(db, doc)
            _meta_set(db, "vuln_kev_source", name)
            return {**res, "source": name, "failed": errors}
        except Exception as exc:
            errors.append(f"{name}: {_err(exc)}")
    raise RuntimeError("; ".join(errors) or "KEV kaynağı yok")


# ------------------------------------------------------------ source choice
def _vm_distros(db) -> dict:
    """{distro: [eligible VMs, all Linux VMs]} from the inventory."""
    out = defaultdict(lambda: [0, 0])
    for g, k, st, tpl in db.query(VirtualMachine.guest_os, VirtualMachine.kernel,
                                  VirtualMachine.support_status, VirtualMachine.is_template):
        if tpl:
            continue
        d = identify(g, k).distro
        if not d:
            continue
        out[d][1] += 1
        if (st or "unknown") in ELIGIBLE:
            out[d][0] += 1
    return out


# "auto" picks ONE source per distro: the small AlmaLinux data covers RHEL and
# Rocky too (same kernel NVRs, GitHub fallback); Red Hat / Rocky dumps are
# large and only added by hand.
_AUTO_SOURCE = {"ubuntu": "Ubuntu", "debian": "Debian", "almalinux": "AlmaLinux",
                "rocky-linux": "AlmaLinux", "rhel": "AlmaLinux", "sles": "SUSE",
                "opensuse": "openSUSE", "oracle-linux": "Oracle Linux", "photon": "Photon OS",
                "windows-server": "Windows", "windows": "Windows"}


def get_selection(db) -> dict:
    try:
        sel = json.loads(_setting(db, SELECTION_KEY) or "{}")
    except ValueError:
        sel = {}
    mode = sel.get("mode") if sel.get("mode") in ("auto", "manual") else "auto"
    manual = [e for e in sel.get("manual") or [] if e in SOURCES]
    return {"mode": mode, "manual": manual}


def set_selection(db, mode: str, manual) -> dict:
    if mode not in ("auto", "manual"):
        raise ValueError("mode auto veya manual olmalı")
    bad = [e for e in manual or [] if e not in SOURCES]
    if bad:
        raise ValueError(f"bilinmeyen kaynak: {', '.join(bad)}")
    _meta_set(db, SELECTION_KEY, json.dumps({"mode": mode, "manual": list(dict.fromkeys(manual or []))}))
    db.commit()
    return get_selection(db)


def auto_sources(db) -> list:
    need = {_AUTO_SOURCE[d] for d, (elig, _) in _vm_distros(db).items() if elig and d in _AUTO_SOURCE}
    return [e for e in CATALOGUE if e in need]


def selected_sources(db) -> list:
    sel = get_selection(db)
    if sel["mode"] == "manual":
        return [e for e in CATALOGUE if e in sel["manual"]]
    return auto_sources(db)


def sources_overview(db) -> dict:
    """Administration table: per source the VMs that need it, whether it is
    selected, and how much data is stored (a source with VMs but no data is
    the gap to fix - e.g. on an offline server after a bundle import)."""
    vm = _vm_distros(db)
    sel = get_selection(db)
    auto = set(auto_sources(db))
    chosen = set(selected_sources(db))
    stored = dict(db.query(VulnAdvisory.ecosystem, func.count(func.distinct(VulnAdvisory.cve)))
                  .group_by(VulnAdvisory.ecosystem).all())
    used = json.loads(_setting(db, "vuln_osv_sources") or "{}")
    rows = []
    for name in CATALOGUE:
        meta_ = SOURCES[name]
        elig = sum(vm[d][0] for d in meta_["distros"] if d in vm)
        total = sum(vm[d][1] for d in meta_["distros"] if d in vm)
        own = sum(vm[d][0] for d, src in _AUTO_SOURCE.items() if src == name and d in vm)
        cves = sum(n for e, n in stored.items() if e.startswith(meta_["prefix"]))
        rows.append({"name": name, "vms": elig, "vms_total": total, "auto_vms": own,
                     "auto": name in auto, "selected": name in chosen, "size": meta_["size"],
                     "cves": cves, "ecosystems": sorted(e for e in stored if e.startswith(meta_["prefix"])),
                     "source": used.get(name), "github": name in OSV_GITHUB})
    missing = [r["name"] for r in rows if r["auto"] and not r["cves"]]
    return {"mode": sel["mode"], "manual": sel["manual"], "rows": rows, "missing": missing}


def sync_osv(db, ecosystems=None) -> dict:
    """osv.dev dumps per SELECTED ecosystem; when the storage host is
    unreachable the rest are skipped at once (one short failure, not five) and
    the GitHub fallbacks (OSV_GITHUB) are tried for the ecosystems that got
    nothing."""
    ecosystems = list(selected_sources(db) if ecosystems is None else ecosystems)
    if not ecosystems:
        raise RuntimeError("seçili zafiyet kaynağı yok (envanterde eşleşecek VM yok "
                           "veya elle seçim boş)")
    done, sources = {}, {}
    for name in [e for e in ecosystems if e in VENDOR]:
        try:
            done[name] = sync_vendor(db, name)
            sources[name] = done[name]["source"]
        except Exception as exc:
            done[name] = {"error": _err(exc) if not isinstance(exc, RuntimeError) else str(exc)}
            logger.warning("%s download failed (%s)", name, done[name]["error"])
    ecosystems = [e for e in ecosystems if e in OSV_ECOSYSTEMS]
    storage_down = None
    for eco in ecosystems:
        if storage_down:
            done[eco] = {"error": f"osv.dev erişilemedi ({storage_down})"}
            continue
        path = None
        try:
            path = _download(OSV_URL.format(quote(eco)), ".zip")
            done[eco] = import_osv_zip(db, path, "osv")
            sources[eco] = "osv.dev"
        except Exception as exc:
            msg = _err(exc)
            done[eco] = {"error": msg}
            if not sources:                   # nothing came from the storage yet
                storage_down = msg
            logger.warning("OSV download failed for %s (%s)", eco, msg)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    for eco, url in OSV_GITHUB.items():
        if eco not in done or "error" not in done[eco] or eco not in ecosystems:
            continue
        path = None
        try:
            path = _download(url, ".tar.gz")
            done[eco] = {**import_osv_tar(db, path, "github"), "source": "github.com"}
            sources[eco] = "github.com"
        except Exception as exc:
            done[eco]["error"] += f"; GitHub: {_err(exc)}"
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    try:                                     # keep what other runs brought
        merged = json.loads(_setting(db, "vuln_osv_sources") or "{}")
    except ValueError:
        merged = {}
    merged.update(sources)
    if "Debian" in done:                     # Debian 12 VMware kernels need the ABI table
        try:
            done["Debian"]["abi"] = sync_debian_abi(db)
        except Exception as exc:
            logger.info("Debian ABI refresh failed: %s", exc)
    _meta_set(db, "vuln_osv_sources", json.dumps(merged))
    if not sources:
        raise RuntimeError("; ".join(f"{e}: {d['error']}" for e, d in done.items())[:600])
    return done


def _vendor_versions(db, name: str) -> list:
    """Releases to fetch: in auto mode those of eligible VMs, else all known."""
    conf = VENDOR[name]
    if get_selection(db)["mode"] == "manual":
        return list(conf["versions"])
    distro = SOURCES[name]["distros"][0]
    have = set()
    for g, k, st, tpl in db.query(VirtualMachine.guest_os, VirtualMachine.kernel,
                                  VirtualMachine.support_status, VirtualMachine.is_template):
        if tpl or (st or "unknown") not in ELIGIBLE:
            continue
        i = identify(g, k)
        if i.distro == distro and i.version:
            have.add(i.version)
    return [v for v in conf["versions"] if v in have] or list(conf["versions"])


def sync_vendor(db, name: str) -> dict:
    """Download one vendor feed (per release); first reachable URL wins."""
    conf = VENDOR[name]
    if conf["kind"] == "msrc":
        return sync_msrc(db)
    out = {"versions": {}, "records": 0, "rows": 0, "source": None}
    errors, missing = [], []
    for v in _vendor_versions(db, name):
        got = False
        for tpl in conf["urls"]:
            url = tpl.format(v=v)
            path = None
            try:
                path = _download(url, ".bz2" if conf["kind"] == "oval" else ".json")
                if conf["kind"] == "oval":
                    res = import_oracle_oval(db, path, "oracle", versions=[v])
                else:
                    with open(path, "rb") as f:
                        res = import_photon(db, json.loads(f.read()), v, "photon")
                out["versions"][v] = res.get("records", 0)
                out["records"] += res.get("records", 0)
                out["rows"] += res.get("rows", 0)
                out["source"] = re.sub(r"^https?://([^/]+).*", r"\1", url)
                got = True
                break
            except Exception as exc:
                errors.append(f"{v}: {_err(exc)}")
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
        if not got:
            missing.append(v)
    if missing and conf.get("all"):          # Oracle: one big file covers every release
        path = None
        try:
            path = _download(conf["all"], ".bz2", timeout=(8, 900))
            res = import_oracle_oval(db, path, "oracle", versions=missing)
            for v in missing:
                out["versions"][v] = "all"
            out["records"] += res.get("records", 0)
            out["rows"] += res.get("rows", 0)
            out["source"] = re.sub(r"^https?://([^/]+).*", r"\1", conf["all"])
            missing = []
        except Exception as exc:
            errors.append(f"all: {_err(exc)}")
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    if not out["versions"]:
        raise RuntimeError("; ".join(errors)[:300] or "indirilemedi")
    if errors:
        out["errors"] = errors[:6]
    return out


MSRC_DOCS_KEY = "vuln_msrc_docs"


def _msrc_stamp(mid: str, current: str) -> str:
    """Compact "2611" + 6 hex of the document's CurrentReleaseDate (app
    settings hold 512 characters; 24 months fit)."""
    y, m = mid.split("-")
    return f"{y[2:]}{_MS_MONTHS.index(m) + 1:02d}{hashlib.sha1(current.encode()).hexdigest()[:6]}"


def sync_msrc(db) -> dict:
    """The monthly MSRC documents of the data window (MSRC_MONTHS). The index
    (/updates) gives each document's CurrentReleaseDate: an unchanged document
    is not downloaded again (only the revised months come down each week).
    Months the index does not list yet are tried directly - MSRC sometimes
    lists the newest ones late; a 404 there just means "not published"."""
    conf = VENDOR["Windows"]
    seen = set((_setting(db, MSRC_DOCS_KEY) or "").split(","))
    index, errors = {}, []
    try:
        r = _get(conf["index"], timeout=(8, 60))
        r.raise_for_status()
        for u in (r.json() or {}).get("value") or []:
            index[str(u.get("ID"))] = str(u.get("CurrentReleaseDate") or "")
    except Exception as exc:
        errors.append(f"index: {_err(exc)}")
    host = re.sub(r"^https?://([^/]+).*", r"\1", conf["urls"][0])
    have_rows = db.query(VulnAdvisory.id).filter(VulnAdvisory.ecosystem.like("Windows%")).first() is not None
    out = {"versions": {}, "records": 0, "rows": 0, "source": host if index else None, "unchanged": 0}
    stamps, stats = [], Counter()
    for mid in msrc_months():
        st = _msrc_stamp(mid, index[mid]) if mid in index else None
        if st and have_rows and st in seen:
            out["unchanged"] += 1
            stamps.append(st)
            continue
        path = None
        try:
            path = _download(conf["urls"][0].format(v=mid), ".xml", timeout=(8, 600))
            res = import_msrc(db, path, "msrc")
            out["versions"][mid] = res.get("records", 0)
            out["records"] += res.get("records", 0)
            out["rows"] += res.get("rows", 0)
            out["source"] = host
            for u in res.get("unrecognized") or []:
                stats[u] += 1
            if st:
                stamps.append(st)
        except Exception as exc:
            if mid not in index and re.search(r"\b404\b", str(exc)):
                continue                      # not published yet
            errors.append(f"{mid}: {_err(exc)}")
            if not out["versions"] and not out["unchanged"]:
                break                         # host unreachable: one failure, not 24
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    _meta_set(db, MSRC_DOCS_KEY, ",".join(stamps))
    db.commit()
    if not out["versions"] and not out["unchanged"]:
        raise RuntimeError("; ".join(errors)[:300] or "indirilemedi")
    if out["unchanged"]:
        out["versions"]["unchanged"] = out["unchanged"]
    if stats:
        out["unrecognized"] = list(stats)[:8]
    if errors:
        out["errors"] = errors[:6]
    return out


def probe() -> list:
    """Reachability of every download source (Administration -> 'Test
    sources'): status / time / short reason, checked in parallel, only the
    first bytes are read."""
    from concurrent.futures import ThreadPoolExecutor
    targets = [("CISA KEV", n, u) for n, u, _ in _kev_sources()]
    targets += [("OSV", "osv.dev (" + e + ")", OSV_URL.format(quote(e))) for e in ("Ubuntu", "AlmaLinux")]
    targets += [("OSV", "github.com (" + e + ")", u) for e, u in OSV_GITHUB.items()]
    targets += [("Oracle Linux", "linux.oracle.com (OL9)", VENDOR["Oracle Linux"]["urls"][0].format(v="9")),
                ("Photon OS", "packages.broadcom.com (5.0)", VENDOR["Photon OS"]["urls"][0].format(v="5.0")),
                ("Windows", "api.msrc.microsoft.com", VENDOR["Windows"]["index"])]

    def one(t):
        group, name, url = t
        t0 = time.monotonic()
        try:
            with _get(url, stream=True, timeout=(6, 10)) as r:
                next(r.iter_content(1024), b"")
                ok = r.status_code < 400
                why = f"HTTP {r.status_code}"
        except Exception as exc:
            ok, why = False, _err(exc)
        res = {"group": group, "name": name, "url": url, "ok": ok, "detail": why,
               "ms": int((time.monotonic() - t0) * 1000)}
        if not ok and "Sertifika" in why:
            # name the CA that signed what this server is shown (TLS inspection)
            from ..core.outbound import peer_issuer
            res["issuer"] = peer_issuer(url)
        return res
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, targets))


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
        self.cve_score = {c: sc for c, sc in db.query(VulnCve.cve, VulnCve.score)
                          .filter(VulnCve.score.isnot(None)).all()}
        self._rows = {}
        self._series = {}
        self._abi = None

    @property
    def abi(self):
        if self._abi is None:
            self._abi = abi_table(self.db)
        return self._abi

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


# Debian kernel release strings (uname -r):
#  - Debian 13+: "6.12.107+deb13-amd64" = package 6.12.107-1; a re-upload of
#    the same upstream version is "+deb13.1" = 6.12.115-2 (seen in the archive).
#  - Debian 12 / 11: "6.1.0-40-amd64" = ABI 40 only -> VulnKernelAbi table.
_DEB_ABI_NEW = re.compile(r"^(\d+\.\d+\.\d+)\+deb(\d+)(?:\.(\d+))?-[a-z0-9][a-z0-9-]*$")
_DEB_ABI_OLD = re.compile(r"^(\d+\.\d+)\.0-(\d+)-[a-z0-9][a-z0-9-]*$")
_DEB_SERIES = {"6.1": "12", "5.10": "11", "4.19": "10"}       # ABI table releases


def _debian_source(vm, ident, data):
    """-> ((eco, pkg, running version or None, abi or None), None) | (None, reason).
    Exact version from uname -v (Proxmox agent) or a Debian 13 kernel name;
    Debian 12 VMware kernels give only the ABI -> resolved by the ABI table."""
    eco = f"Debian:{ident.version}"
    if eco not in data.ecos:
        return None, f"Debian {ident.version} zafiyet verisi yüklenmemiş"
    k = (vm.kernel or "").strip()
    km = re.match(r"(\d+\.\d+)\.", k)
    if not km:
        return None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    if k.endswith("-pve"):
        return None, ("Proxmox VE çekirdeği (-pve): Debian güvenlik verisi bu çekirdeğe uygulanamaz, "
                      "Proxmox çekirdekleri için yayımlanmış CVE verisi yok")
    mm = km.group(1)
    pkg = next((p for p in ("linux", f"linux-{mm}") if (eco, p) in data.pairs and
                (p.endswith(f"-{mm}") or data.series(eco, p) in (mm, None))), None)
    new = _DEB_ABI_NEW.match(k)
    if not pkg:
        if new and new.group(2) == ident.version:
            return None, (f"Backports çekirdeği: Debian {ident.version} güvenlik verisi "
                          f"yalnızca dağıtımın kendi çekirdeğini kapsar ({k})")
        return None, f"Çekirdek paketi eşleşmedi (linux {mm})"
    bm = re.search(r"Debian (\d[^\s)]*)", vm.kernel_build or "")
    if bm:
        return (eco, pkg, bm.group(1), None), None
    if new:
        return (eco, pkg, f"{new.group(1)}-{int(new.group(3) or 0) + 1}", None), None
    old = _DEB_ABI_OLD.match(k)
    if old:
        return (eco, pkg, None, (old.group(1), int(old.group(2)))), None
    return None, ("Debian paket sürümü bilinmiyor: çekirdek adı tanınmadı ve uname -v yok "
                  f"({vm.kernel})")


def _abi_span(table: dict, release: str, num: int):
    """(lower, upper, known versions) for ABI `num` of a Debian release:
    lower = newest version of a smaller ABI, upper = oldest of a bigger one
    (ABIs only grow), known = versions seen with exactly this ABI."""
    from functools import cmp_to_key
    rows = table.get(release) or {}
    key = cmp_to_key(dpkg_cmp)
    below = [v for n, vs in rows.items() if n < num for v in vs]
    above = [v for n, vs in rows.items() if n > num for v in vs]
    return (max(below, key=key) if below else None, min(above, key=key) if above else None,
            sorted(rows.get(num) or (), key=key))


def _abi_check(span, fixed: str) -> str:
    lower, upper, known = span
    if lower and dpkg_cmp(fixed, lower) <= 0:
        return "ok"
    if upper and dpkg_cmp(fixed, upper) >= 0:
        return "affected"
    if known:
        if dpkg_cmp(fixed, known[0]) <= 0:
            return "ok"
        if dpkg_cmp(fixed, known[-1]) > 0:
            return "affected"
    return "uncertain"


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


def _oracle_source(vm, ident, data):
    """Oracle Linux: UEK ("…el8uek") -> kernel-uek-<series>, RHCK -> kernel.
    RHCK falls back to AlmaLinux data (same RHEL NVRs) when Oracle's is missing."""
    eco = f"Oracle Linux:{ident.version}"
    running = _ARCH.sub("", (vm.kernel or "").strip())
    m = re.match(r"^(\d+)\.(\d+)\.\d+-\S+\.el\d+", running)
    if not m:
        return None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    uek = "uek" in running
    pkg = f"kernel-uek-{m.group(1)}.{m.group(2)}" if uek else "kernel"
    if (eco, pkg) in data.pairs:
        return (eco, pkg, running), None
    if not uek and (f"AlmaLinux:{ident.version}", "kernel") in data.pairs:
        return (f"AlmaLinux:{ident.version}", "kernel", running), None
    if eco not in data.ecos:
        return None, f"{ident.label} çekirdek zafiyet verisi yüklenmemiş"
    return None, (f"Çekirdek paketi eşleşmedi ({'UEK ' + m.group(1) + '.' + m.group(2) if uek else 'RHCK'}"
                  " için bu sürümde ELSA kaydı yok)")


def _photon_source(vm, ident, data):
    """Photon: "6.1.126-5.ph5" -> linux, "6.1.126-5.ph5-esx" -> linux-esx."""
    eco = f"Photon OS:{ident.version}"
    m = re.match(r"^(\d+\.\d+\.\d+-[\d.]+\.ph\d+)(?:-([a-z]+))?$", (vm.kernel or "").strip())
    if not m:
        return None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    pkg = f"linux-{m.group(2)}" if m.group(2) else "linux"
    if (eco, pkg) not in data.pairs:
        if eco not in data.ecos:
            return None, f"{ident.label} çekirdek zafiyet verisi yüklenmemiş"
        return None, f"Çekirdek paketi eşleşmedi ({pkg})"
    return (eco, pkg, m.group(1)), None


def _suse_source(vm, ident, data):
    """SLES / openSUSE: uname -r "5.14.21-150500.55.73-default" -> package
    kernel-default, version-release "5.14.21-150500.55.73"."""
    prefix = "SUSE" if ident.distro == "sles" else "openSUSE"
    eco = f"{prefix}:{ident.version}"
    m = re.match(r"^(\d+\.\d+\.\d+-[\d.]+)-([a-z0-9]+)$", (vm.kernel or "").strip())
    if not m:
        return None, f"Çekirdek dizesi tanınmadı: {vm.kernel}"
    pkg = f"kernel-{m.group(2)}"
    if (eco, pkg) not in data.pairs:
        if eco not in data.ecos:
            return None, f"{ident.label} çekirdek zafiyet verisi yüklenmemiş"
        return None, f"Çekirdek paketi eşleşmedi ({pkg})"
    return (eco, pkg, m.group(1)), None


def _suse_cmp(running: str, fixed: str) -> int:
    """rpm compare, but uname -r has no rebuild counter: running
    "…-150500.55.73" equals fixed "…-150500.55.73.1" (same kernel build)."""
    c = rpm_cmp(running, fixed)
    if c < 0 and fixed.startswith(running + ".") and re.fullmatch(r"\d+", fixed[len(running) + 1:]):
        return 0
    return c


_NT = re.compile(r"^\s*NT\s+(?:(\d+\.\d+)|[A-Za-z]+)\.(\d{4,5})(?:\.(\d+))?\s*$")


def nt_version(kernel: Optional[str]):
    """"NT 10.0.17763.6893" -> ("10.0", 17763, 6893); UBR None when the string
    has none ("NT 10.0.17763" - Proxmox agent, old VMware Tools). The broken
    "NT Windows.17763.6775" some Tools versions produced is read too."""
    m = _NT.match(kernel or "")
    if not m:
        return None
    build = int(m.group(2))
    return (m.group(1) or ("10.0" if build >= 10240 else "?"), build,
            int(m.group(3)) if m.group(3) else None)


def _platform_type(vm) -> str:
    try:
        return (vm.platform.type or "") if vm.platform is not None else ""
    except Exception:                       # detached object (tests, exports)
        return ""


def _windows_evaluate(vm, data):
    """Windows: the running build + UBR against each CVE's fixed build of the
    same product (MSRC). Cumulative updates: a higher UBR contains every
    earlier fix of that build."""
    ident = identify(vm.guest_os, vm.kernel)
    if ident.distro not in ("windows-server", "windows") or not ident.version:
        return "unknown", f"Windows sürümü anlaşılamadı ({vm.guest_os or vm.kernel or '?'})", {}
    nt = nt_version(vm.kernel)
    if not nt:
        return "unknown", (_no_kernel_reason(vm) if not vm.kernel else
                           f"Windows yapı numarası okunamadı ({vm.kernel})"), {}
    mm, build, ubr = nt
    if ubr is None:
        if _platform_type(vm) == "proxmox":
            return "unknown", (f"Windows güncelleme numarası (UBR) bilinmiyor: {vm.kernel} - "
                               f"QEMU agent get-osinfo UBR vermez; envanter onu agent ile "
                               f"\"cmd /c ver\" çalıştırarak okur, bunun için API token'ına "
                               f"VM.GuestAgent.Unrestricted (PVE 9) / VM.Monitor (PVE 8) izni gerekir"), {}
        return "unknown", (f"Windows güncelleme numarası (UBR) bilinmiyor: {vm.kernel} - "
                           f"VMware Tools 11.2+ yapıyı \"Build {build}.xxxx\" olarak bildirir, "
                           f"Tools güncellenmeli"), {}
    eco = f"{'Windows Server' if ident.distro == 'windows-server' else 'Windows'}:{ident.version}"
    if (eco, "windows") not in data.pairs:
        return "unknown", f"{ident.label} için Microsoft (MSRC) zafiyet verisi yüklenmemiş", {}
    shown = f"{mm}.{build}.{ubr}"
    findings, oldest = {}, None
    for cve, (fixed, intro, osv_id, sev) in data.rows(eco, "windows").items():
        m = _MS_FIXED.match(fixed or "")
        if not m or int(m.group(1)) != build:
            continue
        fu = int(m.group(2))
        oldest = fu if oldest is None else min(oldest, fu)
        if ubr >= fu:
            continue
        kb = intro if (intro or "").startswith("KB") else None
        findings[cve] = {"osv_id": osv_id, "package": kb or "windows", "fixed": fixed,
                         "status": "affected", "fix_available": True,
                         "severity": data.cve_sev.get(cve) or sev or "unknown", "kev": cve in data.kev,
                         "reason": f"{ident.label} · yapı {shown} · düzeltme {fixed}"
                                   f"{' (' + kb + ')' if kb else ''} -> etkileniyor"}
    if oldest is None:
        return "unknown", f"Yapı {build}, {ident.label} verisindeki yapılarla eşleşmedi", {}
    head = f"{ident.label} · Windows yapı {shown}"
    if ubr < oldest:
        head += (f" · uyarı: güncelleme {MSRC_MONTHS} aylık veri penceresinden eski, "
                 f"gerçek açık sayısı daha fazla olabilir")
    return "evaluated", head, findings


def _no_kernel_reason(vm) -> str:
    """Why the platform sent no kernel - with what fixes it."""
    tv = getattr(vm, "tools_version", None)
    running = (vm.tools_status or "").lower() in ("guesttoolsrunning", "running")
    if tv == "unmanaged":
        return ("Çekirdek sürümü bilinmiyor: işletim sisteminin kendi VMware Tools'u (unmanaged) "
                "ayrıntılı misafir verisi göndermiyor - open-vm-tools 11.2+ gerekir")
    m = re.match(r"(\d+)\.(\d+)", tv or "")
    if m and (int(m.group(1)), int(m.group(2))) < (11, 2):
        return (f"Çekirdek sürümü bilinmiyor: VMware Tools {tv} çekirdek bilgisini göndermez - "
                f"Tools 11.2 veya üstüne güncellenmeli")
    if not running:
        return "Çekirdek sürümü bilinmiyor: VMware Tools / QEMU agent çalışmıyor"
    return "Çekirdek sürümü bilinmiyor (agent / Tools bildirmiyor)"


def evaluate(vm, data):
    """-> (vm_status, vm_reason, findings{cve: dict}).
    vm_status: evaluated | skipped (not supported) | unknown (cannot tell)."""
    if vm.is_template:
        return "skipped", "Şablon - değerlendirilmez", {}
    if (vm.support_status or "unknown") not in ELIGIBLE:
        return "skipped", ("İşletim sistemi desteği bitmiş (EOL) - değerlendirilmedi"
                           if vm.support_status == "eol" else
                           "İşletim sistemi desteği bilinmiyor - değerlendirilmedi"), {}
    if "windows" in (vm.guest_os or "").lower() or (vm.kernel or "").startswith("NT "):
        return _windows_evaluate(vm, data)
    if not vm.kernel:
        return "unknown", _no_kernel_reason(vm), {}
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
    elif extended and ident.distro not in ("debian", "sles"):   # Debian LTS / SUSE LTSS share the eco
        return "unknown", f"Uzatılmış destek: {ident.label} için ELS/ESU çekirdek verisi yok", {}
    elif ident.distro in ("debian", "rhel", "almalinux", "rocky-linux", "sles", "opensuse",
                          "oracle-linux", "photon") and ident.version:
        if "_ciq" in (vm.kernel or ""):
            return "unknown", ("CIQ LTS çekirdeği: CIQ düzeltmeleri kendi sürüm numarasıyla geri "
                               "taşıyor; Rocky / RHEL verisiyle karşılaştırmak yanlış sonuç verir"), {}
        fn = {"debian": _debian_source, "sles": _suse_source, "opensuse": _suse_source,
              "oracle-linux": _oracle_source, "photon": _photon_source}.get(ident.distro, _rh_source)
        tgt, why = fn(vm, ident, data)
        if tgt is None:
            return "unknown", why, {}
        eco, pkg, running = tgt[:3]
        abi = tgt[3] if len(tgt) > 3 else None
        src, shown = [(eco, pkg)], running
        cmp_ = {"debian": dpkg_cmp, "sles": _suse_cmp, "opensuse": _suse_cmp}.get(ident.distro, rpm_cmp)
        other = eco.split(":")[0]
        if abi:                               # Debian 12 on VMware: ABI -> versions
            span = _abi_span(data.abi, ident.version, abi[1])
            if not any(span):
                return "unknown", (f"Debian {ident.version} çekirdek ABI tablosu yok: "
                                   f"{abi[0]}.0-{abi[1]}"), {}
            known = span[2]
            shown = (f"{abi[0]}.0-{abi[1]} (= {known[0]})" if len(known) == 1 else
                     f"{abi[0]}.0-{abi[1]} ({' / '.join(known)})" if known else
                     f"{abi[0]}.0-{abi[1]} (ABI tabloda yok)")
        head = f"{ident.label} · {pkg} {shown}"
        if (ident.distro in _RH_NAME and other != _RH_NAME[ident.distro]) or \
                (ident.distro == "oracle-linux" and other != "Oracle Linux"):
            head += f" ({other} verisiyle - aynı çekirdek sürümleri)"
        if abi:
            head += " · paket sürümü ABI tablosundan"

            def check(eco, fixed):
                return _abi_check(span, fixed)
            cmp_running = None
        else:
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
                if st == "uncertain" and ident.distro == "debian":
                    why = f"düzeltme {fixed} · bu ABI'nin paket sürümü kesin bilinmiyor -> belirsiz"
            findings[cve] = {"osv_id": osv_id, "package": pkg, "fixed": fixed, "status": st,
                             "fix_available": fixed is not None,
                             "severity": data.cve_sev.get(cve) or sev or "unknown",
                             "kev": cve in data.kev,
                             "reason": f"{ident.label}{' Pro' if ':Pro:' in eco else ''} · "
                                       f"{pkg} {shown} · {why}"}
    return "evaluated", head, {c: f for c, f in findings.items() if f}


_FIELDS = ("osv_id", "package", "fixed", "status", "fix_available", "kev", "severity", "reason")


def _top_key(data, cve, f):
    """Most urgent finding first: KEV, fix available, severity, CVSS, newest."""
    return (f["kev"], f["status"] == "affected" and f["fix_available"],
            SEV_RANK.get(f["severity"], 0), data.cve_score.get(cve) or 0, cve)


def _vm_summary(data, status, found) -> dict:
    if status != "evaluated":
        return dict(vuln_total=None, vuln_open=None, vuln_kev=None, vuln_max_sev=None,
                    vuln_top=None, vuln_top_sev=None, vuln_crit=None, vuln_high=None)
    fixable = [f for f in found.values() if f["status"] == "affected" and f["fix_available"]]
    top = max(found.items(), key=lambda kv: _top_key(data, *kv)) if found else None
    return dict(
        vuln_total=len(found), vuln_open=len(fixable),
        vuln_kev=sum(1 for f in found.values() if f["kev"]),
        vuln_max_sev=(max((f["severity"] for f in found.values()), key=lambda x: SEV_RANK.get(x, 0))
                      if found else None),
        vuln_top=top[0] if top else None, vuln_top_sev=top[1]["severity"] if top else None,
        vuln_crit=sum(1 for f in fixable if f["severity"] == "critical"),
        vuln_high=sum(1 for f in fixable if f["severity"] == "high"))


# Bump when the matching rules change, so every VM is evaluated again once.
MATCH_VERSION = 6


def _data_signature(db) -> str:
    adv = db.query(func.count(VulnAdvisory.id), func.max(VulnAdvisory.id)).one()
    cve = db.query(func.count(VulnCve.cve), func.max(VulnCve.modified)).one()
    kev = db.query(func.count(VulnKev.cve)).scalar()
    abi = db.query(func.count(VulnKernelAbi.id), func.max(VulnKernelAbi.id)).one()
    return (f"{MATCH_VERSION}|{adv[0]}|{adv[1]}|{cve[0]}|{cve[1]}|{kev}|{_setting(db, 'vuln_kev_version')}"
            f"|{abi[0]}|{abi[1]}")


def _vm_signature(vm, base: str) -> str:
    import hashlib
    key = (bool(vm.is_template), vm.support_status, vm.guest_os, vm.kernel, vm.kernel_build,
           getattr(vm, "tools_version", None), vm.platform_id)
    return hashlib.sha1((repr(key) + base).encode()).hexdigest()


def recompute(db, platform_id: Optional[int] = None, vm_ids=None) -> dict:
    """Evaluate VMs, open / update / close findings, refresh VM summaries.

    Scale (an old Ubuntu kernel has thousands of CVEs, so a few hundred VMs
    mean ~1M findings): VMs sharing OS + kernel are evaluated once, existing
    findings are read as plain tuples in small VM batches, and only rows that
    really change are written (bulk insert / update) - a sync with no kernel
    change writes nothing."""
    try:                                     # Proxmox Debian VMs teach the ABI table
        learn_abi_from_inventory(db)
    except Exception as exc:                 # never block the evaluation
        logger.warning("Debian ABI learning failed: %s", exc)
        db.rollback()
    data = _Data(db)
    q = db.query(VirtualMachine)
    if platform_id is not None:
        q = q.filter(VirtualMachine.platform_id == platform_id)
    if vm_ids is not None:
        q = q.filter(VirtualMachine.id.in_(list(vm_ids)))
    vms = q.order_by(VirtualMachine.id).all()
    now = datetime.utcnow()
    memo = {}
    tot = {"evaluated": 0, "skipped": 0, "unknown": 0, "new": 0, "closed": 0, "open": 0,
           "unchanged": 0}
    # A VM whose inputs (OS, kernel, support status) and the data are the same
    # as at its last evaluation is skipped without reading its findings - the
    # recompute after every platform sync then costs next to nothing.
    base = _data_signature(db)
    todo = []
    for vm in vms:
        sig = _vm_signature(vm, base)
        if vm.vuln_sig == sig and vm.vuln_status:
            tot[vm.vuln_status] = tot.get(vm.vuln_status, 0) + 1
            tot["unchanged"] += 1
            tot["open"] += vm.vuln_total or 0
        else:
            todo.append((vm, sig))
    vms = [v for v, _ in todo]
    sigs = {v.id: sg for v, sg in todo}
    changed = False
    cols = (VmVuln.id, VmVuln.vm_id, VmVuln.cve, VmVuln.closed_at) + \
        tuple(getattr(VmVuln, f) for f in _FIELDS)
    for i in range(0, len(vms), 25):
        chunk = vms[i:i + 25]
        existing = defaultdict(dict)
        for r in db.query(*cols).filter(VmVuln.vm_id.in_([v.id for v in chunk])):
            existing[r[1]][r[2]] = r
        inserts, updates = [], []
        for vm in chunk:
            was_evaluated = vm.vuln_status == "evaluated"
            key = (bool(vm.is_template), vm.support_status, vm.guest_os, vm.kernel, vm.kernel_build,
                   getattr(vm, "tools_version", None), vm.platform_id)
            if key not in memo:
                st, why, fnd = evaluate(vm, data)
                memo[key] = (st, why, fnd, _vm_summary(data, st, fnd))
            status, reason, found, summ = memo[key]
            tot[status] += 1
            mine = existing.get(vm.id, {})
            new_cves, closed_cves = [], []
            for cve, f in found.items():
                vals = {k: f[k] for k in _FIELDS}
                r = mine.get(cve)
                if r is None:
                    inserts.append(dict(vm_id=vm.id, cve=cve, first_seen=now, last_seen=now, **vals))
                    new_cves.append(cve)
                elif r[3] is not None:                      # closed earlier -> reopened
                    updates.append(dict(id=r[0], closed_at=None, closed_reason=None,
                                        first_seen=now, last_seen=now, **vals))
                    new_cves.append(cve)
                elif tuple(r[4:]) != tuple(vals[k] for k in _FIELDS):
                    updates.append(dict(id=r[0], last_seen=now, **vals))
            for cve, r in mine.items():
                if r[3] is None and cve not in found:
                    updates.append(dict(id=r[0], closed_at=now, last_seen=now,
                                        closed_reason="patched" if status == "evaluated" else "not_evaluated"))
                    if status == "evaluated":
                        closed_cves.append(cve)
            vm.vuln_status, vm.vuln_reason = status, (reason or None)
            vm.vuln_sig = sigs[vm.id]
            for k, v in summ.items():
                setattr(vm, k, v)
            tot["open"] += len(found)
            tot["new"] += len(new_cves)
            tot["closed"] += len(closed_cves)
            # Change History: only for a VM that had been evaluated before, so
            # the first data import does not write thousands of rows
            if was_evaluated and new_cves:
                db.add(ChangeHistory(
                    entity_type="vm", entity_name=vm.name, platform_id=vm.platform_id,
                    change_type="updated", field="vuln", category="security",
                    old_value=None, vm_external_id=vm.external_id, cluster=vm.cluster,
                    new_value=_cve_list(new_cves, [c for c in new_cves if found[c]["kev"]], "yeni")))
            if was_evaluated and closed_cves:
                db.add(ChangeHistory(
                    entity_type="vm", entity_name=vm.name, platform_id=vm.platform_id,
                    change_type="updated", field="vuln", category="security",
                    old_value=_cve_list(closed_cves, [], "kapandı"), new_value=None,
                    vm_external_id=vm.external_id, cluster=vm.cluster))
        if inserts:
            db.bulk_insert_mappings(VmVuln, inserts)
        if updates:
            db.bulk_update_mappings(VmVuln, updates)
        changed = changed or bool(inserts or updates)
        db.flush()
    if platform_id is None and vm_ids is None:          # findings of deleted VMs
        changed = bool(db.query(VmVuln).filter(~VmVuln.vm_id.in_(db.query(VirtualMachine.id)))
                       .delete(synchronize_session=False)) or changed
    if changed or not db.query(VulnCveStat.cve).first():
        refresh_stats(db)
    db.commit()
    if tot["new"]:
        try:
            from ..core import events
            events.publish({"kind": "vuln", "new": tot["new"], "closed": tot["closed"],
                            "ts": now.isoformat() + "Z"})
        except Exception:
            pass
    return tot


def refresh_stats(db) -> None:
    """Rebuild vuln_cve_stat from the open findings (one INSERT ... SELECT)."""
    from sqlalchemy import case, insert, select
    agg = (select(VmVuln.cve, func.count(VmVuln.id),
                  func.sum(case((and_(VmVuln.status == "affected", VmVuln.fix_available == True), 1),  # noqa: E712
                                else_=0)),
                  func.sum(case((VmVuln.status == "uncertain", 1), else_=0)),
                  func.sum(case((VmVuln.fix_available == False, 1), else_=0)),  # noqa: E712
                  func.max(_sev_rank_expr()),
                  func.max(case((VmVuln.kev == True, 1), else_=0)) == 1,  # noqa: E712
                  func.max(VmVuln.first_seen))
           .where(VmVuln.closed_at.is_(None)).group_by(VmVuln.cve))
    db.query(VulnCveStat).delete(synchronize_session=False)
    db.execute(insert(VulnCveStat).from_select(
        ["cve", "vms", "fixable", "uncertain", "nofix", "rank", "kev", "first_seen"], agg))


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
            "last_error": _setting(db, "vuln_last_error"), "job": dict(JOB),
            "kev_source": _setting(db, "vuln_kev_source"),
            "osv_sources": json.loads(_setting(db, "vuln_osv_sources") or "{}")}


# ==================================================================== views
def _sev_key(s):
    return -SEV_RANK.get(s or "unknown", 0)


_RANK_SEV = {v: k for k, v in SEV_RANK.items() if k not in ("none",)}


def _sev_rank_expr():
    from sqlalchemy import case
    return case(*[(VmVuln.severity == k, v) for k, v in SEV_RANK.items() if v], else_=0)


def _kev_info(db, cves) -> dict:
    return {k.cve: k for k in db.query(VulnKev).filter(VulnKev.cve.in_(list(cves)))} if cves else {}


def vm_findings(db, vm_id: int, limit: int = 50) -> list:
    """The most urgent open findings of one VM (VM detail panel): KEV, fix
    available, severity, CVSS. The full list is the Vulnerabilities page
    filtered to the VM (an old kernel can have thousands)."""
    from sqlalchemy import case
    fixable = case((and_(VmVuln.status == "affected", VmVuln.fix_available == True), 1),  # noqa: E712
                   else_=0)
    rows = (db.query(VmVuln, VulnCve.score, VulnCve.summary)
            .outerjoin(VulnCve, VulnCve.cve == VmVuln.cve)
            .filter(VmVuln.vm_id == vm_id, VmVuln.closed_at.is_(None))
            .order_by(VmVuln.kev.desc(), fixable.desc(), _sev_rank_expr().desc(),
                      func.coalesce(VulnCve.score, 0).desc(), VmVuln.cve.desc())
            .limit(limit).all())
    kev = _kev_info(db, [r.cve for r, *_ in rows])
    return [{"cve": r.cve, "status": r.status, "fix_available": bool(r.fix_available),
             "fixed": r.fixed, "package": r.package, "severity": r.severity or "unknown",
             "score": score, "summary": summ, "kev": bool(r.kev),
             "kev_due": kev[r.cve].due_date.isoformat() if r.cve in kev and kev[r.cve].due_date else None,
             "ransomware": (kev[r.cve].ransomware == "Known") if r.cve in kev else False,
             "reason": r.reason, "osv_id": r.osv_id,
             "first_seen": r.first_seen.isoformat(timespec="seconds") + "Z" if r.first_seen else None}
            for r, score, summ in rows]


def cve_page(db, q: str = "", kev_only: bool = False, severity: str = "", fix: str = "",
             vm_id: Optional[int] = None, page: int = 1, per_page: Optional[int] = 100):
    """CVEs with at least one open finding, one aggregate query in SQL
    (counts, worst severity, KEV) ordered KEV > severity > CVSS > fixable VMs,
    paged. -> (items, total)."""
    from sqlalchemy import case, select
    if not vm_id:
        return _cve_page_stats(db, q, kev_only, severity, fix, page, per_page)
    fixable = func.sum(case((and_(VmVuln.status == "affected", VmVuln.fix_available == True), 1),  # noqa: E712
                            else_=0))
    nofix = func.sum(case((VmVuln.fix_available == False, 1), else_=0))  # noqa: E712
    rank = func.max(_sev_rank_expr())
    kev = func.max(case((VmVuln.kev == True, 1), else_=0))  # noqa: E712
    agg = (select(VmVuln.cve.label("cve"), func.count(VmVuln.id).label("vms"),
                  fixable.label("fixable"),
                  func.sum(case((VmVuln.status == "uncertain", 1), else_=0)).label("uncertain"),
                  nofix.label("nofix"), rank.label("rank"), kev.label("kev"),
                  func.max(VmVuln.first_seen).label("first"))
           .where(VmVuln.closed_at.is_(None)).group_by(VmVuln.cve))
    if q:
        agg = agg.where(VmVuln.cve.ilike(f"%{q.strip()}%"))
    if vm_id:
        agg = agg.where(VmVuln.vm_id == vm_id)
    if kev_only:
        agg = agg.where(VmVuln.kev == True)  # noqa: E712
    if severity in SEV_RANK:
        agg = agg.having(rank == SEV_RANK[severity])
    if fix == "fixable":
        agg = agg.having(fixable > 0)
    elif fix == "nofix":
        agg = agg.having(nofix > 0)
    sub = agg.subquery()
    total = db.execute(select(func.count()).select_from(sub)).scalar() or 0
    stmt = (select(sub, VulnCve.score, VulnCve.summary)
            .outerjoin(VulnCve, VulnCve.cve == sub.c.cve)
            .order_by(sub.c.kev.desc(), sub.c.rank.desc(), func.coalesce(VulnCve.score, 0).desc(),
                      sub.c.fixable.desc(), sub.c.cve.desc()))
    if per_page:
        stmt = stmt.limit(per_page).offset((max(page, 1) - 1) * per_page)
    return _page_items(db, db.execute(stmt).all()), total


def _page_items(db, rows) -> list:
    kv = _kev_info(db, [r.cve for r in rows])
    items = []
    for r in rows:
        k = kv.get(r.cve)
        items.append({"cve": r.cve, "vms": r.vms, "fixable": int(r.fixable or 0),
                      "uncertain": int(r.uncertain or 0), "nofix": int(r.nofix or 0),
                      "severity": _RANK_SEV.get(r.rank or 0, "unknown"), "score": r.score,
                      "summary": r.summary, "kev": bool(r.kev),
                      "kev_added": k.date_added.isoformat() if k and k.date_added else None,
                      "kev_due": k.due_date.isoformat() if k and k.due_date else None,
                      "kev_name": k.name if k else None,
                      "ransomware": bool(k and k.ransomware == "Known"),
                      "first_seen": r.first.isoformat(timespec="seconds") + "Z" if r.first else None})
    return items


def _cve_page_stats(db, q, kev_only, severity, fix, page, per_page):
    """Same answer as the aggregate, read from vuln_cve_stat (milliseconds)."""
    from sqlalchemy import select
    S = VulnCveStat
    stmt = select(S.cve, S.vms, S.fixable, S.uncertain, S.nofix, S.rank, S.kev,
                  S.first_seen.label("first"), VulnCve.score, VulnCve.summary) \
        .outerjoin(VulnCve, VulnCve.cve == S.cve)
    conds = []
    if q:
        conds.append(S.cve.ilike(f"%{q.strip()}%"))
    if kev_only:
        conds.append(S.kev == True)  # noqa: E712
    if severity in SEV_RANK:
        conds.append(S.rank == SEV_RANK[severity])
    if fix == "fixable":
        conds.append(S.fixable > 0)
    elif fix == "nofix":
        conds.append(S.nofix > 0)
    if conds:
        stmt = stmt.where(*conds)
    total = db.execute(select(func.count()).select_from(S).where(*conds)).scalar() or 0
    stmt = stmt.order_by(S.kev.desc(), S.rank.desc(), func.coalesce(VulnCve.score, 0).desc(),
                         S.fixable.desc(), S.cve.desc())
    if per_page:
        stmt = stmt.limit(per_page).offset((max(page, 1) - 1) * per_page)
    return _page_items(db, db.execute(stmt).all()), total


def cve_list(db, q: str = "", kev_only: bool = False, severity: str = "",
             fix: str = "", vm_id: Optional[int] = None) -> list:
    """Every CVE with an open finding (exports); the page uses cve_page."""
    return cve_page(db, q=q, kev_only=kev_only, severity=severity, fix=fix, vm_id=vm_id,
                    per_page=None)[0]


# What to do about each kind of "not verifiable" (Administration table).
_REASON_HINTS = (
    (r"verisi yüklenmemiş", "Bu sunucuda o dağıtımın verisi yok. İnternetli sunucuda \"İndirilecek "
     "dağıtımlar\"dan seçip indirin; internetsiz sunucu için paketi o dağıtım seçiliyken hazırlayıp yükleyin."),
    (r"UBR", "Windows'un güncelleme numarası gelmiyor. VMware: Tools 11.2+ kurulmalı. Proxmox: API "
     "token'ına agent exec izni (PVE 9: VM.GuestAgent.Unrestricted, PVE 8: VM.Monitor) verilirse "
     "envanter \"cmd /c ver\" ile okur."),
    (r"Çekirdek sürümü bilinmiyor|yapı numarası okunamadı",
     "Platform çekirdek sürümünü göndermiyor. VMware: VMware Tools / open-vm-tools 11.2 veya üstü "
     "gerekli (10.x ve 11.0-11.1 göndermez). Proxmox: QEMU guest agent açık ve çalışır olmalı."),
    (r"Proxmox VE çekirdeği", "Proxmox VE çekirdeği için yayımlanmış CVE verisi yok; bu VM'ler "
     "değerlendirilemez (Proxmox'un kendi güncellemeleriyle takip edilir)."),
    (r"Backports", "Backports çekirdekleri dağıtımın güvenlik verisinde yok; dağıtımın kendi çekirdeğine dönmek ya da elle takip gerekir."),
    (r"CIQ", "CIQ LTS çekirdeklerinin herkese açık CVE verisi yok; CIQ portalından takip edilir."),
    (r"ABI tablosu", "Debian ABI tablosunda bu çekirdek yok: internetli sunucuda Debian seçiliyken \"Şimdi indir\" "
     "tabloyu Debian arşivinden günceller; paket de tabloyu taşır."),
    (r"Çekirdek paketi eşleşmedi", "Yüklü veri bu çekirdek akışını içermiyor (ör. UEK sürümü, bulut / "
     "özel çekirdek). Kaynağın güncel olduğunu kontrol edin."),
    (r"kapsam dışı", "Bu çekirdek türü için veri tutulmuyor (bulut / OEM çekirdekleri)."),
    (r"sürümü anlaşılamadı|dizesi tanınmadı", "İşletim sistemi adı veya çekirdek dizesi tanınmadı; örneği bize iletin."),
)


def _reason_key(reason: str) -> str:
    r = (reason or "").strip()
    i = r.find(": ")
    return r[:i] if i > 8 else r


def unknown_overview(db, examples: int = 4) -> list:
    """Not-verifiable VMs grouped by reason, biggest group first, each with
    examples and what to do."""
    groups = {}
    for name, reason in db.query(VirtualMachine.name, VirtualMachine.vuln_reason) \
            .filter(VirtualMachine.vuln_status == "unknown").order_by(VirtualMachine.name):
        key = _reason_key(reason) or "?"
        g = groups.get(key)
        if g is None:
            hint = next((h for pat, h in _REASON_HINTS if re.search(pat, reason or "")), "")
            g = groups[key] = {"reason": key, "count": 0, "examples": [], "hint": hint, "detail": reason}
        g["count"] += 1
        if len(g["examples"]) < examples:
            g["examples"].append(name)
    return sorted(groups.values(), key=lambda g: (-g["count"], g["reason"]))


def summary(db) -> dict:
    """Counts for the dashboard and the Vulnerabilities page header."""
    vm_counts = dict(db.query(func.coalesce(VirtualMachine.vuln_status, "unknown"),
                              func.count(VirtualMachine.id))
                     .group_by(func.coalesce(VirtualMachine.vuln_status, "unknown")).all())
    return {
        "vms_evaluated": vm_counts.get("evaluated", 0),
        "vms_skipped": vm_counts.get("skipped", 0),
        "vms_unknown": vm_counts.get("unknown", 0),
        "vms_open": db.query(func.count(VirtualMachine.id)).filter(VirtualMachine.vuln_open > 0).scalar() or 0,
        "vms_kev": db.query(func.count(VirtualMachine.id)).filter(VirtualMachine.vuln_kev > 0).scalar() or 0,
        "cves_open": db.query(func.count(VulnCveStat.cve)).scalar() or 0,
        "cves_kev": db.query(func.count(VulnCveStat.cve)).filter(VulnCveStat.kev == True).scalar() or 0,  # noqa: E712
        "has_data": bool(db.query(VulnAdvisory.id).first()),
    }
