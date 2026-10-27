"""Fill a throwaway SQLite database with a FICTIONAL inventory.

Used to take the README screenshots (tools/screenshots.py) and to try the UI
without connecting a real vCenter / Proxmox. Every name, IP and user here is
made up. It refuses anything but a SQLite file, so it can never touch the
production PostgreSQL database.

    DATABASE_URL=sqlite:///./data/demo.db SECRET_KEY=demo ENCRYPTION_KEY=demo \\
        python3 tools/demo_data.py
    # then start the app with the same DATABASE_URL and log in as admin / admin123
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

url = os.environ.get("DATABASE_URL", "")
if not url.startswith("sqlite:///"):
    sys.exit("demo_data.py only writes to a SQLite file (DATABASE_URL=sqlite:///...).")
path = url[len("sqlite:///"):]
if os.path.exists(path):
    os.remove(path)
os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

from app.database import Base, engine, SessionLocal, ensure_schema  # noqa: E402
import app.models  # noqa: E402,F401  (registers every table)
from app.models import (Platform, SyncLog, Host, VirtualMachine, Datastore, Network,  # noqa: E402
                        Snapshot, Backup, Tag, ChangeHistory, CapacitySnapshot,
                        VmUsageDaily, ClusterAlias, PhysicalDevice)

Base.metadata.create_all(bind=engine)
ensure_schema(engine)
db = SessionLocal()
rnd = random.Random(42)
now = datetime.utcnow().replace(microsecond=0)

# ---------------------------------------------------------------- platforms
vc = Platform(name="East vCenter", type="vcenter", host="vcsa-east.example.lan", port=443,
              location="Frankfurt", environment="production", enabled=True,
              last_sync=now - timedelta(minutes=4), last_usage_sync=now - timedelta(minutes=1),
              last_sync_status="success")
px = Platform(name="West Proxmox", type="proxmox", host="pve-west.example.lan", port=8006,
              auth_method="token", location="Amsterdam", environment="production", enabled=True,
              last_sync=now - timedelta(minutes=6), last_usage_sync=now - timedelta(minutes=2),
              last_sync_status="success")
db.add_all([vc, px])
db.commit()
for p, hosts, vms in ((vc, 7, 104), (px, 3, 38)):
    for i in range(12):
        db.add(SyncLog(platform_id=p.id, started_at=now - timedelta(minutes=15 * i + 5),
                       finished_at=now - timedelta(minutes=15 * i + 4), status="success",
                       hosts_found=hosts, vms_found=vms))

# ---------------------------------------------------------------- hosts
ESXI = "VMware ESXi 8.0.2 build-22380479"
PVE = "Proxmox VE 8.2.4 (kernel 6.8.12-1-pve)"
host_specs = [
    # name, platform, cluster, cpu model, cores, ram GB, model
    ("esx-e01.example.lan", vc, "PROD-East", "Intel Xeon Gold 6338", 64, 768, "Dell PowerEdge R750"),
    ("esx-e02.example.lan", vc, "PROD-East", "Intel Xeon Gold 6338", 64, 768, "Dell PowerEdge R750"),
    ("esx-e03.example.lan", vc, "PROD-East", "Intel Xeon Gold 6338", 64, 768, "Dell PowerEdge R750"),
    ("esx-e04.example.lan", vc, "PROD-East", "Intel Xeon Gold 6338", 64, 768, "Dell PowerEdge R750"),
    ("esx-dmz01.example.lan", vc, "DMZ", "Intel Xeon Silver 4314", 32, 384, "HPE ProLiant DL360 Gen10"),
    ("esx-dmz02.example.lan", vc, "DMZ", "Intel Xeon Silver 4314", 32, 384, "HPE ProLiant DL360 Gen10"),
    ("esx-rep01.example.lan", vc, "", "Intel Xeon Silver 4210", 20, 256, "Dell PowerEdge R640"),
    ("pve-w01", px, "pve-west", "AMD EPYC 7443P", 48, 512, "Supermicro AS-1114S"),
    ("pve-w02", px, "pve-west", "AMD EPYC 7443P", 48, 512, "Supermicro AS-1114S"),
    ("pve-w03", px, "pve-west", "AMD EPYC 7443P", 48, 512, "Supermicro AS-1114S"),
]
hosts = []
for i, (name, plat, cl, cpu, cores, ram, model) in enumerate(host_specs):
    is_pve = plat is px
    h = Host(platform_id=plat.id, external_id=name if is_pve else f"host-{1000 + i}", name=name,
             mgmt_ip=f"10.{20 if not is_pve else 40}.0.{11 + i}",
             os_version=PVE if is_pve else ESXI, cpu_model=cpu, hw_model=model,
             cpu_cores=cores, ram_total_mb=ram * 1024,
             ram_used_mb=int(ram * 1024 * rnd.uniform(.45, .82)),
             cpu_usage_pct=round(rnd.uniform(18, 71), 1),
             disk_total_gb=None if not is_pve else 1800, disk_used_gb=None if not is_pve else 540,
             cluster=cl or "Replica-Site", cluster_is_alias=not cl,
             status="online", last_boot=now - timedelta(days=rnd.randint(9, 140)))
    hosts.append(h)
db.add_all(hosts)
db.commit()
# The standalone replica host carries an operator-given cluster name (phase 149)
db.add(ClusterAlias(platform_id=vc.id, host_name="esx-rep01.example.lan", alias="Replica-Site"))

# ---------------------------------------------------------------- datastores / networks
ds_specs = [
    ("vsanDatastore-East", vc, "vsan", None, True, 92000, 61500),
    ("vmfs-sql-01", vc, "VMFS", None, True, 18000, 13300),
    ("vmfs-sql-02", vc, "VMFS", None, True, 18000, 16450),
    ("nfs-backup-east", vc, "NFS", None, True, 40000, 21800),
    ("iso-library", vc, "NFS", None, True, 4000, 1240),
    ("vmfs-dmz", vc, "VMFS", None, True, 12000, 9850),
    ("local-rep01", vc, "VMFS", "esx-rep01.example.lan", False, 16000, 12900),
    ("ceph-west", px, "rbd", None, True, 48000, 23100),
    ("ceph-west-ssd", px, "rbd", None, True, 12000, 9100),
    ("pbs-west", px, "pbs", None, True, 30000, 17400),
    ("local-lvm", px, "lvmthin", "pve-w01", False, 1800, 540),
    ("local-lvm", px, "lvmthin", "pve-w02", False, 1800, 610),
]
datastores = []
for name, plat, typ, node, shared, cap, used in ds_specs:
    datastores.append(Datastore(platform_id=plat.id, name=name, type=typ, node=node, shared=shared,
                     capacity_gb=cap, used_gb=used, free_gb=cap - used,
                     host_count=1 if node else (6 if plat is vc else 3), vm_count=0, status="ok"))
db.add_all(datastores)
VLANS = {"110": "PG-App-110", "120": "PG-DB-120", "130": "PG-Web-130", "200": "PG-DMZ-200"}
for vlan, pg in VLANS.items():
    db.add(Network(platform_id=vc.id, name=pg, vlan=vlan, vswitch="DSwitch-East", portgroup=pg,
                   subnet=f"10.20.{vlan[:2]}.0/24", kind="portgroup"))
for br, vlan in (("vmbr0", ""), ("vmbr0.310", "310"), ("vmbr0.320", "320")):
    db.add(Network(platform_id=px.id, name=br, vlan=vlan, vswitch="vmbr0", kind="bridge",
                   host_name="pve-w01"))

# ---------------------------------------------------------------- physical (non-virtualised) devices
for dtype, name, loc, brand, model, ip in (
        ("storage", "pure-east-01", "Frankfurt / Rack B04", "Pure Storage", "FlashArray//X70", "10.20.0.60"),
        ("san_switch", "mds-east-a", "Frankfurt / Rack B04", "Cisco", "MDS 9148T", "10.20.0.61"),
        ("san_switch", "mds-east-b", "Frankfurt / Rack B05", "Cisco", "MDS 9148T", "10.20.0.62"),
        ("backup", "datadomain-east", "Frankfurt / Rack B06", "Dell", "PowerProtect DD6900", "10.20.0.70"),
        ("server", "bastion-phys-01", "Amsterdam / Rack A02", "HPE", "ProLiant DL20 Gen10 Plus", "10.40.0.50")):
    db.add(PhysicalDevice(device_type=dtype, name=name, location=loc, status="active", brand=brand,
                          model=model, mgmt_ip=ip, serial_no=f"SN{rnd.randint(10**7, 10**8 - 1)}",
                          role="linux" if dtype == "server" else None))

# ---------------------------------------------------------------- tags
tags = {n: Tag(name=n, color=c) for n, c in
        (("critical", "#e5534b"), ("pci", "#e8a13c"), ("k8s", "#2f81f7"), ("legacy", "#64748b"))}
db.add_all(tags.values())
db.commit()

# ---------------------------------------------------------------- VMs
OS = {
    "ubuntu": "Ubuntu 24.04.1 LTS", "ubuntu22": "Ubuntu 22.04.4 LTS", "rhel": "Red Hat Enterprise Linux 9.4",
    "rocky": "Rocky Linux 9.3", "debian": "Debian GNU/Linux 12 (bookworm)",
    "win22": "Microsoft Windows Server 2022 Standard", "win19": "Microsoft Windows Server 2019 Datacenter",
    "sles": "SUSE Linux Enterprise Server 15 SP5", "photon": "VMware Photon OS 5.0",
}
roles = [  # prefix, count, os, vcpu, ram GB, disk GB, vlan, tags, owner, env, cluster
    ("web", 10, "ubuntu", 4, 8, 80, "130", [], "web-team", "production", "PROD-East"),
    ("app", 12, "rhel", 8, 16, 120, "110", [], "app-team", "production", "PROD-East"),
    ("db-pg", 4, "rocky", 16, 64, 900, "120", ["critical"], "dba", "production", "PROD-East"),
    ("sql", 3, "win22", 16, 64, 1200, "120", ["critical", "pci"], "dba", "production", "PROD-East"),
    ("k8s-node", 12, "ubuntu22", 8, 32, 200, "110", ["k8s"], "platform", "production", "PROD-East"),
    ("dc", 2, "win22", 4, 8, 100, "110", ["critical"], "it-ops", "production", "PROD-East"),
    ("file", 2, "win19", 4, 16, 2000, "110", [], "it-ops", "production", "PROD-East"),
    ("rdsh", 6, "win19", 8, 32, 150, "110", [], "it-ops", "production", "PROD-East"),
    ("kafka", 3, "rhel", 8, 32, 500, "110", [], "data", "production", "PROD-East"),
    ("elastic", 5, "rocky", 8, 32, 1000, "110", [], "data", "production", "PROD-East"),
    ("monitor", 3, "ubuntu", 4, 16, 300, "110", [], "platform", "production", "PROD-East"),
    ("legacy-erp", 2, "win19", 8, 32, 600, "110", ["legacy"], None, "production", "PROD-East"),
    ("dmz-proxy", 4, "debian", 2, 4, 40, "200", ["pci"], "netsec", "production", "DMZ"),
    ("dmz-mail", 2, "sles", 4, 8, 200, "200", [], "netsec", "production", "DMZ"),
    ("vpn-gw", 2, "debian", 2, 4, 30, "200", ["critical"], "netsec", "production", "DMZ"),
    ("vcsa", 1, "photon", 4, 21, 600, "110", [], "it-ops", "production", "PROD-East"),
    ("rep-app", 10, "rhel", 8, 16, 120, "110", [], None, "production", "Replica-Site"),
    ("rep-sql", 3, "win22", 16, 64, 1200, "120", [], None, "production", "Replica-Site"),
    ("ci-runner", 6, "ubuntu", 8, 16, 200, "310", [], "devops", "development", "pve-west"),
    ("gitlab", 1, "ubuntu", 8, 32, 800, "310", ["critical"], "devops", "production", "pve-west"),
    ("test-app", 10, "debian", 4, 8, 60, "320", [], "qa", "test", "pve-west"),
    ("dev-box", 8, "ubuntu", 4, 8, 80, "320", [], None, "development", "pve-west"),
    ("win-test", 4, "win22", 4, 8, 80, "320", [], "qa", "test", "pve-west"),
    ("sandbox", 6, "rocky", 2, 4, 40, "320", [], None, "development", "pve-west"),
]
hosts_by_cluster = {}
for h in hosts:
    hosts_by_cluster.setdefault(h.cluster, []).append(h)
vms = []
vmid = 100
for prefix, count, os_key, vcpu, ram, disk, vlan, tg, owner, env, cl in roles:
    for n in range(1, count + 1):
        h = rnd.choice(hosts_by_cluster[cl])
        is_pve = h.platform_id == px.id
        is_replica = cl == "Replica-Site"
        state = "stopped" if is_replica else rnd.choices(
            ["running", "stopped", "suspended"], [92, 7, 1])[0]
        if prefix in ("sandbox", "dev-box") and n > 5:
            state = "stopped"
        agent = "guestToolsRunning" if state == "running" and rnd.random() > .08 else (
            "guestToolsNotRunning" if not is_pve else "")
        name = f"{prefix}-{n:02d}" + ("_replica" if is_replica else "")
        vmid += 1
        ip_ok = state == "running" and agent == "guestToolsRunning"
        third = {"110": 10, "120": 12, "130": 13, "200": 200, "310": 31, "320": 32}[vlan]
        cpu_use = round(min(99, rnd.betavariate(1.6, 4.5) * 100 + (35 if prefix in ("sql", "kafka", "elastic") else 0)), 1) if state == "running" else None
        ram_use = int(ram * 1024 * min(.97, rnd.uniform(.35, .9) + (.1 if prefix.startswith("db") else 0))) if state == "running" else None
        disk_used = round(disk * rnd.uniform(.25, .93), 1) if (state == "running" and agent) else 0
        v = VirtualMachine(
            platform_id=h.platform_id, host_id=h.id,
            external_id=f"{h.name}/{vmid}" if is_pve else f"vm-{vmid}", vmid=str(vmid) if is_pve else f"vm-{vmid}",
            name=name, ip_addresses=f"10.{20 if not is_pve else 40}.{third}.{10 + n}" if ip_ok else "",
            mac_addresses=f"00:50:56:{rnd.randint(16, 255):02x}:{rnd.randint(16, 255):02x}:{rnd.randint(16, 255):02x}",
            guest_os=OS[os_key], cpu_count=vcpu, ram_mb=ram * 1024, disk_total_gb=float(disk),
            power_state=state, cluster=cl, cluster_is_alias=is_replica,
            datastore=(("ceph-west-ssd" if prefix in ("gitlab", "ci-runner") else "ceph-west") if is_pve else
                       "local-rep01" if is_replica else "vmfs-dmz" if cl == "DMZ" else
                       f"vmfs-sql-0{1 + n % 2}" if prefix in ("sql", "db-pg") else "vsanDatastore-East"),
            vlans=vlan, networks=("vmbr0" if is_pve else VLANS.get(vlan, "")),
            created_date=now - timedelta(days=rnd.randint(20, 900)),
            last_boot=(now - timedelta(days=rnd.randint(1, 120), hours=rnd.randint(0, 23))) if state == "running" else None,
            tools_status=agent, owner=owner, environment=env,
            pool=("Production" if env == "production" else "Lab") if not is_replica else None,
            folder=None if is_pve else ("/DC-East/" + prefix.split("-")[0].upper()),
            cpu_usage_pct=cpu_use, ram_usage_mb=ram_use, disk_used_gb=disk_used,
            guest_notes="Veeam replica of " + name.replace("_replica", "") if is_replica else None,
            platform_tags="backup-gold" if "critical" in tg else None)
        v.tags = [tags[x] for x in tg]
        vms.append(v)
db.add_all(vms)
db.commit()

# datastore VM counts (the sync derives them; here we count the demo VMs)
for d in datastores:
    d.vm_count = sum(1 for v in vms if v.datastore == d.name and (d.shared or v.host_ref is None
                                                                   or v.host_ref.name == d.node))

# ---------------------------------------------------------------- snapshots / backups
for v in rnd.sample([v for v in vms if v.cluster != "Replica-Site"], 14):
    age = rnd.choice([1, 3, 6, 9, 15, 22, 41, 66, 120])
    db.add(Snapshot(platform_id=v.platform_id, vm_id=v.id, vm_external_id=v.external_id, vm_name=v.name,
                    name=rnd.choice(["before-patch", "pre-upgrade", "change-4471", "baseline", "VM Snapshot"]),
                    description="taken before maintenance", created_at=now - timedelta(days=age),
                    is_current=True))
for v in [v for v in vms if v.platform_id == px.id and v.power_state == "running"]:
    for d in range(rnd.randint(2, 6)):
        db.add(Backup(platform_id=px.id, vm_id=v.id, vmid=v.vmid, vm_name=v.name, storage="pbs-west",
                      volid=f"pbs-west:backup/vm/{v.vmid}/{d}", fmt="pbs-vm",
                      created_at=now - timedelta(days=d, hours=rnd.randint(1, 5)),
                      size_gb=round(v.disk_total_gb * rnd.uniform(.2, .5), 1), source="pbs"))

# ---------------------------------------------------------------- change history
people = {"vcenter": ["EXAMPLE\\j.smith", "EXAMPLE\\a.novak", "VSPHERE.LOCAL\\svc-automation"],
          "proxmox": ["m.jensen@pve", "root@pam", "ci@pve"]}
events = []
for _ in range(70):
    v = rnd.choice(vms)
    ptype = "proxmox" if v.platform_id == px.id else "vcenter"
    kind = rnd.choices(["ram", "cpu", "disk", "power", "migrate", "created", "ip"], [14, 8, 8, 18, 10, 6, 6])[0]
    when = now - timedelta(days=rnd.uniform(0, 13), minutes=rnd.randint(0, 600))
    actor = rnd.choice(people[ptype])
    base = dict(entity_type="vm", entity_name=v.name, platform_id=v.platform_id, changed_at=when,
                platform_type=ptype, cluster=v.cluster, host=v.host_ref.name if v.host_ref else "",
                vm_external_id=v.external_id, actor=actor)
    if kind == "ram":
        old = v.ram_mb // 2
        events.append(ChangeHistory(change_type="updated", field="ram_mb", old_value=str(old),
                                    new_value=str(v.ram_mb), category="hardware",
                                    op_type="VmReconfiguredEvent" if ptype == "vcenter" else "update (cluster log)", **base))
    elif kind == "cpu":
        events.append(ChangeHistory(change_type="updated", field="cpu_count", old_value=str(max(2, v.cpu_count // 2)),
                                    new_value=str(v.cpu_count), category="hardware",
                                    op_type="VmReconfiguredEvent" if ptype == "vcenter" else "update (cluster log)", **base))
    elif kind == "disk":
        events.append(ChangeHistory(change_type="updated", field="disk_total_gb", old_value=str(v.disk_total_gb - 100),
                                    new_value=str(v.disk_total_gb), category="disk",
                                    op_type="VmReconfiguredEvent" if ptype == "vcenter" else "resize", **base))
    elif kind == "power":
        on = rnd.random() > .5
        events.append(ChangeHistory(change_type="updated", field="power_state",
                                    old_value="stopped" if on else "running", new_value="running" if on else "stopped",
                                    category="power", op_type=("VmPoweredOnEvent" if on else "VmPoweredOffEvent")
                                    if ptype == "vcenter" else ("qmstart" if on else "qmshutdown"), **base))
    elif kind == "migrate":
        same = [h for h in hosts if h.cluster == v.cluster and h.id != v.host_id] or hosts[:1]
        dst = rnd.choice(same)
        b = dict(base, host=f"{base['host']} → {dst.name}")
        events.append(ChangeHistory(change_type="migrated", field="host", old_value=base["host"], new_value=dst.name,
                                    category="migrate", op_type="VmMigratedEvent" if ptype == "vcenter" else "qmigrate", **b))
    elif kind == "created":
        events.append(ChangeHistory(change_type="created", category="lifecycle",
                                    op_type="VmClonedEvent" if ptype == "vcenter" else "qmclone", **base))
    else:
        events.append(ChangeHistory(change_type="updated", field="ip_addresses", old_value="",
                                    new_value=v.ip_addresses or "10.20.10.99", category="network", **dict(base, actor=None)))
db.add_all(events)

# ---------------------------------------------------------------- capacity trend + daily usage
running = [v for v in vms if v.power_state == "running"]
for d in range(45, -1, -1):
    day = (now - timedelta(days=d)).date()
    g = (45 - d) / 45.0
    db.add(CapacitySnapshot(
        snap_date=day, alloc_disk_gb=sum(v.disk_total_gb for v in vms) * (0.9 + .1 * g),
        alloc_ram_mb=sum(v.ram_mb for v in vms) * (0.92 + .08 * g),
        used_disk_gb=158000 * (0.86 + .14 * g), used_ram_mb=sum(v.ram_usage_mb or 0 for v in running) * (0.88 + .12 * g),
        datastore_capacity_gb=sum(s[5] for s in ds_specs), datastore_used_gb=sum(s[6] for s in ds_specs) * (0.86 + .14 * g),
        host_ram_mb=sum(h.ram_total_mb for h in hosts), host_cpu_cores=sum(h.cpu_cores for h in hosts),
        alloc_vcpu=int(sum(v.cpu_count for v in vms) * (0.93 + .07 * g)), used_cpu_pct=38 + 9 * g + rnd.uniform(-2, 2),
        vm_count=int(len(vms) * (0.93 + .07 * g))))
for v in vms:
    if v.power_state != "running":
        continue
    idle = v.name.startswith(("sandbox", "dev-box", "legacy-erp"))
    for d in range(14, 0, -1):
        cpu = rnd.uniform(.2, 1.5) if idle else (v.cpu_usage_pct or 10) * rnd.uniform(.7, 1.2)
        db.add(VmUsageDaily(vm_id=v.id, day=(now - timedelta(days=d)).date(), cpu_avg=cpu, cpu_max=cpu * 1.8,
                            ram_avg_mb=(v.ram_usage_mb or 0) * (.3 if idle else 1), ram_min_mb=(v.ram_usage_mb or 0) * .2,
                            ram_max_mb=v.ram_usage_mb, net_kbps=.4 if idle else rnd.uniform(40, 900),
                            diskio_kbps=.3 if idle else rnd.uniform(60, 1500), samples=96))
db.commit()
print(f"Demo inventory written to {path}: {len(hosts)} hosts, {len(vms)} VMs, {len(events)} history rows.")
