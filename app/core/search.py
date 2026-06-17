"""
Google benzeri gelişmiş arama motoru.

Desteklenen söz dizimi:
    ALAN ARAMALARI : ip:10.10.10.15  mac:00:50:56  os:windows  name:web
                     vlan:100  cluster:production  host:esxi01  node:pve01
                     status:running  datastore:ds01  tag:kritik  env:test
                     platform:"Ankara vCenter"  location:ankara  owner:ali
                     tools:running | tools:yok   (VMware Tools / QEMU Agent)
    SAYISAL        : cpu:>4  cpu:>=8  ram:>=16 (GB)  ram:<4  disk:>500 (GB)
    DIŞLAMA        : -os:windows  -cluster:test  -web01  (önüne '-' koy)
    ÇOKLU DEĞER    : os:windows,linux   status:running,suspended  (virgül = VEYA)
    BOŞ DEĞER      : ip:yok  (IP'si alınamayan VM'ler)  owner:yok  tag:yok
    SERBEST METİN  : alan belirtilmeyen kelimeler ad, IP, MAC, OS, cluster
                     ve notlarda aranır
    TIRNAKLAMA     : cluster:"Ankara Prod"  (boşluk içeren değerler)

Kriterler boşlukla birleştirilir (VE mantığı):
    cluster:production os:linux status:running ram:>=16 -tag:test

Tüm sorgular LOKAL veritabanına gider - canlı API çağrısı yapılmaz.
"""
import re
from sqlalchemy import or_, and_, not_, func
from sqlalchemy.orm import Query

from ..models import VirtualMachine, Host, Tag, Platform


def _like(col, pattern: str):
    """
    NULL-güvenli ilike: kolon NULL ise '' kabul edilir.
    Bu olmadan dışlama (-alan:değer) NULL satırları yanlışlıkla eler
    (SQL üç değerli mantık: NOT NULL = NULL).
    """
    return func.coalesce(col, "").ilike(pattern)

# token deseni: [-]alan:"tırnaklı değer" | [-]alan:değer | [-]kelime
TOKEN_RE = re.compile(r'(-?)(\w+):"([^"]+)"|(-?)(\w+):(\S+)|(-?)(\S+)')

# sayısal karşılaştırma deseni: >=16  <4  >100  =8  16
NUM_RE = re.compile(r'^(>=|<=|>|<|=)?(\d+(?:\.\d+)?)$')

# "boş" anlamına gelen değerler
EMPTY_WORDS = ("yok", "bos", "boş", "none", "empty", "null")

# Basit ilike alanları: arama alanı -> model kolonu
FIELD_MAP = {
    "name": VirtualMachine.name,
    "vm": VirtualMachine.name,
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
    "network": VirtualMachine.networks,
}

# Sayısal alanlar: alan -> (kolon, çarpan)  — ram GB cinsinden girilir, MB saklanır
NUMERIC_MAP = {
    "cpu": (VirtualMachine.cpu_count, 1),
    "ram": (VirtualMachine.ram_mb, 1024),
    "disk": (VirtualMachine.disk_total_gb, 1),
}

# OS ailesi takma adları — "os:linux" tüm dağıtımları yakalar
# (dashboard'daki OS dağılım sınıflandırmasıyla tutarlı)
OS_ALIASES = {
    "linux": ("linux", "ubuntu", "centos", "rhel", "red hat", "debian",
              "suse", "fedora", "alma", "rocky", "oracle linux", "l26"),
    "windows": ("windows", "win"),
}

# Güç durumu eşlemeleri (TR karşılıkları dahil)
STATUS_MAP = {"calisan": "running", "çalışan": "running", "açık": "running",
              "acik": "running", "kapali": "stopped", "kapalı": "stopped",
              "askida": "suspended", "askıda": "suspended"}

# Tools/Agent durumu eşlemeleri
TOOLS_MAP = {"running": "guestToolsRunning", "calisan": "guestToolsRunning",
             "var": "guestToolsRunning", "ok": "guestToolsRunning",
             "yok": "guestToolsNotRunning", "notrunning": "guestToolsNotRunning",
             "kapali": "guestToolsNotRunning"}


def parse_query(q: str):
    """Sorguyu (negatif?, alan, değer) ve serbest metin listelerine ayır."""
    fields, free_text = [], []
    for m in TOKEN_RE.finditer(q or ""):
        if m.group(2):          # [-]alan:"tırnaklı"
            fields.append((bool(m.group(1)), m.group(2).lower(), m.group(3)))
        elif m.group(5):        # [-]alan:değer
            fields.append((bool(m.group(4)), m.group(5).lower(), m.group(6)))
        elif m.group(8):        # [-]kelime
            word = m.group(8)
            free_text.append((bool(m.group(7)), word))
    return fields, free_text


def _ilike_or(column, value: str):
    """Virgülle ayrılmış değerler için OR'lu ilike koşulu üret."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return or_(*[_like(column, f"%{p}%") for p in parts]) if parts else None


def _field_condition(field: str, value: str):
    """
    Tek bir alan:değer çiftini SQLAlchemy koşuluna çevir.
    Dönüş None ise alan tanınmadı demektir (serbest metne düşülür).
    """
    vlow = value.lower()

    # ---- Boş değer aramaları: ip:yok, owner:yok, tag:yok ----
    # NOT: status/tools gibi özel eşlemeli alanlara uygulanmaz
    # (tools:yok "agent kurulu değil" demektir, "alan boş" değil)
    if vlow in EMPTY_WORDS and field not in ("status", "tools", "agent"):
        if field == "tag":
            return ~VirtualMachine.tags.any()
        col = FIELD_MAP.get(field)
        if col is not None:
            return or_(col.is_(None), col == "")
        if field == "host":
            return VirtualMachine.host_id.is_(None)
        return None

    # ---- Sayısal karşılaştırmalar: cpu:>4, ram:>=16, disk:<100 ----
    if field in NUMERIC_MAP:
        m = NUM_RE.match(value)
        if m:
            op, num = m.group(1) or "=", float(m.group(2))
            col, mult = NUMERIC_MAP[field]
            num *= mult
            return {">": col > num, ">=": col >= num, "<": col < num,
                    "<=": col <= num, "=": col == num}[op]
        return None

    # ---- İlişkili tablolar ----
    if field in ("host", "node"):       # üzerinde çalıştığı host/node adı
        cond = _ilike_or(Host.name, value)
        return VirtualMachine.host_ref.has(cond) if cond is not None else None
    if field == "tag":
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return or_(*[VirtualMachine.tags.any(_like(Tag.name, f"%{p}%"))
                     for p in parts])
    if field == "platform":             # platform görünen adı
        cond = _ilike_or(Platform.name, value)
        return VirtualMachine.platform.has(cond) if cond is not None else None
    if field in ("location", "lokasyon"):
        cond = _ilike_or(Platform.location, value)
        return VirtualMachine.platform.has(cond) if cond is not None else None
    if field == "type":                 # platform tipi: vcenter / proxmox
        cond = _ilike_or(Platform.type, value)
        return VirtualMachine.platform.has(cond) if cond is not None else None

    # ---- Özel eşlemeli alanlar ----
    if field == "status":
        parts = [STATUS_MAP.get(p.strip().lower(), p.strip().lower())
                 for p in value.split(",") if p.strip()]
        return or_(*[_like(VirtualMachine.power_state, f"%{p}%") for p in parts])
    if field in ("tools", "agent"):
        if vlow in ("yok", "notrunning", "kapali", "kapalı", "none"):
            # Agent/Tools kurulu değil: NotRunning, unknown veya boş
            return or_(_like(VirtualMachine.tools_status, "%NotRunning%"),
                       _like(VirtualMachine.tools_status, "%unknown%"),
                       func.coalesce(VirtualMachine.tools_status, "") == "")
        mapped = TOOLS_MAP.get(vlow, value)
        return _like(VirtualMachine.tools_status, f"%{mapped}%")
    if field == "os":
        conds = []
        for part in (p.strip().lower() for p in value.split(",") if p.strip()):
            if part in OS_ALIASES:      # aile araması: tüm dağıtım adlarıyla eşle
                conds.append(or_(*[_like(VirtualMachine.guest_os, f"%{a}%")
                                   for a in OS_ALIASES[part]]))
            else:
                conds.append(_like(VirtualMachine.guest_os, f"%{part}%"))
        return or_(*conds) if conds else None

    # ---- Basit ilike alanları ----
    if field in FIELD_MAP:
        return _ilike_or(FIELD_MAP[field], value)

    return None     # bilinmeyen alan


def apply_vm_search(query: Query, q: str) -> Query:
    """VM sorgusuna arama filtrelerini uygula (VE mantığı, '-' ile dışlama)."""
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
            _like(VirtualMachine.ip_addresses, like),
            _like(VirtualMachine.mac_addresses, like),
            _like(VirtualMachine.guest_os, like),
            _like(VirtualMachine.cluster, like),
            _like(VirtualMachine.notes, like),
            _like(VirtualMachine.guest_notes, like),
            _like(VirtualMachine.owner, like),
        )
        query = query.filter(not_(cond) if negative else cond)
    return query
