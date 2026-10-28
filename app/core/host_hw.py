"""Effective hardware brand / model of a hypervisor host.

The collectors write one combined string into ``Host.hw_model`` (e.g.
"Dell Inc. PowerEdge Rx5xx"). Proxmox cannot expose the exact system model
through its API, so an operator may override brand / model by hand
(``HostSupplement.brand`` / ``.model``). Every consumer - Hosts page,
physical inventory, exports, scheduled reports - must show the same value,
so the merge rule lives here:

    manual brand / model (when set)  >  value derived from Host.hw_model
"""
import re

# Server chassis families: the model starts at the family name
# ("Dell Inc. PowerEdge R650" -> brand "Dell Inc.", model "PowerEdge R650").
_CHASSIS = re.compile(
    r"\b(PowerEdge|ProLiant|Synergy|Apollo|ThinkSystem|ThinkServer|ThinkAgile"
    r"|PRIMERGY|PowerVault|Super ?[Ss]erver|SYS-|UCS[CB]?-|FusionServer)",
    re.IGNORECASE)

# Vendor prefixes, longest first, for strings without a known chassis family.
_VENDORS = [
    "Hewlett Packard Enterprise", "Hewlett-Packard", "Cisco Systems Inc",
    "Cisco Systems, Inc.", "Super Micro Computer", "Supermicro", "Dell Inc.",
    "Dell EMC", "FUJITSU", "Fujitsu", "Lenovo", "HPE", "HP", "Dell", "IBM",
    "Huawei", "Inspur", "Gigabyte", "ASUSTeK COMPUTER INC.", "Intel Corporation",
    "VMware, Inc.", "QEMU",
]


def split_hw(text: str):
    """Split a combined vendor+model string into (brand, model).

    "Dell Inc. PowerEdge R650" -> ("Dell Inc.", "PowerEdge R650")
    "HPE ProLiant DL380 Gen10" -> ("HPE", "ProLiant DL380 Gen10")
    "HPE"                      -> ("HPE", "")
    A plain first-space split used to give "Dell" / "Inc. PowerEdge R650".
    """
    s = " ".join((text or "").split())
    if not s:
        return "", ""
    m = _CHASSIS.search(s)
    if m and m.start() > 0:
        return s[:m.start()].strip(" ,"), s[m.start():].strip()
    if m:                                   # starts with the family name
        return "", s
    for v in _VENDORS:
        if s.lower() == v.lower():
            return s, ""
        if s.lower().startswith(v.lower() + " "):
            return s[:len(v)], s[len(v):].strip()
    if " " not in s:
        return s, ""
    brand, model = s.split(" ", 1)
    return brand, model


def effective_hw(host, sup=None) -> dict:
    """Merged hardware info for one host.

    Returns {brand, model, text, manual, auto}: ``text`` is what lists show,
    ``manual`` is True when an operator override is in effect, ``auto`` is
    the collector value (kept visible so a better detection can be noticed).
    """
    auto = (getattr(host, "hw_model", None) or "").strip()
    brand, model = split_hw(auto)
    manual = bool(sup and ((sup.brand or "").strip() or (sup.model or "").strip()))
    if manual:
        brand = (sup.brand or "").strip() or brand
        model = (sup.model or "").strip() or model
    text = " ".join(x for x in (brand, model) if x)
    return {"brand": brand, "model": model, "text": text,
            "manual": manual, "auto": auto}


def supplements_by_host(db) -> dict:
    """{host_id: HostSupplement} for every host that has manual extras."""
    from ..models import HostSupplement
    return {s.host_id: s for s in db.query(HostSupplement).all()}


def annotate_hosts(db, hosts):
    """Attach export-only attributes (hw_brand, hw_name, hw_source) to Host
    ORM objects so report_service can read them like ordinary columns."""
    sups = supplements_by_host(db)
    for h in hosts:
        hw = effective_hw(h, sups.get(h.id))
        h.hw_brand = hw["brand"]
        h.hw_name = hw["model"]
        h.hw_source = ("Elle" if hw["manual"] else "Otomatik") if hw["text"] else ""
    return hosts
