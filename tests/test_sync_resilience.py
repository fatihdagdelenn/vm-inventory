"""
Sync resilience suite (phase 155): values must not "come and go" between syncs.

1. VMware: a VM that exists but cannot be read in one round is reported as
   unreadable and its stored row is kept untouched - no 'deleted' history, no
   loss of owner / notes / tags / kernel; a VM really gone is still deleted.
   Also drives VMwareCollector.collect_vms with one VM whose read raises.
2. Proxmox live migration: when the agent does not answer on the first round
   on the new node, the agent-sourced identity (OS name, kernel, arch, IPs)
   is carried over from the old row instead of starting generic / empty.
3. kernel / arch are never overwritten by an empty value.

Run:  PYTHONPATH=. python3 tests/test_sync_resilience.py
"""
import sys
import types
sys.path.insert(0, "tests")

from _actor_harness import make_env, FakeCollector, run_sync, change_rows  # noqa: E402

db, ss = make_env("_resilience")
from app.models import Platform, VirtualMachine, Tag  # noqa: E402

NS = types.SimpleNamespace


def vm_row(pid, **kw):
    return db.query(VirtualMachine).filter_by(platform_id=pid, **kw).one_or_none()


# ---------------------------------------------------------------- 1) VMware
vc = Platform(name="vc", type="vcenter", host="v", environment="production", enabled=True)
db.add(vc); db.commit()
B = dict(power_state="poweredOn", host_name="h1", cluster="c1", cpu_count=2, ram_mb=2048)
A = dict(B, external_id="vm-1", name="rocky01", guest_os="Rocky Linux 9.4",
         kernel="5.14.0-427.13.1.el9_4.x86_64", ip_addresses="10.0.0.1")
C = dict(B, external_id="vm-2", name="ubuntu01", guest_os="Ubuntu 24.04.1 LTS",
         kernel="6.8.0-45-generic")


def vsync(vms):
    run_sync(ss, vc.id, FakeCollector(vms=[dict(v) for v in vms])); db.expire_all()


vsync([A, C])
r = vm_row(vc.id, external_id="vm-1")
r.owner = "fatih"; r.notes = "kritik"; r.tags = [Tag(name="prod")]; db.commit()
row_id = r.id

# round with vm-1 unreadable
vsync([{"external_id": "vm-1", "read_failed": True}, C])
r = vm_row(vc.id, external_id="vm-1")
assert r is not None and r.id == row_id, "unreadable VM must keep its row"
assert (r.owner, r.notes, [t.name for t in r.tags], r.kernel, r.ip_addresses) == \
    ("fatih", "kritik", ["prod"], "5.14.0-427.13.1.el9_4.x86_64", "10.0.0.1")
assert not change_rows(db, change_type="deleted"), "no 'deleted' history for an unreadable VM"
# readable again: normal update continues on the same row, no 'created' noise
A = dict(A, kernel="5.14.0-503.11.1.el9_5.x86_64")      # kernel upgraded in the guest
vsync([A, C])
r = vm_row(vc.id, external_id="vm-1")
assert r.id == row_id and r.kernel == "5.14.0-503.11.1.el9_5.x86_64"
assert len(change_rows(db, change_type="created")) == 2      # only the first round
# a never-seen VM that is unreadable is not created half-empty
vsync([A, C, {"external_id": "vm-9", "read_failed": True}])
assert vm_row(vc.id, external_id="vm-9") is None
# a VM really gone is still deleted
vsync([A])
assert vm_row(vc.id, external_id="vm-2") is None
assert [x.entity_name for x in change_rows(db, change_type="deleted")] == ["ubuntu01"]
# empty kernel never wipes a stored one
vsync([dict(A, kernel="", arch="")])
r = vm_row(vc.id, external_id="vm-1")
assert r.kernel == "5.14.0-503.11.1.el9_5.x86_64", r.kernel
print("1) VMware unreadable-VM handling ok")

# --- the collector itself turns a read error into read_failed -------------
import app.collectors.vmware_collector as vmc  # noqa: E402
vmc._fetch_vcenter_tags = lambda *a, **k: {}
vmc.vim = NS(VirtualMachine="VirtualMachine")     # the SDK is stubbed offline


class Boom:
    _moId = "vm-77"
    name = "boom"

    @property
    def summary(self):
        raise RuntimeError("vim.fault.InvalidState: VM is migrating")


class Gone(Boom):
    _moId = "vm-78"

    @property
    def summary(self):
        ManagedObjectNotFound = type("ManagedObjectNotFound", (Exception,), {})
        raise ManagedObjectNotFound("deleted meanwhile")


col = vmc.VMwareCollector.__new__(vmc.VMwareCollector)
col.host, col.port, col.username, col.password, col.verify_ssl = "v", 443, "u", "p", False
col._cluster_map = lambda: {}
col._pool_map = lambda: {}
col._get_objects = lambda t: [Boom(), Gone()]
out = col.collect_vms()
assert out == [{"external_id": "vm-77", "read_failed": True}], out
print("1b) collector read error -> read_failed ok")

# ------------------------------------------------- 2) Proxmox live migration
pm = Platform(name="pmx", type="proxmox", host="p", environment="production", enabled=True)
db.add(pm); db.commit()
HOSTS = [{"external_id": n, "name": n, "cluster": "c", "status": "online"} for n in ("pve1", "pve2")]
P = dict(vmid="300", name="es01", power_state="running", cluster="c", cpu_count=4,
         ram_mb=8192, disk_total_gb=100.0)


def psync(vm):
    run_sync(ss, pm.id, FakeCollector(vms=[vm], hosts=HOSTS)); db.expire_all()


psync(dict(P, external_id="pve1/300", host_name="pve1", guest_os="Rocky Linux 9.4",
           kernel="5.14.0-427.13.1.el9_4.x86_64", arch="x86_64", ip_addresses="10.1.1.5",
           dns_servers="10.1.0.2", os_from_agent=True, ip_from_agent=True))
# first round on the new node: agent silent -> collector falls back to ostype
psync(dict(P, external_id="pve2/300", host_name="pve2", guest_os="Linux 6.x - 2.6 Kernel",
           ip_addresses="", os_from_agent=False, ip_from_agent=False))
r = vm_row(pm.id, vmid="300")
assert r.external_id == "pve2/300"
assert (r.guest_os, r.kernel, r.arch, r.ip_addresses, r.dns_servers) == \
    ("Rocky Linux 9.4", "5.14.0-427.13.1.el9_4.x86_64", "x86_64", "10.1.1.5", "10.1.0.2"), \
    (r.guest_os, r.kernel, r.arch, r.ip_addresses, r.dns_servers)
# next round the agent answers with a newer kernel -> taken
psync(dict(P, external_id="pve2/300", host_name="pve2", guest_os="Rocky Linux 9.5",
           kernel="5.14.0-503.11.1.el9_5.x86_64", ip_addresses="10.1.1.5",
           os_from_agent=True, ip_from_agent=True))
r = vm_row(pm.id, vmid="300")
assert (r.guest_os, r.kernel) == ("Rocky Linux 9.5", "5.14.0-503.11.1.el9_5.x86_64")
# migration where the agent DID answer: fresh agent values win over the old row
psync(dict(P, external_id="pve1/300", host_name="pve1", guest_os="Rocky Linux 9.5",
           kernel="5.14.0-503.15.1.el9_5.x86_64", ip_addresses="10.1.1.6",
           os_from_agent=True, ip_from_agent=True))
r = vm_row(pm.id, vmid="300")
assert (r.kernel, r.ip_addresses) == ("5.14.0-503.15.1.el9_5.x86_64", "10.1.1.6")
print("2) Proxmox migration carry-over ok")

print("RESILIENCE SUITE OK")
