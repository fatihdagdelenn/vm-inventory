"""
Google-like advanced search engine.

Supported syntax:
  FIELD SEARCHES : ip:10.10.10.15  mac:00:50:56  os:windows  cluster:prod
  NUMERIC        : cpu:>4  ram:>=16  disk:<100
  EMPTY VALUES   : ip:yok  owner:yok  tag:yok
  EXCLUSION      : -cluster:test  !os:windows
  OR             : os:ubuntu,centos
  FREE TEXT      : plain words search across common fields (AND)
"""
import re
from sqlalchemy import or_, and_, not_, func
from sqlalchemy.orm import Query

from ..models import VirtualMachine, Host, Tag, Platform


def _like(col, pattern: str):
    """
        NULL-safe ilike: a NULL column is treated as ''. Without this, exclusion
        (-field:value) would wrongly drop NULL rows.
        """
    return func.coalesce(col, "").ilike(pattern)

# token pattern: [-/!]field:"quoted value" | [-/!]field:value | [-/!]word
TOKEN_RE = re.compile(r'([-!]?)(\w+):"([^"]+)"|([-!]?)(\w+):(\S+)|([-!]?)(\S+)')

# numeric comparison pattern: >=16  <4  >100  =8  16
NUM_RE = re.compile(r'^(>=|<=|>|<|=)?(\d+(?:\.\d+)?)$')

# values that mean "empty"
EMPTY_WORDS = ("yok", "bos", "boş", "none", "empty", "null")

# Simple ilike fields: search field -> model column
FIELD_MAP = {
    "name": VirtualMachine.name,
    "vm": VirtualMachine.name,
    "vmid": VirtualMachine.vmid,
    "id": VirtualMachine.vmid,
    "ip": VirtualMachine.ip_addresses,
    "mac": VirtualMachine.mac_addresses,
    "os": VirtualMachine.guest_os,
    "vlan": VirtualMachine.vlans,
    "cluster": VirtualMachine.cluster,
    "datastore": VirtualMachine.datastore,
    "env": VirtualMachine.environment,
    "environment": VirtualMachine.environment,
    "owner": VirtualMachine.owner,
    "notes": VirtualMachine.notes,
    "not": VirtualMachine.notes,
    "aciklama": VirtualMachine.guest_notes,
    "açıklama": VirtualMachine.guest_notes,
    "desc": VirtualMachine.guest_notes,
    "platformnot": VirtualMachine.guest_notes,
    "pool": VirtualMachine.pool,
    "havuz": VirtualMachine.pool,
    "folder": VirtualMachine.folder,
    "klasor": VirtualMachine.folder,
    "klasör": VirtualMachine.folder,
    "ptag": VirtualMachine.platform_tags,
    "petiket": VirtualMachine.platform_tags,
    "network": VirtualMachine.networks,
}

# Numeric fields: field -> (column, multiplier) - ram is entered in GB, stored MB
NUMERIC_MAP = {
    "cpu": (VirtualMachine.cpu_count, 1),
    "ram": (VirtualMachine.ram_mb, 1024),
    "disk": (VirtualMachine.disk_total_gb, 1),
}

# OS family aliases - "os:linux" catches all distros
# (consistent with the dashboard OS distribution classification)
OS_ALIASES = {
    "linux": ("linux", "ubuntu", "centos", "rhel", "red hat", "debian",
              "suse", "fedora", "alma", "rocky", "oracle linux", "l26"),
    "windows": ("windows", "win"),
}

# Power state mappings (incl. Turkish aliases)
STATUS_MAP = {"calisan": "running", "çalışan": "running", "açık": "running",
              "acik": "running", "kapali": "stopped", "kapalı": "stopped",
              "askida": "suspended", "askıda": "suspended"}

# Tools/Agent state mappings
TOOLS_MAP = {"running": "guestToolsRunning", "calisan": "guestToolsRunning",
             "var": "guestToolsRunning", "ok": "guestToolsRunning",
             "yok": "guestToolsNotRunning", "notrunning": "guestToolsNotRunning",
             "kapali": "guestToolsNotRunning"}


def parse_query(q: str):
    """Split the query into (negative?, field, value) and free-text lists."""
    fields, free_text = [], []
    for m in TOKEN_RE.finditer(q or ""):
        if m.group(2):          # [-]field:"quoted"
            fields.append((bool(m.group(1)), m.group(2).lower(), m.group(3)))
        elif m.group(5):        # [-]field:value
            fields.append((bool(m.group(4)), m.group(5).lower(), m.group(6)))
        elif m.group(8):        # [-]kelime
            word = m.group(8)
            free_text.append((bool(m.group(7)), word))
    return fields, free_text


def _ilike_or(column, value: str):
    """Build an OR'ed ilike condition for comma-separated values."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return or_(*[_like(column, f"%{p}%") for p in parts]) if parts else None


def _field_condition(field: str, value: str):
    """
        Convert one field:value pair into a SQLAlchemy condition.
        A None return means the field was not recognized (falls back to free text).
        """
    vlow = value.lower()

    # ---- Empty-value searches: ip:yok, owner:yok, tag:yok ----
    # NOTE: not applied to specially-mapped fields like status/tools
    # (tools:yok means "agent not installed", not "field empty")
    if vlow in EMPTY_WORDS and field not in ("status", "tools", "agent"):
        if field == "tag":
            return ~VirtualMachine.tags.any()
        col = FIELD_MAP.get(field)
        if col is not None:
            return or_(col.is_(None), col == "")
        if field == "host":
            return VirtualMachine.host_id.is_(None)
        return None

    # ---- Numeric comparisons: cpu:>4, ram:>=16, disk:<100 ----
    if field in NUMERIC_MAP:
        m = NUM_RE.match(value)
        if m:
            op, num = m.group(1) or "=", float(m.group(2))
            col, mult = NUMERIC_MAP[field]
            num *= mult
            return {">": col > num, ">=": col >= num, "<": col < num,
                    "<=": col <= num, "=": col == num}[op]
        return None

    # ---- Related tables ----
    if field in ("host", "node"):       # the host/node it runs on
        cond = _ilike_or(Host.name, value)
        return VirtualMachine.host_ref.has(cond) if cond is not None else None
    if field == "tag":
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return or_(*[VirtualMachine.tags.any(_like(Tag.name, f"%{p}%"))
                     for p in parts])
    if field == "platform":             # platform display name
        cond = _ilike_or(Platform.name, value)
        return VirtualMachine.platform.has(cond) if cond is not None else None
    if field in ("location", "lokasyon"):
        cond = _ilike_or(Platform.location, value)
        return VirtualMachine.platform.has(cond) if cond is not None else None
    if field == "type":                 # platform tipi: vcenter / proxmox
        cond = _ilike_or(Platform.type, value)
        return VirtualMachine.platform.has(cond) if cond is not None else None

    # ---- Specially-mapped fields ----
    if field == "status":
        parts = [STATUS_MAP.get(p.strip().lower(), p.strip().lower())
                 for p in value.split(",") if p.strip()]
        return or_(*[_like(VirtualMachine.power_state, f"%{p}%") for p in parts])
    if field in ("tools", "agent"):
        if vlow in ("yok", "notrunning", "kapali", "kapalı", "none"):
            # Agent/Tools not installed: NotRunning, unknown or empty
            return or_(_like(VirtualMachine.tools_status, "%NotRunning%"),
                       _like(VirtualMachine.tools_status, "%unknown%"),
                       func.coalesce(VirtualMachine.tools_status, "") == "")
        mapped = TOOLS_MAP.get(vlow, value)
        return _like(VirtualMachine.tools_status, f"%{mapped}%")
    if field == "os":
        conds = []
        for part in (p.strip().lower() for p in value.split(",") if p.strip()):
            if part in OS_ALIASES:      # family search: match all distro names
                conds.append(or_(*[_like(VirtualMachine.guest_os, f"%{a}%")
                                   for a in OS_ALIASES[part]]))
            else:
                conds.append(_like(VirtualMachine.guest_os, f"%{part}%"))
        return or_(*conds) if conds else None

    # ---- OS ailesi (tek token): osfam:windows, osfam:other … ----
    # The dashboard pie and filter menu use this field; family logic lives
    # in core/os_family.py (first-match wins -> exclude list).
    if field in ("osfam", "osailesi", "os_family", "osaile"):
        from .os_family import match_keywords
        inc, exc = match_keywords(value)
        if inc is None and exc is None:
            return None          # bilinmeyen aile
        conds = []
        if inc:
            conds.append(or_(*[_like(VirtualMachine.guest_os, f"%{k}%")
                               for k in inc]))
        conds.extend(not_(_like(VirtualMachine.guest_os, f"%{k}%"))
                     for k in exc)
        return and_(*conds) if conds else None

    # ---- Simple ilike fields ----
    if field in FIELD_MAP:
        return _ilike_or(FIELD_MAP[field], value)

    return None     # bilinmeyen alan


def apply_vm_search(query: Query, q: str) -> Query:
    """Apply search filters to the VM query (AND logic, '-' excludes)."""
    fields, free_text = parse_query(q)

    for negative, field, value in fields:
        cond = _field_condition(field, value)
        if cond is None:
            free_text.append((negative, f"{field}:{value}"))  # bilinmeyen alan
            continue
        query = query.filter(not_(cond) if negative else cond)

    for negative, word in free_text:
        like = f"%{word}%"
        cond = or_(
            _like(VirtualMachine.name, like),
            _like(VirtualMachine.vmid, like),
            _like(VirtualMachine.ip_addresses, like),
            _like(VirtualMachine.mac_addresses, like),
            _like(VirtualMachine.guest_os, like),
            _like(VirtualMachine.cluster, like),
            _like(VirtualMachine.notes, like),
            _like(VirtualMachine.guest_notes, like),
            _like(VirtualMachine.platform_tags, like),
            _like(VirtualMachine.pool, like),
            _like(VirtualMachine.folder, like),
            _like(VirtualMachine.owner, like),
            _like(VirtualMachine.networks, like),
            _like(VirtualMachine.vlans, like),
        )
        query = query.filter(not_(cond) if negative else cond)
    return query
