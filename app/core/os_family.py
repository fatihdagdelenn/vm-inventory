"""
OS family classification (single source of truth).
Used by both the dashboard OS pie and the VM page family filter.
"""

# (key, label, keywords [lowercase])
FAMILIES = [
    ("windows",    "Windows",            ["windows", "w2k"]),
    ("ubuntu",     "Ubuntu",             ["ubuntu"]),
    ("debian",     "Debian",             ["debian"]),
    ("redhat",     "Red Hat / CentOS",   ["rhel", "red hat", "redhat", "centos",
                                          "rocky", "almalinux", "alma", "fedora",
                                          "oracle linux"]),
    ("suse",       "SUSE",               ["suse", "sles"]),
    ("otherlinux", "Diğer Linux",        ["linux", "l26", "l24"]),
    ("bsd",        "BSD / Solaris",      ["bsd", "solaris", "openindiana",
                                          "aix", "unix"]),
    ("vmware",     "VMware / Appliance", ["vmware", "esxi", "photon"]),
    ("macos",      "macOS",              ["mac os", "macos", "darwin", "os x"]),
]

CATCHALL_KEY = "other"
CATCHALL_LABEL = "Diğer / Bilinmiyor"

LABELS = {k: lbl for k, lbl, _kw in FAMILIES}
LABELS[CATCHALL_KEY] = CATCHALL_LABEL


def classify(guest_os: str) -> str:
    """guest_os -> family key (first match); CATCHALL_KEY when none."""
    s = (guest_os or "").lower()
    for key, _label, kws in FAMILIES:
        if any(k in s for k in kws):
            return key
    return CATCHALL_KEY


def match_keywords(key: str):
    """
        Return (include, exclude) keyword lists for a family key.
        - include: words selecting the family (empty for CATCHALL)
        - exclude: words of families ranked above it (first-match-wins logic)
        """
    key = (key or "").lower()
    before = []
    for idx, (k, _label, kws) in enumerate(FAMILIES):
        if k == key:
            return list(kws), list(before)
        before.extend(kws)
    if key == CATCHALL_KEY:
        return None, before          # anything that fits no family (incl. blank OS)
    return None, None                # bilinmeyen key


def distribution(rows):
    """
        rows: (guest_os, count) pairs. Returns [{key, label, count, query}]
        sorted by count desc. query is the single-token search filter.
        """
    agg = {}
    for os_name, count in rows:
        agg[classify(os_name)] = agg.get(classify(os_name), 0) + count
    out = [{"key": k, "label": LABELS.get(k, k), "count": c,
            "query": f"osfam:{k}"} for k, c in agg.items()]
    out.sort(key=lambda x: x["count"], reverse=True)
    return out
