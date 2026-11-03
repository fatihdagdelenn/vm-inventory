"""
Click-to-filter tokens of the Virtual Machines table (phase 157).

Every token a table cell produces must find exactly the VMs that show that
value: exact OS / kernel names (also with a comma in them), agent badges
(Active / Passive / None), platform, power state, CPU count and RAM in GB.

Run:  PYTHONPATH=. python3 tests/test_vm_cell_filters.py
"""
import sys
sys.path.insert(0, "tests")

from _actor_harness import make_env  # noqa: E402

db, ss = make_env("_cellfilters")
from app.models import Platform, VirtualMachine  # noqa: E402
from app.core.search import apply_vm_search, _split_values  # noqa: E402
import app.api.vms as vms_api  # noqa: E402

vc = Platform(name="vc", type="vcenter", host="v", environment="p", enabled=True)
pm = Platform(name="pm", type="proxmox", host="p", environment="p", enabled=True)
db.add_all([vc, pm]); db.commit()
WIN = "Windows Server 2022, 64-bit (Build 20348.2582)"
rows = [
    (vc, "w1", WIN, "NT 10.0.20348.2582", "guestToolsRunning", "running", 4, 8192),
    (vc, "w2", "Windows Server 2022", None, "guestToolsNotRunning", "running", 4, 8192),
    (vc, "u1", "Ubuntu 24.04.1 LTS", "6.8.0-45-generic", "guestToolsRunning", "stopped", 2, 512),
    (pm, "u2", "Ubuntu 24.04.1 LTS (Noble)", "6.8.0-45-generic", "guestToolsNotRunning", "running", 8, 16384),
    (pm, "r1", "Rocky Linux 9.4", None, "", "suspended", 8, 16384),
]
for p, n, os_, k, ts, st, cpu, ram in rows:
    db.add(VirtualMachine(platform_id=p.id, external_id=n, name=n, guest_os=os_, kernel=k,
                          tools_status=ts, power_state=st, cpu_count=cpu, ram_mb=ram))
db.commit()
q = lambda s: {v.name for v in apply_vm_search(db.query(VirtualMachine), s)}
agent = {v.name: vms_api._agent_state(v.tools_status, v.platform.type) for v in db.query(VirtualMachine)}

# splitting: an exact value keeps its own comma; mixed lists still split
assert _split_values('=' + WIN) == ['=' + WIN]
assert _split_values('=Lab,=DC East') == ['=Lab', '=DC East']
assert _split_values('lab,dc') == ['lab', 'dc']

# OS / kernel exact (cell click) vs partial (typed)
assert q('os:"=' + WIN + '"') == {"w1"}
assert q('os:"=Ubuntu 24.04.1 LTS"') == {"u1"}             # not "... (Noble)"
assert q('os:ubuntu') == {"u1", "u2"}                      # partial still works
assert q('os:linux') == {"u1", "u2", "r1"}                 # family alias untouched
assert q('-os:"=Ubuntu 24.04.1 LTS"') == {"w1", "w2", "u2", "r1"}
assert q('kernel:"=NT 10.0.20348.2582"') == {"w1"}
assert q('kernel:=6.8.0-45-generic') == {"u1", "u2"}

# agent badges: same split as api/vms._agent_state
by_state = {s: {n for n, a in agent.items() if a == s} for s in ("running", "stopped", "none")}
assert q("tools:running") == by_state["running"] == {"w1", "u1"}
assert q("tools:passive") == by_state["stopped"] == {"w2"}          # vCenter only
assert q("tools:pasif") == {"w2"}
assert q("tools:none -tools:passive") == by_state["none"] == {"u2", "r1"}
assert q("tools:none") == {"w2", "u2", "r1"}                       # documented superset
assert q("-tools:passive") == {"w1", "u1", "u2", "r1"}

# platform / status / cpu / ram (GB, incl. fractions)
assert q("type:vcenter") == {"w1", "w2", "u1"}
assert q("status:suspended") == {"r1"}
assert q("cpu:8") == {"u2", "r1"}
assert q("ram:16") == {"u2", "r1"}
assert q("ram:0.5") == {"u1"}
print("CELL FILTER SUITE OK")
