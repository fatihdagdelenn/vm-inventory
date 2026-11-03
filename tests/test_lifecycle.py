"""
OS lifecycle (EOL) suite (phase 158).

Seed loading (newest data wins), import formats, endoflife.date sync offline /
online, status computation (supported / soon / extended / eol / unknown with
reasons), extended-support exceptions (vm > tag > all), the 'soon' threshold,
search, sort, dashboard counts, exports and the recompute hooks (platform sync,
tag edit, admin API).

Run:  PYTHONPATH=. python3 tests/test_lifecycle.py
"""
import io
import sys
import types
from datetime import date, datetime, timedelta
sys.path.insert(0, "tests")

from _actor_harness import make_env, FakeCollector, run_sync  # noqa: E402

db, ss = make_env("_lifecycle")
from app.models import (Platform, VirtualMachine, Tag, OsLifecycle,  # noqa: E402
                        LifecycleOverride)
from app.services import lifecycle_service as ls  # noqa: E402
from app.core.search import apply_vm_search  # noqa: E402

NS = types.SimpleNamespace
TODAY = date(2026, 11, 3)

# ------------------------------------------------------------ 1) seed
r1 = ls.ensure_seed(db); db.commit()
assert r1["added"] > 300 and r1["updated"] == 0, r1
r2 = ls.ensure_seed(db); db.commit()
assert r2["added"] == 0 and r2["updated"] == 0 and r2["kept"] == r1["added"], r2
u2404 = db.query(OsLifecycle).filter_by(distro="ubuntu", version="24.04").one()
assert u2404.eol_standard == date(2029, 5, 31) and u2404.eol_extended == date(2034, 4, 25)
assert db.query(OsLifecycle).filter_by(distro="photon", version="5.0").one().eol_standard is None
print("1) seed ok")

# renamed product id (vmware-photon -> photon): old rows dropped, exceptions moved
db.add(OsLifecycle(distro="vmware-photon", version="5.0", source="seed", updated_at=datetime(2026, 1, 1)))
db.add(LifecycleOverride(scope="all", distro="vmware-photon", extended=True)); db.commit()
assert ls.apply_renames(db) == 1; db.commit()
assert db.query(OsLifecycle).filter_by(distro="vmware-photon").count() == 0
assert db.query(LifecycleOverride).one().distro == "photon"
db.query(LifecycleOverride).delete(); db.commit()
assert db.query(OsLifecycle).filter_by(distro="linux", version="5.18").one().eol_standard == date(2022, 8, 21)

# ------------------------------------------------------------ 2) import / newest wins
v1 = {"schema_version": "1.2.0", "generated_at": "2027-01-01T00:00:00+00:00",
      "last_modified": "2027-01-01T00:00:00+00:00",
      "result": {"name": "ubuntu", "releases": [
          {"name": "24.04", "releaseDate": "2024-04-25", "isEol": False, "eolFrom": "2029-06-30",
           "isEoes": False, "eoesFrom": "2034-04-25"},
          {"name": "99.04", "releaseDate": "2099-04-01", "isEol": False, "eolFrom": None}]}}
rows, stamp = ls.parse_import(v1)
assert len(rows) == 2 and stamp == datetime(2027, 1, 1)
res = ls.upsert_rows(db, rows, "manual", stamp); db.commit()
assert res == {"added": 1, "updated": 1, "kept": 0}, res
db.expire_all()
u2404 = db.query(OsLifecycle).filter_by(distro="ubuntu", version="24.04").one()
assert (u2404.eol_standard, u2404.source) == (date(2029, 6, 30), "manual")
assert ls.ensure_seed(db)["updated"] == 0          # older seed does not undo newer data
old = dict(v1, last_modified="2020-01-01T00:00:00+00:00", generated_at="2020-01-01T00:00:00+00:00")
assert ls.upsert_rows(db, *ls.parse_import(old)[:1], "manual", datetime(2020, 1, 1))["kept"] == 2
# accepted shapes
assert len(ls.parse_import([v1, v1])[0]) == 4
assert len(ls.parse_import({"ubuntu": v1})[0]) == 2
assert ls.parse_import({"products": {"debian": [{"cycle": "12", "eol": "2028-06-30"}]}})[0][0]["version"] == "12"
for bad in ({}, [], {"foo": 1}, "x", [{"nope": 1}]):
    try:
        ls.parse_import(bad); raise SystemExit(f"accepted {bad!r}")
    except ValueError:
        pass
eolflag = ls.rows_from_api_v1({"result": {"name": "x", "releases": [
    {"name": "1", "isEol": True, "eolFrom": None}]}})[0]
assert eolflag["eol_reached"] is True
db.rollback()
print("2) import / newest-wins ok")

# ------------------------------------------------------------ 3) status computation
vc = Platform(name="vc", type="vcenter", host="v", environment="production", enabled=True)
pm = Platform(name="pm", type="proxmox", host="p", environment="production", enabled=True)
db.add_all([vc, pm]); db.commit()
N = 0


def vm(guest_os, kernel=None, platform=vc, ts="guestToolsRunning", power="running",
       boot=True, ip="10.0.0.1", tags=()):
    global N
    N += 1
    v = VirtualMachine(platform_id=platform.id, external_id=f"x{N}", vmid=f"x{N}", name=f"vm{N}",
                       guest_os=guest_os, kernel=kernel, tools_status=ts, power_state=power,
                       last_boot=datetime(2026, 10, 1) if boot else None, ip_addresses=ip)
    v.tags = [db.query(Tag).filter_by(name=t).first() or Tag(name=t) for t in tags]
    db.add(v); db.commit()
    return v


def st(v, soon=180, today=TODAY):
    db.expire_all()
    return ls.compute(db.get(VirtualMachine, v.id), ls._Index(db), soon, today)


u24 = vm("Ubuntu 24.04.2 LTS", "6.8.0-57-generic")
assert st(u24)[:3] == ("supported", date(2029, 6, 30), "standard")
assert st(u24, today=date(2029, 3, 1))[0] == "soon"
assert st(u24, soon=30, today=date(2029, 3, 1))[0] == "supported"
u18 = vm("Ubuntu 18.04.6 LTS", tags=("legacy",))
assert st(u18)[:3] == ("eol", date(2023, 5, 31), "extended_available")      # ESM exists, not owned
c7 = vm("CentOS Linux 7 (Core)")
assert st(c7)[:3] == ("eol", date(2024, 6, 30), "ended")
ph5 = vm("VMware Photon OS/Linux", "6.1.126-5.ph5")
s = st(ph5)
assert s[0] == "supported" and s[1] is None and s[2] == "no_end_date" and s[3] == "Photon OS 5.0"
w12 = vm("Microsoft Windows Server 2012 R2 Standard")
assert st(w12)[:3] == ("eol", date(2023, 10, 10), "ended")              # ESU ended 2026-10-13
# rolling releases: judged by the running kernel's upstream support
kali = vm("Kali GNU/Linux Rolling", "5.18.0-kali5-amd64")                    # prod case
s = st(kali)
assert s[:3] == ("eol", date(2022, 8, 21), "rolling_kernel_eol") and s[4] == "estimated", s
assert s[3] == "Kali Linux (rolling) · kernel 5.18", s
arch = vm("Arch Linux", "6.12.10-arch1-1")
assert st(arch)[:3] == ("supported", date(2028, 12, 31), "rolling_kernel"), st(arch)
assert st(vm("Kali GNU/Linux Rolling"))[:3] == ("unknown", None, "rolling_no_kernel")
assert st(vm("Alpine Linux v3.20"))[0] in ("supported", "soon", "eol")        # versioned, not rolling
# release unknown, but every possible release is past EOL
c45 = vm("CentOS 4/5 (64-bit)")
s = st(c45)
assert s[0] == "eol" and s[2] == "all_releases_eol" and s[4] == "estimated", s
w10 = vm("Microsoft Windows 10 Pro")
assert st(w10)[0] == "eol" and st(w10)[2] == "all_releases_eol"
w10l = vm("Microsoft Windows 10 Enterprise LTSC 2021")        # LTSC 2021 lives until 2027
assert st(w10l)[0] == "unknown"
# unknown + reasons
assert st(vm("Other 2.6.x Linux (64-bit)"))[:3] == ("unknown", None, "tools_old")
assert st(vm("Other 2.6.x Linux (64-bit)", ts="guestToolsNotRunning"))[2] == "no_agent"
assert st(vm("Ubuntu Linux (64-bit)", ts="", power="stopped", boot=False, ip=""))[2] == "never_powered"
assert st(vm("Linux", platform=pm, ts="", ip=""))[2] == "no_agent"
assert st(vm("Windows 11 Pro"))[2] == "version_unknown"                       # agent name, no build
assert st(vm("Ubuntu 98.04 LTS"))[:3] == ("unknown", None, "no_data")
# estimated identity still gets a status, marked estimated
rh7 = vm("Red Hat Enterprise Linux 7 (64-bit)", ts="guestToolsNotRunning")
s = st(rh7)
assert s[0] == "eol" and s[4] == "estimated" and s[3] == "RHEL 7", s
print("3) status computation ok")

# ------------------------------------------------------------ 4) exceptions vm > tag > all
db.add(LifecycleOverride(scope="all", distro="ubuntu", extended=True)); db.commit()
assert st(u18)[:3] == ("extended", date(2028, 4, 26), "extended_subscription")
assert st(u18, today=date(2028, 1, 1))[0] == "soon"                           # ESM ending
db.add(LifecycleOverride(scope="tag", target="legacy", extended=False)); db.commit()
assert st(u18)[0] == "eol"                                                     # tag beats all
db.add(LifecycleOverride(scope="vm", target=f"{vc.id}:{u18.vmid}", extended=True)); db.commit()
assert st(u18)[0] == "extended"                                                # vm beats tag
assert st(c7)[0] == "eol"                       # 'all' rule limited to ubuntu; CentOS has no ELS
db.query(LifecycleOverride).delete(); db.commit()
print("4) exceptions ok")

# ------------------------------------------------------------ 5) recompute, search, sort, dashboard
counts = ls.recompute(db)
assert sum(counts.values()) == db.query(VirtualMachine).count()
q = lambda s_: {v.name for v in apply_vm_search(db.query(VirtualMachine), s_)}
db.expire_all()
eol_names = {v.name for v in db.query(VirtualMachine) if v.support_status == "eol"}
assert q("destek:eol") == eol_names == q("support:eol") and u18.name in eol_names
assert q("destek:bilinmiyor") == q("support:unknown")
assert q("destek:eol,bilinmiyor") == q("destek:eol") | q("destek:unknown")
assert q("destek:destekli") >= {u24.name, ph5.name}
assert q("destek:yakinda") == set()
import app.api.vms as vms_api  # noqa: E402
U = NS(username="t", role="admin")
items = vms_api.list_vms(sort="support", order="asc", per_page=200, db=db, user=U)["items"]
ranks = [{"eol": 0, "soon": 1, "extended": 2, "supported": 3}.get(i["support_status"], 4) for i in items]
assert ranks == sorted(ranks), ranks
assert items[0]["support_until"] and "support_reason" in items[0]
import app.api.dashboard as dash  # noqa: E402
sup = dash.summary(db=db, user=None)["support"]
assert sup["eol"] == len(eol_names) and set(sup) == {"eol", "soon", "extended", "unknown", "supported"}
print("5) recompute / search / sort / dashboard ok")

# ------------------------------------------------------------ 6) exports
from app.services import report_service as rs  # noqa: E402
cols = [f for _, f in rs.VM_COLUMNS]
assert cols[cols.index("kernel") + 1: cols.index("kernel") + 3] == ["support_status", "support_until"]
v = db.query(VirtualMachine).filter_by(name=c7.name).one()
vals = rs._row_values(v, [c for c in rs.VM_COLUMNS if c[1] in ("support_status", "support_until")])
assert vals == ["EOL", "2024-06-30"], vals
import app.api.reports as rep  # noqa: E402
rep.log_audit = lambda *a, **k: None
for fmt in ("xlsx", "csv", "pdf"):
    assert len(rep.export_vms(fmt=fmt, q="", db=db, user=U).body) > 200
csv = rep.export_vms(fmt="csv", q="", db=db, user=U).body.decode("utf-8-sig")
assert "Destek Bitişi" in csv and "Bilinmiyor" in csv and "2024-06-30" in csv
print("6) exports ok")

# ------------------------------------------------------------ 7) endoflife.date sync offline / online
import requests  # noqa: E402
calls = []


def offline(url, **kw):
    calls.append(url)
    raise requests.exceptions.ConnectionError("Name or service not known")


_orig = requests.get
requests.get = offline
res = ls.sync_from_api(db)
assert res["ok"] is False and len(calls) == 1, (res, calls)     # stops at the first failure
m = ls.meta(db)
assert "ConnectionError" in m["last_error"] and m["last_sync"] is None and m["cycles"] > 300


class Resp:
    def __init__(self, url):
        self.status_code = 404 if url.endswith("/photon") else 200
        self.url = url

    def raise_for_status(self):
        pass

    def json(self):
        name = self.url.rsplit("/", 1)[1]
        return {"last_modified": "2027-06-01T00:00:00+00:00", "result": {"name": name, "releases": [
            {"name": "1", "releaseDate": "2027-01-01", "isEol": False, "eolFrom": "2030-01-01"}]}}


requests.get = lambda url, **kw: Resp(url)
res = ls.sync_from_api(db)
requests.get = _orig
assert res["ok"] and "photon" not in res["products"] and len(res["products"]) == len(ls.PRODUCTS) - 1
assert ls.meta(db)["last_error"] is None and ls.meta(db)["last_sync"]
assert db.query(OsLifecycle).filter_by(distro="debian", version="1").one().source == "endoflife.date"
print("7) endoflife.date sync offline / online ok")

# ------------------------------------------------------------ 8) hooks: platform sync, tag edit, admin API
B = dict(power_state="poweredOn", host_name="h1", cluster="c1", cpu_count=2, ram_mb=2048,
         tools_status="guestToolsRunning", ip_addresses="10.9.9.9")
vc2 = Platform(name="vc2", type="vcenter", host="v2", environment="production", enabled=True)
db.add(vc2); db.commit()
run_sync(ss, vc2.id, FakeCollector(vms=[dict(B, external_id="s1", name="synced01",
                                            guest_os="Ubuntu 18.04.6 LTS")]))
db.expire_all()
s1 = db.query(VirtualMachine).filter_by(external_id="s1").one()
assert (s1.support_status, s1.support_os) == ("eol", "Ubuntu 18.04"), (s1.support_status, s1.support_os)

import app.api.lifecycle as lapi  # noqa: E402
for mod in (lapi, vms_api):
    mod.validate_csrf = lambda *a, **k: None
    mod.log_audit = lambda *a, **k: None
r = lapi.add_override(None, {"scope": "tag", "target": "esm", "distro": "ubuntu", "extended": True},
                      db=db, user=U)
assert r["item"]["scope"] == "tag"
vms_api.update_vm_meta(s1.id, None, {"tags": ["esm"]}, db=db, user=U)       # tag added -> recomputed
db.expire_all()
assert db.get(VirtualMachine, s1.id).support_status == "extended"
r = lapi.add_override(None, {"scope": "vm", "target": "synced01", "extended": False}, db=db, user=U)
db.expire_all()
assert db.get(VirtualMachine, s1.id).support_status == "eol"
lapi.delete_override(r["item"]["id"], None, db=db, user=U)
db.expire_all()
assert db.get(VirtualMachine, s1.id).support_status == "extended"
from fastapi import HTTPException  # noqa: E402
for bad in ({"scope": "x"}, {"scope": "tag"}, {"scope": "vm", "target": "nope"},
            {"scope": "all", "distro": "beos"}):
    try:
        lapi.add_override(None, dict(bad), db=db, user=U); raise SystemExit(f"accepted {bad}")
    except HTTPException as e:
        assert e.status_code in (400, 404)
r = lapi.lifecycle_settings(None, {"soon_days": 3000}, db=db, user=U)
db.expire_all()
assert db.query(VirtualMachine).filter_by(name=u24.name).one().support_status == "soon"
lapi.lifecycle_settings(None, {"soon_days": 180}, db=db, user=U)
try:
    lapi.lifecycle_settings(None, {"soon_days": 0}, db=db, user=U); raise SystemExit("0 days accepted")
except HTTPException as e:
    assert e.status_code == 400
r = lapi.lifecycle_import(None, v1, db=db, user=U)
assert r["rows"] == 2
try:
    lapi.lifecycle_import(None, {"foo": 1}, db=db, user=U); raise SystemExit("bad json accepted")
except HTTPException as e:
    assert e.status_code == 400
st_ = lapi.lifecycle_status(db=db, user=U)
assert st_["meta"]["soon_days"] == 180 and any(p["distro"] == "ubuntu" for p in st_["products"])
print("8) hooks / admin API ok")

print("LIFECYCLE SUITE OK")
