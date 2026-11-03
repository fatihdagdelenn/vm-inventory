"""Operating-system identity of a VM, for lifecycle (EOL) tracking.

identify(guest_os, kernel) turns the OS string the inventory already stores
into an endoflife.date product + release cycle:

    "Ubuntu 24.04.2 LTS"                              -> ubuntu 24.04         (high)
    "Red Hat Enterprise Linux 7 (64-bit)"             -> rhel 7               (estimated)
    "Microsoft Windows Server 2016 or later (64-bit)"
        + kernel "NT 10.0.20348.2582"                 -> windows-server 2022  (high, kernel)
    "VMware Photon OS/Linux" + kernel "6.1.126-5.ph5" -> vmware-photon 5.0    (high, kernel)
    "Other 2.6.x Linux (64-bit)"                      -> unknown

`distro` is the endoflife.date product id and `version` its release-cycle id,
so a lookup is a plain key match. Confidence:

- high      - the name the guest itself reports (VMware Tools detailed data,
              QEMU agent get-osinfo) or a version read from the kernel string;
- estimated - VMware's catalog name from the VM settings ("... (64-bit)") or
              the Proxmox ostype hint: what someone picked when the VM was
              created, not what is installed (prod has CentOS 7 VMs whose
              settings still say "CentOS 4/5");
- none      - nothing recognisable.

`version` is None whenever the string does not pin one release down
("Ubuntu Linux (64-bit)", "Windows Server 2016 or later", "CentOS 4/5").
"""
import re
from dataclasses import dataclass
from typing import Optional

# endoflife.date product id -> display name
PRODUCT_NAMES = {
    "ubuntu": "Ubuntu", "debian": "Debian", "rhel": "RHEL", "centos": "CentOS",
    "centos-stream": "CentOS Stream", "rocky-linux": "Rocky Linux",
    "almalinux": "AlmaLinux", "oracle-linux": "Oracle Linux", "sles": "SLES",
    "opensuse": "openSUSE Leap", "fedora": "Fedora", "amazon-linux": "Amazon Linux",
    "windows-server": "Windows Server", "windows": "Windows",
    "freebsd": "FreeBSD", "vmware-photon": "Photon OS",
}
RHEL_FAMILY = ("rhel", "centos", "rocky-linux", "almalinux", "oracle-linux")


@dataclass(frozen=True)
class OsIdentity:
    distro: Optional[str]       # endoflife.date product id
    version: Optional[str]      # release-cycle id ("24.04", "9", "2022", "11-23h2")
    confidence: str             # high | estimated | none
    source: str                 # agent | catalog | ostype | kernel | none
    edition: Optional[str] = None   # Windows client cycle suffix: w | e | e-lts | iot-lts
    prefix: Optional[str] = None    # Windows client without a build: "10-" / "11-"

    @property
    def label(self) -> str:
        """Human label: 'Ubuntu 24.04', 'Windows 11 23H2', 'RHEL'."""
        if not self.distro:
            return ""
        name = PRODUCT_NAMES.get(self.distro, self.distro)
        if not self.version:
            return name
        v = self.version
        if self.distro == "windows":
            v = v.replace("-", " ", 1).upper()
        elif self.distro == "windows-server":
            v = v.replace("-r2", " R2").replace("-sp", " SP").upper()
        elif self.distro == "sles" and "." in v:          # 15.5 -> 15 SP5, 15.0 -> 15
            major, sp = v.split(".", 1)
            v = major if sp == "0" else f"{major} SP{sp}"
        return f"{name} {v}"

    def cycles(self):
        """Candidate release-cycle ids for the lifecycle lookup, best first.
        Windows 10 22H2 is a single cycle, most others split by edition."""
        if not self.version:
            return []
        if self.distro == "windows" and self.edition:
            return [f"{self.version}-{self.edition}", self.version]
        return [self.version]


UNKNOWN = OsIdentity(None, None, "none", "none")

# Strings the Proxmox collector emits from the VM's 'ostype' when no agent
# answers (collectors/proxmox_collector.py OSTYPE_MAP + LXC ostype names).
_PROXMOX_OSTYPE = {
    "linux", "linux (eski çekirdek)", "windows 11 / server 2022+",
    "windows 10 / server 2016-2019", "windows 8 / server 2012",
    "windows 7 / server 2008 r2", "windows server 2008", "windows server 2003",
    "windows 2000", "windows xp", "windows vista", "solaris / openindiana",
    "diğer", "other",
}
_CATALOG_RE = re.compile(r"\((?:32|64)-bit\)\s*$|\bor later\b|^other\b", re.I)

# NT build -> release (Windows kernel string "NT 10.0.<build>[.<ubr>]")
_SERVER_BUILDS = {
    6002: "2008-sp2", 6003: "2008-sp2", 7601: "2008-r2-sp1", 9200: "2012",
    9600: "2012-r2", 14393: "2016", 17763: "2019", 20348: "2022",
    25398: "23h2-ac", 26100: "2025",
}
_CLIENT_BUILDS = {
    10240: "10-1507", 10586: "10-1511", 14393: "10-1607", 15063: "10-1703",
    16299: "10-1709", 17134: "10-1803", 17763: "10-1809", 18362: "10-1903",
    18363: "10-1909", 19041: "10-2004", 19042: "10-20h2", 19043: "10-21h1",
    19044: "10-21h2", 19045: "10-22h2", 22000: "11-21h2", 22621: "11-22h2",
    22631: "11-23h2", 26100: "11-24h2", 26200: "11-25h2", 26300: "11-26h2",
    28000: "11-26h1",
}
_DEBIAN_CODENAMES = {
    "trixie": "13", "bookworm": "12", "bullseye": "11", "buster": "10",
    "stretch": "9", "jessie": "8", "wheezy": "7", "squeeze": "6",
}


def _nt_build(kernel: str) -> Optional[int]:
    m = re.match(r"^\s*NT\s+\d+\.\d+\.(\d+)", kernel or "")
    return int(m.group(1)) if m else None


def _source_of(guest_os: str) -> str:
    s = guest_os.strip().lower()
    if s in _PROXMOX_OSTYPE:
        return "ostype"
    # LXC containers report the bare ostype ("Ubuntu", "Debian", "Centos")
    if re.fullmatch(r"[a-z]+", s):
        return "ostype"
    if _CATALOG_RE.search(guest_os):
        return "catalog"
    return "agent"


def _windows(s: str, kernel: str):
    """(distro, version, edition, version_from_kernel)"""
    low = s.lower()
    build = _nt_build(kernel)
    if build is None:                     # VMware pretty name "... (Build 20348.2582)"
        m = re.search(r"\bbuild\s+(\d{4,5})", low)
        build = int(m.group(1)) if m else None
    if "/" in low:                        # Proxmox ostype "Windows 10 / Server 2016-2019"
        return ("windows-server" if "server" in low else "windows"), None, None, False
    server = "server" in low
    if server:
        if build in _SERVER_BUILDS:
            return "windows-server", _SERVER_BUILDS[build], None, True
        if re.search(r"or later|\d{4}\s*[-+/]|\+", low):     # "2016 or later", "2016-2019", "2022+"
            return "windows-server", None, None, False
        m = re.search(r"server\s*(\d{4})(\s*r2)?", low)
        if not m:
            return "windows-server", None, None, False
        year, r2 = m.group(1), bool(m.group(2))
        if year == "2012":
            return "windows-server", "2012-r2" if r2 else "2012", None, False
        if year == "2008":
            return "windows-server", "2008-r2-sp1" if r2 else "2008-sp2", None, False
        if year == "2003":
            return "windows-server", "2003-sp2", None, False
        return "windows-server", year, None, False
    if "ltsc" in low or "ltsb" in low:
        edition = "iot-lts" if "iot" in low else "e-lts"
    elif "enterprise" in low or "education" in low:
        edition = "e"
    else:
        edition = "w"
    if build in _CLIENT_BUILDS and _CLIENT_BUILDS[build][:2] in ("10", "11"):
        ver = _CLIENT_BUILDS[build]
        # 26100 is both Server 2025 and Windows 11 24H2 - the name decides
        return "windows", ver, edition, True
    m = re.search(r"windows\s*(11|10|8\.1|8|7)\b", low)
    if m and m.group(1) == "7":
        return "windows", "7-sp1", None, False
    if m and m.group(1) in ("8.1", "8"):
        return "windows", m.group(1), None, False
    return "windows", None, edition, False      # 10 / 11: feature update unknown


_LINUX_RULES = [
    # (product, regex, version builder) - first match wins; order matters
    ("centos-stream", r"centos\s+stream\s*(\d+)", lambda m: m.group(1)),
    ("centos", r"centos(?:\s+linux)?\s*(\d+)(?!\s*/)\b", lambda m: m.group(1)),
    ("rocky-linux", r"rocky(?:\s+linux)?\s*(\d+)", lambda m: m.group(1)),
    ("almalinux", r"alma\s*linux\s*(\d+)", lambda m: m.group(1)),
    ("oracle-linux", r"oracle\s+linux(?:\s+server)?\s*(?:release\s*)?(\d+)", lambda m: m.group(1)),
    ("rhel", r"(?:red\s*hat\s+enterprise\s+linux|\brhel)(?:\s+(?:server|workstation|for\s+\w+))?"
             r"\s*(?:release\s*)?(\d+)", lambda m: m.group(1)),
    ("ubuntu", r"ubuntu\s+(\d{2}\.\d{2})", lambda m: m.group(1)),
    ("debian", r"debian(?:\s+gnu/linux)?\s+(\d{1,2})\b", lambda m: m.group(1)),
    ("opensuse", r"opensuse\s+leap\s*(\d+\.\d+)", lambda m: m.group(1)),
    ("sles", r"(?:suse\s+linux\s+enterprise(?:\s+server)?|\bsles)\s*(\d+)(?:[\s-]*sp\s*(\d+))?",
     lambda m: f"{m.group(1)}.{m.group(2) or 0}"),
    ("fedora", r"fedora(?:\s+linux)?\s*(\d+)", lambda m: m.group(1)),
    ("amazon-linux", r"amazon\s+linux(?:\s+ami)?\s*(2023|2018\.03|2017\.09|2\b)", lambda m: m.group(1)),
    ("freebsd", r"freebsd\s*(\d+)(?:\.(\d+))?", lambda m: m.group(1) + (f".{m.group(2)}" if m.group(2) else "")),
    ("vmware-photon", r"photon\s*(?:os)?\s*(\d+)(?:\.(\d+))?", lambda m: f"{m.group(1)}.{m.group(2) or 0}"),
]
# Name without a version -> product only
_PRODUCT_ONLY = [
    ("centos-stream", r"centos\s+stream"), ("centos", r"centos"), ("rocky-linux", r"rocky"),
    ("almalinux", r"alma\s*linux"), ("oracle-linux", r"oracle\s+linux"),
    ("rhel", r"red\s*hat\s+enterprise\s+linux|\brhel\b"), ("ubuntu", r"ubuntu"),
    ("debian", r"debian"), ("opensuse", r"opensuse"), ("sles", r"suse\s+linux\s+enterprise|\bsles\b"),
    ("fedora", r"fedora"), ("amazon-linux", r"amazon\s+linux"), ("freebsd", r"freebsd"),
    ("vmware-photon", r"photon"),
]


def identify(guest_os: Optional[str], kernel: Optional[str] = None) -> OsIdentity:
    """Product + release cycle of a guest OS string (see module docstring)."""
    raw = (guest_os or "").strip()
    kernel = (kernel or "").strip()
    if not raw:
        return UNKNOWN
    source = _source_of(raw)
    conf = "high" if source == "agent" else "estimated"
    # "(64-bit)" would otherwise read as a version number
    s = re.sub(r"\((?:32|64)-bit\)", " ", raw, flags=re.I).strip()
    low = s.lower()

    if "windows" in low:
        distro, ver, edition, from_build = _windows(s, kernel)
        if from_build:
            # the build number comes from the guest itself (kernel / pretty name)
            src = "kernel" if _nt_build(kernel) else source
            return OsIdentity(distro, ver, "high", src, edition)
        prefix = None
        if distro == "windows" and not ver:
            m = re.search(r"windows\s*(10|11)\b", low)
            prefix = f"{m.group(1)}-" if m else None
        return OsIdentity(distro, ver, conf, source, edition, prefix)

    distro = ver = None
    if not re.search(r"\d+\s*/\s*\d+", low):          # "CentOS 4/5": two releases, no version
        for product, pattern, build in _LINUX_RULES:
            m = re.search(pattern, low)
            if m:
                distro, ver = product, build(m)
                break
    if distro is None:
        for product, pattern in _PRODUCT_ONLY:
            if re.search(pattern, low):
                distro = product
                break
    if distro is None:
        return OsIdentity(None, None, "none", source)
    # VMware's catalog name never carries the service pack ("SUSE Linux
    # Enterprise 15") - only the guest's own name does ("... 15 SP5")
    if distro == "sles" and source != "agent" and not re.search(r"sp\s*\d", low):
        ver = None

    # The kernel string pins the release where the name does not
    k = kernel.lower()
    km = re.search(r"\.el(\d+)(?:_\d+)?\b", k)
    if km and distro in RHEL_FAMILY:
        kver = km.group(1)
        if ver != kver:
            return OsIdentity(distro, kver, "high", "kernel")
        if conf != "high":
            return OsIdentity(distro, ver, "high", "kernel")
    km = re.search(r"\.ph(\d+)\b", k)
    if km and distro == "vmware-photon" and not ver:
        return OsIdentity(distro, f"{km.group(1)}.0", "high", "kernel")
    km = re.match(r"(\d+)\.(\d+)-(?:release|stable|rc)", k)
    if km and distro == "freebsd" and (not ver or "." not in ver):
        return OsIdentity(distro, f"{km.group(1)}.{km.group(2)}", "high", "kernel")
    if distro == "debian" and not ver:
        for name, num in _DEBIAN_CODENAMES.items():
            if name in low:
                ver = num
                break
    return OsIdentity(distro, ver, conf, source)
