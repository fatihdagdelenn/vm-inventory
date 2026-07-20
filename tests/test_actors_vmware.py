"""vCenter actor-attribution regression suite (INDEPENDENT of Proxmox).

    PYTHONPATH=. python3 tests/test_actors_vmware.py

Scenarios mirror REAL vCenter event streams. If you change actor matching,
this file must stay green - and so must tests/test_actors_proxmox.py.
"""
import time
from _actor_harness import make_env, FakeCollector, run_sync, op, change_rows

db, ss = make_env("_t_act_vmw")
from app.models import Platform  # noqa: E402

p = Platform(name="vc", type="vcenter", host="h", environment="production", enabled=True)
db.add(p)
db.commit()
PID = p.id
NOW = time.time()

BASE = dict(external_id="vm-100", name="app01", power_state="poweredOn",
            host_name="h1", cluster="c1", cpu_count=24, ram_mb=8192)


def sync(vm=None, ops=None):
    run_sync(ss, PID, FakeCollector(vms=[dict(vm or BASE)], vm_ops=ops or {}))
    db.expire_all()


# --- kurulum: VM olustur ---
sync()

# 1) UI'dan Power ON: tek VmPoweredOnEvent (userName dolu)
vm = dict(BASE)
sync(vm)  # baseline poweredOn
vm["power_state"] = "poweredOff"
sync(vm, {"vm-100": [op(NOW, "VmPoweredOffEvent", "power", "off", "admin@vsphere")]})
rows = change_rows(db, field="power_state")
assert rows[-1].actor == "admin@vsphere", ("1) sert power-off aktoru", rows[-1].actor)

# 2) 'Shut Down Guest OS': VmPoweredOffEvent (actor BOS, daha yeni) +
#    VmGuestShutdownEvent (actor DOLU, 5 sn once) -> DOLU olan tercih edilmeli
vm["power_state"] = "poweredOn"
sync(vm, {"vm-100": [op(NOW, "VmPoweredOnEvent", "power", "on", "opener@corp")]})
vm["power_state"] = "poweredOff"
sync(vm, {"vm-100": [
    op(NOW + 10, "VmPoweredOffEvent", "power", "off", None),          # guest-initiated: bos
    op(NOW + 5, "VmGuestShutdownEvent", "power", "off", "closer@corp"),
    op(NOW, "VmPoweredOnEvent", "power", "on", "opener@corp"),
]})
rows = change_rows(db, field="power_state")
assert rows[-1].actor == "closer@corp", ("2) guest-shutdown aktoru", rows[-1].actor)
assert rows[-1].old_value == "poweredOn" and rows[-1].new_value == "poweredOff"

# 3) Aktorlu eski olay COK eskiyse (15 dk penceresi disi) tercih EDILMEZ
vm["power_state"] = "poweredOn"
sync(vm, {"vm-100": [op(NOW + 20, "VmPoweredOnEvent", "power", "on", "x@y")]})
vm["power_state"] = "poweredOff"
sync(vm, {"vm-100": [
    op(NOW + 100, "VmPoweredOffEvent", "power", "off", None),
    op(NOW - 7200, "VmPoweredOffEvent", "power", "off", "olduser@corp"),  # 2 saat once
]})
rows = change_rows(db, field="power_state")
assert not rows[-1].actor, ("3) eski aktore atif YAPILMAMALI", rows[-1].actor)
assert rows[-1].op_type == "VmPoweredOffEvent"   # olay yine de rozette gorunur

# 4) CPU reconfigure: config kategorisi; daha YENI power olayina kaymamali
vm["power_state"] = "poweredOn"
sync(vm, {"vm-100": [op(NOW + 200, "VmPoweredOnEvent", "power", "on", "power@corp")]})
vm["cpu_count"] = 64
sync(vm, {"vm-100": [
    op(NOW + 300, "VmPoweredOnEvent", "power", "on", "power@corp"),
    op(NOW + 250, "VmReconfiguredEvent", "config", None, "cpuadmin@corp"),
]})
rows = change_rows(db, field="cpu_count")
assert rows[-1].actor == "cpuadmin@corp", ("4) cpu aktoru", rows[-1].actor)
assert rows[-1].old_value == "24" and rows[-1].new_value == "64"
assert rows[-1].category == "hardware"

# 5) vMotion: migrate kategorisi + kaynak→hedef detayi
vm["host_name"] = "h2"
run_sync(ss, PID, FakeCollector(
    vms=[dict(vm)],
    hosts=[{"external_id": "h1", "name": "h1", "cluster": "c1", "status": "online"},
           {"external_id": "h2", "name": "h2", "cluster": "c1", "status": "online"}],
    vm_ops={"vm-100": [op(NOW + 400, "VmMigratedEvent", "migrate", "migrate",
                          "vmotion@corp", host="h2", detail="h1 → h2")]}))
db.expire_all()
rows = change_rows(db, change_type="migrated")
assert rows and rows[-1].actor == "vmotion@corp", "5) vMotion aktoru"
assert rows[-1].new_value == "h1 → h2"

# 6) Silme: destroy yonlu lifecycle
run_sync(ss, PID, FakeCollector(vms=[], vm_ops={
    "vm-100": [op(NOW + 500, "VmRemovedEvent", "lifecycle", "destroy", "deleter@corp")]}))
db.expire_all()
rows = change_rows(db, change_type="deleted")
assert rows and rows[-1].actor == "deleter@corp", "6) silme aktoru"

print("VMWARE ACTOR SUITE OK (6 senaryo)")
