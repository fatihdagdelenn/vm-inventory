"""Web-UI links for physical devices and hypervisor hosts.

Lists turn management / BMC addresses into links that open the device's own
web console in a new tab. One rule for every page:

- ``web_url`` (operator-entered, optional) wins - for UIs on a custom port or
  path ("https://10.0.5.20:8443/").
- Platform hosts default to their hypervisor UI: Proxmox node
  ``https://<ip>:8006``, ESXi host ``https://<ip>/ui/``.
- Anything else: ``https://<address>``.

Only http / https are ever produced or stored, so a stored value can never
become a ``javascript:`` (or other scheme) link.
"""
import ipaddress
import re
from urllib.parse import urlsplit

_HOSTPORT = re.compile(r"^[A-Za-z0-9.\-_\[\]:]+(/\S*)?$")


def _bracket_v6(addr: str) -> str:
    """Bare IPv6 needs brackets inside a URL."""
    host = addr.split("/", 1)[0]
    try:
        if ":" in host and ipaddress.ip_address(host).version == 6:
            return "[" + host + "]" + addr[len(host):]
    except ValueError:
        pass
    return addr


def normalize_web_url(value):
    """Validate an operator-entered web address. Returns the URL (scheme
    added when missing: https), None for empty input; raises ValueError for
    anything that is not a plain http(s) address."""
    v = (value or "").strip()
    if not v:
        return None
    if len(v) > 255 or any(c.isspace() for c in v):
        raise ValueError("invalid web address")
    if "://" not in v:
        if not _HOSTPORT.match(v):
            raise ValueError("invalid web address")
        v = "https://" + _bracket_v6(v)
    parts = urlsplit(v)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("invalid web address")
    _ = parts.port                    # ValueError for a non-numeric port ("data:text")
    return v


def address_url(addr):
    """Link for a bare address field (mgmt / iLO IP, optionally host:port or
    a full http(s) URL). '' when the value cannot be linked safely."""
    try:
        return normalize_web_url(addr) or ""
    except ValueError:
        return ""


def host_ui_url(host, web_url=None) -> str:
    """Hypervisor host web UI: manual web_url > platform default."""
    if web_url:
        return web_url
    ip = (getattr(host, "mgmt_ip", None) or "").strip()
    if not ip:
        return ""
    ptype = getattr(getattr(host, "platform", None), "type", "") or ""
    base = address_url(ip)
    if not base:
        return ""
    if ptype == "proxmox":
        return base.rstrip("/") + ":8006/"
    if ptype == "vcenter":
        return base.rstrip("/") + "/ui/"
    return base
