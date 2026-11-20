"""Outbound HTTPS for data downloads (kernel vulnerability data, endoflife.date)
behind corporate networks.

Many companies inspect TLS: a firewall / proxy re-signs every site with the
company's own root CA. Browsers and the host OS trust that CA (IT installed it),
the container does not - Python's `requests` ships its own CA list (certifi),
so every download fails with "certificate verify failed".

Fix without turning verification off: extra CA certificates are ADDED to
certifi's list, only for these downloads (vCenter / Proxmox connections keep
their own TLS settings). Sources, both optional:
- OUTBOUND_CA_BUNDLE: a PEM file or a directory of .pem/.crt/.cer files (e.g.
  the host's /etc/ssl/certs/ca-certificates.crt mounted read-only);
- a file uploaded in Administration -> Vulnerability Data, kept in the data
  volume (<data>/certs/extra-ca.pem), so it survives image rebuilds.
The merged bundle is rebuilt whenever a source changes.
"""
import hashlib
import logging
import os
import socket
import ssl
import threading
from datetime import timezone
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("outbound")

UPLOAD_NAME = "extra-ca.pem"
COMBINED_NAME = "combined-ca.pem"
MAX_UPLOAD = 2 * 1024 * 1024
_lock = threading.Lock()


def _settings():
    from ..config import get_settings
    return get_settings()


def cert_dir() -> str:
    """<data>/certs next to the reports folder (the app's data volume)."""
    base = os.path.dirname(os.path.abspath(_settings().report_dir))
    return os.path.join(base, "certs")


def uploaded_path() -> str:
    return os.path.join(cert_dir(), UPLOAD_NAME)


def extra_sources() -> list:
    """Existing files that hold extra CAs (env setting + uploaded file)."""
    out = []
    env = (getattr(_settings(), "outbound_ca_bundle", "") or "").strip()
    if env:
        if os.path.isdir(env):
            out += sorted(os.path.join(env, f) for f in os.listdir(env)
                          if f.lower().endswith((".pem", ".crt", ".cer")))
        elif os.path.isfile(env):
            out.append(env)
        else:
            logger.warning("OUTBOUND_CA_BUNDLE not found: %s", env)
    if os.path.isfile(uploaded_path()):
        out.append(uploaded_path())
    return out


def _pem_of(path: str) -> bytes:
    with open(path, "rb") as f:
        data = f.read()
    if b"-----BEGIN CERTIFICATE-----" in data:
        return data if data.endswith(b"\n") else data + b"\n"
    try:                                     # a single DER certificate (.cer)
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding
        return x509.load_der_x509_certificate(data).public_bytes(Encoding.PEM)
    except Exception:
        logger.warning("Not a certificate, ignored: %s", path)
        return b""


def verify():
    """The `verify=` value for requests: True (certifi only) or the path of a
    bundle = certifi + extra CAs."""
    srcs = extra_sources()
    if not srcs:
        return True
    import certifi
    combined = os.path.join(cert_dir(), COMBINED_NAME)
    with _lock:
        newest = max([os.path.getmtime(p) for p in srcs] + [os.path.getmtime(certifi.where())])
        if not os.path.isfile(combined) or os.path.getmtime(combined) < newest \
                or _sources_changed(srcs):
            os.makedirs(cert_dir(), exist_ok=True)
            with open(certifi.where(), "rb") as f:
                parts = [f.read()]
            parts += [b"\n# --- extra CA: " + p.encode() + b"\n" + _pem_of(p) for p in srcs]
            tmp = combined + ".tmp"
            with open(tmp, "wb") as f:
                f.write(b"".join(parts))
            os.replace(tmp, combined)
            with open(combined + ".src", "w") as f:
                f.write("\n".join(srcs))
    return combined


def _sources_changed(srcs) -> bool:
    try:
        with open(os.path.join(cert_dir(), COMBINED_NAME + ".src")) as f:
            return f.read().split("\n") != list(srcs)
    except OSError:
        return True


def proxies() -> Optional[dict]:
    """VULN_PROXY: proxy for these downloads only. Without it requests honours
    HTTPS_PROXY / NO_PROXY from the environment."""
    p = (getattr(_settings(), "vuln_proxy", "") or "").strip()
    return {"http": p, "https": p} if p else None


_local = threading.local()


def _session():
    """One keep-alive session per thread (the incremental OSV sync fetches
    hundreds of small records), with retries for the transient failures a
    corporate network produces: 429 / 5xx answers and dropped reads - up to
    3 tries with backoff (1.5 s, 3 s, 6 s), GET only; a failed connect is
    tried once more only."""
    s = getattr(_local, "session", None)
    if s is None:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        # connect=1: an offline server (DNS / no route) gives up after one
        # quick second try instead of waiting through three backoffs per URL
        # other=0: a proxy that refuses the tunnel (403) is an answer, not a glitch
        retry = Retry(total=3, connect=1, read=2, other=0, backoff_factor=1.5,
                      status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET"}),
                      raise_on_status=False, respect_retry_after_header=True)
        s = requests.Session()
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.session = s
    return s


def get(url, retries=True, **kw):
    """retries=False: one attempt (reachability probe - must answer fast)."""
    kw.setdefault("verify", verify())
    kw.setdefault("proxies", proxies())
    if not retries:
        import requests
        return requests.get(url, **kw)
    return _session().get(url, **kw)


# ------------------------------------------------------------- certificates
def parse_certs(data: bytes) -> list:
    """PEM (one or many) or a single DER certificate -> x509 objects."""
    from cryptography import x509
    if b"-----BEGIN CERTIFICATE-----" in data:
        return x509.load_pem_x509_certificates(data)
    return [x509.load_der_x509_certificate(data)]


def _name(n) -> str:
    from cryptography.x509.oid import NameOID
    for oid in (NameOID.COMMON_NAME, NameOID.ORGANIZATIONAL_UNIT_NAME, NameOID.ORGANIZATION_NAME):
        v = n.get_attributes_for_oid(oid)
        if v:
            return v[0].value
    return n.rfc4514_string()


_public = None


def _public_fingerprints() -> set:
    """SHA-256 of every CA certifi already trusts (to tell company CAs apart)."""
    global _public
    if _public is None:
        import certifi
        from cryptography.hazmat.primitives.serialization import Encoding
        with open(certifi.where(), "rb") as f:
            _public = {hashlib.sha256(c.public_bytes(Encoding.DER)).hexdigest()
                       for c in parse_certs(f.read())}
    return _public


def describe(certs) -> list:
    from cryptography.hazmat.primitives.serialization import Encoding
    pub = _public_fingerprints()
    out = []
    for c in certs:
        fp = hashlib.sha256(c.public_bytes(Encoding.DER)).hexdigest()
        try:
            end = c.not_valid_after_utc
        except AttributeError:               # cryptography < 42
            end = c.not_valid_after.replace(tzinfo=timezone.utc)
        out.append({"subject": _name(c.subject), "issuer": _name(c.issuer),
                    "self_signed": c.subject == c.issuer, "not_after": end.date().isoformat(),
                    "sha256": fp, "public": fp in pub})
    return out


def save_upload(data: bytes) -> list:
    """Validate and store an uploaded CA file; returns its certificates."""
    if len(data) > MAX_UPLOAD:
        raise ValueError("Dosya çok büyük (en fazla 2 MB)")
    try:
        certs = parse_certs(data)
    except Exception:
        certs = []
    if not certs:
        raise ValueError("Sertifika okunamadı - PEM (.pem / .crt) veya DER (.cer) bekleniyor")
    from cryptography.hazmat.primitives.serialization import Encoding
    os.makedirs(cert_dir(), exist_ok=True)
    tmp = uploaded_path() + ".tmp"
    with open(tmp, "wb") as f:
        f.write(b"".join(c.public_bytes(Encoding.PEM) for c in certs))
    os.replace(tmp, uploaded_path())
    return describe(certs)


def remove_upload() -> bool:
    try:
        os.unlink(uploaded_path())
        return True
    except FileNotFoundError:
        return False


def status() -> dict:
    """Administration view: where extra CAs come from and which company
    (non-public) certificates they add."""
    srcs, extra, total = [], [], 0
    for p in extra_sources():
        try:
            certs = describe(parse_certs(_pem_of(p) or b""))
        except Exception:
            certs = []
        total += len(certs)
        srcs.append({"path": p, "uploaded": p == uploaded_path(), "count": len(certs)})
        extra += [c for c in certs if not c["public"]]
    seen, uniq = set(), []
    for c in extra:
        if c["sha256"] not in seen:
            seen.add(c["sha256"])
            uniq.append(c)
    return {"sources": srcs, "extra": uniq, "total": total,
            "uploaded": os.path.isfile(uploaded_path()),
            "env": (getattr(_settings(), "outbound_ca_bundle", "") or "").strip() or None}


def peer_issuer(url: str, timeout: float = 6) -> Optional[str]:
    """Who signed the certificate this server is actually shown for `url`
    (verification off, nothing is sent) - under TLS inspection that is the
    company CA, which tells the operator which root certificate to add.
    Only for direct connections (not through VULN_PROXY / HTTPS_PROXY)."""
    if proxies() or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return None
    u = urlparse(url)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((u.hostname, u.port or 443), timeout=timeout) as s:
            with ctx.wrap_socket(s, server_hostname=u.hostname) as ts:
                der = ts.getpeercert(binary_form=True)
        from cryptography import x509
        return _name(x509.load_der_x509_certificate(der).issuer)
    except Exception:
        return None
