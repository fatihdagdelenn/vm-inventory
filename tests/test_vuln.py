"""
Kernel vulnerability matching suite (phase 160).

Fixtures in tests/fixtures/vuln are REAL OSV / KEV records trimmed to a few
packages (Ubuntu UBUNTU-CVE-2026-43040 + UBUNTU-CVE-2024-1086, AlmaLinux
ALSA-2024:2394, CISA KEV 2026.10.30); Debian / Red Hat / Rocky records are
built inline in the verified formats.

Covers: version comparators, parsing / kernel filter, newest-wins storage,
zip / bundle / KEV imports, Ubuntu GA / HWE / lowlatency / ABI rule / uname -v
upload number / Pro ecosystem, Debian with and without uname -v, RHEL family
incl. the AlmaLinux fallback, no-fix = affected, EOL skip, open / close /
reopen of findings, change history, VM summary columns, search, export.

Acceptance: CVE-2026-43040, Ubuntu 24.04 fixed=6.8.0-136.136 ->
6.8.0-124-generic AFFECTED, 6.8.0-136-generic NOT affected.

Run:  PYTHONPATH=. python3 tests/test_vuln.py
"""
import copy
import gzip
import io
import json
import os
import sys
import tempfile
import threading
import zipfile
from sqlalchemy import func
from datetime import datetime
sys.path.insert(0, "tests")

from _actor_harness import make_env  # noqa: E402

db, ss = make_env("_vuln")
from app.core.pkgversion import cvss3_score, dpkg_cmp, rpm_cmp  # noqa: E402
from app.models import (ChangeHistory, Platform, VirtualMachine, VmVuln,  # noqa: E402
                        VulnAdvisory, VulnCve, VulnKernelAbi, VulnKev, LifecycleOverride)
from app.services import lifecycle_service as ls  # noqa: E402
from app.services import vuln_service as vs  # noqa: E402

FX = "tests/fixtures/vuln/"


def load(name):
    with open(FX + name) as f:
        return json.load(f)


U43040, U1086, ALSA = load("UBUNTU-CVE-2026-43040.json"), load("UBUNTU-CVE-2024-1086.json"), \
    load("ALSA-2024-2394.json")

# ------------------------------------------------------------ 1) comparators
assert dpkg_cmp("6.8.0-124.124", "6.8.0-136.136") < 0
assert dpkg_cmp("6.8.0-136.136~22.04.1", "6.8.0-136.136") < 0
assert dpkg_cmp("6.8.0-136.136.2", "6.8.0-136.136") > 0
assert dpkg_cmp("1:1.0", "2.0") > 0 and dpkg_cmp("6.1.153-1", "6.1.153-1") == 0
assert dpkg_cmp("6.1.153-1~deb11u1", "6.1.153-1") < 0
assert rpm_cmp("5.14.0-362.24.1.el9_3", "5.14.0-427.13.1.el9_4") < 0
assert rpm_cmp("0:5.14.0-427.13.1.el9_4", "5.14.0-427.13.1.el9_4") == 0
assert rpm_cmp("5.14.0-427.13.1.el9_4", "5.14.0-427.13.1.el9_4.x") < 0
assert rpm_cmp("4.18.0-553.el8_10", "4.18.0-80.el8") > 0
assert cvss3_score("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:H") == 7.1
assert cvss3_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H") == 10.0
assert cvss3_score("CVSS:4.0/AV:N") is None
print("1) comparators ok")

# ------------------------------------------------------------ 2) parsing
rows = vs.parse_osv(U43040)
pk = {(r["ecosystem"], r["package"]): r["fixed"] for r in rows}
assert pk[("Ubuntu:24.04:LTS", "linux")] == "6.8.0-136.136"
assert pk[("Ubuntu:22.04:LTS", "linux-hwe-6.8")] == "6.8.0-136.136~22.04.1"
assert pk[("Ubuntu:24.04:LTS", "linux-hwe-6.14")] is None          # no fix yet
assert not any(p == "linux-aws" for _, p in pk), "cloud kernels are filtered"
assert not any("FIPS" in e for e, _ in pk), "FIPS / Realtime ecosystems are filtered"
assert {r["cve"] for r in rows} == {"CVE-2026-43040"}
assert vs.severity_of(U43040)[:2] == ("medium", 7.1)               # Ubuntu priority wins
arows = vs.parse_osv(ALSA)
assert {r["package"] for r in arows} == {"kernel"} and len({r["cve"] for r in arows}) == 61
assert arows[0]["fixed"] == "5.14.0-427.13.1.el9_4"
assert vs.severity_of(ALSA) == ("high", None, False)               # advisory-wide "Important:"
summ = vs.summaries_of(ALSA, sorted({r["cve"] for r in arows}))
assert "use-after-free" in summ["CVE-2024-1086"], summ["CVE-2024-1086"]
RH = {"id": "RHSA-2024:2394", "modified": "2024-05-01T00:00:00Z", "upstream": ["CVE-2024-1086"],
      "affected": [{"package": {"ecosystem": "Red Hat:enterprise_linux:9::baseos", "name": "kernel"},
                    "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"},
                                                                 {"fixed": "0:5.14.0-427.13.1.el9_4"}]}]},
                   {"package": {"ecosystem": "Red Hat:enterprise_linux:9::appstream", "name": "kernel"},
                    "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"},
                                                                 {"fixed": "0:5.14.0-427.13.1.el9_4"}]}]},
                   {"package": {"ecosystem": "Red Hat:rhel_eus:9.2::baseos", "name": "kernel"},
                    "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1"}]}]}],
      "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"}]}
rr = vs.parse_osv(RH)
assert rr == [{"cve": "CVE-2024-1086", "ecosystem": "Red Hat:9", "package": "kernel",
               "introduced": "0", "fixed": "5.14.0-427.13.1.el9_4"}], rr     # epoch off, deduped, EUS out
print("2) parsing ok")

# ------------------------------------------------------------ 3) import + newest wins
res = vs._store(db, vs._osv_records([U43040, U1086, ALSA]), "upload")
assert res["records"] == 3 and res["kept"] == 0, res
n_rows = db.query(VulnAdvisory).count()
res = vs._store(db, vs._osv_records([U43040]), "upload")
assert res == {"records": 0, "replaced": 0, "kept": 1, "rows": 0}, res      # same record kept
old = copy.deepcopy(U43040); old["modified"] = "2026-01-01T00:00:00Z"
old["affected"][0]["ranges"][0]["events"] = [{"introduced": "0"}]
assert vs._store(db, vs._osv_records([old]), "upload")["kept"] == 1        # older ignored
assert db.query(VulnAdvisory).count() == n_rows
c = db.get(VulnCve, "CVE-2024-1086")
assert c.severity == "high" and c.specific and "use-after-free" in (c.summary or "") or c.summary
# KEV
kev = load("kev.json")
r = vs.import_kev(db, kev)
assert r["kev"] == 2 and not r["kept"], r
assert vs.import_kev(db, kev)["kept"] is True                               # same catalogue
assert db.get(VulnKev, "CVE-2024-1086").ransomware == "Known"
# zip import (streaming + byte pre-filter)
tmp = tempfile.mkdtemp()
zp = os.path.join(tmp, "all.zip")
with zipfile.ZipFile(zp, "w") as z:
    z.writestr("RH.json", json.dumps(RH))
    z.writestr("noise.json", json.dumps({"id": "USN-1", "affected": [
        {"package": {"ecosystem": "Ubuntu:24.04:LTS", "name": "openssl"}}]}))
    z.writestr("bad.json", "{not json")
r = vs.import_file(db, zp)
assert r["type"] == "osv-zip" and r["records"] == 1, r
print("3) imports ok")

# ------------------------------------------------------------ 4) matching
vc = Platform(name="vc", type="vcenter", host="v", environment="production", enabled=True)
pm = Platform(name="pm", type="proxmox", host="p", environment="production", enabled=True)
db.add_all([vc, pm]); db.commit()
ls.ensure_seed(db); db.commit()
N = 0


def vm(guest_os, kernel, build=None, platform=vc, name=None):
    global N
    N += 1
    v = VirtualMachine(platform_id=platform.id, external_id=f"x{N}", vmid=f"x{N}",
                       name=name or f"vm{N}", guest_os=guest_os, kernel=kernel,
                       kernel_build=build, tools_status="guestToolsRunning", power_state="running")
    db.add(v); db.commit()
    return v


def finding(v, cve):
    return db.query(VmVuln).filter_by(vm_id=v.id, cve=cve, closed_at=None).first()


U24 = "Ubuntu 24.04.3 LTS"
a124 = vm(U24, "6.8.0-124-generic", name="acc-124")
a136 = vm(U24, "6.8.0-136-generic", name="acc-136")
a139 = vm(U24, "6.8.0-139-generic")
hwe14 = vm(U24, "6.14.0-37-generic")                       # HWE 6.14: no fix published
ll = vm(U24, "6.8.0-136-lowlatency")                       # fix 6.8.0-136.136.2 -> uncertain
llpx = vm(U24, "6.8.0-136-lowlatency", "#136.2-Ubuntu SMP PREEMPT_DYNAMIC", platform=pm)
aws = vm(U24, "6.8.0-1050-aws")                            # cloud kernel: out of scope
u22hwe = vm("Ubuntu 22.04.5 LTS", "6.8.0-124-generic")     # linux-hwe-6.8 ~22.04.1
u22hwe_ok = vm("Ubuntu 22.04.5 LTS", "6.8.0-136-generic")
u22ga = vm("Ubuntu 22.04.5 LTS", "5.15.0-100-generic")     # GA linux: both CVEs
u22px = vm("Ubuntu 22.04.5 LTS", "6.8.0-136-generic", "#136~22.04.1-Ubuntu SMP", platform=pm)
u20 = vm("Ubuntu 20.04.6 LTS", "5.4.0-150-generic")        # standard support over -> EOL
u20ext = vm("Ubuntu 20.04.6 LTS", "5.15.0-100-generic", name="u20-pro")
alma = vm("AlmaLinux 9.3 (Shamrock Pampas Cat)", "5.14.0-362.24.1.el9_3.x86_64")
alma_ok = vm("AlmaLinux 9.4 (Seafoam Ocelot)", "5.14.0-427.13.1.el9_4.x86_64")
rhel = vm("Red Hat Enterprise Linux 9.3 (Plow)", "5.14.0-362.8.1.el9_3.x86_64")
rocky = vm("Rocky Linux 9.3 (Blue Onyx)", "5.14.0-362.8.1.el9_3.x86_64")
win = vm("Microsoft Windows Server 2022 (64-bit)", None)
db.add(LifecycleOverride(scope="vm", target=f"{vc.id}:{u20ext.vmid}", target_label=u20ext.name,
                         distro="ubuntu", extended=True))
db.commit()
ls.recompute(db)          # lifecycle -> vuln recompute (hook)
db.expire_all()

# Acceptance (CVE-2026-43040, Ubuntu 24.04, fixed 6.8.0-136.136)
f = finding(a124, "CVE-2026-43040")
assert f and f.status == "affected" and f.fix_available and f.fixed == "6.8.0-136.136", f
assert "6.8.0-136.136 -> etkileniyor" in f.reason and f.reason.startswith("Ubuntu 24.04 · linux 6.8.0-124")
assert finding(a136, "CVE-2026-43040") is None, "first upload of ABI 136 contains the fix"
assert finding(a139, "CVE-2026-43040") is None
assert a124.vuln_status == "evaluated" and a124.vuln_open == 1 and a124.vuln_max_sev == "medium"
assert a136.vuln_status == "evaluated" and a136.vuln_open == 0 and a136.vuln_total == 0
f = finding(hwe14, "CVE-2026-43040")
assert f and f.status == "affected" and not f.fix_available and "yayımlanmadı" in f.reason
assert hwe14.vuln_open == 0 and hwe14.vuln_total == 1      # "Açık CVE" = fixable only
f = finding(ll, "CVE-2026-43040")
assert f and f.status == "uncertain" and "belirsiz" in f.reason
assert finding(llpx, "CVE-2026-43040") is None, "uname -v #136.2 = exact fixed upload"
assert aws.vuln_status == "unknown" and "kapsam dışı" in aws.vuln_reason
f = finding(u22hwe, "CVE-2026-43040")
assert f and f.package == "linux-hwe-6.8" and f.fixed == "6.8.0-136.136~22.04.1"
assert finding(u22hwe_ok, "CVE-2026-43040") is None          # 136.136~22.04.1 = first upload
assert finding(u22px, "CVE-2026-43040") is None
assert finding(u22ga, "CVE-2026-43040").package == "linux"
f = finding(u22ga, "CVE-2024-1086")
assert f and f.kev and f.severity == "high" and f.fixed == "5.15.0-101.111"
assert u22ga.vuln_kev == 1 and u22ga.vuln_open == 2
# EOL skip / Pro ecosystem for extended support
assert u20.support_status == "eol" and u20.vuln_status == "skipped" and u20.vuln_open is None
assert db.query(VmVuln).filter_by(vm_id=u20.id).count() == 0
assert u20ext.support_status == "extended", u20ext.support_status
f = finding(u20ext, "CVE-2026-43040")
assert f and f.package == "linux-hwe-5.15" and f.fixed == "5.15.0-186.196~20.04.1" \
    and "Pro" in f.reason, (f and f.reason)
assert finding(u20ext, "CVE-2024-1086").fixed == "5.15.0-101.111~20.04.1"   # standard eco
# RHEL family
f = finding(alma, "CVE-2024-1086")
assert f and f.status == "affected" and f.kev and f.fixed == "5.14.0-427.13.1.el9_4"
assert alma.vuln_open == 61 and alma.vuln_kev == 1, (alma.vuln_open, alma.vuln_kev)
assert alma_ok.vuln_total == 0
assert finding(rhel, "CVE-2024-1086") and rhel.vuln_total == 1      # Red Hat's own data
assert "Red Hat verisiyle" in rocky.vuln_reason and rocky.vuln_total == 1   # Rocky -> RH fallback
assert win.vuln_status == "unknown" and "Çekirdek sürümü bilinmiyor" in win.vuln_reason, win.vuln_reason   # no kernel
print("4) matching ok (acceptance CVE-2026-43040 passed)")

# ------------------------------------------------------------ 5) Debian
DEB = {"id": "DEBIAN-CVE-2026-1111", "modified": "2026-10-01T00:00:00Z", "upstream": ["CVE-2026-1111"],
       "details": "A test flaw.",
       "affected": [{"package": {"ecosystem": "Debian:13", "name": "linux"},
                     "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"},
                                                                  {"fixed": "6.12.48-1"}]}]}]}
DEB2 = {"id": "DEBIAN-CVE-2026-2222", "modified": "2026-10-01T00:00:00Z", "upstream": ["CVE-2026-2222"],
        "affected": [{"package": {"ecosystem": "Debian:13", "name": "linux"},
                      "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "6.12.60-1"},
                                                                   {"fixed": "6.12.61-1"}]}]}]}
vs._store(db, vs._osv_records([DEB, DEB2]), "upload")
d_old = vm("Debian GNU/Linux 13 (trixie)", "6.12.43+deb13-amd64",
           "#1 SMP PREEMPT_DYNAMIC Debian 6.12.43-1 (2025-08-27)", platform=pm)
d_new = vm("Debian GNU/Linux 13 (trixie)", "6.12.48+deb13-amd64",
           "#1 SMP PREEMPT_DYNAMIC Debian 6.12.48-1 (2025-09-20)", platform=pm)
d_vc = vm("Debian GNU/Linux 13 (trixie)", "6.12.43+deb13-amd64")       # VMware: no uname -v
ls.recompute(db)
db.expire_all()
assert finding(d_old, "CVE-2026-1111").reason.endswith("düzeltme 6.12.48-1 -> etkileniyor")
assert finding(d_old, "CVE-2026-2222") is None, "introduced after the running version"
assert d_new.vuln_total == 0
# VMware gives no uname -v, but Debian 13's kernel name carries the version (phase 170)
assert d_vc.vuln_status == "evaluated" and "6.12.43-1" in d_vc.vuln_reason, d_vc.vuln_reason
assert finding(d_vc, "CVE-2026-1111").status == "affected"
print("5) debian ok")

# ------------------------------------------------------------ 6) lifecycle of findings
hist0 = db.query(ChangeHistory).filter_by(field="vuln").count()
assert hist0 == 0, "first evaluation writes no history"
# patch: kernel moved to 136 -> finding closed as patched, history row written
a124.kernel = "6.8.0-136-generic"; db.commit()
vs.recompute(db, vm_ids=[a124.id])
db.expire_all()
row = db.query(VmVuln).filter_by(vm_id=a124.id, cve="CVE-2026-43040").one()
assert row.closed_at is not None and row.closed_reason == "patched"
assert a124.vuln_open == 0
h = db.query(ChangeHistory).filter_by(field="vuln", entity_name="acc-124").one()
assert h.category == "security" and "kapandı" in h.old_value and "CVE-2026-43040" in h.old_value
# rollback to the old kernel -> reopened, history "yeni"
a124.kernel = "6.8.0-124-generic"; db.commit()
vs.recompute(db, vm_ids=[a124.id])
db.expire_all()
row = db.query(VmVuln).filter_by(vm_id=a124.id, cve="CVE-2026-43040").one()
assert row.closed_at is None and row.status == "affected"
assert db.query(ChangeHistory).filter_by(field="vuln", entity_name="acc-124").count() == 2
# new data: a fresh Ubuntu CVE appears -> one history row with the CVE list (KEV marked)
NEW = copy.deepcopy(U43040)
NEW["id"], NEW["upstream"], NEW["modified"] = "UBUNTU-CVE-2026-9999", ["CVE-2026-9999"], "2026-11-01T00:00:00Z"
NEW["aliases"] = []
vs._store(db, vs._osv_records([NEW]), "upload")
vs.recompute(db)
db.expire_all()
assert a124.vuln_open == 2
h = db.query(ChangeHistory).filter_by(field="vuln", entity_name="acc-124").order_by(ChangeHistory.id.desc()).first()
assert h.new_value.startswith("1 CVE yeni: CVE-2026-9999"), h.new_value
# VM goes EOL (support removed) -> findings closed as not_evaluated, no history
before = db.query(ChangeHistory).filter_by(field="vuln").count()
db.query(LifecycleOverride).delete(); db.commit()
ls.recompute(db)
db.expire_all()
assert u20ext.vuln_status == "skipped"
assert db.query(VmVuln).filter_by(vm_id=u20ext.id, closed_at=None).count() == 0
assert {r.closed_reason for r in db.query(VmVuln).filter_by(vm_id=u20ext.id)} == {"not_evaluated"}
assert db.query(ChangeHistory).filter_by(field="vuln").count() == before
print("6) open / close / history ok")

# ------------------------------------------------------------ 7) bundle round trip
blob = vs.export_bundle(db)
doc = json.loads(gzip.decompress(blob))
assert doc["kind"] == vs.BUNDLE_KIND and doc["kev"] and doc["cves"]
_main_session = ss.SessionLocal
db2, _ = make_env("_vuln2")               # second database: the "offline server"
ss.SessionLocal = _main_session           # syncs below still go to the first one
bp = os.path.join(tmp, "bundle.json.gz")
with open(bp, "wb") as fh:
    fh.write(blob)
r = vs.import_file(db2, bp)
assert r["type"] == "bundle" and r["records"] == db.query(VulnAdvisory.osv_id).distinct().count(), r
assert db2.query(VulnAdvisory).count() == db.query(VulnAdvisory).count()
assert db2.get(VulnCve, "CVE-2024-1086").summary == db.get(VulnCve, "CVE-2024-1086").summary
assert db2.query(VulnKev).count() == 2
assert r["contents"] == {"AlmaLinux": 61, "Debian": 2, "Red Hat": 1, "Ubuntu": 3, "CISA KEV": 2}, r["contents"]
assert vs.import_file(db2, bp)["kept"] == r["records"]          # same bundle again: nothing new
kev_only = dict(doc, records=[], cves=[])
assert vs.bundle_contents(kev_only) == {"CISA KEV": 2}
for bad in (b"{}", b"[1,2]"):
    p = os.path.join(tmp, "bad.json")
    with open(p, "wb") as fh:
        fh.write(bad)
    try:
        vs.import_file(db2, p)
        raise AssertionError("unknown file accepted")
    except ValueError:
        pass
db2.close()
print("7) bundle ok")

# ------------------------------------------------------------ 8) offline sync
import requests  # noqa: E402
_orig = requests.get


def _offline(*a, **k):
    raise requests.ConnectionError("no route to host")


_orig_sget = requests.Session.get
requests.get = _offline
requests.Session.get = lambda self, url, **k: _offline(url, **k)   # outbound: keep-alive session (phase 173)
try:
    vs.job_sync(db, osv=True)
    raise AssertionError("offline sync must raise")
except RuntimeError as exc:
    assert "Ağ erişimi yok" in str(exc), str(exc)
finally:
    requests.get = _orig
    requests.Session.get = _orig_sget
m = vs.meta(db)
assert "Ağ erişimi yok" in m["last_error"] and m["rows"] > 0 and m["kev"] == 2


class _Resp:
    def __init__(self, doc):
        self.doc = doc

    def raise_for_status(self):
        pass

    def json(self):
        return self.doc


newer = dict(kev, catalogVersion="2026.11.02",
             vulnerabilities=kev["vulnerabilities"] + [{"cveID": "CVE-2026-43040", "dateAdded": "2026-11-02",
                                                         "dueDate": "2026-11-23", "vulnerabilityName": "x"}])


def _kev_only(url, *a, **k):        # KEV mirror reachable, OSV storage blocked
    if "known_exploited" in url:
        return _Resp(newer)
    raise requests.ConnectionError("blocked")


requests.get = _kev_only
requests.Session.get = lambda self, url, **k: _kev_only(url, **k)
try:
    res = vs.job_sync(db, osv=True)
finally:
    requests.get = _orig
    requests.Session.get = _orig_sget
assert res["kev"]["kev"] == 3 and "OSV" in res["errors"][0] and "match" in res
db.expire_all()
assert finding(a124, "CVE-2026-43040").kev is True and a124.vuln_kev == 1   # recomputed
m = vs.meta(db)
assert m["last_sync"] and "OSV" in m["last_error"] and m["kev_version"] == "2026.11.02"
vs.import_kev(db, dict(kev, catalogVersion="2026.11.03"))   # back to the 2-entry catalogue
vs.recompute(db)
db.expire_all()
assert a124.vuln_kev == 0
print("8) offline / partial sync ok")

# ------------------------------------------------------------ 8b) GitHub sources
# cisa.gov and osv.dev storage blocked, only github.com reachable: KEV comes
# from the cisagov/kev-data branch archive, AlmaLinux OSV from the
# AlmaLinux/osv-database archive (both .tar.gz, as codeload serves them).
import tarfile  # noqa: E402


def _targz(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, obj in members.items():
            raw = json.dumps(obj).encode()
            ti = tarfile.TarInfo(name); ti.size = len(raw)
            tf.addfile(ti, io.BytesIO(raw))
    return path


kev_tar = _targz(os.path.join(tmp, "kev.tar.gz"), {"kev-data-develop/" + vs.KEV_FILE: kev,
                                                   "kev-data-develop/schema.json": {"x": 1}})
alma_tar = _targz(os.path.join(tmp, "alma.tar.gz"), {
    "osv-database-master/advisories/almalinux9/ALSA-2024:2394.json": ALSA,
    "osv-database-master/advisories/almalinux9/ALBA-2024:0001.json": {"id": "ALBA-2024:0001", "affected": [
        {"package": {"ecosystem": "AlmaLinux:9", "name": "bash"}}]}})


class _File:
    def __init__(self, path):
        self.f, self.status_code = open(path, "rb"), 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        while True:
            b = self.f.read(n)
            if not b:
                return
            yield b


_seen = []


def _github_only(url, stream=False, timeout=None, headers=None, **_k):
    _seen.append(url)
    if url.startswith("https://github.com/cisagov/kev-data/archive/"):
        return _File(kev_tar)
    if url.startswith("https://github.com/AlmaLinux/osv-database/archive/"):
        return _File(alma_tar)
    raise requests.ConnectionError("Tunnel connection failed: 403 Forbidden")


_main_session = ss.SessionLocal
db3, _ = make_env("_vuln3")
ss.SessionLocal = _main_session
_orig_get = vs._get
vs.set_selection(db3, "manual", list(vs.OSV_ECOSYSTEMS))   # empty inventory: pick by hand
vs._get = _github_only
try:
    res = vs.job_sync(db3, osv=True)
finally:
    vs._get = _orig_get
assert res["kev"]["source"] == "github.com (arşiv)" and res["kev"]["kev"] == 2, res["kev"]
assert [f.split(":")[0] for f in res["kev"]["failed"]] == ["cisa.gov", "raw.githubusercontent.com",
                                                           "api.github.com"], res["kev"]["failed"]
assert res["osv"]["AlmaLinux"]["source"] == "github.com" and res["osv"]["AlmaLinux"]["records"] == 1
assert "osv.dev erişilemedi" in res["osv"]["Debian"]["error"]
# storage unreachable -> only ONE osv.dev attempt, then the GitHub fallback
assert sum("storage.googleapis.com" in u for u in _seen) == 1, _seen
m3 = vs.meta(db3)
assert m3["kev_source"] == "github.com (arşiv)" and m3["osv_sources"] == {"AlmaLinux": "github.com"}
assert m3["by_ecosystem"] == {"AlmaLinux:9": 61}
# api.github.com answers -> the archive is not needed
vs._get = lambda url, **k: (_Resp(dict(kev, catalogVersion="2026.12.01")) if "api.github.com" in url
                            else (_ for _ in ()).throw(requests.ConnectionError("blocked")))
try:
    assert vs.sync_kev(db3)["source"] == "api.github.com"
finally:
    vs._get = _orig_get
# own mirror replaces the list (VULN_KEV_URLS)
from app.config import get_settings  # noqa: E402
get_settings().vuln_kev_urls = "https://mirror.example.lan/kev.json"
try:
    assert [n for n, *_ in vs._kev_sources()] == ["mirror.example.lan"]
finally:
    get_settings().vuln_kev_urls = ""
# uploads: the same archives work through "Upload file"
db3.query(VulnAdvisory).delete(); db3.commit()
assert vs.import_file(db3, alma_tar)["type"] == "osv-tar" and db3.query(VulnAdvisory).count() == 61
assert vs.import_file(db3, kev_tar)["type"] == "kev"
# source probe: every source listed, blocked ones with a short reason
vs._get = _github_only
try:
    pr = vs.probe()
finally:
    vs._get = _orig_get
ok = {r["name"]: r["ok"] for r in pr}
assert ok["github.com (arşiv)"] and ok["github.com (AlmaLinux)"] and not ok["cisa.gov"], ok
assert next(r for r in pr if r["name"] == "cisa.gov")["detail"] == \
    "Proxy engelledi (403)"
db3.close()
print("8b) GitHub sources ok")

# ------------------------------------------------------------ 9) eligibility guard
assert all(v.vuln_status in ("evaluated", "skipped", "unknown")
           for v in db.query(VirtualMachine).all())
# ------------------------------------------------------------ 10) search / views / export
from app.core.search import apply_vm_search  # noqa: E402
from app.services import report_service as rs  # noqa: E402


def names(q):
    return {v.name for v in apply_vm_search(db.query(VirtualMachine), q).all()}


assert "acc-124" in names("cve:CVE-2026-43040") and "acc-136" not in names("cve:CVE-2026-43040")
assert "acc-124" in names("cve:2026-4304")                      # fragment
assert names("kev:evet") >= {u22ga.name, alma.name} and "acc-124" not in names("kev:evet")
assert "acc-124" in names("zafiyet:var") and "acc-136" in names("zafiyet:yok")
assert ll.name in names("zafiyet:belirsiz") and hwe14.name in names("zafiyet:duzeltmesiz")
assert aws.name in names("zafiyet:bilinmiyor") and u20.name in names("zafiyet:kapsamdisi")
assert "acc-136" in names("cve:yok") and "acc-124" not in names("cve:yok")
assert alma.name in names("acikcve:>50") and "acc-124" not in names("acikcve:>50")
assert "acc-124" not in names("-zafiyet:var")
lst = vs.cve_list(db)
assert lst[0]["kev"] and lst[0]["cve"] == "CVE-2024-1086", lst[0]          # KEV first
row = next(r for r in lst if r["cve"] == "CVE-2026-43040")
assert row["vms"] >= 4 and row["uncertain"] == 1 and row["nofix"] >= 1 and row["severity"] == "medium"
assert {r["cve"] for r in vs.cve_list(db, vm_id=a124.id)} == {"CVE-2026-43040", "CVE-2026-9999"}
sm = vs.summary(db)
assert sm["vms_kev"] >= 2 and sm["cves_kev"] == 1 and sm["has_data"]
det = vs.vm_findings(db, alma.id)
assert det[0]["cve"] == "CVE-2024-1086" and det[0]["kev"] and det[0]["summary"]
vms_x = [a124, a136, u20, alma]
frows = rs.attach_vulns(db, vms_x)
vals = {v.name: dict(zip([c for c, _ in rs.VM_COLUMNS], rs._row_values(v, rs.VM_COLUMNS))) for v in vms_x}
assert vals["acc-124"]["Açık CVE"] == 2 and "CVE-2026-43040" in vals["acc-124"]["CVE Listesi"]
assert vals[u20.name]["Açık CVE"] == "Kapsam dışı" and vals["acc-136"]["Açık CVE"] == 0
assert "CVE-2024-1086 (KEV)" in vals[alma.name]["CVE Listesi"]
assert any(r["vm"] == alma.name and r["kev"] == "Evet" for r in frows)
print("10) search / views / export ok")

# ------------------------------------------------------------ 11) sync: uname -v kept + recompute hook
from _actor_harness import FakeCollector, run_sync  # noqa: E402
px2 = Platform(name="px2", type="proxmox", host="p2", environment="production", enabled=True)
db.add(px2); db.commit()
S = dict(power_state="running", host_name="h1", cluster="c1", cpu_count=2, ram_mb=2048,
         external_id="h1/901", vmid="901", name="sync-u24", guest_os="Ubuntu 24.04.3 LTS",
         kernel="6.8.0-136-lowlatency", kernel_build="#136.2-Ubuntu SMP PREEMPT_DYNAMIC",
         tools_status="guestToolsRunning")


def psync(vm):
    run_sync(ss, px2.id, FakeCollector(vms=[dict(vm)])); db.expire_all()


psync(S)
from app.models import SyncLog  # noqa: E402
r = db.query(VirtualMachine).filter_by(platform_id=px2.id).one_or_none()
assert r is not None, [(l.status, l.message) for l in db.query(SyncLog).filter_by(platform_id=px2.id)]
assert r.kernel_build.startswith("#136.2") and r.vuln_status == "evaluated" and r.vuln_total == 0, \
    (r.kernel_build, r.vuln_status, r.vuln_total, r.vuln_reason)
psync(dict(S, kernel_build=""))                     # agent answered without it: kept
r = db.query(VirtualMachine).filter_by(platform_id=px2.id).one()
assert r.kernel_build.startswith("#136.2") and r.vuln_total == 0
psync(dict(S, kernel="6.8.0-124-lowlatency", kernel_build="#124.1-Ubuntu SMP"))
r = db.query(VirtualMachine).filter_by(platform_id=px2.id).one()
assert r.vuln_open == 2, (r.vuln_open, r.vuln_reason)  # downgraded kernel -> sync recomputes
psync(dict(S, kernel="6.8.0-140-lowlatency", kernel_build=""))   # new kernel, no uname -v
r = db.query(VirtualMachine).filter_by(platform_id=px2.id).one()
assert r.kernel == "6.8.0-140-lowlatency" and r.kernel_build is None, r.kernel_build
print("11) sync hook ok")

# ------------------------------------------------------------ 12) source choice + SUSE
assert vs.get_selection(db) == {"mode": "auto", "manual": []}
assert vs.auto_sources(db) == ["Ubuntu", "Debian", "AlmaLinux", "Windows"], vs.auto_sources(db)
ov = {r["name"]: r for r in vs.sources_overview(db)["rows"]}
assert ov["AlmaLinux"]["auto"] and ov["AlmaLinux"]["vms"] >= 3 and ov["AlmaLinux"]["cves"] == 61
assert not ov["Red Hat"]["auto"] and ov["Red Hat"]["cves"] == 1          # stored from the zip test
assert ov["SUSE"]["vms"] == 0 and not ov["SUSE"]["selected"]
# sync downloads only the selected dumps
_urls = []


def _record(url, **k):
    _urls.append(url)
    raise requests.ConnectionError("blocked")


vs._get = _record
try:
    try:
        vs.sync_osv(db)
    except RuntimeError:
        pass
    # (phase 173: the change list is read first; unreachable -> the storage counts as down)
    assert [u for u in _urls if "storage.googleapis" in u] == [vs.OSV_IDS_URL.format("Ubuntu")], _urls
    _urls.clear()
    vs.set_selection(db, "manual", ["SUSE", "Red Hat"])
    assert vs.selected_sources(db) == ["Red Hat", "SUSE"]       # catalogue order
    try:
        vs.sync_osv(db)
    except RuntimeError:
        pass
    assert _urls[0] == vs.OSV_IDS_URL.format("Red%20Hat") and not any("AlmaLinux" in u for u in _urls), _urls
    vs.set_selection(db, "manual", [])
    try:
        vs.sync_osv(db)
        raise AssertionError("empty selection must say so")
    except RuntimeError as exc:
        assert "seçili zafiyet kaynağı yok" in str(exc)
finally:
    vs._get = _orig_get
try:
    vs.set_selection(db, "manual", ["Gentoo"])
    raise AssertionError("unknown source accepted")
except ValueError:
    pass
vs.set_selection(db, "auto", [])

# SUSE / openSUSE (format per OSV's SUSE feed: one ecosystem per product /
# module, binary package names, rpm versions with a rebuild counter)
SUSE = {"id": "SUSE-SU-2026:3001-1", "modified": "2026-10-01T00:00:00Z", "upstream": ["CVE-2026-3001"],
        "summary": "Security update for the Linux Kernel",
        "affected": [
            {"package": {"ecosystem": "SUSE:Linux Enterprise Module for Basesystem 15 SP7", "name": "kernel-default"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "6.4.0-150700.53.19.1"}]}]},
            {"package": {"ecosystem": "SUSE:Linux Enterprise Server 15 SP7", "name": "kernel-default"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "6.4.0-150700.53.19.1"}]}]},
            {"package": {"ecosystem": "SUSE:Linux Enterprise Server 15 SP7", "name": "kernel-source"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "6.4.0-150700.53.19.1"}]}]},
            {"package": {"ecosystem": "SUSE:Linux Enterprise Micro 6.1", "name": "kernel-default"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "6.4.0-150700.53.19.1"}]}]},
            {"package": {"ecosystem": "SUSE:Linux Enterprise Fancy Server 15 SP7", "name": "kernel-default"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "6.4.0-150700.53.19.1"}]}]},
            {"package": {"ecosystem": "openSUSE:Leap 16.0", "name": "kernel-default"},
             "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "6.4.0-150700.53.19.1"}]}]}]}
rows = vs.parse_osv(SUSE)
assert {(r["ecosystem"], r["package"]) for r in rows} == {("SUSE:15.7", "kernel-default"),
                                                          ("openSUSE:16.0", "kernel-default")}, rows
st = vs.Counter()
vs.parse_osv(SUSE, st)
assert list(st) == ["SUSE:Linux Enterprise Fancy Server 15 SP7 / kernel-default"], st   # Micro = known skip
zp2 = os.path.join(tmp, "suse.zip")
with zipfile.ZipFile(zp2, "w") as z:
    z.writestr("SUSE-SU-2026_3001-1.json", json.dumps(SUSE))
res = vs.import_file(db, zp2)
assert res["records"] == 1 and res["unrecognized"] == ["SUSE:Linux Enterprise Fancy Server 15 SP7 / kernel-default (1)"]
assert vs._suse_cmp("6.4.0-150700.53.19", "6.4.0-150700.53.19.1") == 0
assert vs._suse_cmp("6.4.0-150700.53.11", "6.4.0-150700.53.19.1") < 0
assert vs._suse_cmp("6.4.0-150700.53.22", "6.4.0-150700.53.19.1") > 0
s_old = vm("SUSE Linux Enterprise Server 15 SP7", "6.4.0-150700.53.11-default", name="sles-old")
s_fix = vm("SUSE Linux Enterprise Server 15 SP7", "6.4.0-150700.53.19-default", name="sles-fix")
s_rt = vm("SUSE Linux Enterprise Server 15 SP7", "6.4.0-150700.53.11-rt", name="sles-rt")
o_old = vm("openSUSE Leap 16.0", "6.4.0-150700.53.11-default", name="leap-old")
ls.recompute(db)
db.expire_all()
f = finding(s_old, "CVE-2026-3001")
assert f and f.reason == ("SLES 15 SP7 · kernel-default 6.4.0-150700.53.11 · "
                          "düzeltme 6.4.0-150700.53.19.1 -> etkileniyor"), (f and f.reason, s_old.vuln_reason)
assert s_fix.vuln_status == "evaluated" and s_fix.vuln_total == 0, (s_fix.vuln_status, s_fix.vuln_reason)
assert s_rt.vuln_status == "unknown" and "kernel-rt" in s_rt.vuln_reason
assert finding(o_old, "CVE-2026-3001") is not None
assert "SUSE" in vs.auto_sources(db) and "openSUSE" in vs.auto_sources(db)
assert vs.sources_overview(db)["missing"] == ["Windows"]    # every Linux source has data (Windows: section 15)
print("12) source choice + SUSE ok")

# ------------------------------------------------------------ 13) scale paths (phase 164)
db.expire_all()
a124 = db.get(VirtualMachine, a124.id)
assert a124.vuln_top in ("CVE-2026-43040", "CVE-2026-9999") and a124.vuln_top_sev == "medium"
alma_r = db.get(VirtualMachine, alma.id)
assert alma_r.vuln_top == "CVE-2024-1086" and alma_r.vuln_crit == 0 and alma_r.vuln_high == 61
# nothing changed -> every VM skipped without reading its findings
r2 = vs.recompute(db)
assert r2["unchanged"] == db.query(VirtualMachine).count() and r2["new"] == 0, r2
# a kernel change re-evaluates only that VM
a124.kernel = "6.8.0-136-generic"; db.commit()
r3 = vs.recompute(db)
assert r3["unchanged"] == db.query(VirtualMachine).count() - 1 and r3["closed"] == 2, r3
a124.kernel = "6.8.0-124-generic"; db.commit(); vs.recompute(db)
# the stats table answers like the raw aggregate
from app.models import VulnCveStat  # noqa: E402
fast, n_fast = vs.cve_page(db, per_page=500)
db.query(VulnCveStat).delete(); db.commit()
assert vs.cve_page(db, per_page=500)[1] == 0              # (empty until rebuilt)
vs.refresh_stats(db); db.commit()
again, _ = vs.cve_page(db, per_page=500)
assert [(x["cve"], x["vms"], x["fixable"], x["severity"], x["kev"]) for x in fast] == \
    [(x["cve"], x["vms"], x["fixable"], x["severity"], x["kev"]) for x in again]
page2, total = vs.cve_page(db, page=2, per_page=10)
assert total == n_fast and len(page2) == 10 and page2[0]["cve"] == fast[10]["cve"]
vm_list, vm_total = vs.cve_page(db, vm_id=alma.id, per_page=5)       # raw path (VM filter)
assert vm_total == 61 and vm_list[0]["cve"] == "CVE-2024-1086" and len(vm_list) == 5
assert len(vs.vm_findings(db, alma.id, limit=7)) == 7
# export cap: a note row says how many were left out
rows = rs.attach_vulns(db, [alma_r, db.get(VirtualMachine, u22ga.id)], max_rows=30)
assert len(rows) == 31 and rows[-1]["vm"].startswith("… 34 bulgu daha listelenmedi"), rows[-1]
assert "CVE-2024-1086 (KEV)" in alma_r._vuln_cves and alma_r._vuln_cves.endswith("… +21")
print("13) scale paths ok")

# ------------------------------------------------------------ 14) Oracle Linux (OVAL) + Photon (phase 167)
# oracle-elsa-sample.xml = two REAL definitions from Oracle's 2018 OVAL file
# (ELSA-2018-0151 RHCK OL7, ELSA-2018-4001 UEK OL6+OL7, via quay/claircore
# testdata) + one OL8 definition written in the same format.
res = vs.import_file(db, FX + "oracle-elsa-sample.xml")
assert res["type"] == "oracle-oval" and res["records"] == 4, res        # ELSA-2018-4001 = OL6 + OL7 records
pk = {(a.ecosystem, a.package): a.fixed for a in db.query(VulnAdvisory).filter(VulnAdvisory.ecosystem.like("Oracle Linux:%"))}
assert pk[("Oracle Linux:7", "kernel-uek-4.1")] == "4.1.12-112.14.2.el7uek", pk        # own build per release
assert pk[("Oracle Linux:6", "kernel-uek-4.1")] == "4.1.12-112.14.2.el6uek"
assert pk[("Oracle Linux:7", "kernel")] == "3.10.0-693.17.1.el7"
assert pk[("Oracle Linux:8", "kernel-uek-5.15")] == "5.15.0-300.163.18.el8uek"
assert pk[("Oracle Linux:8", "kernel")] == "4.18.0-553.30.1.el8_10"
assert not any(p.endswith("devel") for _, p in pk)
c = db.get(VulnCve, "CVE-2026-5001")
assert c.score == 9.8 and c.severity == "critical" and c.specific          # per-CVE CVSS from the OVAL
o_uek_old = vm("Oracle Linux Server 8.10", "5.15.0-206.153.7.el8uek.x86_64", name="ol8-uek7-old")
o_uek_new = vm("Oracle Linux Server 8.10", "5.15.0-314.193.5.5.el8uek.x86_64", name="ol8-uek7-new")
o_uek6 = vm("Oracle Linux Server 8.10", "5.4.17-2136.350.3.2.el8uek.x86_64", name="ol8-uek6")
o_rhck = vm("Oracle Linux Server 8.10", "4.18.0-553.16.1.el8_10.x86_64", name="ol8-rhck")
ph = vm("VMware Photon OS/Linux", "6.1.126-5.ph5", name="photon5")
ph_esx = vm("VMware Photon OS/Linux", "6.1.126-5.ph5-esx", name="photon5-esx")
ciq = vm("Rocky Linux from CIQ - LTS 9.6 (Blue Onyx)", "5.14.0-570.60.1+27.2.el9_6_ciq.x86_64", name="ciq")
res = vs.import_file(db, FX + "cve_data_photon5.0.json")
assert res["type"] == "photon" and res["version"] == "5.0" and res["records"] == 3, res   # Not Affected / curl out
ls.recompute(db)
db.expire_all()
f = finding(o_uek_old, "CVE-2026-5001")
assert f and f.severity == "critical" and f.reason == ("Oracle Linux 8 · kernel-uek-5.15 5.15.0-206.153.7.el8uek · "
                                                       "düzeltme 5.15.0-300.163.18.el8uek -> etkileniyor"), f and f.reason
assert db.get(VirtualMachine, o_uek_new.id).vuln_total == 0
u6 = db.get(VirtualMachine, o_uek6.id)
assert u6.vuln_status == "unknown" and "UEK 5.4" in u6.vuln_reason, u6.vuln_reason
assert finding(o_rhck, "CVE-2026-5001").package == "kernel"
assert finding(ph, "CVE-2026-6001").fixed == "6.1.130-1.ph5" and finding(ph, "CVE-2026-6002") is None
f3 = finding(ph, "CVE-2026-6003")
assert f3 and not f3.fix_available and f3.severity == "critical"
assert finding(ph_esx, "CVE-2026-6001").package == "linux-esx"
cq = db.get(VirtualMachine, ciq.id)
assert cq.support_status == "supported" and cq.vuln_status == "unknown" and "CIQ" in cq.vuln_reason
assert {"Oracle Linux", "Photon OS"} <= set(vs.auto_sources(db))
assert vs._vendor_versions(db, "Oracle Linux") == ["8"] and vs._vendor_versions(db, "Photon OS") == ["5.0"]
# vendor download: per-release Oracle file missing -> the all-in-one file
with open(FX + "oracle-elsa-sample.xml", "rb") as fh:
    ora_bytes = fh.read()
_urls.clear()


def _vendor_get(url, **k):
    _urls.append(url)
    if url.endswith("elsa-ol8.xml.bz2"):
        class R404(_File):
            def __init__(self):
                self.status_code = 404

            def raise_for_status(self):
                raise requests.HTTPError("404 Client Error: Not Found")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass
        return R404()
    if url.endswith("elsa-all.xml.bz2"):
        import bz2
        pth = os.path.join(tmp, "all.xml.bz2")
        with open(pth, "wb") as fh:
            fh.write(bz2.compress(ora_bytes))
        return _File(pth)
    if "photon_cve_metadata" in url:
        return _File(FX + "cve_data_photon5.0.json")
    raise requests.ConnectionError("blocked")


vs._get = _vendor_get
try:
    out = vs.sync_vendor(db, "Oracle Linux")
    assert out["versions"] == {"8": "all"} and out["source"] == "linux.oracle.com" and out["errors"] == ["8: HTTP 404"], out
    out = vs.sync_vendor(db, "Photon OS")
    assert out["versions"] == {"5.0": 3} and out["source"] == "packages.broadcom.com", out
finally:
    vs._get = _orig_get
# phase 171 (found on prod): the per-release files repeat a shared advisory -
# the second release must get its rows too (OL8 had no UEK 5.4 data at all)
db.add(VulnAdvisory(osv_id="ELSA-2018-4001", cve="CVE-2017-5715", ecosystem="Oracle Linux:7",
                    package="kernel-uek-4.1", introduced="0", fixed="4.1.12-112.14.2.el7uek",
                    modified=datetime(2018, 1, 1), source="oracle"))           # pre-171 form
db.commit()
db.query(VulnAdvisory).filter(VulnAdvisory.osv_id.like("ELSA-2018-4001/%")).delete(synchronize_session=False)
db.commit()
r6 = vs.import_oracle_oval(db, FX + "oracle-elsa-sample.xml", "oracle", versions=["6"])
r7 = vs.import_oracle_oval(db, FX + "oracle-elsa-sample.xml", "oracle", versions=["7"])
assert r6["records"] == 1 and r7["records"] >= 1, (r6, r7)
ids = {(a.osv_id, a.ecosystem) for a in db.query(VulnAdvisory).filter(VulnAdvisory.osv_id.like("ELSA-2018-4001%"))}
assert ids == {("ELSA-2018-4001/OL6", "Oracle Linux:6"), ("ELSA-2018-4001/OL7", "Oracle Linux:7")}, ids
print("14) Oracle Linux + Photon ok")

# ------------------------------------------------------------ 15) Windows (MSRC CVRF, phase 168)
# msrc-cvrf-sample.xml = structure of a real MSRC CVRF v3.0 XML document with
# the real products / KBs / fixed builds of five CVEs (+ one synthetic
# "Customer Action Required: No" CVE), see the file's header.
from app.core.os_identity import identify  # noqa: E402
assert vs.msrc_product("Windows Server 2019") == ("Windows Server:2019", 17763)
assert vs.msrc_product("Windows Server 2025 (Server Core installation)") == ("Windows Server:2025", 26100)
assert vs.msrc_product("Windows Server 2022, 23H2 Edition (Server Core installation)") == \
    ("Windows Server:23h2-ac", 25398)
assert vs.msrc_product("Windows 11 Version 24H2 for ARM64-based Systems") == ("Windows:11-24h2", 26100)
assert vs.msrc_product("Windows 10 Version 22H2 for 32-bit Systems") == ("Windows:10-22h2", 19045)
assert vs.msrc_product("Windows Server 2012 R2") == ("Windows Server:2012-r2", 9600)
assert vs.msrc_product(".NET 8.0") is None and vs.msrc_product("Windows Server 2008 R2 for x64-based "
                                                               "Systems Service Pack 1") is None
assert vs.nt_version("NT 10.0.17763.6893") == ("10.0", 17763, 6893)
assert vs.nt_version("NT Windows.17763.6775") == ("10.0", 17763, 6775)          # broken Tools string
assert vs.nt_version("NT 10.0.17763") == ("10.0", 17763, None) and vs.nt_version("6.8.0-1") is None
assert identify("Microsoft Windows Server 2019 Standard", "NT Windows.17763.6775").version == "2019"
assert vs.msrc_months(3, datetime(2026, 1, 20).date()) == ["2026-Jan", "2025-Dec", "2025-Nov"]

res = vs.import_file(db, FX + "msrc-cvrf-sample.xml")
assert res["type"] == "msrc" and res["records"] == 3 and "unrecognized" not in res, res
rows = {(a.cve, a.ecosystem): (a.fixed, a.introduced) for a in db.query(VulnAdvisory)
        .filter(VulnAdvisory.ecosystem.like("Windows%"))}
assert rows == {
    ("CVE-2026-42825", "Windows Server:2012"): ("6.2.9200.26079", "KB5087470"),
    ("CVE-2026-42825", "Windows Server:2022"): ("10.0.20348.5139", "KB5087545"),    # not the hotpatch
    ("CVE-2026-42825", "Windows Server:2025"): ("10.0.26100.32860", "KB5087539"),
    ("CVE-2026-42825", "Windows:11-24h2"): ("10.0.26100.8457", "KB5089549"),
    ("CVE-2022-21971", "Windows Server:2019"): ("10.0.17763.2565", "KB5010351"),
    ("CVE-2022-21971", "Windows Server:2022"): ("10.0.20348.524", "KB5010354"),
    ("CVE-2026-6726", "Windows Server:2022"): ("10.0.20348.5499", "KB5120242"),
    ("CVE-2026-6726", "Windows Server:2025"): ("10.0.26100.33296", "KB5120233"),   # from Server Core
    ("CVE-2026-6726", "Windows:11-24h2"): ("10.0.26100.9165", "KB5123273"),        # lowest of two
}, rows
assert not db.query(VulnAdvisory).filter(VulnAdvisory.cve.in_(["CVE-2023-24898", "CVE-2099-0001",
                                                                "CVE-2024-21392"])).count()
c = db.get(VulnCve, "CVE-2022-21971")
assert c.score == 7.8 and c.severity == "high" and c.summary == "Windows Runtime Remote Code Execution Vulnerability"
assert db.query(VulnAdvisory).filter_by(osv_id="MSRC-CVE-2026-42825").first().modified == datetime(2026, 6, 1, 7)
again = vs.import_file(db, FX + "msrc-cvrf-sample.xml")
assert again["records"] == 0 and again["kept"] == 3, again                       # same revisions
# the JSON form (official MSRC PowerShell module field names, numeric enums)
jdoc = {"DocumentTracking": {"Identification": {"ID": {"Value": "2025-Jan"}},
                             "CurrentReleaseDate": "2025-01-14T08:00:00Z"},
        "ProductTree": {"FullProductName": [{"ProductID": "11571", "Value": "Windows Server 2019"},
                                            {"ProductID": "11572", "Value": "Windows Server 2019 (Server Core installation)"}]},
        "Vulnerability": [{"CVE": "CVE-2025-21333", "Title": {"Value": "Windows Hyper-V NT Kernel Integration VSP EoP"},
                           "Notes": [{"Title": "Customer Action Required", "Type": 7, "Value": "Yes"}],
                           "ProductStatuses": [{"ProductID": ["11571", "11572"], "Type": 3}],
                           "Threats": [{"Type": 3, "Description": {"Value": "Important"}, "ProductID": ["11571"]}],
                           "CVSSScoreSets": [{"BaseScore": 7.8, "ProductID": ["11571", "11572"]}],
                           "Remediations": [{"Type": 2, "Description": {"Value": "5050008"}, "SubType": "Security Update",
                                             "FixedBuild": "10.0.17763.6775", "ProductID": ["11571", "11572"]}],
                           "RevisionHistory": [{"Number": "1.0", "Date": "2025-01-14T08:00:00"}]}]}
jp = os.path.join(tmp, "2025-Jan.json")
with open(jp, "w") as fh:
    json.dump(jdoc, fh)
res = vs.import_file(db, jp)
assert res["type"] == "msrc" and res["records"] == 1, res
assert db.query(VulnAdvisory).filter_by(cve="CVE-2025-21333").one().fixed == "10.0.17763.6775"
db.add(VulnKev(cve="CVE-2025-21333", name="Microsoft Windows Hyper-V Use-After-Free")); db.commit()

W19, W22 = "Microsoft Windows Server 2019 Standard", "Microsoft Windows Server 2022 Datacenter"
w19_old = vm(W19, "NT 10.0.17763.1000", name="w19-old")       # older than every fix in the data
w19 = vm(W19, "NT 10.0.17763.6000", name="w19")
w19_ok = vm(W19, "NT Windows.17763.6775", name="w19-ok")       # broken string, patched
w19_noubr = vm(W19, "NT 10.0.17763", platform=pm, name="w19-noubr")
w22 = vm(W22, "NT 10.0.20348.5200", name="w22")
w25 = vm("Microsoft Windows Server 2025 Standard", "NT 10.0.26100.32900", name="w25")
w11 = vm("Microsoft Windows 11 Enterprise", "NT 10.0.26100.9100", name="w11")
w16 = vm("Microsoft Windows Server 2016 Standard", "NT 10.0.14393.7000", name="w16")
w12 = vm("Microsoft Windows Server 2012 R2 Standard", "NT 6.3.9600.21000", name="w12r2")
ls.recompute(db)
db.expire_all()
f = finding(w19, "CVE-2025-21333")
assert f and f.kev and f.fixed == "10.0.17763.6775" and f.package == "KB5050008" and f.severity == "high", f
assert f.reason == ("Windows Server 2019 · yapı 10.0.17763.6000 · düzeltme 10.0.17763.6775 (KB5050008) "
                    "-> etkileniyor"), f.reason
assert finding(w19, "CVE-2022-21971") is None                   # 6000 >= 2565
w = db.get(VirtualMachine, w19.id)
assert w.vuln_status == "evaluated" and w.vuln_open == 1 and w.vuln_kev == 1 and w.vuln_top == "CVE-2025-21333"
assert "uyarı" not in w.vuln_reason
wo = db.get(VirtualMachine, w19_old.id)
assert wo.vuln_total == 2 and "veri penceresinden eski" in wo.vuln_reason, wo.vuln_reason
assert db.get(VirtualMachine, w19_ok.id).vuln_total == 0 and db.get(VirtualMachine, w19_ok.id).vuln_status == "evaluated"
wn = db.get(VirtualMachine, w19_noubr.id)
assert wn.vuln_status == "unknown" and "UBR" in wn.vuln_reason, wn.vuln_reason
assert {x.cve for x in db.query(VmVuln).filter_by(vm_id=w22.id, closed_at=None)} == {"CVE-2026-6726"}
assert finding(w22, "CVE-2026-6726").package == "KB5120242"
assert {x.cve for x in db.query(VmVuln).filter_by(vm_id=w25.id, closed_at=None)} == {"CVE-2026-6726"}
assert {x.cve for x in db.query(VmVuln).filter_by(vm_id=w11.id, closed_at=None)} == {"CVE-2026-6726"}
assert finding(w11, "CVE-2026-6726").fixed == "10.0.26100.9165"   # client row, not Server 2025's
w6 = db.get(VirtualMachine, w16.id)
assert w6.vuln_status == "unknown" and "Windows Server 2016" in w6.vuln_reason and "yüklenmemiş" in w6.vuln_reason
w2 = db.get(VirtualMachine, w12.id)
assert w2.support_status == "eol" and w2.vuln_status == "skipped"   # 2012 R2: ESU only, not tracked as extended
assert "Windows" in vs.auto_sources(db)
ov = {r["name"]: r for r in vs.sources_overview(db)["rows"]}
assert ov["Windows"]["vms"] >= 6 and len(ov["Windows"]["ecosystems"]) == 5, ov["Windows"]
assert vs.source_of("Windows Server:2019") == "Windows" and vs.source_of("Windows:11-24h2") == "Windows"
# bundle round trip keeps the KB
doc = json.loads(gzip.decompress(vs.export_bundle(db)))
assert vs.bundle_contents(doc)["Windows"] == 4
win_rec = next(r for r in doc["records"] if r["id"] == "MSRC-CVE-2025-21333")
assert win_rec["rows"] == [["CVE-2025-21333", "Windows Server:2019", "windows", "KB5050008", "10.0.17763.6775"]]
# download: index + monthly documents; unchanged months are not fetched again
xml_bytes = open(FX + "msrc-cvrf-sample.xml", "rb").read()
_urls.clear()
INDEX = {"value": [{"ID": "2026-May", "CurrentReleaseDate": "2026-09-25T02:43:53Z"},
                   {"ID": "2026-Apr", "CurrentReleaseDate": "2026-04-14T07:00:00Z"}]}


class _Json:
    status_code = 200

    def __init__(self, d):
        self.d = d

    def raise_for_status(self):
        pass

    def json(self):
        return self.d


def _msrc_get(url, **k):
    _urls.append(url)
    assert "api.msrc.microsoft.com" in url
    if url.endswith("/updates"):
        return _Json(INDEX)
    if url.endswith("/cvrf/2026-May") or url.endswith("/cvrf/2026-Apr"):
        pth = os.path.join(tmp, "m.xml")
        with open(pth, "wb") as fh:
            fh.write(xml_bytes)
        return _File(pth)

    class R404(_File):
        def __init__(self):
            self.status_code = 404

        def raise_for_status(self):
            raise requests.HTTPError("404 Client Error: Not Found for url")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass
    return R404()


_today = vs.msrc_months
vs.msrc_months = lambda n=vs.MSRC_MONTHS, today=None: _today(n, datetime(2026, 5, 20).date())
vs._get = _msrc_get
try:
    out = vs.sync_vendor(db, "Windows")
    assert out["source"] == "api.msrc.microsoft.com" and set(out["versions"]) == {"2026-May", "2026-Apr"}, out
    assert "errors" not in out and len(_urls) == 1 + vs.MSRC_MONTHS, (out, len(_urls))   # 404 = not published
    _urls.clear()
    out = vs.sync_vendor(db, "Windows")
    assert out["unchanged"] == 2 and _urls[0].endswith("/updates") and \
        not any(u.endswith(("2026-May", "2026-Apr")) for u in _urls), (out, _urls)
    INDEX["value"][0]["CurrentReleaseDate"] = "2026-10-01T00:00:00Z"            # May revised
    _urls.clear()
    out = vs.sync_vendor(db, "Windows")
    assert out["unchanged"] == 1 and any(u.endswith("/cvrf/2026-May") for u in _urls), out
finally:
    vs._get = _orig_get
    vs.msrc_months = _today
print("15) Windows (MSRC) ok")

# ------------------------------------------------------------ 16) "not verified" cases (phase 170)
# Debian 12 on VMware: uname -r has only the ABI -> ABI table (seed from the
# Debian archive file names, e.g. linux-image-6.1.0-40-amd64_6.1.153-1)
seed = vs._abi_seed()["12"]
assert seed["6.1.0-40"] == ["6.1.153-1"] and seed["6.1.0-47"] == ["6.1.170-3"] and "6.1.0-19" not in seed
DEB12 = [{"id": f"DEBIAN-CVE-2026-71{n:02d}", "modified": "2026-10-01T00:00:00Z", "upstream": [f"CVE-2026-71{n:02d}"],
          "affected": [{"package": {"ecosystem": "Debian:12", "name": "linux"},
                        "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": fx}]}]}]}
         for n, fx in enumerate(["6.1.158-1", "6.1.153-1", "6.1.140-1", "6.1.80-1", "6.1.70-1", "6.1.90-1",
                                 "6.1.195-1"])]
vs._store(db, vs._osv_records(DEB12), "upload")
D12 = "Debian GNU/Linux 12 (bookworm)"
d40 = vm(D12, "6.1.0-40-amd64", name="deb12-abi40")        # = 6.1.153-1
d19 = vm(D12, "6.1.0-19-amd64", name="deb12-abi19")        # not in the table: between 18 and 20
d57 = vm(D12, "6.1.0-57-amd64", name="deb12-abi57")        # newer than the table
pve = vm("Debian GNU/Linux 13 (trixie)", "7.0.14-23-pve", platform=pm, name="pve-nested")
bpo = vm(D12, "6.12.95+deb12-amd64", name="deb12-bpo")
ls.recompute(db)
db.expire_all()


def st(v, cve):
    f = finding(v, cve)
    return f.status if f else None


assert [st(d40, f"CVE-2026-71{n:02d}") for n in range(7)] == \
    ["affected", None, None, None, None, None, "affected"], [st(d40, f"CVE-2026-71{n:02d}") for n in range(7)]
d = db.get(VirtualMachine, d40.id)
assert d.vuln_status == "evaluated" and "6.1.0-40 (= 6.1.153-1)" in d.vuln_reason and "ABI tablosundan" in d.vuln_reason, d.vuln_reason
assert [st(d19, f"CVE-2026-71{n:02d}") for n in (3, 4, 5)] == ["uncertain", None, "affected"]
assert "kesin bilinmiyor" in finding(d19, "CVE-2026-7103").reason
assert st(d57, "CVE-2026-7106") == "uncertain" and st(d57, "CVE-2026-7100") is None
p_ = db.get(VirtualMachine, pve.id)
assert p_.vuln_status == "unknown" and p_.vuln_reason.startswith("Proxmox VE çekirdeği"), p_.vuln_reason
assert db.get(VirtualMachine, bpo.id).vuln_reason.startswith("Backports çekirdeği")
# a Proxmox Debian VM reports both strings -> learned, the VMware twin becomes exact
vm(D12, "6.1.0-57-amd64", "#1 SMP PREEMPT_DYNAMIC Debian 6.1.195-1 (2026-11-02)", platform=pm, name="deb12-px57")
ls.recompute(db)
db.expire_all()
assert db.query(VulnKernelAbi).filter_by(release="12", abi="6.1.0-57", source="inventory").one().version == "6.1.195-1"
assert st(d57, "CVE-2026-7106") is None and "(= 6.1.195-1)" in db.get(VirtualMachine, d57.id).vuln_reason
# archive listing refresh + the offline package carries the table
LISTING = ('<a href="linux-image-6.1.0-58-amd64_6.1.196-1_amd64.deb">x</a> '
           '<a href="linux-image-6.1.0-58-amd64-dbg_6.1.196-1_amd64.deb">x</a> '
           '<a href="linux-image-6.12.115+deb13-amd64_6.12.115-1_amd64.deb">x</a> '
           '<a href="linux-image-6.1.0-0.deb11.44-amd64_6.1.164-1~deb11u1_amd64.deb">x</a>')
assert vs.parse_abi_listing(LISTING) == [("12", "6.1.0-58", "6.1.196-1")]


class _Txt:
    status_code, text = 200, LISTING

    def raise_for_status(self):
        pass


vs._get = lambda url, **k: _Txt()
try:
    r = vs.sync_debian_abi(db)
finally:
    vs._get = _orig_get
assert r["added"] == 1 and r["seen"] == 1, r
doc = json.loads(gzip.decompress(vs.export_bundle(db)))
assert ["12", "6.1.0-58", "6.1.196-1"] in doc["abi"] and ["12", "6.1.0-57", "6.1.195-1"] in doc["abi"]
db.query(VulnKernelAbi).delete(); db.commit()
assert vs.import_bundle(db, doc)["abi"] == 2
# Tools version explains a missing kernel; Proxmox Windows names the privilege
old_tools = vm("Red Hat Enterprise Linux 8 (64-bit)", None, name="rhel-old-tools")
old_tools.tools_version = "10.3.22"
os_tools = vm("Microsoft Windows Server 2019 (64-bit)", None, name="win-os-tools")
os_tools.tools_version = "unmanaged"
pxw = vm("Windows Server 2019 Standard", "NT 10.0.17763", platform=pm, name="win-px")
db.commit()
ls.recompute(db)
db.expire_all()
assert "Tools 10.3.22" in db.get(VirtualMachine, old_tools.id).vuln_reason
assert "unmanaged" in db.get(VirtualMachine, os_tools.id).vuln_reason
assert "VM.GuestAgent.Unrestricted" in db.get(VirtualMachine, pxw.id).vuln_reason
groups = {g["reason"]: g for g in vs.unknown_overview(db)}
g = groups["Windows güncelleme numarası (UBR) bilinmiyor"]
assert g["count"] >= 2 and "win-px" in g["examples"] and "Proxmox" in g["hint"], g
assert "Proxmox VE çekirdeği (-pve)" in groups and groups["Çekirdek sürümü bilinmiyor"]["count"] >= 2
print("16) not-verified cases ok")

# ------------------------------------------------------------ 17) daily changes-only sync (phase 173)
def _deb(rid, fixed, modified, pkg="linux"):
    return {"id": rid, "modified": modified, "upstream": [rid.replace("DEBIAN-", "")],
            "affected": [{"package": {"ecosystem": "Debian:12", "name": pkg},
                          "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": fixed}]}]}]}


OSV = {"DEBIAN-CVE-2026-9001": _deb("DEBIAN-CVE-2026-9001", "6.1.158-1", "2026-11-01T10:00:00Z"),
       "DEBIAN-CVE-2026-9002": _deb("DEBIAN-CVE-2026-9002", "2.0-1", "2026-11-01T11:00:00Z", pkg="openssl")}
CSV = ["2026-11-01T11:00:00Z,DEBIAN-CVE-2026-9002", "2026-11-01T10:00:00Z,DEBIAN-CVE-2026-9001"]
calls = []


class _Body:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def iter_content(self, n):
        for i in range(0, len(self.data), n):
            yield self.data[i:i + n]

    @property
    def content(self):
        return self.data

    @property
    def text(self):
        return self.data.decode()


def _osv_get(url, headers=None, **k):
    calls.append((url, dict(headers or {})))
    if url.endswith("/Debian/modified_id.csv"):
        return _Body(("\n".join(CSV) + "\n").encode())
    if url.endswith("/Debian/all.zip"):
        if (headers or {}).get("If-None-Match") == '"zip-1"':
            return _Body(b"", 304)
        zp = os.path.join(tmp, "deb.zip")
        with zipfile.ZipFile(zp, "w") as z:
            for rid, rec in OSV.items():
                z.writestr(rid + ".json", json.dumps(rec))
        return _Body(open(zp, "rb").read(), headers={"ETag": '"zip-1"'})
    m = re.search(r"/Debian/(.+)\.json$", url)
    if m:
        rec = OSV.get(requests.utils.unquote(m.group(1)))
        return _Body(json.dumps(rec).encode()) if rec else _Body(b"", 404)
    if "linux-signed-amd64" in url:
        return _Body(b"")
    raise requests.ConnectionError("blocked")


import re  # noqa: E402
db4, _ = make_env("_vuln4")
ss.SessionLocal = _main_session
vs._get = _osv_get
try:
    r1 = vs.sync_osv(db4, ["Debian"])                      # first time: the dump
    assert r1["Debian"]["mode"] == "full" and r1["Debian"]["records"] == 1, r1
    assert vs._cursors(db4)["Debian"] == "2026-11-01T11:00:00", vs._cursors(db4)
    calls.clear()
    r2 = vs.sync_osv(db4, ["Debian"])                      # nothing new: one short read of the list
    assert {k: v for k, v in r2["Debian"].items() if k != "abi"} == \
        {"records": 0, "replaced": 0, "kept": 0, "rows": 0, "mode": "incremental", "changed": 0, "failed": 0}, r2
    assert not any("all.zip" in u for u, _ in calls) and not any(u.endswith(".json") for u, _ in calls)
    # a day later: one kernel record revised, one new non-kernel record
    OSV["DEBIAN-CVE-2026-9001"] = _deb("DEBIAN-CVE-2026-9001", "6.1.159-1", "2026-11-02T08:00:00Z")
    OSV["DEBIAN-CVE-2026-9003"] = _deb("DEBIAN-CVE-2026-9003", "1.0-1", "2026-11-02T09:00:00Z", pkg="curl")
    CSV[:0] = ["2026-11-02T09:00:00Z,DEBIAN-CVE-2026-9003", "2026-11-02T08:00:00Z,DEBIAN-CVE-2026-9001"]
    calls.clear()
    r3 = vs.sync_osv(db4, ["Debian"])
    assert r3["Debian"]["mode"] == "incremental" and r3["Debian"]["changed"] == 2 and r3["Debian"]["replaced"] == 1, r3
    assert sorted(u.rsplit("/", 1)[1] for u, _ in calls if u.endswith(".json")) == \
        ["DEBIAN-CVE-2026-9001.json", "DEBIAN-CVE-2026-9003.json"]
    assert db4.query(VulnAdvisory).filter_by(cve="CVE-2026-9001").one().fixed == "6.1.159-1"
    assert vs._cursors(db4)["Debian"] == "2026-11-02T09:00:00"
    # too many changes (a kernel update day) -> the dump again, answered 304 when unchanged
    CSV[:0] = ["2026-11-03T09:00:00Z,DEBIAN-CVE-2026-9002"]
    _lim = vs.OSV_MAX_CHANGED
    vs.OSV_MAX_CHANGED = 0
    calls.clear()
    r4 = vs.sync_osv(db4, ["Debian"])
    vs.OSV_MAX_CHANGED = _lim
    zipcall = [h for u, h in calls if u.endswith("all.zip")]
    assert zipcall and zipcall[0].get("If-None-Match") == '"zip-1"', calls
    assert r4["Debian"]["mode"] == "full" and r4["Debian"].get("unchanged"), r4
finally:
    vs._get = _orig_get
print("17a) incremental OSV ok")

# changes-only package for the offline server, with gap detection
_info = {}
full = json.loads(gzip.decompress(vs.export_bundle(db4, delta=True, info=_info)))   # first package: complete
assert _info == {"partial": False} and not full.get("partial")
assert not full.get("partial") and vs.bundle_info(db4)["changed_records"] == 0
vs._store(db4, vs._osv_records([_deb("DEBIAN-CVE-2026-9004", "6.1.160-1", "2026-11-04T08:00:00Z")]), "osv")
assert vs.bundle_info(db4)["changed_records"] == 1
part = json.loads(gzip.decompress(vs.export_bundle(db4, delta=True, info=_info)))
assert _info == {"partial": True}
assert part["partial"] and part["since"] == full["generated_at"], part
assert [r["id"] for r in part["records"]] == ["DEBIAN-CVE-2026-9004"] and [c[0] for c in part["cves"]] == ["CVE-2026-9004"]
db5, _ = make_env("_vuln5")
ss.SessionLocal = _main_session
r = vs.import_bundle(db5, part)                          # the full one was never imported here
assert r["partial"] and r["gap"] == "-", r
db6, _ = make_env("_vuln6")
ss.SessionLocal = _main_session
assert "gap" not in vs.import_bundle(db6, full)
r = vs.import_bundle(db6, part)
assert r["partial"] and "gap" not in r and r["records"] == 1, r
assert vs.bundle_info(db6)["last_applied"] == part["generated_at"]
print("17b) changes-only package ok")

# vendor files are fetched only when changed (ETag -> 304), Photon not re-imported
ph_bytes = open(FX + "cve_data_photon5.0.json", "rb").read()
pcalls = []


def _ph_get(url, headers=None, **k):
    pcalls.append(dict(headers or {}))
    if (headers or {}).get("If-None-Match") == '"ph-1"':
        return _Body(b"", 304)
    return _Body(ph_bytes, headers={"ETag": '"ph-1"'})


vs._get = _ph_get
try:
    a1 = vs.sync_vendor(db4, "Photon OS")
    n_rows = db4.query(VulnAdvisory).filter(VulnAdvisory.ecosystem.like("Photon OS:%")).count()
    max_id = db4.query(func.max(VulnAdvisory.id)).scalar()
    a2 = vs.sync_vendor(db4, "Photon OS")
finally:
    vs._get = _orig_get
assert all(v != "same" for v in a1["versions"].values()) and set(a2["versions"].values()) == {"same"}, (a1, a2)
assert pcalls[-1].get("If-None-Match") == '"ph-1"' and n_rows > 0
assert db4.query(func.max(VulnAdvisory.id)).scalar() == max_id      # nothing re-inserted -> no recompute
print("17c) conditional vendor download ok")

# ------------------------------------------------------------ 18) stop a running job, automatic download off (phase 174)
import time  # noqa: E402
hits = []


def _slow_get(url, **k):
    hits.append(url)
    time.sleep(0.05)
    raise requests.ConnectionError("slow network")


def _many_downloads(d):
    for i in range(400):                       # like a long sync: one request after the other
        try:
            vs._get(f"https://example.invalid/{i}")
        except requests.ConnectionError:
            pass
    return "finished"


from app.core import outbound as _ob  # noqa: E402
_ob_get, _ob.get = _ob.get, _slow_get                       # the real vs._get (with its check point) runs
try:
    assert vs.cancel_job() is False                         # nothing running
    assert vs.run_background("manual", _many_downloads)
    time.sleep(0.4)
    assert vs.cancel_job() is True
    for _ in range(100):
        if not vs.JOB["running"]:
            break
        time.sleep(0.05)
finally:
    _ob.get = _ob_get
assert not vs.JOB["running"] and vs.JOB["cancelled"] and vs.JOB["ok"] is False, vs.JOB
assert "durduruldu" in vs.JOB["message"] and len(hits) < 60, (vs.JOB, len(hits))
# the check point lives in the real _get: a cancelled job makes no further request
vs.JOB["cancel"] = True
threading.current_thread().name = "vuln-test"
try:
    vs._get("https://example.invalid/never")
    raise AssertionError("request made after Stop")
except vs.JobCancelled:
    pass
finally:
    vs.JOB["cancel"] = False
    threading.current_thread().name = "MainThread"
# automatic download off: the boot / daily jobs do nothing
assert vs.auto_sync_enabled(db) is True and vs.meta(db)["auto"] is True
vs.set_auto_sync(db, False)
started = []
_rb, vs.run_background = vs.run_background, lambda kind, fn: started.append(kind) or True
import app.database as _dbmod  # noqa: E402
_sl, _dbmod.SessionLocal = _dbmod.SessionLocal, ss.SessionLocal
try:
    vs.scheduled_osv(); vs.scheduled_kev(); vs.scheduled_boot()
    assert started == [], started
    vs.set_auto_sync(db, True)
    vs.scheduled_kev()
    assert started == ["kev"], started
finally:
    vs.run_background = _rb
    _dbmod.SessionLocal = _sl
print("18) stop / automatic download ok")

print("ALL VULN TESTS PASSED")
