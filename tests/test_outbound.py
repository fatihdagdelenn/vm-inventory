"""
Outbound downloads behind TLS inspection (phase 162).

A local HTTPS server presents a certificate signed by a made-up "company" CA -
exactly what a TLS-inspecting firewall does. Checks: the download fails with the
short "certificate" reason, the probe names the signing CA, an uploaded CA (PEM
or DER) or OUTBOUND_CA_BUNDLE makes it work WITHOUT turning verification off,
the public CAs keep working next to it, removal restores the failure, bad files
are refused, and the KEV sync / source probe go through the same path.

Run:  PYTHONPATH=. python3 tests/test_outbound.py
"""
import datetime as dt
import http.server
import json
import os
import ssl
import sys
import tempfile
import threading
sys.path.insert(0, "tests")

from _actor_harness import make_env  # noqa: E402

for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
    os.environ.pop(k, None)           # local server, direct connection
os.environ["NO_PROXY"] = "127.0.0.1,localhost"

db, ss = make_env("_outbound")
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
import ipaddress  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core import outbound  # noqa: E402
from app.services import vuln_service as vs  # noqa: E402

tmp = tempfile.mkdtemp()
get_settings().report_dir = os.path.join(tmp, "data", "reports")


# ---------------------------------------------------------------- PKI
def name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Example Corp")])


now = dt.datetime.now(dt.timezone.utc)
ca_key = ec.generate_private_key(ec.SECP256R1())
ca = (x509.CertificateBuilder().subject_name(name("Example Corp SSL Inspection CA"))
      .issuer_name(name("Example Corp SSL Inspection CA")).public_key(ca_key.public_key())
      .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
      .not_valid_after(now + dt.timedelta(days=3650))
      .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
      .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                   content_commitment=False, key_encipherment=False,
                                   data_encipherment=False, key_agreement=False,
                                   encipher_only=False, decipher_only=False), critical=True)
      .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
      .sign(ca_key, hashes.SHA256()))
srv_key = ec.generate_private_key(ec.SECP256R1())
srv = (x509.CertificateBuilder().subject_name(name("127.0.0.1")).issuer_name(ca.subject)
       .public_key(srv_key.public_key()).serial_number(x509.random_serial_number())
       .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                      critical=False)
       .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                      critical=False)
       .sign(ca_key, hashes.SHA256()))
PEM = serialization.Encoding.PEM
srv_pem = os.path.join(tmp, "srv.pem")
with open(srv_pem, "wb") as f:
    f.write(srv.public_bytes(PEM) + srv_key.private_bytes(PEM, serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
ca_pem = ca.public_bytes(PEM)
ca_der = ca.public_bytes(serialization.Encoding.DER)

# ---------------------------------------------------------------- HTTPS server
KEV = {"title": "t", "catalogVersion": "2026.11.16", "dateReleased": "x", "count": 1,
       "vulnerabilities": [{"cveID": "CVE-2024-1086", "dateAdded": "2024-05-30",
                            "dueDate": "2024-06-20", "knownRansomwareCampaignUse": "Known",
                            "vulnerabilityName": "Linux Kernel Use-After-Free"}]}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(KEV).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
httpd.handle_error = lambda *a: None     # probes hang up after the first bytes
sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
sctx.load_cert_chain(srv_pem)
httpd.socket = sctx.wrap_socket(httpd.socket, server_side=True)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = f"https://127.0.0.1:{httpd.server_address[1]}/known_exploited_vulnerabilities.json"


def fails():
    try:
        outbound.get(URL, timeout=5)
        return None
    except Exception as exc:
        return vs._err(exc)


# 1) inspected connection fails with the short reason; the probe names the CA
assert outbound.verify() is True
why = fails()
assert why and why.startswith("Sertifika doğrulanamadı"), why
assert outbound.peer_issuer(URL) == "Example Corp SSL Inspection CA"
print("1) failure + issuer ok")

# 2) upload the company CA (PEM) -> works, verification still on
certs = outbound.save_upload(ca_pem)
assert len(certs) == 1 and not certs[0]["public"] and certs[0]["self_signed"]
assert certs[0]["subject"] == "Example Corp SSL Inspection CA"
bundle = outbound.verify()
assert isinstance(bundle, str) and os.path.isfile(bundle)
with open(bundle, "rb") as f:
    content = f.read()
import certifi  # noqa: E402
assert content.count(b"BEGIN CERTIFICATE") > 100            # public CAs kept
assert ca_pem.strip() in content
r = outbound.get(URL, timeout=5)
assert r.status_code == 200 and r.json()["catalogVersion"] == "2026.11.16"
st = outbound.status()
assert st["uploaded"] and [c["subject"] for c in st["extra"]] == ["Example Corp SSL Inspection CA"]
print("2) PEM upload ok")

# 3) remove -> fails again; DER (.cer from Windows) works too
assert outbound.remove_upload() is True and outbound.verify() is True and fails()
outbound.save_upload(ca_der)
assert outbound.get(URL, timeout=5).status_code == 200
outbound.remove_upload()
print("3) remove + DER ok")

# 4) a whole bundle (host's ca-certificates.crt style): only the company CA is "extra"
with open(certifi.where(), "rb") as f:
    host_bundle = f.read() + b"\n" + ca_pem
st = {c["subject"] for c in outbound.save_upload(host_bundle) if not c["public"]}
assert st == {"Example Corp SSL Inspection CA"}, st
assert outbound.get(URL, timeout=5).status_code == 200
outbound.remove_upload()
print("4) whole bundle ok")

# 5) OUTBOUND_CA_BUNDLE (file / folder), switched off again
d = os.path.join(tmp, "anchors"); os.makedirs(d)
with open(os.path.join(d, "corp.crt"), "wb") as f:
    f.write(ca_pem)
get_settings().outbound_ca_bundle = d
assert outbound.get(URL, timeout=5).status_code == 200
assert outbound.status()["env"] == d
get_settings().outbound_ca_bundle = ""
assert outbound.verify() is True and fails()
print("5) OUTBOUND_CA_BUNDLE ok")

# 6) bad files refused
for bad in (b"hello", b"-----BEGIN CERTIFICATE-----\nxx\n-----END CERTIFICATE-----\n", b"x" * (3 << 20)):
    try:
        outbound.save_upload(bad)
        raise AssertionError("bad file accepted")
    except ValueError:
        pass
assert not outbound.status()["uploaded"]
print("6) validation ok")

# 7) KEV sync + probe go through the same path
get_settings().vuln_kev_urls = URL
try:
    try:
        vs.sync_kev(db)
        raise AssertionError("must fail without the CA")
    except RuntimeError as exc:
        assert "Sertifika doğrulanamadı" in str(exc), exc
    vs.OSV_URL, vs.OSV_GITHUB = URL + "?{}", {}
    for _v in vs.VENDOR.values():                      # vendor feeds -> the same local server
        _v["urls"] = (URL + "?{v}",)
        if "index" in _v:
            _v["index"] = URL + "?updates"
    pr = vs.probe()
    assert "Windows" in {r["group"] for r in pr}
    assert all(not r["ok"] for r in pr) and pr[0]["issuer"] == "Example Corp SSL Inspection CA", pr
    outbound.save_upload(ca_pem)
    res = vs.sync_kev(db)
    assert res["kev"] == 1 and res["source"].startswith("127.0.0.1"), res
    assert all(r["ok"] for r in vs.probe())
finally:
    get_settings().vuln_kev_urls = ""
    outbound.remove_upload()
httpd.shutdown()
print("OUTBOUND SUITE OK")
