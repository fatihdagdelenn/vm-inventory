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
import zipfile
from datetime import datetime
sys.path.insert(0, "tests")

from _actor_harness import make_env  # noqa: E402

db, ss = make_env("_vuln")
from app.core.pkgversion import cvss3_score, dpkg_cmp, rpm_cmp  # noqa: E402
from app.models import (ChangeHistory, Platform, VirtualMachine, VmVuln,  # noqa: E402
                        VulnAdvisory, VulnCve, VulnKev, LifecycleOverride)
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
assert win.vuln_status == "skipped" and "Linux" in win.vuln_reason
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
assert d_vc.vuln_status == "unknown" and "uname -v" in d_vc.vuln_reason
assert db.query(VmVuln).filter_by(vm_id=d_vc.id).count() == 0
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
assert vs.import_file(db2, bp)["kept"] == r["records"]          # same bundle again: nothing new
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


requests.get = _offline
try:
    vs.job_sync(db, osv=True)
    raise AssertionError("offline sync must raise")
except RuntimeError as exc:
    assert "ConnectionError" in str(exc)
finally:
    requests.get = _orig
m = vs.meta(db)
assert "no route" in m["last_error"] and m["rows"] > 0 and m["kev"] == 2


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
try:
    res = vs.job_sync(db, osv=True)
finally:
    requests.get = _orig
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

print("ALL VULN TESTS PASSED")
