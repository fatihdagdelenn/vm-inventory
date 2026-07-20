"""Shared harness for the per-platform actor-attribution regression tests.

Run the suites BEFORE shipping any change that touches actor matching:

    PYTHONPATH=. python3 tests/test_actors_vmware.py
    PYTHONPATH=. python3 tests/test_actors_proxmox.py

They are fully offline: heavy SDKs are stubbed and a throwaway SQLite file is
used. Each platform's scenarios live in their own file ON PURPOSE - fixing one
platform must never silently regress the other.
"""
import os
import sys
import types

for _n in ["pyVmomi", "proxmoxer", "ldap3", "pyVim", "pyVim.connect"]:
    _m = types.ModuleType(_n)
    _m.__getattr__ = lambda a: type(a, (), {})
    sys.modules[_n] = _m

os.environ.setdefault("SECRET_KEY", "x")
os.environ.setdefault("ENCRYPTION_KEY", "x")


def make_env(db_name):
    """Fresh engine + session factory + platform; returns (db, platform_id, ss)."""
    os.environ["DATABASE_URL"] = f"sqlite:///./data/{db_name}.db"
    os.makedirs("data", exist_ok=True)
    path = f"data/{db_name}.db"
    if os.path.exists(path):
        os.remove(path)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, ensure_schema
    import app.models  # noqa: F401  (registers tables)
    import app.services.sync_service as ss

    eng = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(eng)
    ensure_schema(eng)
    S = sessionmaker(bind=eng)
    ss.SessionLocal = S
    return S(), ss


class FakeCollector:
    """Minimal collector double: pass vms / hosts / actor-ops per sync."""

    def __init__(self, vms=None, hosts=None, vm_ops=None, backups=None):
        self.vms = vms or []
        self.hosts = hosts or [{"external_id": "h1", "name": "h1",
                                "cluster": "c1", "status": "online"}]
        self.vm_ops = vm_ops or {}
        self.backups = backups or []

    def connect(self):
        pass

    def disconnect(self):
        pass

    def collect_hosts(self):
        return [dict(h) for h in self.hosts]

    def collect_vms(self):
        return [dict(v) for v in self.vms]

    def collect_networks(self):
        return []

    def collect_datastores(self):
        return []

    def collect_snapshots(self):
        return []

    def collect_backups(self):
        return [dict(b) for b in self.backups]

    def collect_recent_actors(self):
        return {k: [dict(o) for o in v] for k, v in self.vm_ops.items()}

    def collect_entity_actors(self):
        return {}


def run_sync(ss, platform_id, collector):
    ss._build_collector = lambda plat: collector
    ss.sync_platform(platform_id)


def op(ts, optype, category, direction=None, actor=None, host=None, detail=None):
    return {"ts": ts, "op": optype, "category": category, "direction": direction,
            "actor": actor, "actor_ip": None, "actor_agent": None,
            "host": host, "detail": detail}


def change_rows(db, field=None, change_type=None):
    from app.models import ChangeHistory
    q = db.query(ChangeHistory).filter_by(entity_type="vm")
    if field:
        q = q.filter_by(field=field)
    if change_type:
        q = q.filter_by(change_type=change_type)
    return q.order_by(ChangeHistory.id).all()
