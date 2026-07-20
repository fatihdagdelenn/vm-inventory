"""Proxmox actor-attribution regression suite (INDEPENDENT of vCenter).

    PYTHONPATH=. python3 tests/test_actors_proxmox.py

Ops mimic what proxmox_collector.collect_recent_actors emits from
/nodes/{node}/tasks + /cluster/log. The _TASK_CATEGORY mapping itself is also
asserted here so a task-type rename in PVE (e.g. 'resize' vs 'qmresize') is
caught by tests instead of by the user.
"""
import time
from _actor_harness import make_env, FakeCollector, run_sync, op, change_rows

db, ss = make_env("_t_act_pmx")
from app.models import Platform  # noqa: E402
from app.collectors.proxmox_collector import ProxmoxCollector  # noqa: E402

# --- 0) Harita sozlesmeleri: gercek PVE gorev tipleri esli OLMALI ---
TC = ProxmoxCollector._TASK_CATEGORY
assert TC.get("resize") == ("disk", None), "PVE disk buyutme gorevi 'resize' esli degil!"
assert TC.get("vzresize") == ("disk", None)
assert TC.get("qmigrate", ("", ""))[0] == "migrate"   # tek 'm' — gercek tip
assert TC.get("qmshutdown") == ("power", "off")
assert TC.get("qmstart") == ("power", "on")

p = Platform(name="pmx", type="proxmox", host="h", environment="production", enabled=True)
db.add(p)
db.commit()
PID = p.id
NOW = time.time()

BASE = dict(external_id="pve101/2612", vmid="2612", name="devtestelastic01-sL1",
            power_state="running", host_name="pve101", cluster="25-cluster",
            cpu_count=8, ram_mb=8192, disk_total_gb=175.0)
HOSTS = [{"external_id": "pve101", "name": "pve101",
          "cluster": "25-cluster", "status": "online"}]


def sync(vm=None, ops=None):
    run_sync(ss, PID, FakeCollector(vms=[dict(vm or BASE)], hosts=HOSTS,
                                    vm_ops=ops or {}))
    db.expire_all()


sync()  # kurulum

# 1) DISK BUYUTME via 'resize' GOREVI (ekran goruntusu vakasi: 175 -> 325 GB)
vm = dict(BASE)
vm["disk_total_gb"] = 325.0
sync(vm, {"pve101/2612": [op(NOW, "resize", "disk", None, "fatih@pam", host="pve101")]})
rows = change_rows(db, field="disk_total_gb")
assert rows[-1].actor == "fatih@pam", ("1) resize gorevi aktoru", rows[-1].actor)
assert rows[-1].old_value == "175.0" and rows[-1].new_value == "325.0"

# 2) DISK BUYUTME yalniz CLUSTER-LOG'dan (senkron resize, gorev yok):
#    collector 'update (cluster log)' / config op uretir; disk alani config'i kabul eder
vm["disk_total_gb"] = 400.0
sync(vm, {"pve101/2612": [op(NOW + 60, "update (cluster log)", "config", None,
                            "root@pam", host="pve101",
                            detail="update VM 2612: resize --disk scsi0 --size +75G")]})
rows = change_rows(db, field="disk_total_gb")
assert rows[-1].actor == "root@pam", ("2) cluster-log resize aktoru", rows[-1].actor)

# 3) RAM degisimi cluster-log config'inden; daha YENI power gorevine kaymamali
vm["ram_mb"] = 16384
sync(vm, {"pve101/2612": [
    op(NOW + 200, "qmstart", "power", "on", "starter@pam"),
    op(NOW + 150, "update (cluster log)", "config", None, "ramadmin@pam"),
]})
rows = change_rows(db, field="ram_mb")
assert rows[-1].actor == "ramadmin@pam", ("3) ram aktoru", rows[-1].actor)
assert rows[-1].category == "hardware"

# 4) GUC: qmshutdown 'off' yonuyle eslesir; config op'a atif YAPILMAZ
vm["power_state"] = "stopped"
sync(vm, {"pve101/2612": [
    op(NOW + 300, "qmshutdown", "power", "off", "stopper@pam"),
    op(NOW + 290, "update (cluster log)", "config", None, "ramadmin@pam"),
]})
rows = change_rows(db, field="power_state")
assert rows[-1].actor == "stopper@pam", ("4) shutdown aktoru", rows[-1].actor)

# 5) GUC ON: qmstart
vm["power_state"] = "running"
sync(vm, {"pve101/2612": [op(NOW + 400, "qmstart", "power", "on", "starter@pam")]})
rows = change_rows(db, field="power_state")
assert rows[-1].actor == "starter@pam", ("5) start aktoru", rows[-1].actor)

# 6) UYGUN OP YOKSA aktor BOS kalmali (yanlis kisiye atif yok):
#    yalniz konsol op'u varken CPU degisimi aktorsuz yazilir
vm["cpu_count"] = 16
sync(vm, {"pve101/2612": [op(NOW + 500, "vncproxy", "console", "open", "viewer@pam")]})
rows = change_rows(db, field="cpu_count")
assert not rows[-1].actor, ("6) yanlis-kisi korumasi", rows[-1].actor)

# 7) GOC (node degisir -> ayni vmid yeni external_id): tek 'Goc' satiri + aktor
vm2 = dict(vm)
vm2["external_id"] = "pve102/2612"
vm2["host_name"] = "pve102"
run_sync(ss, PID, FakeCollector(
    vms=[vm2],
    hosts=HOSTS + [{"external_id": "pve102", "name": "pve102",
                    "cluster": "25-cluster", "status": "online"}],
    vm_ops={"pve101/2612": [op(NOW + 600, "qmigrate", "migrate", "migrate",
                               "mover@pam", host="pve101")]}))
db.expire_all()
rows = change_rows(db, change_type="migrated")
assert rows and rows[-1].actor == "mover@pam", ("7) goc aktoru",
                                               rows[-1].actor if rows else None)
deleted = change_rows(db, change_type="deleted")
created = [r for r in change_rows(db, change_type="created") if r.entity_name == vm["name"]]
assert not deleted, "7) goc 'silindi' olarak yazilmamali"
assert len(created) == 1, "7) goc yeni 'eklendi' uretmemeli (yalniz kurulum kaydi kalmali)"

# 8) RAM: log satiri onceki sync'ten YENI ama 10+ dk once yazilmis (sync araligi
#    uzun) — pencere matematigi onu ELEMEMELI (min_ts = prev_sync - 300)
import time as _time
_time.sleep(1.1)   # prev_sync (bir onceki senkron) gecmiste kalsin
# NOT: senaryo 7'de VM pve102'ye goctu — bundan sonra dogru external_id vm2'dir.
vm2["ram_mb"] = 32768
HOSTS2 = HOSTS + [{"external_id": "pve102", "name": "pve102",
                   "cluster": "25-cluster", "status": "online"}]
run_sync(ss, PID, FakeCollector(vms=[dict(vm2)], hosts=HOSTS2, vm_ops={
    "pve102/2612": [op(_time.time() - 0.5, "update (cluster log)", "config",
                       None, "lateram@pam")]}))
db.expire_all()
rows = change_rows(db, field="ram_mb")
assert rows[-1].actor == "lateram@pam", ("8) genis pencere aktoru", rows[-1].actor)

# 9) RAM: op onceki senkrondan da eski (kurulum donemi op'u) -> atif YAPILMAMALI
_time.sleep(1.1)
vm2["ram_mb"] = 4096
run_sync(ss, PID, FakeCollector(vms=[dict(vm2)], hosts=HOSTS2, vm_ops={
    "pve102/2612": [op(_time.time() - 86400, "update (cluster log)", "config",
                       None, "ancient@pam")]}))
db.expire_all()
rows = change_rows(db, field="ram_mb")
assert not rows[-1].actor, ("9) eski op korumasi", rows[-1].actor)

print("PROXMOX ACTOR SUITE OK (9 senaryo + harita sozlesmeleri)")
