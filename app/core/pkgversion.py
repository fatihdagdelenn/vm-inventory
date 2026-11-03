"""Package version comparison and CVSS scoring - pure Python on purpose.

The prod server builds its image without internet, so a new pip dependency
(python-debian, rpm bindings, cvss) would break `docker compose up --build`
there. These are faithful ports of the reference algorithms:

- dpkg_cmp: dpkg's verrevcmp (lib/dpkg/version.c) incl. epochs and '~'
- rpm_cmp:  rpmvercmp (rpmio/rpmvercmp.c) incl. '~' / '^' and epoch:version-release
- cvss3_score: CVSS v3.0/v3.1 base score from a vector string
"""
import math
import re
from typing import Optional


# ------------------------------------------------------------------ dpkg
def _dpkg_order(c: str) -> int:
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256 if c else 0


def _verrevcmp(a: str, b: str) -> int:
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _dpkg_order(a[i]) if i < len(a) else 0
            bc = _dpkg_order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def _dpkg_split(v: str):
    v = v.strip()
    epoch = 0
    if ":" in v:
        e, v = v.split(":", 1)
        epoch = int(e) if e.isdigit() else 0
    upstream, rev = (v.rsplit("-", 1) + [""])[:2] if "-" in v else (v, "")
    return epoch, upstream, rev


def dpkg_cmp(a: str, b: str) -> int:
    """<0 if a < b, 0 if equal, >0 if a > b (Debian / Ubuntu versions)."""
    ea, ua, ra = _dpkg_split(a)
    eb, ub, rb = _dpkg_split(b)
    if ea != eb:
        return ea - eb
    r = _verrevcmp(ua, ub)
    return r if r else _verrevcmp(ra, rb)


# ------------------------------------------------------------------- rpm
def _rpmvercmp(a: str, b: str) -> int:
    if a == b:
        return 0
    i = j = 0
    while i < len(a) or j < len(b):
        while i < len(a) and not a[i].isalnum() and a[i] not in "~^":
            i += 1
        while j < len(b) and not b[j].isalnum() and b[j] not in "~^":
            j += 1
        if (i < len(a) and a[i] == "~") or (j < len(b) and b[j] == "~"):
            if not (i < len(a) and a[i] == "~"):
                return 1
            if not (j < len(b) and b[j] == "~"):
                return -1
            i += 1
            j += 1
            continue
        if (i < len(a) and a[i] == "^") or (j < len(b) and b[j] == "^"):
            if i >= len(a):
                return -1
            if j >= len(b):
                return 1
            if a[i] != "^":
                return 1
            if b[j] != "^":
                return -1
            i += 1
            j += 1
            continue
        if not (i < len(a) and j < len(b)):
            break
        numeric = a[i].isdigit()
        si, sj = i, j
        test = str.isdigit if numeric else str.isalpha
        while i < len(a) and test(a[i]):
            i += 1
        while j < len(b) and test(b[j]):
            j += 1
        sa, sb = a[si:i], b[sj:j]
        if not sb:                      # segments of different types
            return 1 if numeric else -1
        if numeric:
            sa, sb = sa.lstrip("0"), sb.lstrip("0")
            if len(sa) != len(sb):
                return 1 if len(sa) > len(sb) else -1
        if sa != sb:
            return 1 if sa > sb else -1
    if i >= len(a) and j >= len(b):
        return 0
    return -1 if i >= len(a) else 1


def _rpm_split(v: str):
    v = v.strip()
    epoch = 0
    if ":" in v:
        e, v = v.split(":", 1)
        epoch = int(e) if e.isdigit() else 0
    ver, rel = (v.rsplit("-", 1) + [""])[:2] if "-" in v else (v, "")
    return epoch, ver, rel


def rpm_cmp(a: str, b: str) -> int:
    """<0 / 0 / >0 for [epoch:]version-release strings (RHEL family)."""
    ea, va, ra = _rpm_split(a)
    eb, vb, rb = _rpm_split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    r = _rpmvercmp(va, vb)
    return r if r else _rpmvercmp(ra, rb)


# ------------------------------------------------------------------ CVSS
_W = {
    "AV": {"N": .85, "A": .62, "L": .55, "P": .2}, "AC": {"L": .77, "H": .44},
    "UI": {"N": .85, "R": .62}, "CIA": {"H": .56, "L": .22, "N": 0.0},
}


def _roundup(x: float) -> float:
    i = int(round(x * 100000))
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss3_score(vector: str) -> Optional[float]:
    """Base score of a CVSS:3.0 / 3.1 vector; None when it is not one."""
    if not vector or not re.match(r"CVSS:3\.[01]/", vector):
        return None
    m = dict(p.split(":", 1) for p in vector.split("/")[1:] if ":" in p)
    try:
        scope_changed = m["S"] == "C"
        pr = {"N": .85, "L": .68 if scope_changed else .62,
              "H": .5 if scope_changed else .27}[m["PR"]]
        c, i, a = (_W["CIA"][m[k]] for k in ("C", "I", "A"))
        iss = 1 - (1 - c) * (1 - i) * (1 - a)
        impact = (7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15) if scope_changed else 6.42 * iss
        expl = 8.22 * _W["AV"][m["AV"]] * _W["AC"][m["AC"]] * pr * _W["UI"][m["UI"]]
    except (KeyError, ValueError):
        return None
    if impact <= 0:
        return 0.0
    total = 1.08 * (impact + expl) if scope_changed else impact + expl
    return _roundup(min(total, 10.0))


def severity_of_score(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low" if score > 0 else "none"
