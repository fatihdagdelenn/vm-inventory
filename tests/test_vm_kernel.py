"""
Kernel column regression suite (phase 154).

Covers: VMware detailed-data parsing (kernelVersion, Linux only, live data
before the persistent extraConfig copy), sync persistence (an absent key keeps
the stored value), VM list sort, free-text + kernel: search, and the
"Çekirdek" column in Excel / CSV / PDF exports.

Run:  PYTHONPATH=. python3 tests/test_vm_kernel.py
"""
import io
import sys
import types
sys.path.insert(0, "tests")

from _actor_harness import make_env, FakeCollector, run_sync  # noqa: E402

db, ss = make_env("_kernel")

from app.models import Platform, VirtualMachine  # noqa: E402
from app.collectors.vmware_collector import (  # noqa: E402
    _guest_os_and_kernel, _best_guest_os, _parse_detailed, _detailed_fields, _detailed_kernel)
from app.core.search import apply_vm_search  # noqa: E402
from app.services import report_service as rs  # noqa: E402
import app.api.vms as vms_api  # noqa: E402
import app.api.reports as rep_api  # noqa: E402

NS = types.SimpleNamespace
LINUX = ("architecture='X86' bitness='64' buildNumber='' cpeString='cpe:/o:rocky:rocky:9' "
         "distroAddlVersion='9.4 (Blue Onyx)' distroName='Rocky Linux' distroVersion='9.4' "
         "familyName='Linux' kernelVersion='5.14.0-427.13.1.el9_4.x86_64' "
         "prettyName='Rocky Linux 9.4 (Blue Onyx)'")
WINDOWS = ("architecture='X86' bitness='64' buildNumber='20348' distroName='Windows' "
           "distroVersion='10.0' familyName='Windows' kernelVersion='20348' "
           "prettyName='Windows Server 2022, 64-bit (Build 20348.2582)'")


def vmobj(extra=None, calls=None):
    """Fake pyVmomi VM; counts vm.config reads (extraConfig is expensive)."""
    class VM:
        @property
        def config(self):
            if calls is not None:
                calls.append(1)
            return NS(extraConfig=[NS(key="guestinfo.detailed.data", value=extra)] if extra else [])
    return VM()


# --- 1) parser ---
assert _detailed_kernel(_detailed_fields(LINUX)) == "5.14.0-427.13.1.el9_4.x86_64"
assert _detailed_kernel(_detailed_fields(WINDOWS)) == ""          # build number, not a kernel
assert _detailed_kernel(_detailed_fields("familyName='Linux'")) == ""
assert _parse_detailed(LINUX) == "Rocky Linux 9.4 (Blue Onyx)"   # old helper unchanged
cfg = NS(guestFullName="Rocky Linux (64-bit)")

calls = []
assert _guest_os_and_kernel(vmobj(None, calls), NS(guestDetailedData=LINUX), cfg) == \
    ("Rocky Linux 9.4 (Blue Onyx)", "5.14.0-427.13.1.el9_4.x86_64")
assert not calls, "live data answered both -> extraConfig must not be read"

calls = []
assert _guest_os_and_kernel(vmobj(None, calls), NS(guestDetailedData=WINDOWS), cfg)[1] == ""
assert not calls, "Windows family -> no kernel to look for, no extraConfig read"

# powered-off VM: no live data, persistent copy in extraConfig
assert _guest_os_and_kernel(vmobj(LINUX), NS(guestDetailedData=None), cfg) == \
    ("Rocky Linux 9.4 (Blue Onyx)", "5.14.0-427.13.1.el9_4.x86_64")
# no detailed data at all (old Tools): catalog name, no kernel
assert _guest_os_and_kernel(vmobj(None), NS(guestDetailedData=None, guestFullName=""), cfg) == \
    ("Rocky Linux (64-bit)", "")
assert _best_guest_os(vmobj(None), NS(guestDetailedData=LINUX), cfg) == "Rocky Linux 9.4 (Blue Onyx)"
print("1) parser ok")

# --- 2) sync: kernel stored; a round without the key keeps it ---
p = Platform(name="vc", type="vcenter", host="v", environment="production", enabled=True)
db.add(p); db.commit()
B = dict(power_state="poweredOn", host_name="h1", cluster="c1", cpu_count=2, ram_mb=2048)
vms = [dict(B, external_id="vm-1", name="rocky01", guest_os="Rocky Linux 9.4", kernel="5.14.0-427.13.1.el9_4.x86_64"),
       dict(B, external_id="vm-2", name="ubuntu01", guest_os="Ubuntu 24.04.1 LTS", kernel="6.8.0-45-generic"),
       dict(B, external_id="vm-3", name="win01", guest_os="Windows Server 2022")]
run_sync(ss, p.id, FakeCollector(vms=vms)); db.expire_all()
k = {v.name: v.kernel for v in db.query(VirtualMachine).all()}
assert k == {"rocky01": "5.14.0-427.13.1.el9_4.x86_64", "ubuntu01": "6.8.0-45-generic", "win01": None}, k
vms[0] = {x: y for x, y in vms[0].items() if x != "kernel"}       # Tools silent this round
run_sync(ss, p.id, FakeCollector(vms=vms)); db.expire_all()
assert db.query(VirtualMachine).filter_by(name="rocky01").one().kernel == "5.14.0-427.13.1.el9_4.x86_64"
print("2) sync ok")

# --- 3) list: field, sort (case-insensitive, NULL handled), search ---
U = NS(username="t", role="admin")
lst = lambda **kw: vms_api.list_vms(db=db, user=U, **kw)["items"]
items = lst(sort="kernel", order="asc")
assert all("kernel" in i for i in items)
order = [i["name"] for i in items if i["kernel"]]
assert order == ["rocky01", "ubuntu01"], order
order = [i["name"] for i in lst(sort="kernel", order="desc") if i["kernel"]]
assert order == ["ubuntu01", "rocky01"], order
assert "kernel" in vms_api.SORTABLE and "kernel" in vms_api.CASE_INSENSITIVE
q = lambda s: {v.name for v in apply_vm_search(db.query(VirtualMachine), s)}
assert q("el9_4") == {"rocky01"}                    # free text covers kernel
assert q("kernel:6.8") == {"ubuntu01"}
assert q("cekirdek:5.14") == {"rocky01"}
assert q("kernel:yok") == {"win01"}
print("3) list / sort / search ok")

# --- 4) exports: column right after the OS, in every format ---
fields = [f for _, f in rs.VM_COLUMNS]
assert fields[fields.index("guest_os") + 1] == "kernel"
assert ("Çekirdek", "kernel") in rs.VM_COLUMNS
rep_api.log_audit = lambda *a, **k: None
for fmt in ("xlsx", "csv", "pdf"):
    body = rep_api.export_vms(fmt=fmt, q="", db=db, user=U).body
    assert len(body) > 200, fmt
csv = rep_api.export_vms(fmt="csv", q="", db=db, user=U).body.decode("utf-8-sig")
assert "Çekirdek" in csv and "6.8.0-45-generic" in csv
from openpyxl import load_workbook  # noqa: E402
wb = load_workbook(io.BytesIO(rep_api.export_vms(fmt="xlsx", q="", db=db, user=U).body))
cells = [c for row in wb.worksheets[0].iter_rows(values_only=True) for c in row]
assert "Çekirdek" in cells and "5.14.0-427.13.1.el9_4.x86_64" in cells
pdf = rep_api.export_vms(fmt="pdf", q="", db=db, user=U).body
assert pdf[:4] == b"%PDF"
print("4) exports ok")

print("KERNEL SUITE OK")
