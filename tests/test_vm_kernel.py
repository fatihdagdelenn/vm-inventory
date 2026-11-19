"""
Kernel column regression suite (phase 154).

Covers: VMware detailed-data parsing (kernelVersion for Linux / FreeBSD /
other families, NT version for Windows, live data before the persistent
extraConfig copy), Proxmox agent kernel (Windows -> NT version), sync persistence (an absent key keeps
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
from app.collectors.proxmox_collector import _agent_kernel  # noqa: E402
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
WIN_NOPRETTY = ("buildNumber='17763' distroName='Windows' distroVersion='10.0' "
                "familyName='Windows' kernelVersion='17763.6293'")
FREEBSD = ("architecture='X86' bitness='64' distroName='FreeBSD' distroVersion='13.2' "
           "familyName='FreeBSD' kernelVersion='13.2-RELEASE-p4' prettyName='FreeBSD 13.2-RELEASE-p4'")


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
assert _detailed_kernel(_detailed_fields(WINDOWS)) == "NT 10.0.20348.2582"   # build + UBR
assert _detailed_kernel(_detailed_fields(WIN_NOPRETTY)) == "NT 10.0.17763.6293"
assert _detailed_kernel(_detailed_fields("familyName='Windows' distroVersion='10.0'")) == ""
# some Tools versions send distroVersion='Windows' (was "NT Windows.17763.6775", phase 168)
assert _detailed_kernel(_detailed_fields("familyName='Windows' distroVersion='Windows' kernelVersion='17763' "
                                         "prettyName='Windows Server 2019 (Build 17763.6775)'")) == "NT 10.0.17763.6775"
assert _detailed_kernel(_detailed_fields(FREEBSD)) == "13.2-RELEASE-p4"
assert _detailed_kernel(_detailed_fields("familyName='Linux'")) == ""
# Proxmox QEMU agent get-osinfo
assert _agent_kernel({"id": "mswindows", "kernel-release": "20348", "kernel-version": "10.0"}) == "NT 10.0.20348"
assert _agent_kernel({"id": "ubuntu", "kernel-release": "6.8.0-45-generic",
                      "kernel-version": "#45-Ubuntu SMP"}) == "6.8.0-45-generic"
assert _agent_kernel({"id": "freebsd", "kernel-release": "14.1-RELEASE"}) == "14.1-RELEASE"
assert _agent_kernel({}) == ""
assert _parse_detailed(LINUX) == "Rocky Linux 9.4 (Blue Onyx)"   # old helper unchanged
cfg = NS(guestFullName="Rocky Linux (64-bit)")

calls = []
assert _guest_os_and_kernel(vmobj(None, calls), NS(guestDetailedData=LINUX), cfg) == \
    ("Rocky Linux 9.4 (Blue Onyx)", "5.14.0-427.13.1.el9_4.x86_64")
assert not calls, "live data answered both -> extraConfig must not be read"

calls = []
assert _guest_os_and_kernel(vmobj(None, calls), NS(guestDetailedData=WINDOWS), cfg)[1] == "NT 10.0.20348.2582"
assert not calls, "Windows answered from live data -> no extraConfig read"

# powered-off VM: no live data, persistent copy in extraConfig
assert _guest_os_and_kernel(vmobj(LINUX), NS(guestDetailedData=None), cfg) == \
    ("Rocky Linux 9.4 (Blue Onyx)", "5.14.0-427.13.1.el9_4.x86_64")
# Tools too old for detailed data (CentOS 4/5, Tools 10.x): catalog name, no kernel
calls = []
assert _guest_os_and_kernel(vmobj(None, calls), NS(guestDetailedData="", guestFullName="CentOS 4/5 (64-bit)"),
                            NS(guestFullName="CentOS 4/5 (64-bit)")) == ("CentOS 4/5 (64-bit)", "")
assert calls, "no live data -> persistent copy is checked"
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

# --- 5) phase 170: Tools version, Windows update revision through the Proxmox agent ---
from app.collectors.vmware_collector import _tools_version  # noqa: E402
from app.collectors import proxmox_collector as pxc  # noqa: E402
assert _tools_version(12389) == "12.3.5" and _tools_version(10358) == "10.3.22"
assert _tools_version(2147483647) == "unmanaged" and _tools_version(None) == "" and _tools_version("x") == ""
assert pxc._parse_ver_output("\r\nMicrosoft Windows [Version 10.0.17763.6775]\r\n", "NT 10.0.17763") == "NT 10.0.17763.6775"
assert pxc._parse_ver_output("Microsoft Windows [Sürüm 10.0.17763.6775]", "NT 10.0.17763") == "NT 10.0.17763.6775"
assert pxc._parse_ver_output("Microsoft Windows [Version 10.0.20348.2700]", "NT 10.0.17763") == ""   # other build


class _QA:
    def __init__(self, deny=False):
        self.deny, self.calls = deny, []

    def agent(self, cmd):
        qa = self

        class C:
            def post(self, **k):
                qa.calls.append((cmd, k))
                if qa.deny:
                    raise RuntimeError("403 Forbidden: Permission check failed (VM.GuestAgent.Unrestricted)")
                return {"pid": 7}

            def get(self, **k):
                qa.calls.append((cmd, k))
                return {"exited": 1, "out-data": "\r\nMicrosoft Windows [Version 10.0.17763.6775]\r\n"}
        return C()


col = pxc.ProxmoxCollector.__new__(pxc.ProxmoxCollector)
col.host = "pve-test"
qa = _QA()
assert col._windows_version(qa, 101, "NT 10.0.17763", None) == "NT 10.0.17763.6775"
assert qa.calls[0] == ("exec", {"command": ["cmd.exe", "/c", "ver"]})
n = len(qa.calls)
assert col._windows_version(qa, 101, "NT 10.0.17763", None) == "NT 10.0.17763.6775" and len(qa.calls) == n  # cached
denied = _QA(deny=True)
assert col._windows_version(denied, 102, "NT 10.0.17763", None) == ""
assert col._windows_version(denied, 102, "NT 10.0.17763", None) == "" and len(denied.calls) == 1   # failure cached
# sync keeps "NT 10.0.17763.6775" when a round only brings "NT 10.0.17763"
win_px = Platform(name="pxw", type="proxmox", host="px", environment="production", enabled=True)
db.add(win_px); db.commit()
base = dict(vms[0], external_id="h1/300", vmid="300", name="win-px", guest_os="Windows Server 2019 Standard",
            kernel="NT 10.0.17763.6775")
base.pop("kernel_build", None)
run_sync(ss, win_px.id, FakeCollector(vms=[base])); db.expire_all()
run_sync(ss, win_px.id, FakeCollector(vms=[dict(base, kernel="NT 10.0.17763")])); db.expire_all()
assert db.query(VirtualMachine).filter_by(platform_id=win_px.id).one().kernel == "NT 10.0.17763.6775"
run_sync(ss, win_px.id, FakeCollector(vms=[dict(base, kernel="NT 10.0.17763.6893")])); db.expire_all()
assert db.query(VirtualMachine).filter_by(platform_id=win_px.id).one().kernel == "NT 10.0.17763.6893"
print("5) tools version / Windows UBR ok")

print("KERNEL SUITE OK")
