"""Kernel vulnerability data (OSV + CISA KEV) and per-VM findings.

VulnAdvisory keeps ONLY kernel source packages (see services/vuln_service:
KERNEL_FILTERS) - one row per (OSV record, CVE, ecosystem, package, range).
Ecosystems are stored normalised: "Ubuntu:24.04:LTS", "Ubuntu:Pro:18.04:LTS",
"Debian:12", "AlmaLinux:9", "Rocky Linux:9", "Red Hat:9" (Red Hat's own
"Red Hat:enterprise_linux:9::baseos" mainline stream). Newest OSV record wins
(modified).

VmVuln is the finding list: one row per (VM, CVE); `closed_at` is set when the
VM is no longer affected (patched or no longer evaluable - closed_reason says
which), and cleared again if it reappears.
"""
from datetime import datetime
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, Integer, String, Text,
                        UniqueConstraint)
from ..database import Base


class VulnAdvisory(Base):
    __tablename__ = "vuln_advisory"

    id = Column(Integer, primary_key=True)
    osv_id = Column(String(80), index=True, nullable=False)
    cve = Column(String(32), index=True, nullable=False)
    ecosystem = Column(String(48), index=True, nullable=False)
    package = Column(String(96), index=True, nullable=False)
    introduced = Column(String(96))            # "0" = every version
    fixed = Column(String(96))                 # None = no fix published
    severity = Column(String(12))              # level given by THIS record
    score = Column(Float)                      # CVSS v3 base score when the record has one
    modified = Column(DateTime)                # OSV 'modified' (newest record wins)
    source = Column(String(16))                # osv | bundle | upload


class VulnCve(Base):
    """One row per CVE: description and the best known severity (kept out of
    vuln_advisory, which has ~30 rows per Ubuntu kernel CVE)."""
    __tablename__ = "vuln_cve"

    cve = Column(String(32), primary_key=True)
    summary = Column(Text)
    severity = Column(String(12))
    specific = Column(Boolean, default=False)  # False = advisory-wide level (RH "Important:")
    score = Column(Float)
    modified = Column(DateTime)


class VulnKev(Base):
    """CISA Known Exploited Vulnerabilities catalogue (all vendors)."""
    __tablename__ = "vuln_kev"

    cve = Column(String(32), primary_key=True)
    date_added = Column(Date)
    due_date = Column(Date)
    ransomware = Column(String(16))            # Known | Unknown
    name = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow)


class VmVuln(Base):
    __tablename__ = "vm_vuln"
    __table_args__ = (UniqueConstraint("vm_id", "cve", name="uq_vm_vuln_vm_cve"),)

    id = Column(Integer, primary_key=True)
    vm_id = Column(Integer, index=True, nullable=False)   # virtual_machines.id (logical)
    cve = Column(String(32), index=True, nullable=False)
    osv_id = Column(String(80))
    package = Column(String(96))
    fixed = Column(String(96))
    status = Column(String(12))                # affected | uncertain
    fix_available = Column(Boolean, default=True)
    kev = Column(Boolean, default=False)
    severity = Column(String(12))
    reason = Column(Text)                      # Turkish, with the evidence
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, index=True)   # None = open
    closed_reason = Column(String(16))         # patched | not_evaluated
