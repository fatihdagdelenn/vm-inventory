"""
OS identity parser (phase 158): guest_os (+ kernel) -> endoflife.date product,
release cycle, confidence and source.

The strings are real values the collectors store: VMware Tools detailed data
("prettyName"), QEMU agent get-osinfo pretty-name, VMware catalog names from
the VM settings ("... (64-bit)"), Proxmox ostype hints - many taken from the
production probe outputs (vCenter 8.0.3 / PVE 9.2).

Run:  PYTHONPATH=. python3 tests/test_os_identity.py
"""
import sys
sys.path.insert(0, ".")
from app.core.os_identity import identify  # noqa: E402

H, E, N = "high", "estimated", "none"
CASES = [
    # (guest_os, kernel, distro, version, confidence, source)
    # ---- Ubuntu
    ("Ubuntu 24.04.2 LTS", "6.8.0-57-generic", "ubuntu", "24.04", H, "agent"),
    ("Ubuntu 24.04.5 LTS", "6.8.0-111-generic", "ubuntu", "24.04", H, "agent"),
    ("Ubuntu 22.04.4 LTS", "5.15.0-143-generic", "ubuntu", "22.04", H, "agent"),
    ("Ubuntu 20.04.6 LTS", None, "ubuntu", "20.04", H, "agent"),
    ("Ubuntu 18.04.6 LTS", None, "ubuntu", "18.04", H, "agent"),
    ("Ubuntu 25.04", None, "ubuntu", "25.04", H, "agent"),
    ("Ubuntu Linux (64-bit)", None, "ubuntu", None, E, "catalog"),
    ("Ubuntu", None, "ubuntu", None, E, "ostype"),                 # Proxmox LXC ostype
    # ---- Debian
    ("Debian GNU/Linux 12 (bookworm)", "6.1.0-44-amd64", "debian", "12", H, "agent"),
    ("Debian GNU/Linux 11 (bullseye)", None, "debian", "11", H, "agent"),
    ("Debian GNU/Linux 13 (trixie)", None, "debian", "13", H, "agent"),
    ("Debian GNU/Linux 10 (64-bit)", None, "debian", "10", E, "catalog"),
    ("Debian GNU/Linux trixie/sid", None, "debian", "13", H, "agent"),
    ("Debian", None, "debian", None, E, "ostype"),
    # ---- RHEL family
    ("Red Hat Enterprise Linux 9.4 (Plow)", "5.14.0-427.13.1.el9_4.x86_64", "rhel", "9", H, "agent"),
    ("Red Hat Enterprise Linux Server 7.9 (Maipo)", "3.10.0-1160.el7.x86_64", "rhel", "7", H, "agent"),
    ("Red Hat Enterprise Linux 7 (64-bit)", None, "rhel", "7", E, "catalog"),
    ("Red Hat Enterprise Linux 8 (64-bit)", "4.18.0-553.el8_10.x86_64", "rhel", "8", H, "kernel"),
    ("CentOS Linux 7 (Core)", None, "centos", "7", H, "agent"),
    ("CentOS 7 (64-bit)", None, "centos", "7", E, "catalog"),
    ("CentOS 4/5 (64-bit)", None, "centos", None, E, "catalog"),     # prod: really CentOS 7
    ("CentOS 4/5 (64-bit)", "3.10.0-1160.el7.x86_64", "centos", "7", H, "kernel"),
    ("CentOS Stream 9", None, "centos-stream", "9", H, "agent"),
    ("Rocky Linux 8.10 (Green Obsidian)", "4.18.0-553.51.1.el8_10.x86_64", "rocky-linux", "8", H, "agent"),
    ("Rocky Linux 9.4 (Blue Onyx)", None, "rocky-linux", "9", H, "agent"),
    ("Rocky Linux (64-bit)", None, "rocky-linux", None, E, "catalog"),
    ("AlmaLinux 9.4 (Seafoam Ocelot)", None, "almalinux", "9", H, "agent"),
    ("AlmaLinux 8 (64-bit)", None, "almalinux", "8", E, "catalog"),
    ("Oracle Linux Server 8.9", None, "oracle-linux", "8", H, "agent"),
    ("Oracle Linux 7 (64-bit)", None, "oracle-linux", "7", E, "catalog"),
    # ---- SUSE
    ("SUSE Linux Enterprise Server 15 SP5", None, "sles", "15.5", H, "agent"),
    ("SUSE Linux Enterprise Server 12 SP5", None, "sles", "12.5", H, "agent"),
    ("SUSE Linux Enterprise Server 15", None, "sles", "15.0", H, "agent"),
    ("SLES 15-SP4", None, "sles", "15.4", H, "agent"),
    ("SUSE Linux Enterprise 15 (64-bit)", None, "sles", None, E, "catalog"),
    ("openSUSE Leap 15.6", None, "opensuse", "15.6", H, "agent"),
    ("SUSE openSUSE (64-bit)", None, "opensuse", None, E, "catalog"),
    # ---- other Linux
    ("Fedora Linux 40 (Server Edition)", None, "fedora", "40", H, "agent"),
    ("Amazon Linux 2023", None, "amazon-linux", "2023", H, "agent"),
    ("Amazon Linux 2", None, "amazon-linux", "2", H, "agent"),
    ("VMware Photon OS/Linux", "6.1.126-5.ph5", "photon", "5.0", H, "kernel"),
    ("VMware Photon OS/Linux", "5.10.252-4.ph4", "photon", "4.0", H, "kernel"),
    ("VMware Photon OS 5.0", None, "photon", "5.0", H, "agent"),
    ("VMware Photon OS (64-bit)", None, "photon", None, E, "catalog"),
    # ---- rolling releases (no cycles; judged by the kernel - see test_lifecycle)
    ("Kali GNU/Linux Rolling", "5.18.0-kali5-amd64", "kali-linux", None, H, "agent"),   # prod
    ("Arch Linux", "6.11.5-arch1-1", "arch-linux", None, H, "agent"),
    ("Archlinux", None, "arch-linux", None, E, "ostype"),                              # Proxmox LXC
    ("openSUSE Tumbleweed", "6.11.3-1-default", "opensuse-tumbleweed", None, H, "agent"),
    ("Gentoo Linux", None, "gentoo", None, H, "agent"),
    ("Manjaro Linux", None, "manjaro", None, H, "agent"),
    # ---- Alpine
    ("Alpine Linux v3.20", None, "alpine-linux", "3.20", H, "agent"),
    ("Alpine", None, "alpine-linux", None, E, "ostype"),
    # ---- FreeBSD
    ("FreeBSD 13.2-RELEASE-p4", "13.2-RELEASE-p4", "freebsd", "13.2", H, "agent"),
    ("FreeBSD 14.1-RELEASE", None, "freebsd", "14.1", H, "agent"),
    ("FreeBSD 13 (64-bit)", None, "freebsd", "13", E, "catalog"),
    ("FreeBSD 13 (64-bit)", "13.2-RELEASE-p4", "freebsd", "13.2", H, "kernel"),
    # ---- Windows Server
    ("Microsoft Windows Server 2022 Standard", "NT 10.0.20348", "windows-server", "2022", H, "kernel"),
    ("Microsoft Windows Server 2019 Datacenter", None, "windows-server", "2019", H, "agent"),
    ("Windows Server 2016 Standard", None, "windows-server", "2016", H, "agent"),
    ("Microsoft Windows Server 2012 R2 Standard", None, "windows-server", "2012-r2", H, "agent"),
    ("Microsoft Windows Server 2008 R2 Enterprise", None, "windows-server", "2008-r2-sp1", H, "agent"),
    ("Windows Server 2022, 64-bit (Build 20348.2582)", "NT 10.0.20348.2582", "windows-server", "2022", H, "kernel"),
    ("Windows Server 2025, 64-bit (Build 26100.1742)", None, "windows-server", "2025", H, "agent"),
    ("Microsoft Windows Server 2019 (64-bit)", None, "windows-server", "2019", E, "catalog"),
    ("Microsoft Windows Server 2016 or later (64-bit)", None, "windows-server", None, E, "catalog"),
    ("Microsoft Windows Server 2016 or later (64-bit)", "NT 10.0.17763.6414", "windows-server", "2019", H, "kernel"),
    ("Microsoft Windows Server 2012 (64-bit)", None, "windows-server", "2012", E, "catalog"),
    ("Windows 10 / Server 2016-2019", None, "windows-server", None, E, "ostype"),
    ("Windows 11 / Server 2022+", None, "windows-server", None, E, "ostype"),
    ("Windows 8 / Server 2012", None, "windows-server", None, E, "ostype"),
    ("Windows Server 2008", None, "windows-server", "2008-sp2", E, "ostype"),
    # ---- Windows client
    ("Microsoft Windows 10 Pro", "NT 10.0.19045", "windows", "10-22h2", H, "kernel"),
    ("Microsoft Windows 11 Enterprise", "NT 10.0.22631.4317", "windows", "11-23h2", H, "kernel"),
    ("Microsoft Windows 11 Pro", "NT 10.0.26100", "windows", "11-24h2", H, "kernel"),
    ("Microsoft Windows 10 Enterprise LTSC 2021", "NT 10.0.19044", "windows", "10-21h2", H, "kernel"),
    ("Windows 11 Pro", None, "windows", None, H, "agent"),
    ("Microsoft Windows 10 (64-bit)", None, "windows", None, E, "catalog"),
    ("Microsoft Windows 7 (64-bit)", None, "windows", "7-sp1", E, "catalog"),
    # ---- unknown
    ("Other 2.6.x Linux (64-bit)", None, None, None, N, "catalog"),
    ("Other 3.x or later Linux (64-bit)", None, None, None, N, "catalog"),
    ("Linux", None, None, None, N, "ostype"),
    ("Diğer", None, None, None, N, "ostype"),
    ("", None, None, None, N, "none"),
    (None, None, None, None, N, "none"),
]

bad = []
for g, k, d, v, c, src in CASES:
    i = identify(g, k)
    got = (i.distro, i.version, i.confidence, i.source)
    if got != (d, v, c, src):
        bad.append(f"{g!r} + {k!r}: got {got}, want {(d, v, c, src)}")
assert not bad, "\n".join(bad)

# Windows client cycles carry the edition suffix used by endoflife.date
assert identify("Microsoft Windows 11 Enterprise", "NT 10.0.22631").cycles() == ["11-23h2-e", "11-23h2"]
assert identify("Microsoft Windows 11 Pro", "NT 10.0.22631").cycles() == ["11-23h2-w", "11-23h2"]
assert identify("Microsoft Windows 10 Pro", "NT 10.0.19045").cycles() == ["10-22h2-w", "10-22h2"]
assert identify("Microsoft Windows 10 Enterprise LTSC 2021", "NT 10.0.19044").cycles()[0] == "10-21h2-e-lts"
assert identify("Microsoft Windows 10 IoT Enterprise LTSC 2021", "NT 10.0.19044").cycles()[0] == "10-21h2-iot-lts"
assert identify("Ubuntu 24.04.2 LTS").cycles() == ["24.04"]
assert identify("Ubuntu Linux (64-bit)").cycles() == []
# rolling flag + kernel series
from app.core.os_identity import kernel_cycle  # noqa: E402
assert identify("Kali GNU/Linux Rolling", "5.18.0-kali5-amd64").rolling
assert not identify("Ubuntu 24.04.2 LTS").rolling
assert identify("Kali GNU/Linux Rolling").label == "Kali Linux (rolling)"
assert kernel_cycle("5.18.0-kali5-amd64") == "5.18" and kernel_cycle("6.8.0-45-generic") == "6.8"
assert kernel_cycle("NT 10.0.20348") is None and kernel_cycle("13.2-RELEASE-p4") is None
assert kernel_cycle(None) is None and kernel_cycle("") is None
# labels
assert identify("Ubuntu 24.04.2 LTS").label == "Ubuntu 24.04"
assert identify("Microsoft Windows Server 2012 R2 Standard").label == "Windows Server 2012 R2"
assert identify("Microsoft Windows 11 Pro", "NT 10.0.22631").label == "Windows 11 23H2"
assert identify("SUSE Linux Enterprise Server 15 SP5").label == "SLES 15 SP5"
assert identify("SUSE Linux Enterprise Server 15").label == "SLES 15"
assert identify("Other 2.6.x Linux (64-bit)").label == ""
print(f"OS IDENTITY SUITE OK ({len(CASES)} strings)")
