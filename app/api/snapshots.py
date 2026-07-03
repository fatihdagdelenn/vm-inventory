"""Snapshot list API - rich search, sorting, age info.
Search syntax (like the VM screen, space = AND):
  vm:web  snap:upgrade  age:>30  current:yes  parent:none  -snap:test"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Snapshot, Platform, VirtualMachine
from ..core.security import get_current_user
from ..core.timezone import to_iso

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

TOKEN_RE = re.compile(r'(-?)(\w+):"([^"]+)"|(-?)(\w+):(\S+)|(-?)(\S+)')
NUM_RE = re.compile(r'^(>=|<=|>|<|=)?(\d+)$')
FIELD_ALIASES = {
    "vm": "vm", "name": "name", "snap": "name", "snapshot": "name",
    "platform": "platform", "pf": "platform",
    "desc": "desc", "aciklama": "desc", "açıklama": "desc",
    "parent": "parent", "ust": "parent", "üst": "parent",
    "current": "current", "aktif": "current", "active": "current",
    "age": "age", "yas": "age", "yaş": "age",
    "cluster": "cluster", "kume": "cluster", "küme": "cluster",
}
TRUE = {"yes", "evet", "true", "1", "var", "aktif"}
FALSE = {"no", "hayir", "hayır", "false", "0", "yok"}


def _parse(q: str):
    toks = []
    for m in TOKEN_RE.finditer(q or ""):
        if m.group(2):      # field:"quoted"
            toks.append((m.group(1) == "-", m.group(2).lower(), m.group(3)))
        elif m.group(5):    # field:value
            toks.append((m.group(4) == "-", m.group(5).lower(), m.group(6)))
        elif m.group(8):    # serbest kelime
            toks.append((m.group(7) == "-", None, m.group(8)))
    return toks


def _token_ok(s: Snapshot, pname: str, cluster: str, field, val: str) -> bool:
    if field is None:   # serbest metin
        hay = " ".join([s.vm_name or "", s.name or "", s.description or "",
                        s.parent or "", pname or "", cluster or ""]).lower()
        return val.lower() in hay
    field = FIELD_ALIASES.get(field)
    if field is None:
        return False
    if field == "age":
        m = NUM_RE.match(val)
        if not m or s.age_days is None:
            return False
        op, num, a = m.group(1) or "=", int(m.group(2)), s.age_days
        return {">": a > num, "<": a < num, ">=": a >= num,
                "<=": a <= num, "=": a == num}[op]
    if field == "current":
        v = val.lower()
        return bool(s.is_current) if v in TRUE else (not s.is_current) if v in FALSE else False
    target = {"vm": s.vm_name, "name": s.name, "platform": pname,
              "desc": s.description, "parent": s.parent, "cluster": cluster}.get(field) or ""
    target = target.lower()
    for piece in val.split(","):
        piece = piece.strip().lower()
        if piece == "yok" and target == "":
            return True
        if piece and piece != "yok" and piece in target:
            return True
    return False


def _matches(s, pname, cluster, toks) -> bool:
    for neg, field, val in toks:
        ok = _token_ok(s, pname, cluster, field, val)
        if neg and ok:
            return False
        if not neg and not ok:
            return False
    return True


def _row(s: Snapshot, pname: str, ptype: str, cluster: str) -> dict:
    return {
        "id": s.id, "vm_name": s.vm_name, "name": s.name,
        "description": s.description or "", "created_at": to_iso(s.created_at),
        "age_days": s.age_days, "is_current": bool(s.is_current),
        "parent": s.parent or "", "size_gb": s.size_gb,
        "platform": pname or "", "platform_type": ptype or "",
        "cluster": cluster or "",
    }


_SORT_KEYS = {
    "vm_name": lambda r: (r[0].vm_name or "").lower(),
    "name": lambda r: (r[0].name or "").lower(),
    "platform": lambda r: (r[1] or "").lower(),
    "cluster": lambda r: (r[3] or "").lower(),
    "created_at": lambda r: r[0].created_at or datetime.min,
    "age": lambda r: r[0].age_days if r[0].age_days is not None else -1,
}


@router.get("")
def list_snapshots(q: str = "", sort: str = "created_at", order: str = "asc",
                   db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    rows = (db.query(Snapshot, Platform.name, Platform.type, VirtualMachine.cluster)
              .outerjoin(Platform, Snapshot.platform_id == Platform.id)
              .outerjoin(VirtualMachine, Snapshot.vm_id == VirtualMachine.id).all())
    # Exclude snapshots of VMs in hidden clusters (consistent with dashboard/VM list)
    from .clusters import hidden_cluster_names, NONE_SENTINEL
    hidden = set(hidden_cluster_names(db))
    if hidden:
        rows = [r for r in rows if not (
            (r[3] and r[3] in hidden) or (not r[3] and NONE_SENTINEL in hidden))]
    platforms = sorted({pn for _, pn, _, _ in rows if pn})
    clusters = sorted({cl for _, _, _, cl in rows if cl})
    toks = _parse(q)
    if toks:
        rows = [r for r in rows if _matches(r[0], r[1], r[3], toks)]
    rows.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["created_at"]),
              reverse=(order == "desc"))
    return {"items": [_row(s, pn, pt, cl) for s, pn, pt, cl in rows],
            "platforms": platforms, "clusters": clusters}
