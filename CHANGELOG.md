# Changelog

All notable changes to this project are documented in this file.
Versioning follows [Semantic Versioning](https://semver.org/).

> **Language:** from v1.8.0 on, release sections and GitHub release notes are
> written in **English**. Sections up to and including v1.7.0 are kept in their
> original Turkish as the historical record.

### Versioning & release policy

- **Phase version** (`app/core/version.py`, shown in the footer) is bumped on
  every phase; it is an *internal* stamp, not a release.
- **Release** = a `## [vX.Y.Z]` section in this file + a **git tag** of the same
  name + a GitHub release. The three always go together. Release notes
  (`RELEASE_vX.Y.Z.md`) are pasted on GitHub only and **never committed**
  (they are in `.gitignore`).
- **When to release?** When any one of these holds: *(a)* **10+ phases** since the
  last tag, *(b)* a **new page or new data source** shipped, *(c)* a user-visible
  **breaking change** or data migration. Accumulation decides, not the calendar.
- **Numbering:** a new page or notable capability → minor (`1.7` → `1.8`); fixes
  and polish only → patch. Internal phase stamps need not match the release
  number; each section states which internal range it covers.
- Every section also states the **honest limits**, so nothing reads as more
  capable than it is.

---

## [Unreleased]

Phases after v1.9.0 (phase 173 →; internal v1.9.1 →).

### ⏹ Stop a running download, switch automatic downloads off; package file names (phase 174)
- Asked on prod (no internet): the automatic boot sync kept running for a
  long time ("running (boot)") - wasted traffic and work, with no way to stop it.
- **Stop** button next to the download buttons while a job runs (admin):
  the job ends at its next check point - before every HTTP request, every
  1 MB downloaded, every 500 records stored, every 25 VMs evaluated. Queued
  record fetches are dropped; the source in progress is rolled back, sources
  already finished stay. The job row shows ⏹ "stopped by the user".
- **Download automatically** switch (default on): off = no scheduled
  download, no boot catch-up - no traffic and no work on a server without
  internet. Manual **Download now** and uploads keep working.
- Why it was slow offline: the retries added in phase 173 also retried a
  tunnel the proxy refused (403) and waited through the backoff for every
  source. Refused tunnels are no longer retried (`other=0`), and a failed
  connect is tried only once more (`connect=1`).
- The first package after phase 173 is always complete (there is no earlier
  package to compare with), even when **Changes only** is clicked - but its
  file was still named `vm-inventory-vuln-changes-….json.gz`, so a 5.9 MB
  "changes" file looked like the feature did not work. The name now follows
  the content: `…-changes-…` only for a real changes-only package.

### 🔁 Daily vulnerability data, downloading only what changed (phase 173)
- Asked: the full download took long; CVEs come out every day. Before, OSV
  dumps (Ubuntu / Debian: hundreds of MB) were downloaded **weekly in full**,
  vendor files on every run, and an offline server got the **whole** package
  each time.
- **OSV, changes only:** each ecosystem's `modified_id.csv` (newest first,
  documented by osv.dev) is read down to the last run's timestamp and only
  those records are fetched (`<id>.json`, 8 at a time on keep-alive
  connections). The dump is used the first time, when the cursor is older
  than 30 days, or when more than 3,000 records changed (a kernel-update day
  rewrites thousands at once). A record that fails is fetched again next time
  (the cursor does not move past it).
- **Vendor files / dumps / GitHub archive:** downloaded with the ETag /
  Last-Modified of the last import; `304 Not Modified` = skipped. Photon is
  no longer re-inserted when unchanged (it used to force a full re-evaluation
  of every VM).
- **Schedule:** everything daily at 03:41, an extra KEV check at 17:23 (was:
  KEV daily, the rest weekly); the boot-time catch-up runs when the last
  download is older than 20 hours.
- **Resilience:** all data downloads go through a keep-alive session with
  retries (3 tries, backoff 1.5 / 3 / 6 s on connection errors, 429, 5xx;
  `Retry-After` honoured). The reachability probe stays single-attempt.
- **Offline servers:** **Changes only** next to **Download data package**
  gives a small package with the records stored or replaced since the last
  package (KEV and the ABI table always complete). The card shows when the
  last package was taken and how many records changed since; the offline
  server shows the last package it imported and **warns when a changes-only
  package continues one it never got** (then import a full package).
- Honest limits: a changes-only package does not carry deletions (a CVE
  removed from a feed stays on the offline server until a full package);
  `modified_id.csv` lists every package of an ecosystem, so a busy day can
  still mean a few thousand small requests - above 3,000 the dump is used.

---

## [v1.9.0] — 2026-11-20

**21 phases since v1.8.0 (phase 152–172; internal v1.8.1 → v1.8.20).** Focus:
**security posture of the inventory** — every VM now shows whether its OS is
still supported (OS lifecycle / EOL) and which published vulnerabilities its
running kernel or Windows build has, with CISA KEV, the fix to install and an
offline workflow for servers without internet. Plus the Kernel column, a
resizable click-to-filter VM table, hardware models on the Hosts page and
device web-console links.

### ⬆️ Upgrading
- No manual migration: new tables (`os_lifecycle`, `lifecycle_overrides`,
  `vuln_*`) and columns are created on startup; the first start after the
  upgrade evaluates every VM once (a few seconds to a minute).
- **Vulnerability data** has to be downloaded once: **Administration →
  Vulnerability Data → Download now** (internet), or a data package from a
  server with internet (**Download data package** → **Upload file**).
  Prepare packages for an offline server with **Distributions to download →
  Choose**, ticking that server's distributions.
- **Proxmox, optional:** for the Windows update revision the API token needs
  agent exec — `VM.GuestAgent.Unrestricted` (PVE 9) / `VM.Monitor` (PVE 8).
  See README → First-time setup → Step 3 (and its security note).
- **Networks with TLS inspection:** upload the company root CA under
  **Company certificate (TLS inspection)**; `.env` gains `VULN_PROXY`,
  `VULN_KEV_URLS`, `OUTBOUND_CA_BUNDLE` (all optional).
- Reverse proxies with a small request limit no longer break uploads (900 KB
  pieces).

### ℹ️ Honest limits
- Matching compares versions; it is not a scanner. Installed applications
  (SQL Server, Exchange, Office, .NET…) and configuration are not covered;
  the *running* kernel / build counts (no live patches, no installed-but-not-
  booted kernels).
- Not verifiable: VMware Tools older than 11.2 (no kernel reported), Proxmox
  Windows without agent exec, Proxmox VE / CIQ LTS / backports / cloud
  kernels. Each shows **Not verified** with its reason.
- SUSE record format and Oracle's per-release file names were not verified
  against a real download; Windows data covers the last 24 months.
- Server-side messages, vulnerability reasons and report titles are Turkish.

### 🔢 Open CVEs shows what needs doing; README brought up to date (phase 172)
- The cell's `+N` counted every other matched CVE - on an old kernel thousands,
  most without a fix, which read as thousands of tasks. Now: the top CVE badge,
  **`+k KEV`** for further actively exploited CVEs, **`+N`** for the other CVEs
  **with a published fix** (click: that VM's fixable list), a grey `+N` when
  only CVEs without a fix remain. The full total is in the tooltip.
  Vulnerabilities page accepts `?fix=fixable|nofix`.
- README (EN + TR): new **OS support and vulnerabilities** section (data per
  OS, what the inventory needs, cell states, offline workflow, honest limits),
  Proxmox 9 and the optional agent exec privilege, Vulnerabilities page and
  Administration tabs in the user guide, moving images to a closed network,
  new troubleshooting rows, current project layout; all screenshots re-taken
  (+ Vulnerabilities, Vulnerability Data).
- Page titles of Physical Inventory and Vulnerabilities are translated; demo
  data includes Windows (MSRC) findings; `tools/screenshots.py` opens the VM
  detail from the name cell.

### 🐛 Oracle Linux 8 UEK 5.4 (and other shared advisories) were missing (phase 171)
- Prod: every Oracle Linux 8.10 VM on UEK 5.4 stayed "Not verified - no
  ELSA record for UEK 5.4", although the package had 9,224 Oracle CVEs. The
  stored data showed why: `Oracle Linux:7 kernel-uek-5.4` 1,227 CVEs,
  `Oracle Linux:8 kernel-uek-5.4` none; likewise OL9 had 4 UEK 5.15 CVEs (OL8:
  3,124) and OL10 1 UEK 6.12 CVE (OL9: 5,640).
- Cause: Oracle publishes one advisory for several releases (UEK 5.4 = OL7 +
  OL8, UEK 7 = OL8 + OL9, UEK 8 = OL9 + OL10) and each per-release file
  repeats it. The records were stored under the bare ELSA id, so the copy in
  the next release's file was taken for "already stored, same date" and
  skipped - only the first release (in download order) got the rows.
- Fix: one record per release (`ELSA-2026-50005/OL8`). Rows stored in the old
  form are removed on the next Oracle download or package upload.
- After updating: run **Download now** on the internet-connected server (with
  Oracle Linux selected) before taking a new package, then upload that package.

### 🔍 Fewer "Not verified" VMs, and a reason for every one left (phase 170)
Prod screenshots showed whole groups as "Not verified". Each kind got its root cause:
- **Debian 13 on VMware** (`6.12.107+deb13-amd64`): the kernel name carries
  the package version (`6.12.107-1`; `+deb13.1` = `-2`, seen in the archive)
  -> evaluated exactly, no uname -v needed.
- **Debian 12 on VMware** (`6.1.0-40-amd64`): only the ABI number. New
  ABI -> package version table (`vuln_kernel_abi` + seed
  `app/resources/debian_kernel_abi.json`, 53 ABIs 6.1.0-1 … -56 built from
  the file names `linux-image-<abi>-amd64_<version>_amd64.deb` in Debian
  archive mirrors that keep old versions). An ABI with one version is exact;
  ABIs are ordered, so a fix newer than the next ABI is "affected" and one
  older than the previous ABI is "not affected" even for an ABI missing from
  the table - only what falls in between is "uncertain". The table grows by
  itself: Proxmox Debian VMs report both strings (learned on every
  recompute), an online server reads the Debian archive folders when Debian
  is downloaded, and the offline package carries it.
- **Windows on Proxmox** (`NT 10.0.17763`): the QEMU agent's get-osinfo has
  no update revision. The collector now runs the read-only `cmd /c ver`
  through the agent (cached per VM until reboot; a miss keeps the stored
  value). Needs agent exec on the API token - PVE 9 `VM.GuestAgent.Unrestricted`,
  PVE 8 `VM.Monitor`; without it the VM stays "Not verified" and the reason
  names the privilege.
- **No kernel at all on VMware**: the VMware Tools version is now stored
  (`tools_version`); the reason says "Tools 10.3.22 - update to 11.2+" or
  "OS-provided (unmanaged) Tools".
- **Proxmox VE kernels** (`…-pve`) and **Debian backports kernels** get their
  own reason (no public CVE data for them) instead of a generic one.
- Administration -> Vulnerability Data: new **"VMs not verified - reasons"**
  table - each reason, how many VMs, examples and what to do.
- Honest limits: Debian 12 ABIs missing from the table (4, 19, 24) and future
  ones before the table learns them can give "uncertain" findings; Proxmox
  kernels, CIQ LTS and VMs whose Tools never send a kernel stay not verifiable.
  The archive URLs used for the refresh were not reachable from the build
  sandbox (found through mirrors).

### 🛡️ Open CVEs cell: "checked, none" no longer looks like "could not check" (phase 169)
- Asked on prod: Debian 12 VMs on VMware showed "—" next to Proxmox ones
  with thousands of CVEs - was "—" safe? It was not: "—" meant **not
  evaluable** (uname -r has no Debian package version; only the Proxmox agent
  reports uname -v), and the same dash was used for "out of scope".
- The cell now has three distinct looks: **Açık yok / No open CVE** (green,
  shield icon) only when the VM WAS checked and nothing matched;
  **Doğrulanamadı / Not verified** (dashed amber, question icon) when it could
  not be checked, the reason in the tooltip; **kapsam dışı / out of scope**
  (plain grey text) for EOL / unknown support. The VM detail uses the same
  badges. "—" is left only for VMs not evaluated yet.

### 🪟 Windows vulnerabilities from Microsoft's update data (phase 168)
- Windows VMs were "out of scope". Windows has no package versions: the OS is
  one cumulative update per month, and its identity is the NT build + update
  revision (UBR) the inventory already shows (`NT 10.0.17763.6775`).
- Data: Microsoft's **MSRC CVRF API** (`api.msrc.microsoft.com/cvrf/v3.0`, no
  key) - one document per month listing, per CVE and product, the update that
  fixes it (KB number + fixed build). The last **24 months** are downloaded;
  the index tells which months changed, so a weekly sync fetches only revised
  documents. Months the index does not list yet are tried directly.
- Matching: VM build + UBR against the fixed build of the same product -
  Windows Server 2016 / 2019 / 2022 / 2022 23H2 / 2025 (Server Core shares
  the row) and Windows 10 / 11 per feature update, each its own data (Server
  2025 and Windows 11 24H2 share build 26100 but not every CVE). The finding
  names the KB to install (`KB5050008`); severity from the CVSS score.
  Hotpatch-only fixes are ignored (only hotpatch-enrolled machines take them)
  and "Customer Action Required: No" CVEs are skipped (fixed in the cloud).
  A VM older than the whole data window gets a warning that the real count
  is higher.
- Format checked against a real MSRC CVRF XML document (vuls-data-update
  testdata) and the official MSRC PowerShell module (JSON field names); both
  forms can be uploaded, and the offline package carries the Windows rows.
- "Windows" is a selectable source (automatic when the inventory has
  supported Windows VMs); **Test sources** checks `api.msrc.microsoft.com`.
- VMware Tools versions that send `distroVersion='Windows'` produced
  `NT Windows.17763.6775`; the collector now writes `NT 10.0.17763.6775`, and
  stored strings of that shape are read too (also for OS lifecycle).
- Honest limits: operating system only - SQL Server, Exchange, Office, .NET
  and other installed products are not in the inventory, so their CVEs are
  not shown. Needs the UBR: the Proxmox QEMU agent reports only the build
  (`NT 10.0.17763`), as do old VMware Tools - those VMs are "not evaluable"
  with the reason. The UBR changes after the reboot that completes an update.
  Windows Server 2012 / 2012 R2 (ESU) and older are EOL here and skipped.
  The download size of 24 monthly documents was not measured (no access to
  the API from the build sandbox).

### 🟥 Oracle Linux and Photon OS kernels are matched (phase 167)
- Prod's inventory is mostly **Oracle Linux 8 / 9 / 10 with UEK kernels**,
  plus Photon OS - all were "not evaluable" because neither is in OSV.
- **Oracle Linux**: Oracle's own OVAL feed
  (`linux.oracle.com/security/oval/com.oracle.elsa-ol{8,9,10}.xml.bz2`, the
  all-in-one `com.oracle.elsa-all.xml.bz2` when a per-release file is
  missing), streamed and kept to kernel advisories. **UEK** (`…el8uek`) and
  **RHCK** (`…el8_10`) are matched separately; the UEK streams (5.4 / 5.15 /
  6.12) each get their own data (`kernel-uek-5.15`), because an advisory for
  one stream says nothing about the others. One advisory often covers two
  releases with a build each (`…el6uek` / `…el7uek`) - every release gets
  only its own build. Per-CVE CVSS scores from the OVAL set the severity.
  RHCK falls back to the AlmaLinux data (same RHEL versions) when Oracle's is
  not loaded. Format checked against a real Oracle OVAL file (2018 ELSAs,
  quay/claircore testdata).
- **Photon OS**: Broadcom's CVE list per release
  (`packages.broadcom.com/photon/photon_cve_metadata/cve_data_photon5.0.json`,
  old `packages.vmware.com` as fallback) - `linux`, `linux-esx`, `linux-secure`,
  `linux-rt`, `linux-aws`; "Not Affected" entries skipped, "all versions are
  vulnerable" without a fixed build = no fix yet. Format checked against
  aquasecurity/vuln-list-update testdata.
- Both are selectable sources ("Distributions to download"); automatic mode
  fetches only the releases the inventory runs. Downloaded files and uploads
  (`.xml.bz2` / `.xml`, `cve_data_photon*.json`) go through the same import,
  and the offline package carries them.
- **Rocky Linux from CIQ - LTS** is recognised ("Rocky Linux from CIQ - LTS
  9.6", kernels `…el9_6_ciq`) so its support status is known; its kernels are
  reported as not evaluable on purpose - CIQ backports fixes under its own
  version numbers, so comparing with Rocky / RHEL data would mislead.
- Honest limits: Debian on VMware still cannot be evaluated (uname -r has the
  ABI, not the package version; only the Proxmox agent reports uname -v).
  Oracle Linux 7 is EOL (extended support has no public feed). Flatcar, SLOS
  and other appliances have no data source.

### ⬆️ Uploads in pieces - works behind a proxy that limits request size (phase 166)
- Reported on prod: "Upload file" showed **HTTP 413** and nothing happened.
  The answer came from a reverse proxy in front of the app (nginx's default
  `client_max_body_size` is 1 MB; the app's own limit is 2 GB and it answers
  with a message, not a bare 413). The `.json.gz` format was not the problem.
- The browser now sends the file in 900 KB pieces (`POST /api/vulns/upload` →
  `PUT /api/vulns/upload/{id}?offset=…` → `POST …/finish`), with a progress
  percentage and up to three retries per piece; a repeated piece is accepted
  at its offset, a gap or a short file is refused, and the import starts only
  when the size matches. Unfinished uploads are removed after a day. The
  one-request endpoint stays for scripts.
- Checked through a small proxy imitating nginx's 1 MB limit: the old single
  request got 413, the 3.2 MB AlmaLinux archive went through in pieces and was
  imported (301 advisories, 38 VMs evaluated).
- A bare 413 from a proxy is now explained in the message instead of showing
  only "HTTP 413".

### 📦 Upload result says what the file contained (phase 165)
- Reported: a package downloaded on the test machine and uploaded on prod
  "changed nothing", with no explanation. The import itself works (re-checked
  end to end over HTTP: export on one server, upload on an empty one → 81 VMs
  evaluated); the likely cause is a package without kernel data - a server
  stores (and packages) only the distributions it downloaded, which since
  phase 163 follow ITS OWN inventory.
- After an upload, a result box under the buttons shows: file type and date,
  what it contained per distribution (CVEs) and KEV entries, new / already
  loaded records, VMs evaluated and new / closed findings, and the
  distributions that have VMs on this server but still no data. A KEV-only
  file gets an explicit warning ("no kernel data - that is why nothing
  changed for the VMs").
- The export side warns before downloading a package when the server holds
  no kernel data (the package would contain KEV only).

### ⚡ Open CVEs by name, fast Vulnerabilities page at real scale (phase 164)
- **"Open CVEs" cell** used to show "7480 +1073" - unclear which CVEs those
  were. It now names the **most urgent open CVE** (KEV first, then fix
  available, severity, CVSS) as a coloured badge, e.g. `CVE-2024-1086`, and
  `+N` for the rest. Clicking the CVE opens it on the Vulnerabilities page;
  clicking `+N` opens that VM's full CVE list there. The tooltip keeps the
  numbers: open with a fix (critical / high), without a fix / uncertain, KEV.
  Clicking the empty part of the cell still filters the list as before.
- **VM detail** shows the 50 most urgent findings (was: all, thousands for an
  old kernel) with a link to the full list.
- **Vulnerabilities page**: paged (100 per page) and read from a small per-CVE
  table (`vuln_cve_stat`) rebuilt after a recompute that changed findings,
  instead of aggregating every finding on each load. Measured on 150 Ubuntu
  VMs x 8,000 CVEs (752,218 findings, SQLite): page load 3.3 s → 0.01 s.
- **Recompute after each sync**: a VM whose OS / kernel / support status and
  the vulnerability data are unchanged since its last evaluation is skipped
  (fingerprint in `virtual_machines.vuln_sig`); only changed findings are
  written, in bulk. Same data set: 40.6 s → 0.1 s per sync with no change;
  first evaluation 53 s → 19 s.
- **Exports**: the "Zafiyetler" sheet lists the most urgent findings first
  and stops at 100,000 rows with a note row ("… N more, full list on the
  Vulnerabilities page") - a sheet holds at most 1,048,576 rows.
- `ensure_schema` now also creates named indexes declared on existing tables
  (two new `vm_vuln` indexes); on first start it may also build indexes that
  older `ALTER`-added columns never got - a one-off, logged as "Index created".

### 🧩 Choose which distributions to download; SUSE / openSUSE (phase 163)
- **Administration → Vulnerability Data → Distributions to download.**
  *Automatic* (default) downloads only what the inventory needs: a source is
  picked when at least one VM of that distribution is supported / ending soon /
  extended (Ubuntu, Debian, AlmaLinux - which also covers RHEL and Rocky -,
  SUSE, openSUSE). *Choose* lets you tick sources by hand - e.g. on the test
  machine, to prepare a package for an offline server whose distributions
  differ; the first switch to *Choose* starts from the automatic picks.
- The table shows, per source, the VMs it matches (supported / all), the CVEs
  already stored, the source it last came from (osv.dev / github.com) and a
  note (size, AlmaLinux covers RHEL/Rocky, Red Hat/Rocky optional). A source
  whose VMs have no data is flagged ("distributions with VMs but no data") -
  on an offline server this shows whether the uploaded package covers its
  distributions.
- Downloads and the weekly job fetch only the selected dumps (one large
  Ubuntu dump is no longer downloaded on a server without Ubuntu VMs).
- **SUSE Linux Enterprise Server / openSUSE Leap** are matched: OSV's `SUSE`
  and `openSUSE` dumps, ecosystems per product / module normalised to
  `SUSE:15.7` / `openSUSE:16.0` (server, Basesystem module, SAP, HPC, LTSS),
  package from the kernel flavour (`…-default` → `kernel-default`), rpm
  comparison where uname -r's missing rebuild counter is not counted as older
  (`…-150700.53.19` = fixed `…-150700.53.19.1`). SUSE LTSS (extended) is
  matched too.
- After every import, kernel entries under an ecosystem name the parser does
  not know are listed in the job result and the log ("not recognised:
  SUSE:… / kernel-default (12)") - a source renaming its products shows up
  instead of silently producing no data.
- The bundle note says what the package contains (every distribution stored
  on this server + CISA KEV) and that the importing server matches it against
  its own VMs.
- Honest limits: the SUSE / openSUSE record format could not be checked
  against a real kernel advisory (no reachable copy here); it follows OSV's
  SUSE feed conventions, and the "not recognised" list is there to catch a
  mismatch. Photon OS, Oracle Linux and Amazon Linux are not in OSV, so they
  are still not matched. Download sizes are estimates.

### 🔐 Company certificate for networks with TLS inspection (phase 162)
- **Problem seen on the user's network:** every source - cisa.gov, GitHub,
  osv.dev - failed with "certificate verify failed". The firewall re-signs
  HTTPS with the company's own root CA; the host OS and browsers trust it,
  the container does not (Python's `requests` uses its own list, certifi).
- **Administration → Vulnerability Data → Company certificate (TLS
  inspection)**: upload the company root CA - PEM / `.crt`, a Windows `.cer`
  (DER), or the server's whole bundle (e.g. `/etc/ssl/certs/ca-certificates.crt`).
  It is **added** to the public list for data downloads only (vulnerability
  data and endoflife.date); verification stays on, vCenter / Proxmox
  connections are untouched. Kept in the data volume, so it survives rebuilds.
  The card lists the company-specific certificates (name, expiry) and can
  remove the upload.
- **Test sources** now names the CA that signed the certificate this server is
  shown when verification fails (direct connections), e.g. "signed by:
  Example Corp SSL Inspection CA" - that is the certificate to ask IT for.
- `OUTBOUND_CA_BUNDLE` (`.env`): a PEM file or a folder of `.pem/.crt/.cer`
  files, for setups that mount the host's CA store instead of uploading.
  `VULN_PROXY` now applies to the endoflife.date sync too.
- New shared module `app/core/outbound.py`; tests `tests/test_outbound.py` run a
  local HTTPS server signed by a made-up company CA (fails → issuer named →
  PEM / DER / whole-bundle upload / env folder → works → removal → fails again).
- Honest limits: TLS verification is never switched off (no "ignore
  certificates" option on purpose). The issuer hint needs a direct connection
  (not through a configured proxy). Python 3.13+ rejects CA certificates
  without a key-usage extension (strict mode); the image runs Python 3.12,
  where such older inspection CAs still work.

### 🌐 Vulnerability data from GitHub when cisa.gov / osv.dev are blocked (phase 161)
- **CISA KEV** is tried from four sources, each on a different host because
  firewalls allow them separately: cisa.gov → `raw.githubusercontent.com` →
  `api.github.com` (contents API, raw media type - the API host answers
  itself) → the `cisagov/kev-data` branch archive from `github.com` (~0.4 MB
  `.tar.gz`). It is CISA's own repository, updated with the feed. The first
  one that answers wins; the source used is shown in Administration and the
  job result. `VULN_KEV_URLS` replaces the list (e.g. an internal mirror).
- **AlmaLinux OSV** falls back to the `AlmaLinux/osv-database` GitHub archive
  (~3 MB, ~300 kernel advisories for AlmaLinux 8 / 9 / 10) when the osv.dev
  storage is unreachable. RHEL and Rocky VMs are matched with it as before.
  Checked with the real archive: 3,091 kernel rows, KEV-listed CVEs found on
  AlmaLinux / Rocky / RHEL 9 test kernels, import well under a second.
- When the osv.dev storage is unreachable the remaining ecosystems are skipped
  at once (one short failure) and the GitHub fallback still runs.
- **Administration → Vulnerability Data → Test sources** checks every source
  in parallel (first bytes only) and shows reachable / unreachable with a short
  reason: "Proxy blocked (403)", "DNS could not be resolved", "Timeout",
  "Certificate could not be verified"… so the firewall request can name the
  exact host.
- `VULN_PROXY`: a proxy for these downloads only (vCenter / Proxmox calls do
  not go through it). Both settings are documented in `.env.example`.
- Uploads also accept `.tar.gz` archives (the two GitHub archives above).
- Honest limits: Ubuntu and Debian have no usable GitHub copy (Ubuntu's
  `canonical/ubuntu-security-notices` holds ~66,000 OSV files, many GB; Debian
  publishes on salsa.debian.org), so they still need osv.dev or a bundle
  exported from a machine that reaches it. `api.github.com` allows 60
  unauthenticated calls per hour per IP - enough for one call a day.

### 🛡️ Kernel vulnerability matching (phase 160)
- **What it answers:** "which of my supported Linux VMs run a kernel with a
  known, fixed CVE - and which of those are actively exploited?" Only VMs whose
  OS status is *supported*, *ending soon* or *extended* are matched (EOL is
  already the bigger problem; Windows is out of scope).
- **Data** (`vuln_advisory`, `vuln_cve`, `vuln_kev`): [OSV.dev](https://osv.dev)
  dumps for Ubuntu, Debian, Red Hat, AlmaLinux and Rocky Linux, of which **only
  kernel source packages** are stored (Ubuntu: GA `linux`, HWE `linux-hwe-X.Y`,
  `linux-kvm`, `linux-lowlatency*`; cloud / OEM / board kernels are left out -
  measured on a real record that cuts the rows from 147 to 34 per CVE), plus the
  **CISA KEV** catalogue. A server with internet downloads KEV daily (05:23),
  OSV weekly (Sun 03:41) and once ~150 s after start when the data is missing or
  older than a week; **without internet it fails once, fast** and keeps the
  stored data. Newest OSV record wins (`modified`); KEV is replaced only by a
  newer `catalogVersion`.
- **Offline servers:** Administration → **Vulnerability Data** on a machine
  with internet → *Download data package* (gzip JSON, kernel rows + CVE
  descriptions + KEV); upload it on the offline server. A raw OSV `all.zip`
  (streamed, pre-filtered), a single OSV JSON and the KEV JSON are accepted too.
  Imports and matching run in the background with live status.
- **Matching** (pure-Python dpkg / rpm version comparison - no new dependency,
  so the offline prod build keeps working):
  - **Ubuntu:** the kernel flavor and series pick the source package (`6.8.0-124-generic`
    on 22.04 → `linux-hwe-6.8`, on 24.04 → `linux`). `uname -r` carries the ABI
    but not the package upload number, so the **ABI** is compared; with an equal
    ABI the fix counts as present when it is the *first* upload of that ABI
    (`6.8.0-136.136`, `…~22.04.1`), otherwise the finding is **uncertain**. The
    Proxmox QEMU agent also reports `uname -v` (`#136~22.04.1-Ubuntu`, new
    `kernel_build` column, protected against empty agent answers like `kernel`)
    which gives the exact package version. Extended support reads the **Ubuntu
    Pro** ecosystem first, then the standard one for older CVEs.
  - **Debian:** the package version comes from `uname -v` (`Debian 6.1.153-1`);
    without it (every VMware guest) the VM is *not evaluable* - no guesses.
    Debian LTS fixes are in the same ecosystem, so extended Debian is matched.
  - **RHEL family:** `uname -r` minus the arch is the package version-release;
    rpm comparison. RHEL and Rocky fall back to AlmaLinux data when their own is
    missing (same kernel NVRs; the reason says so).
  - A record without a `fixed` version = no fix published → **affected, no fix**.
  - Several advisories for one CVE → the earliest fix counts.
- **Findings** (`vm_vuln`, one per VM + CVE) carry a Turkish evidence line,
  e.g. `Ubuntu 24.04 · linux 6.8.0-124 · düzeltme 6.8.0-136.136 -> etkileniyor`.
  They are recomputed after every platform sync, after data imports / downloads
  and whenever the OS support status is recomputed; a fixed kernel closes them
  (`patched`), a VM leaving the scope closes them as `not_evaluated`, a return
  reopens them. VMs that were already evaluated get one **Change History** row
  per change (category *Security*: "3 CVE yeni: … (KEV)" / "… kapandı"); the
  first evaluation writes none.
- **UI:**
  - New **Vulnerabilities** page: summary cards (KEV-affected VMs, VMs with open
    CVEs, distinct CVEs, evaluated / not evaluable / out of scope - each opens the
    filtered VM list) and the CVE list (severity + CVSS, description, affected
    VMs split into fixable / no fix / uncertain, KEV with due date and ransomware
    use, first seen), KEV first; filters for severity, fix state and KEV only.
  - VM table **Open CVEs** column after Support: the number of open CVEs that
    have a published fix (red with an icon when KEV, else colored by the worst
    severity; `+n` for no-fix / uncertain ones). The tooltip has the package,
    version and the split; click to filter, sortable (KEV first).
  - VM detail: **Kernel vulnerabilities** section (KEV / severity order, fix
    version, description, evidence line).
  - Search: `cve:CVE-2024-1086` (or a fragment `cve:2026-`, `cve:yok`),
    `kev:evet|hayir`, `zafiyet:var|yok|belirsiz|duzeltmesiz|bilinmiyor|kapsamdisi`,
    `acikcve:>10`.
  - Dashboard *Needs attention*: "hit by an actively exploited CVE (KEV)" and
    "with open CVEs that have a fix".
  - Exports: VM report columns **Açık CVE**, **KEV**, **CVE Listesi** (also in the
    "all" and scheduled reports) and a **Zafiyetler** sheet with every finding;
    the Vulnerabilities page exports CVEs + findings.
  - History filter category *Security*.
- Demo inventory: real trimmed OSV / KEV records (the test fixtures) plus a few
  made-up Ubuntu / Debian records.
- Tests: `tests/test_vuln.py` with real trimmed records in `tests/fixtures/vuln`
  (comparators, parsing / filters, newest-wins, zip / bundle / KEV import, every
  matching path, open / close / reopen, history, offline sync, search, views,
  exports, sync hook). **Acceptance:** CVE-2026-43040, Ubuntu 24.04, fixed
  `6.8.0-136.136` → `6.8.0-124-generic` affected, `6.8.0-136-generic` not.
- Honest limits:
  - "Affected" means the **running** kernel is older than the fix (that is what
    the platforms report): a newer kernel installed but not yet booted still
    counts as affected - which is correct until the reboot - and livepatch is
    not taken into account.
  - VMware Ubuntu guests: equal-ABI cases where the fix is a later upload of
    that ABI stay *uncertain*. Debian on VMware is not evaluable.
  - Rocky Linux's OSV format could not be checked against a real record (parsed
    like AlmaLinux); RHEL EUS / AUS streams, Oracle Linux, SLES, Photon OS and
    cloud kernels are not covered.
  - Data size is estimated, not measured on a full dump: one Ubuntu kernel CVE
    record is 0.7-1 MB uncompressed, so Ubuntu's weekly `all.zip` is likely
    several hundred MB up to ~1 GB and its import takes minutes (the temporary
    file needs that much free disk). Stored: a few hundred thousand kernel rows;
    the offline bundle is a few MB. Uploads are limited to 2 GB.

### 🐉 Rolling releases, Alpine, Photon id fix (phase 159)
- **Rolling releases** (Kali, Arch, openSUSE Tumbleweed, Gentoo, Manjaro, Void)
  have no release cycles, so "Kali GNU/Linux Rolling" with a running agent and a
  kernel used to end as *unknown - release not identified*. They are now judged
  by the **running kernel**: once its upstream series is out of support the
  system has not been updated for a long time -> **EOL** (estimated), e.g.
  kernel 5.18 -> EOL since 2022-08-21; a maintained series -> supported. Without
  a kernel: unknown, "rolling release, how current cannot be measured". Kernel
  support data comes from endoflife.date's `linux` product (now in the seed).
- **Alpine Linux** is tracked (`Alpine Linux v3.20`).
- **Fix:** endoflife.date names a product by its permalink - Photon OS is
  `photon`, not `vmware-photon` (the data file's name), so the weekly sync would
  have got 404 for it. The seed and identity use `photon`; rows stored under the
  old id are dropped on startup and exceptions moved.
- The "estimated" note in the tooltip now says what the estimate is based on
  (VM settings name / running kernel / every possible release).
- Seed: 18 products, 428 release cycles.
- Honest limit: a rolling system on a maintained kernel series is shown as
  supported even if its other packages are old - the kernel is the only
  version signal the platforms report.

### 🛡️ OS lifecycle (EOL) tracking (phase 158)
- **Identity** (`app/core/os_identity.py`): the stored OS name (+ kernel) is
  mapped to an [endoflife.date](https://endoflife.date) product and release
  cycle - Ubuntu, Debian, RHEL, CentOS (Stream), Rocky, AlmaLinux, Oracle Linux,
  SLES, openSUSE Leap, Fedora, Amazon Linux, Windows Server, Windows 10/11,
  FreeBSD, Photon OS. Confidence is **high** for the guest's own name (Tools
  detailed data / QEMU agent) or a version read from the kernel (`el7`, `ph5`,
  NT build `20348` -> Server 2022), **estimated** for VMware's catalog name in
  the VM settings or the Proxmox ostype hint (shown with "≈"). Ambiguous names
  ("Windows Server 2016 or later", "CentOS 4/5") get no version.
- **Data** (`os_lifecycle`): 16 products / 358 release cycles ship with the app
  (`app/resources/os_lifecycle_seed.json`, built from endoflife.date). A weekly job
  (Mon 04:17, plus once 90 s after start) refreshes them from the endoflife.date
  API v1; **without internet it fails fast** (one attempt, logged at INFO) and
  the stored data keeps working. **Administration → OS Support** shows the data
  status, an "Update from endoflife.date" button and **Upload JSON** (seed format
  or raw API v1 responses; `tools/refresh_lifecycle_seed.py` builds one on any
  machine with internet). For each release the newest data wins, whatever its
  source.
- **Status per VM**: `supported` / `soon` (within the threshold, default 180
  days, set in Administration) / `extended` / `eol` / `unknown`, with the end
  date that applies and a reason - for unknown: agent not running, VMware Tools
  too old for detailed OS data (< 11.2), VM never seen powered on, release not
  identifiable, no data for the release. If the exact release is unknown but
  every possible one is out of support (any CentOS, Windows 10 non-LTSC) the VM
  is EOL (estimated). Recomputed after every platform sync, on lifecycle data /
  threshold / exception changes and when a VM's tags change.
- **Extended-support exceptions** (`lifecycle_overrides`): mark a paid
  subscription (Ubuntu Pro / ESM, RHEL ELS, Windows ESU, Debian ELTS…) for all
  VMs (optionally one product), a tag or a single VM (kept across Proxmox
  migrations). Most specific wins (VM > tag > all), so a VM rule can also switch
  it off inside a tagged group. Without one, an expired release is EOL even when
  paid extended support exists (the tooltip says so).
- **UI**: colored **Support** column after Kernel (tooltip: release, end date,
  reason, "estimated"; click to filter, sortable by severity), Support row in
  the VM detail panel, search `support:` / `destek:` (`eol`, `soon`/`yakinda`,
  `extended`/`uzatilmis`, `supported`/`destekli`, `unknown`/`bilinmiyor`),
  dashboard **OS Support** card in the OS row (EOL / ending soon / extended /
  unknown / supported, each opens the filtered VM list). The OS row is now
  3 x 4 columns; the top-OS chart cuts long names at the end instead of
  clipping them.
- **Exports**: "Destek" and "Destek Bitişi" columns (VM report, "all" report,
  scheduled reports).
- Demo inventory: EOL, ending-soon, extended (tag exception) and both kinds of
  unknown examples.
- Tests: `tests/test_os_identity.py` (76 real OS strings), `tests/test_lifecycle.py`
  (seed / import / newest-wins, offline + online sync, every status and reason,
  exceptions, threshold, search, sort, dashboard, exports, hooks).
- Honest limits: the status is only as good as the OS name - VMs with old Tools
  or no agent stay estimated/unknown. Windows 10/11 needs the build (Tools 11.2+
  or QEMU agent) to pick the feature update. Extended-support end dates exist
  only where endoflife.date has them (e.g. none for CentOS 7 or Photon OS).
  Existing saved dashboard layouts get the new card at the end of the
  first page - Edit Dashboard → Reset gives the aligned default.

### ↔️ Virtual Machines table: scroll, resize, click-to-filter (phase 157)
- **Horizontal scroll is always on screen.** The table now scrolls inside its
  own box sized to the window; before, the horizontal scrollbar sat below all
  50 rows and looked missing once more columns were shown. The **header row and
  the VM name column stay in place** while scrolling. Rows stay on one line
  (no more ragged two-line host / OS / name cells).
- **Resizable columns:** drag a header's right edge; double-click it for the
  automatic width; **Columns → Reset column widths** restores all. A column can
  also be made narrower than its content (cut with "…"). Widths are remembered
  in the browser, like the column chooser; only the columns you dragged are
  fixed, the rest keep sizing to their content.
- **Click a cell to filter:** Agent (Active / Passive / None), Operating
  System, Kernel, Platform, Status, CPU and RAM join Host / Cluster / Pool /
  Folder / VLAN. Click = only that value (exact for OS / kernel / cluster),
  clicking the same value again removes the filter, **Shift+click excludes** it.
  The row's other cells still open the detail panel.
- New search value `tools:passive` (`pasif`, `stopped`): Tools installed but not
  running - the "Passive" badge (vCenter). The "None" badge filters
  `tools:none -tools:passive`. `tools:none` keeps its documented meaning.
- Search: `os:` accepts exact values (`os:"=Ubuntu 24.04.1 LTS"`), and an exact
  value may contain a comma (`os:"=Windows Server 2022, 64-bit (Build …)"`) -
  exact lists split only at `,=`.
- Fix: table cell filters were inline `onclick` code with the value pasted in,
  so a name with an apostrophe broke the click; cells now carry data attributes.
- Fix: the column-resize handle of each header sat half under the next header.
- Tests: new `tests/test_vm_cell_filters.py` (every cell token returns exactly
  the VMs showing that value, incl. comma OS names and the three agent badges).
- Honest limits: column widths are per browser (not per account); the PDF
  export still uses its own fixed layout.

### 🪟 Kernel for Windows and non-Linux guests (phase 156)
- **Windows** now shows its **NT kernel version** instead of an empty cell:
  VMware `NT 10.0.20348.2582` (NT version + build + update revision from the
  detailed guest data), Proxmox `NT 10.0.20348` (QEMU agent build). On Proxmox
  this replaces the bare build number ("20348") the agent used to leave there,
  so the column has one format on both platforms. Search: `kernel:NT`.
- **FreeBSD and other non-Linux families** take `kernelVersion` as reported
  (e.g. `13.2-RELEASE-p4`) - phase 154 accepted only `familyName='Linux'`.
- The persistent extraConfig copy is now checked whenever the live detailed
  data leaves the kernel open, for every family.
- Honest limit: VMware only publishes detailed guest data with **VMware Tools
  11.2+**. Very old guests (CentOS 4/5 on Tools 10.x, "guestToolsUnsupported")
  and guests whose open-vm-tools build does not publish it report no kernel
  through any vSphere API - the cell stays empty even though Tools runs.

### 🛡️ Sync resilience: values no longer come and go (phase 155)
- **Fix (VMware):** a VM that existed but could not be read in one round
  (vMotion in progress, Tools restarting, a transient vCenter error) was dropped
  from the collector result, so the sync recorded it as **deleted** - removing
  its owner / notes / environment / tags, kernel and daily usage history - and
  re-created it as a "new" VM on the next round. Such a VM is now reported as
  *unreadable* and its stored record is kept untouched for that round (no
  update, no delete, no history row). Only a VM vCenter reports as gone
  (`ManagedObjectNotFound`) or that is absent from the inventory is deleted.
  The sync log says how many VMs were kept this way.
- **Fix (Proxmox live migration):** the VM's new row started with the generic
  ostype name, no kernel and no IP whenever the guest agent did not answer on
  the first round on the new node, and they appeared again only when the agent
  did. The agent-sourced identity (OS name, kernel, arch, IPs / MACs / networks,
  DNS) is now carried over from the old row in that case - the same rule an
  existing row already had. Fresh agent values still win.
- Kernel and architecture are never overwritten by an empty value.
- Tests: new `tests/test_sync_resilience.py` (unreadable VM kept with its manual
  fields, no deleted / created noise, real deletion still works, collector turns
  a read error into "unreadable", migration carry-over with silent and answering
  agent, empty-kernel guard).
- Honest limits: values lost to the old behaviour (manual fields of VMs that
  were deleted and re-created) do not come back.

### 🐧 Kernel column on Virtual Machines (phase 154)
- New **Kernel** column right after Operating System (sortable, case-insensitive;
  `—` when unknown). It is part of the column chooser: users with a saved column
  set see it once (new columns start visible) and can hide it like any other.
- **VMware now fills the kernel** - it was always empty there. The collector
  reads `kernelVersion` from the same detailed guest data it already uses for the
  OS name (`guestDetailedData`, or the persistent `guestInfo.detailed.data` copy
  while the VM is off; VMware Tools 11.2+, vSphere 8.0 U2+). Written **only for
  `familyName='Linux'`**: on Windows that field is the OS build number, not a
  kernel. The extraConfig copy is read only when the live data leaves the OS or
  a Linux kernel open (no extra vCenter round trip for Windows VMs). Proxmox is
  unchanged (QEMU agent `get-osinfo` → `kernel-release`).
- A sync round without kernel data (Tools silent) keeps the stored value; kernel
  changes never write Change History rows (it is an enrich field, not tracked).
- **Search:** free text covers the kernel; new field `kernel:` (aliases
  `cekirdek:` / `çekirdek:`), e.g. `kernel:el9`, `kernel:none`. Search help and
  README updated.
- **Exports:** "Çekirdek" column after "İşletim Sistemi" in Excel, CSV and PDF
  (VM report, "all" report, scheduled reports).
- Tests: new `tests/test_vm_kernel.py` (parser incl. Windows build number,
  extraConfig fallback, sync persistence, sort, search, all three export
  formats); actor suites carry kernel values and assert kernel never creates
  history rows. Demo inventory has realistic kernels for Linux VMs.
- Honest limits: VMs with VMware Tools older than 11.2 (or vSphere before 8.0
  U2) report no detailed data, so their kernel stays empty; Windows guests have
  no kernel by design. The VM PDF is already very wide; long RHEL kernel strings
  wrap in it (Excel / CSV are unaffected).

### 🔗 Open device web consoles from the inventory (phase 153)
- **Management and iLO / iDRAC / BMC addresses are links** on Physical Inventory
  and Hosts (cards and table): one click opens the device's web console in a new
  tab.
- **Hypervisor hosts open the right UI by default:** a Proxmox node goes to
  `https://<ip>:8006`, an ESXi host to `https://<ip>/ui/`. Other devices open
  `https://<address>`.
- New optional **Web UI** field (manual devices and hypervisor host extras) for
  consoles on another port or path (`https://10.0.5.20:8443/`, `http://…`); when
  set, the management address opens it. The iLO field accepts `host:port` too.
- **Hosts page** cards show an **iLO/BMC** chip next to the management IP once a
  BMC address is entered (Physical Inventory → host extras).
- Exports (physical inventory, "all" report, scheduled reports) gained a **Web
  UI** column with the address each row opens.
- Safety: only `http` / `https` addresses are stored or rendered as links
  (`javascript:`, `file:`, `data:` and malformed ports are refused with 400);
  links open with `rel="noopener noreferrer"`. Values that cannot be linked
  (e.g. an iLO field holding "10.0.0.5 (iDRAC)") stay plain text.
- Honest limits: the browser still shows its own certificate warning for
  self-signed consoles; the app does not proxy or log in to them.

### 🖥️ Hardware model on the Hosts page (phase 152)
- Proxmox cannot report a node's exact system model through its API (the
  System Report carries only `dmidecode -t bios` + `lspci`), so hosts showed a
  generic family such as "Dell Inc. PowerEdge Rx5xx", only "HPE", or nothing.
- **Edit it on the Hosts page** (operator and above): pencil on the hardware chip
  / table cell → Brand + Model, pre-filled with the detected value so the usual
  fix is one edit (`Rx5xx` → `R650`). Manual values carry a **manual** badge;
  the detected value stays visible in the editor and the tooltip. **Use detected
  value** removes the override. Audit-logged (`host-hardware:<name>`).
- The same override is used everywhere: Hosts cards / table / sorting / search,
  Physical Inventory (it already had brand / model fields - same storage) and
  every export. A sync never overwrites it.
- **Exports:** host exports (Hosts page, Reports, "all" report, scheduled
  reports) gained **Brand**, **Model** and **Model source** (manual / detected)
  columns - hardware was missing from them entirely.
- **Fix:** Physical Inventory split the detected value at the first space
  ("Dell" / "Inc. PowerEdge R750"); brand and model are now split at the chassis
  family ("Dell Inc." / "PowerEdge R750").
- The Proxmox report parser also accepts the sysfs DMI layout
  (`/sys/devices/virtual/dmi/id/product_name`) and `dmidecode -t system`; both
  have been proposed upstream (Proxmox bug #4982). If a future PVE release ships
  either, the exact model is picked up automatically.
- Honest limit: on today's PVE (9.2 tested by the user) the exact model still
  has to be typed once per host.

---

## [v1.8.0] — 2026-10-27

**10 phases since v1.7.0 (phase 142–151; internal v1.7.1 → v1.7.10).** Focus: a
much stronger Virtual Machines page (multi-select filters, saved searches, exact
match), cluster visibility from every page plus aliases for cluster-less hosts,
manual IPs for agent-less VMs, an aligned default dashboard and an English-first
UI and README.

> **First release with English notes.** Sections up to and including v1.7.0 stay
> in Turkish as the historical record.

### ⬆️ Upgrading
- No manual migration: new columns (`ip_manual`, `cluster_is_alias`) and the
  `cluster_aliases` table are created on startup.
- **Dashboard:** saved layouts are kept as they are. To get the new aligned
  default, open **Edit Dashboard → Reset** (once per account).
- **Language:** users who never picked a language now get the browser's language
  (Turkish browser → Turkish, otherwise English). Picking TR / EN once fixes it.
- **Logs:** a few Turkish log lines are now English (`Cluster log came back
  EMPTY`, `Backup scan …`); update any grep / alert rules that matched them.
- **API:** `POST /api/clusters/visibility` now requires the CSRF token like every
  other write endpoint; scripts calling it must send `X-CSRF-Token`.

### ℹ️ Honest limits
- Server-side messages (API errors, backup diagnostics) and report sheet / column
  titles are still Turkish; percentages use the `%61.3` style.
- Disk usage (`diskuse:`, top disk card) is per VM, not per disk.
- A Proxmox live migration still starts the VM's daily usage history from
  scratch (manual fields are carried over since phase 143; usage history is not).
- Owner / notes / tags lost in migrations **before** this release do not come back.
- Cluster aliases apply only to hosts the platform reports without a cluster.

### 📐 Aligned default dashboard (phase 151)
- The default dashboard was ragged: seven 2-column counters overflowed the
  12-column first row, and the **Physical Devices** tile had no default height,
  so it opened **3 rows tall** and pushed the cards around it into gaps.
- New default layout where **every row fills the grid exactly** and cards in a
  row share one height: 6 counters · 4 resource totals · **top CPU / RAM / disk
  VMs** · capacity forecast + idle VMs (taller, nothing cut off) · recent changes
  + platform status · snapshots / needs attention / environments · then the
  charts in pairs.
- The **Suspended VMs** tile starts hidden on a new layout (it broke the row);
  add it back from Edit Dashboard.
- **Existing saved layouts are not changed.** To switch to the new default:
  **Edit Dashboard → Reset**.
- **Fix:** Reset did nothing since layouts were stored per account — the delete
  was debounced and the page reloaded before it was sent, so the saved layout came
  straight back. Reset now deletes the account copy first.
- README: the topology screenshot (too dense to read) is replaced by **Hosts**
  and **Datastores**; the dashboard image shows the aligned default layout. The
  demo inventory now has 12 datastores with real VM counts, and the screenshot
  tool parks the pointer so no card is captured mid-hover.

### 🌐 English README, screenshots, globalisation (phase 150)
- **README is now English** (`README.md`); the Turkish version moved to
  `README.tr.md`, with a language switch at the top of both. Both were brought
  up to date: default port `18443`, new features, current troubleshooting.
- **Screenshots** (`docs/screenshots/`): dashboard, VM list with filter menus,
  VM detail, search help, change history, topology — taken from a fictional
  demo inventory.
- `tools/demo_data.py` fills a **throwaway SQLite** database with that demo
  inventory (refuses any other database), so anyone can try the UI without a
  real vCenter / Proxmox; `tools/screenshots.py` re-takes the README images.
- **English UI completed:** VM detail panel, dashboard forecast ("% of
  physical", "/day", default page name), change-history range buttons, snapshot
  age filter, platform "Sync now" button and a few placeholders were still
  Turkish in English mode; the sidebar shows "VM Inventory". In English the
  quick filters and search help use `none` / `any` instead of `yok` / `var`
  (both keep working everywhere).
- **Default language follows the browser** when the user has never picked one
  (Turkish browser → Turkish, anything else → English); an explicit choice is
  remembered and always wins. The **login page** is now translated too and has
  its own TR / EN switch.
- **Fix:** permission checks in the UI compared the *translated* role label
  with the Turkish word "Görüntüleyici", so in English mode **viewers saw edit
  controls** (the server still refused the changes). The checks now use the
  role itself (`data-role`).
- The remaining Turkish log lines (backup scan, empty cluster log, sampling
  failure) are now English. If you grep logs for the old Turkish text, use
  `Cluster log came back EMPTY` / `Backup scan` instead.
- New installs name the default admin "Administrator" (existing installs keep
  their stored name).
- Honest limits: server-side messages (API errors, backup diagnostics, report
  sheet titles) and the percent style (`%61.3`) are still Turkish-flavoured.

### 🏷️ Aliases for cluster-less hosts (phase 149)
- VMs on standalone ESXi hosts (the platform reports no cluster) were lumped into
  one "(No cluster)" group that did not appear in the VM page's Cluster menu at
  all. The menu now lists **(No cluster)** (new syntax `cluster:=` = empty
  cluster; combinable: `cluster:=,=Lab`).
- **Name it** in the visibility window gives a per-host alias (with "same name
  for all" per platform). The sync writes it into the host's and its VMs'
  cluster (`cluster_is_alias` flag) and it applies immediately; search, filters,
  hiding, dashboard charts, grouping, reports and topology treat it like a real
  cluster. Lists mark it "alias".
- **The platform wins:** once a real cluster is reported for the host, that name
  is used; if the host leaves the cluster, the alias returns. Aliases write no
  "cluster changed" noise into the change history (the audit log records them).
- A new name given to a hidden "(No cluster)" group (or a hidden old alias)
  **starts hidden** — naming does not silently put the group back on the
  dashboard. A real cluster name cannot be used as an alias (409). The visibility
  row of an alias nobody uses any more is removed; deleting a platform removes
  its alias rules.
- **Fix:** the dashboard's top CPU / RAM / disk and datastore cards wrote errors
  to the browser console when their data was empty.

### 👁 Cluster visibility from everywhere (phase 148)
- Hiding / showing clusters lived only behind the "Manage" button of the
  dashboard's cluster chart. Now the **Dashboard, Virtual Machines, Snapshots and
  Topology** pages have a **Clusters** button in the top bar (with an orange
  "N hidden" badge when something is hidden). Shared component:
  `static/js/clusters.js`.
- The window gained search (8+ clusters), **Show all**, per-row **Only this**
  (that cluster visible, all others hidden), a "N visible · N hidden" summary and
  a note that the setting applies to everyone; read-only for viewers. Toggling no
  longer reloads the page each time — changes are saved and the page refreshes
  once when the window closes (the VM page refreshes in place).
- **Cluster filter menu on Virtual Machines:** first in the toolbar, multi-select,
  VM counts, hidden clusters marked (still listed when selected), "Visibility"
  shortcut at the bottom. The advanced panel's cluster picker moved here. Table
  cell and group-card clicks use the same exact match.
- **New search syntax — exact match:** a value starting with `=` must match the
  whole field (`cluster:=Lab` does not find Lab2); combines with commas and quotes
  (`cluster:"=DC East,=Lab"`). Partial matching stays the default.
- Bulk visibility endpoint `POST /api/clusters/visibility/bulk`
  (`all` / `only` / `names`); one audit row per changed cluster, none for no-ops.
- **Security fix:** `POST /api/clusters/visibility` did not check the CSRF token
  (every other write endpoint does); it does now.

### 🧹 Leaner Virtual Machines toolbar (phase 147)
- Phase 146's 14 chips + counts + group labels took three rows above the table.
  Now it is **one row**: Status · Platform · OS · Missing · Usage are **dropdown
  menus** (checkboxes, counts, multi-select; ⊘ or Shift+click excludes, "Clear"
  at the bottom). The button summarises the choice ("Status: Running +1");
  exclusions show in red. The menu stays open while choosing.
- **Columns** and **Export** (Excel / CSV / PDF in one menu) moved from the filter
  row to the table header, next to the result count.
- **Fix:** in the dark theme the arrow of every select box was missing on all pages.

### 🔍 Virtual Machines filters (phase 146)
- **Multi-select quick filters:** a chip used to replace the whole search. Chips
  are now grouped and toggle: same group = OR (Running + Stopped =
  `status:running,stopped`), different groups = AND. **Shift+click excludes**
  (`-field:value`). Chips are derived from the search box, so typed queries light
  them up too.
- Each chip shows how many VMs it returns on its own (same hidden-cluster rule as
  the list).
- **Saved searches** (bookmark icon): query + sort order stored per account,
  reopened from any device, with live VM counts.
- **Advanced panel in sync with the search box** (it used to keep stale picks).
- **Search help rewritten:** rule cards, the full field list with aliases, a value
  dictionary and tips; every example is clickable. `/` focuses the search box.
- **New search fields:** `cpuuse:` `ramuse:` `diskuse:` (live usage %).
- **Fix:** `osfam:` did not support comma OR (`osfam:windows,ubuntu` silently fell
  back to free text and found nothing); `osfam:linux` now covers every Linux
  family. `tools:none,running` ORs correctly too.

### 📊 Top resource VM cards (phase 145)
- Hovering a bar on the CPU / RAM / disk cards shows the **VM's IP** (with `+N`
  for more, "manual" for a typed IP) and then its **host**. Before, only the host.
- Clicking a bar opens Virtual Machines with **running VMs sorted by the same
  metric** and highlights that VM (it used to search by name only). Card and list
  use the same SQL expression, so the first rows match the card exactly.
- VM list usage sorts (`sort=cpu_usage|ram_usage|disk_usage`); VMs without a
  sample go last in both directions. A removable **Sorted by** badge shows the
  sort; a non-default sort is kept in the address bar.

### 📸 Dashboard snapshot card (phase 144)
- **Fix:** the card showed "0/1 — No snapshots" while the Snapshots page listed
  one. The card took at most 1000 rows and applied the hidden-cluster filter
  **after** the limit; with 1000+ hidden snapshots (e.g. Veeam replica restore
  points on cluster-less VMs) the window filled with them. The filter now runs in
  SQL before the limit, oldest first.
- **Fix:** the "snapshots older than 30 days" counter included hidden clusters
  (the page it links to did not). Both use the same rule now.

### ✍️ Manual IP (phase 143)
- A **Manual IP** field in the VM detail panel for VMs whose agent cannot be
  installed. Several IPs separated by commas, semicolons or spaces; invalid
  addresses are refused, a `/24` suffix is dropped.
- Shown with a **"manual"** badge in the VM list, in the detail panel, host /
  datastore VM lists, topology and Excel / CSV / PDF exports.
- Search: `ip:` and free text find manual IPs; `manuelip:any` lists them. `ip:none`
  and the dashboard "no IP" counter no longer count VMs with a manual IP.
- **The platform always wins:** when an agent reports an IP, the manual one is
  cleared and kept in the change history; a VM that already reports IPs cannot
  get a manual one (field locked, API 409).
- **Fix:** after a Proxmox live migration the VM is a new record on the new node,
  and its **owner, notes, environment and tags were lost**. These manual fields
  (manual IP included) are now carried over. Values lost in earlier migrations do
  not come back.

### 🧹 Repository (phase 142)
- The committed `RELEASE_v1.7.0.md` was removed; `RELEASE_*.md` is in `.gitignore`.

---

## [v1.7.0] — 2026-10-09

**v1.5.0'dan bu yana 7 adım (faz134–faz140; dahili v1.5.4 → v1.6.3).** Odak: dashboard
snapshot kartının dürüstleşmesi, Değişiklik Geçmişi'nde geriye dönük arama,
raporlardaki eksik kolonlar ve belgelerin güncellenmesi.

> **v1.2.0'dan beri ilk yayınlanan release.** Aradaki v1.3.0 / v1.4.0 / v1.5.0
> bölümleri aşağıda; o tag'ler geriye dönük olarak kendi commit'lerine atıldı.

### 📸 Dashboard Snapshot Kartı (faz134–136)
- Kart artık **tüm** snapshot'ları listeler; yaş filtresi (**Tümü / 7+ / 14+ / 30+**)
  kullanıcıda. Tarihi okunamayan snapshot'lar da görünür (sessizce düşmüyor).
- Boş kart artık **nedenini söyler**: "daha yeni snapshot'lar var", "hepsi 7 günden
  taze" veya "hiç snapshot yok" — aynı boş kutu üç farklı durumu gizlemiyor.
- Sayı rozeti eklendi.
- **Düzeltme:** "Tümü" seçilemiyordu. `parseInt("0")` falsy olduğu için `|| 30`
  geri-dönüşü sessizce 30+ bucket'ını seçiyordu. localStorage anahtarı
  sürümlendirildi (`vmi-snap-age-v2`) ki hatalı dönemde yazılmış değerler düşsün.

### 🕵️ Değişiklik Geçmişi — Geriye Dönük Arama (faz137)
- **Tarih aralığı filtresi** (başlangıç/bitiş) + 7g/30g/90g hızlı aralıkları.
  Yerel saat dilimine göre, bitiş günü **dahil** (`app_tz()` ile UTC'ye çevrilir).
- **Gerçek SQL sayfalama**: toplam kayıt, sayfa sayısı, sayfa boyutu seçimi.
  Arayüzdeki eski 200 kayıt tavanı kaldırıldı — arşivin tamamı gezilebilir.
- "İşlemi yapan" (kullanıcı/sistem) filtresi SQL'e birebir çevrilemediği için
  Python tarafında kalıyor ve 20.000 satırlık tarama ile sınırlı; bu sınıra
  takılan sorgular **`capped` bayrağıyla açıkça işaretlenir** (sessizce eksik
  sonuç dönmez).

### 🏷️ Sekme Simgesi (faz135, 138)
- SVG favicon eklendi — çok sekmeli çalışırken uygulamayı bulmak kolaylaşıyor.
- `login.html` `base.html`'i extend etmediği için **çıkış yapıldığında** tarayıcı
  varsayılan dünya simgesine dönüyordu; favicon login sayfasına da eklendi.

### 📊 Raporlar (faz139)
- VM export'larına **Pool** kolonu eklendi (Cluster'dan sonra). Alan modelde,
  senkronizasyonda, filtrede ve VM detayında zaten vardı; yalnız Excel/CSV/PDF
  çıktısında yoktu. Proxmox'ta pool birincil gruplama/kiracı işareti olduğu için
  önemli. Tek kolon listesinden beslendiği için VM export, "Tüm Envanter"
  birleşik export ve zamanlanmış raporlara aynı anda yansır.

### 📚 Belgeler (faz140)
- Bu changelog **v1.2.0'da duruyordu**; faz112–faz139 kaydı git geçmişinden
  yeniden kurulup v1.3.0 / v1.4.0 / v1.5.0 / v1.7.0 bölümleri olarak yazıldı.
- README'de hiç belgelenmemiş **beş sayfa** eklendi: Datastore'lar, Snapshot'lar,
  Yedekler, Topoloji ve **Fiziksel Envanter**. Özellik tablosuna fiziksel envanter,
  disk disk görünürlük ve göç-farkında uptime satırları girdi; Raporlar bölümü
  Pool / "Diskler" sayfası / kullanım kolonlarını söylüyor.
- İki ölü dosya kaldırıldı: kazara commit'lenmiş `dosya` ve ~40 faz eskimiş
  `docs/dokumantasyon.html` (README'nin kopyasıydı; git geçmişinde duruyor).

---

## [v1.5.0] — 2026-09

**faz128–faz133 (v1.4.8 → v1.5.3).** Odak: iki "yanlış sayı" sınıfının kökünden
çözülmesi — uptime ve disk boyutu.

### ⏱️ Uptime Doğruluğu (faz128, 129, 131)
- **Düzeltme:** Proxmox uptime'ı yanlış hesaplanıyordu — `utcnow().timestamp()`
  saat dilimi hatası; `time.time()` ile değiştirildi.
- Uptime **sıralanabilir** hale getirildi (iki platformda da; boş değerler sonda,
  yön ters çevrilmiş) ve VM export'una **Çalışma Süresi** kolonu eklendi.
- **Kök neden araştırması:** Proxmox'un `status.current.uptime` değeri KVM
  *sürecinin* ömrünü sayar ve **canlı göçte sıfırlanır** (Proxmox bugzilla #499).
  Yani 60 günlük bir misafir, göçten sonra 20 gün gösterebiliyordu.
- Çözüm: mümkünse gerçek misafir uptime'ı QEMU Guest Agent üzerinden okunur
  (`/proc/uptime`; `file-read`, olmazsa `exec`). Ajan okuması "yapışkan"dır —
  ajan sustuğunda daha kısa olan süreç değeri eskiyi ezmez.
- Ajan kapalıysa (RHEL türevlerinde `guest-file-open` varsayılan olarak kapalı)
  **göç-farkında** yaklaşım: göç tespit edildiğinde önceki boot zamanı taşınır,
  gerçek güç döngüsünde temizlenir. Platformda ayar değişikliği gerekmez.

### 💾 Disk Boyutu Tutarlılığı (faz132, 133)
- **Düzeltme:** Bazı VM'lerde disk boyutu güncellenmiyordu (ör. 40→75 GB
  değişikliği Geçmiş'e doğru işlenirken liste 100 GB göstermeye devam ediyordu).
  Neden: `disk_total_gb` geçici-hata koruması (`_ENRICH_FIELDS`) tarafından
  korunuyor, `disks_json` korunmuyordu → toplam donabiliyordu.
- Artık toplam ile disk listesi **kilitli adım** ilerliyor, üç açık kural ile:
  liste okunabiliyorsa toplam listeden türetilir; liste okunamıyorsa ikisi de
  korunur; taze toplam boş detayla gelirse toplam kabul edilir. Proxmox'un
  `maxdisk` geri-dönüşü artık taze toplamı eski listeyle eşleştirmiyor.
- Yöneticiler için **disk-diag** ucu: envanteri tarar, toplam ile detay arasında
  tutarsızlık olan VM'leri okunabilir Türkçe çıktıyla listeler. (Disksiz VM'ler
  **normaldir**, tutarsızlık sayılmaz.)

---

## [v1.4.0] — 2026-08

**faz118–faz127 (v1.4.0 → v1.4.7).** Odak: sanallaştırma host'larının fiziksel
envantere akması ve çok diskli VM'lerin görünür olması.

### 🖧 Fiziksel Envanter — Platform Host'ları (faz118, 119, 122)
- Sanallaştırma host'ları (ESXi / PVE node) fiziksel envanterde **salt-okunur
  projeksiyon** olarak görünür; elle girilen alanlar (iLO/BMC IP, lokasyon,
  seri no, rol) ayrı bir "supplement" kaydında tutulur — senkronizasyon ezmez.
- Fiziksel sunucuya **rol** alanı (Hypervisor / Windows / Linux / Diğer) + filtre.
- CPU ve RAM ayrı kolonlara bölündü; host'lar fiziksel envanter ve rapor
  export'larına da akıyor.
- Rozetler yumuşatıldı (parlak renkler göz yoruyordu).
- Proxmox'un yanlış bildirdiği **marka/model elle düzeltilebilir** hale geldi;
  otomatik algılanan değer ipucu olarak gösterilir, sıfırlanabilir.
- **Cihaz tipi artık zorunlu**: tip kartları öne çıkarıldı, varsayılan seçim
  kaldırıldı, onay bildirimi seçilen tipi adıyla söyler. (Yanlış tipe kaydedilen
  bir cihazın "kaybolması" sınıfı hata kaynağında kapatıldı.) Filtre yüzünden
  boş kalan liste artık bunu söyler ve "filtreleri temizle" sunar.

### 💽 Çok Diskli VM Görünürlüğü (faz123–127)
- VM export'una **kullanılan** CPU%/RAM/disk kolonları, tahsis edilenlerin
  yanına eklendi (yuvarlanmış; kullanım verisi yoksa boş).
- VM detay panelinde **disk disk liste**, listede **disk sayısı rozeti**.
- Export'ta disk detayı için yol: tek hücre → yatay `Disk 1/2/3…` kolonları →
  **ayrı "Diskler" sayfası** (disk başına bir satır). Son biçim 16 diskli
  VM'lerde tabloyu şişirmiyor.
- Disk sayısı rozeti hücrenin sağ üstüne sabitlendi (hizalama tutarlılığı).
- **Dürüst sınır:** disk **kullanımı** disk başına alınamıyor — hem vCenter hem
  Proxmox yalnızca VM geneli toplam veriyor. Arayüzde böyle etiketlendi.
- **Düzeltme:** koyu temada disk listesi okunamıyordu (`--ink` → `--text`).

---

## [v1.3.0] — 2026-08

**faz112–faz117 (v1.2.1 → v1.3.3).** Odak: yeni **Fiziksel Envanter** sayfası ve
raporlama/zamanlanmış raporların elden geçirilmesi.

### 🏢 Fiziksel Envanter (Yeni Sayfa — faz114, 115)
- Fiziksel sunucu, storage, SAN switch ve yedekleme ünitesi için **elle CRUD**:
  lokasyon, yönetim IP, iLO/BMC IP, marka, model, seri no, CPU, RAM, durum, not.
- **Tipe duyarlı alanlar** — storage/SAN switch'te CPU/RAM sorulmaz.
- Değişiklik geçmişi, Excel/CSV/PDF export, dashboard özet kartı.
- Lokasyon listeden seçilir (datalist), filtreler koyu temada görünür, kolonlar
  sıralanabilir, marka/model ayrı kolonlar.
- **Birleşik "Tüm Envanter" export'u**: VM + host + datastore + fiziksel tek
  dosyada.

### 📄 Raporlar & Zamanlanmış Raporlar (faz116, 117)
- Export paneli yeniden tasarlandı: **kapsam seçici + biçim düğmeleri**,
  bağlama duyarlı filtre, koyu temada okunur.
- Zamanlanmış raporlar: **beş kapsamın tamamı** (VM/host/datastore/fiziksel/tümü),
  gerçek **saat seçici** (saat–dakika karışıklığı giderildi), hedef etiketleri.
- Üretilmiş dosyalar listesi **20 ile sınırlandı** + toplam sayı; dosya başına
  silme ve toplu temizlik eklendi. (Liste sonsuza doğru büyüyordu.)

### 🕵️ Değişiklik Geçmişi — Aktör Doğruluğu (faz112, 113)
- Platformdan bağımsız düzeltmeler: vCenter guest-shutdown olay çifti, PVE
  `resize` görev tipi.
- Proxmox config-aktörü sağlamlaştırıldı: 5000 satırlık cluster-log penceresi,
  log-aralığı ve "eşleşme yok" teşhis satırları.
- Her iki platform için **kalıcı regresyon testleri** eklendi (`tests/`).

---

## [v1.2.0] — 2026-07-16

**v1.1.0'dan bu yana 18 geliştirme adımı (faz94–faz110).** Bu sürümün odağı:
Proxmox agent tespitinin güvenilir hale getirilmesi, Değişiklik Geçmişi'nin
gürültüden arındırılması ve Ağlar / Datastore'lar / Host'lar sayfalarının ortak
modern tasarım diline taşınması. Tüm şema değişiklikleri **otomatik** uygulanır
(`ensure_schema`) — manuel migration gerekmez.

### 🩺 Proxmox Agent Tespiti — Güvenilirlik Paketi (faz94, 96)
- Agent çağrıları için **ayrı 30 sn'lik istemci**: PVE'nin kendi QGA kararı ~10 sn
  sürerken varsayılan 5 sn'lik istemci bağlantıyı kesip canlı agent'ı "Pasif"
  gösteriyordu (özellikle PVE 8.4.x ve Windows misafirlerde).
- **Hata sınıflandırması**: "not running" (kesin kapalı) ≠ timeout (belirsiz) ≠
  **403 izin hatası**. Belirsiz hatalarda eski "Aktif" durumu 3 senkron korunur
  (`agent_miss_count`) — Aktif↔Pasif çırpınması biter; kesin hüküm anında düşer.
- VM config'inde `agent` seçeneği kapalıysa problar tamamen atlanır → durum
  "Yok" + belirgin senkron hızlanması.
- **VM.Monitor izin teşhisi**: agent uçları 403 verirse VM başına log seli yerine
  senkron başına tek, çözüm komutlu WARNING; durum dürüstçe "bilinmiyor" yazılır.
- `enrich_failed` durumunda `tools_status` artık korunur (geçici config hatası
  Agent kolonunu "Yok"a düşürmez).

### 🧾 Değişiklik Geçmişi — Gürültü Temizliği (faz98)
- **Host alan çırpınmaları bitti**: node detay çekimi başarısız olunca (403/
  timeout/offline) alanlar boş yazılıp `değer ↔ —` kayıt selleri oluşuyordu;
  artık başarısızlıkta alanlar **atlanır**, DB'deki değer korunur.
- **mgmt_ip aday koruması**: kayıtlı IP node'da hâlâ mevcutsa farklı bir
  deterministik seçim (bond failover, vmk sırası) değişiklik SAYILMAZ; yalnız
  gerçek re-IP tek sefer kaydedilir. vCenter vmk'ları ada göre sıralı.
- **vCenter olay sayfalaması**: `QueryEvents` tek sayfa (~1000 olay) döndürür ve
  yoğun ortamda reconfigure olayları sayfa dışında kalıp "kim yaptı" kayboluyordu;
  `EventHistoryCollector` ile tam pencere taranır (8000 olay tavanı + fallback).
- **Kaynak türü filtresi**: Kullanıcı + Sistem / Yalnız Kullanıcı / Yalnız Sistem
  (DRS/HA/pvesr/vCLS otomasyonu) / Kullanıcısız. Sınıflandırma backend'de,
  ⚙ sistem rozetiyle tutarlı.
- Varlık filtresi düzeltmesi: Datastore/Ağ seçimi artık backend'de de uygulanır;
  host güncellemeleri kategori + aktör metasıyla yazılır.

### 🗄️ Veri Bütünlüğü (faz99, 99b)
- **FK-güvenli VM silme**: VM silinmeden önce Backup/Snapshot/VmUsageDaily
  satırları temizlenir (PostgreSQL `backups_vm_id_fkey` ihlali ve senkron
  rollback'i giderildi).
- **Yetim arşiv desteği**: VM silindikten sonra depoda yaşayan vzdump/PBS
  arşivleri `vm_id=NULL` ile korunur; silme sonrası `flush` ile aynı senkron
  içindeki yeniden-ekleme çakışması önlendi.

### 🎨 Ortak Tasarım Dili — Ağlar, Datastore'lar, Host'lar (faz95, 97, 104–108)
- **Ağlar**: tekilleştirilmiş kart gridi (aynı ağ N node'da = tek kart), üst stat
  şeridi, kapalı akordeonlar, ağ başına **VM sayısı** ve `network:"ad"` alan
  sözdizimiyle VM listesine deep-link; `networks`/`vlans` serbest metin aramada.
- **Datastore'lar**: stat şeridi (kapasite/kullanım/kritik), Kartlar / Cluster'a
  göre / Tür'e göre / Node'a göre / Tablo modları, **"Yerel diskleri gizle"**
  filtresi, kartlarda cluster çipleri, **son yedek yaşı rozeti** (≤2g yeşil,
  ≤7g sarı) ve çok-cluster paylaşımlı depolarda **çift sayım uyarısı**.
- **Host'lar**: stat şeridi, Kartlar / Cluster'a göre / Tablo modları; 12 kolonlu
  sıralanabilir tablo ve VM modalları aynen korunarak.
- **Datastore↔Host eşleşmesi düzeltildi**: kartta 10, modalda 2 host uyuşmazlığı —
  bağlı (mount) host adları artık toplanıyor (`host_names`) ve modal bu listeyi
  gösteriyor; vCenter mount adları tek geçişli MoId haritasıyla çözülür.

### 👤 Hesap-Bazlı Arayüz Ayarları (faz100)
- Yeni `user_settings` tablosu + `GET/PUT /api/user-settings/{key}`: **dashboard
  düzeni ve topoloji konumları artık hesabı takip eder** — tarayıcı/cihaz
  değişse, temizlense veya yeniden kurulsa da düzen kaybolmaz (yerel kopya
  çevrimdışı yedek olarak durur, ilk kayıtta sunucuya taşınır).

### 📊 Dashboard İyileştirmeleri (faz101–103, 109, 110)
- Dark/light temada mini kart yazı renkleri düzeltildi (her iki temada okunur);
  Ağlar kartında rozet/etiket çakışması giderildi.
- **"Yerel diskleri gizle" gözü** Datastore Doluluk widget'ında: tek tıkla mini
  kart tavanı, depolama donut'ı, doluluk listesi ve kapasite öngörüsünün disk
  satırı yalnız paylaşımlı/merkezi depolarla ("gerçek" kapasite) hesaplanır.

### ℹ️ Notlar
- Proxmox token rolü gereksinimlerine **`VM.Monitor`** eklendi (agent durumu /
  misafir IP / disk kullanımı için): `pveum role add EnvanterVMMon -privs
  VM.Monitor; pveum aclmod / -token '…' -role EnvanterVMMon`.
- Değişiklik Geçmişi kayıtları süresiz saklanır (PostgreSQL `change_history`);
  arayüzdeki 200, yalnız görüntüleme limitidir.

---

## [v1.1.0] — 2026-07-05

**v1.0.3'ten bu yana 66 geliştirme adımı.** Bu sürüm; iki dilli arayüz, akıllı
zombi/kapasite analitiği, topoloji haritası, çok-metrikli değişiklik geçmişi,
çevrimdışı (intranet) çalışma ve monitöring modu ile ürünü büyük ölçüde
olgunlaştırır. Tüm veritabanı değişiklikleri **otomatik** uygulanır
(`ensure_schema`) — manuel migration gerekmez.

### 🌍 Tam TR/EN İki Dilli Arayüz
- Sıfırdan hafif bir i18n motoru (`app/static/js/i18n.js`, 527 anahtar): topbar'dan
  tek tıkla **TR ⇄ EN** geçişi, seçim `localStorage`'da kalıcı.
- **12 sayfanın tamamı** çevrildi: Dashboard, Sanal Makineler, Host'lar,
  Datastore'lar, Değişiklik Geçmişi, Topoloji, Yedekler, Snapshot'lar, Ağlar,
  Platformlar, Raporlar, Yönetim + ortak kabuk (menü/topbar/modallar).
- Sayfa başlıkları ve tarayıcı sekme başlığı (`document.title`) da dile duyarlı.
- Backend kaynaklı metinler (zombi sınıfları, PBS tanı notları, değişiklik tipleri)
  **makine-okunur kodlarla** döndürülüp arayüzde çevriliyor — TR sayfa tamamen TR,
  EN sayfa tamamen EN.

### 📊 Akıllı Dashboard & Analitik
- **Çok-metrikli Zombi (boşta) VM tespiti** (`app/core/zombie.py`): CPU + RAM
  oynaklığı + Disk I/O + Ağ trafiği korelasyonu, 14-30 günlük pencere, 0-100 skor
  ve sınıf (Kesin Zombi / Şüpheli / Aktif). Yalnız-CPU yanılgısını (false-positive)
  önler; "?" butonuyla çalışma mantığını anlatır.
- **Kapasite Öngörüsü**: gerçek doluluk trendinden (lineer regresyon) Disk, RAM
  **ve CPU** için "dolabilir" tahmini. Doluluk (gerçek kullanım) ile Tahsis
  (overcommit) kavramları ayrı; "?" butonlu açıklama.
- **Premium modüler grid**: sürükle/boyutlandır/gizle, **çoklu sayfa** (bir widget
  birden çok sayfada olabilir), sabit-hücreli yerleşim, LocalStorage'da kalıcı.
- **Monitöring / kiosk modu**: birden çok sayfada otomatik döngü (10/15/30/60/120 sn),
  kullanıcı etkileşiminde akıllı duraklama, yeniden yüklemede devam.
- **Uzun Süreli Snapshot'lar** widget'ı: 7+/14+/30+ gün filtresi, gizli cluster'lar
  hariç.
- Tahsisli kartlar artık **Atanan / Toplam** (fiziksel tavan) + oran çubuğu gösterir.
- Gerçek kullanım metrikleri: RAM (guest-active), disk (guest-fs) — thin disk
  şişkinliği olmadan doğru değerler.

### 🗺️ Topoloji Haritası (Yeni)
- Cytoscape tabanlı **altyapı topoloji haritası**: Platform → Cluster → Host → VM.
- Lazy yükleme (host'a tıklayınca VM'ler), **SSE ile canlı akış**, katman filtreleri
  (donanım/depolama/ağ), sunucular arası ağ, VM erişilebilirlik kabloları
  (yeşil/kırmızı), hareketli kablolar, konum kalıcılığı.

### 📜 Zenginleştirilmiş Değişiklik Geçmişi
- **Kategori-bazlı doğru aktör eşleştirme**: bir RAM değişikliği yalnız config
  işlemine, güç değişikliği yalnız güç işlemine atfedilir — yanlış kişiye asla.
- Kaynak: Proxmox görev kaydı + cluster log (Sys.Syslog), vCenter eventManager.
- **Datastore / Ağ / Host eklendi-silindi** artık "kim yaptı" ile geçmişe düşer.
- Sanallaştırmanın kendi/otomasyon işlemleri **"⚙ sistem"** rozetiyle işaretlenir.
- vmid-yeniden-kullanım koruması (ctime filtresi), klon yeni-vmid çözümleme,
  node-arası göç tek satır, konsol erişimi toplama (ayarlanabilir, varsayılan kapalı).

### 💾 Yedekler, Snapshot'lar, Ağlar
- **Proxmox/PBS yedek toplama**: filtresiz+filtreli sorgu, paylaşımlı depoda tüm
  online node'ları deneme, namespace/izin tanılaması ("Neden? Tanıla" akışı).
- Snapshot arama söz dizimi (vm:/snap:/age:/current:/parent:), Ağlar sayfası
  (host/cluster/VLAN/fiziksel gruplama).

### 🖥️ Toplama & Uyumluluk İyileştirmeleri
- **Kademeli QEMU Guest Agent tespiti** (eski agent'lar, PVE 8.4.x): network komutu
  başarısızsa `info`/`ping` ile canlılık; disk kullanımı (fsinfo) artık eski
  agent'larda da gelir.
- **DNS bilgisi**: VM detayında DNS sunucuları (vCenter ipStack / Proxmox
  cloud-init & LXC nameserver).
- **Host donanım modeli**: vCenter'da vendor+model (ör. Dell PowerEdge R750);
  Proxmox'ta `pvereport` (dmidecode) + PCI subsystem'den şasi ailesi çıkarımı.
- Proxmox RAM kaynağı `config.memory` (ballooning salınımı düzeltildi), gerçek
  CPU/RAM/disk kullanımı, tam OS sürümü (vSphere 8 U2+ / Tools 11.2+).

### 🎨 Tasarım & Erişilebilirlik
- Global **dark/light tema** tüm sayfalarda; koyu temada özel bileşenler düzeltildi.
- **Renk körü dostu** (Okabe-Ito) buton/rozet paleti dark temada; daha az parlaklık.
- Dropdown/kolon-seçici okunabilirlik düzeltmeleri, yumuşak geçmiş rozetleri.

### 🔌 Çevrimdışı / İntranet Desteği
- **Sıfır CDN**: Bootstrap, bootstrap-icons, jQuery, DataTables, Chart.js,
  Cytoscape ve Inter fontu (latin + latin-ext) repoya alındı (`app/static/vendor/`,
  25 dosya). Kapalı ağda arayüz artık sorunsuz açılır.

### 🧹 Kod Sağlığı & Düzeltmeler
- Tüm backend yorum/docstring/log mesajları İngilizce'ye çevrildi (34 dosya),
  token-akışı karşılaştırmasıyla **kod davranışının değişmediği** doğrulandı.
- **Kritik düzeltmeler**: platform silme 500 hatası (FK sırası — snapshots/backups/
  usage temizliği), dashboard yükleme çökmesi (i18n `t()` gölgeleme), insights 500
  (PostgreSQL Decimal/float), Proxmox cluster/tasks 400, sync paylaşımlı kilit
  (çakışma önleme).

**Tam commit listesi:** `git log v1.0.3..v1.1.0`

---

## [v1.0.3] — önceki kararlı sürüm
Ayrıntılı özellik listesi için `README.md`.
