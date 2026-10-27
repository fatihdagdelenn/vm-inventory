<div align="center">

# 🖥️ VM Inventory

**One read-only inventory for all your VMware vCenter and Proxmox VE environments**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![UI](https://img.shields.io/badge/UI-English%20%7C%20T%C3%BCrk%C3%A7e-blue)](#)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

*Sub-second search across 500+ VMs and 20+ hosts — everything is served from a local cache, never from a live API call.*

**English** · [Türkçe](README.tr.md)

<img src="docs/screenshots/dashboard.png" alt="Dashboard" width="900">

</div>

---

## 📑 Contents

- [What is it for?](#-what-is-it-for)
- [Screenshots](#-screenshots)
- [Features](#-features)
- [Architecture](#-architecture-how-it-works)
- [Requirements](#-requirements)
- [Installation](#-installation-step-by-step)
- [First-time setup](#-first-time-setup)
- [User guide](#-user-guide)
- [Change history: who, what, when?](#-change-history-who-what-when)
- [Search syntax](#-search-syntax)
- [Roles and permissions](#-roles-and-permissions)
- [LDAP / Active Directory](#-ldap--active-directory-optional)
- [Production notes](#-production-notes)
- [Troubleshooting](#-troubleshooting)
- [Project layout](#-project-layout)
- [FAQ](#-faq)

---

## 🎯 What is it for?

A central inventory for teams running several **VMware vCenter** and **Proxmox VE** environments:

> *"Which host is 10.10.10.15 on?"* — *"How many Windows servers are on VLAN 100?"* — *"Whose RAM changed last week, and who changed it?"* — *"Which VMs have no guest agent?"*

All of these are answered from one search box in well under a second. **No SSH access and no agent rollout** — only the platforms' official APIs are used, with read-only accounts.

## 📸 Screenshots

*Taken from the built-in demo inventory (`tools/demo_data.py`) — every name and address is fictional.*

| | |
|---|---|
| <img src="docs/screenshots/vm-list.png" alt="Virtual machines with filter menus" width="440"><br>**Virtual machines** — multi-select filter menus with counts, live usage bars | <img src="docs/screenshots/vm-detail.png" alt="VM detail panel" width="440"><br>**VM detail** — everything about one VM, plus owner / tags / notes / manual IP |
| <img src="docs/screenshots/search-help.png" alt="Search syntax help" width="440"><br>**Search syntax** — Google-like `field:value` queries; every example is clickable | <img src="docs/screenshots/change-history.png" alt="Change history" width="440"><br>**Change history** — old → new values and *who did it*, from the platforms' own logs |
| <img src="docs/screenshots/topology.png" alt="Topology map" width="440"><br>**Topology** — platform → cluster → host → VM map | <img src="docs/screenshots/dashboard.png" alt="Dashboard" width="440"><br>**Dashboard** — capacity forecast, idle (zombie) VMs, attention list |

## ✨ Features

| | |
|---|---|
| 🔍 **Google-like search** | `ip:` `os:` `vlan:` `cluster:` `ram:>=16` `-tag:test` `ip:none` … combine any criteria; exact match with `cluster:=Lab` |
| 🏷️ **Multi-select quick filters** | One toolbar row of Cluster / Status / Platform / OS / Missing / Usage menus with VM counts; options in one menu are OR'ed, menus are AND'ed, ⊘ or Shift+click excludes |
| 🎛️ **Advanced filter panel** | Pick from existing values (with counts), removable filter badges, clickable table cells |
| 🔖 **Saved searches** | Store a query + sort order in your account, reopen it from any device |
| 📊 **Rich dashboard** | Resource totals, OS / environment / cluster distribution, host CPU-RAM charts, storage, capacity forecast, idle-VM detection, "needs attention" list; drag-and-drop layout per user |
| 🔗 **Multiple platforms** | Any number of vCenters + Proxmox clusters (QEMU VMs **and LXC containers**) in one inventory |
| 📄 **Reporting** | Filtered Excel / CSV / PDF; scheduled daily reports |
| 🕵️ **Change tracking + "who did it"** | Every sync is diffed: what changed, when, old → new **and who did it**. Categorised (hardware / disk / network / power / migration / lifecycle) with source (platform / cluster / host / VM ID), operation type and user — taken from the platform's own task / event log |
| 🔀 **Live migration & lifecycle** | vMotion / Proxmox migration **from which host to which**, plus the user; create, **clone**, delete and template conversions tracked separately |
| 🖥️ **Console access audit** *(optional)* | Users who opened a VM console (noVNC / SPICE / MKS) — off by default, grouped in 30-minute windows |
| 👁️ **Cluster visibility** | Hide old / test clusters from counts and lists with one switch, from the **Clusters** button in the top bar; nothing is deleted |
| 🏷️ **Cluster aliases** | Standalone ESXi hosts (no cluster) can be given a cluster name per host; the platform's real cluster always wins |
| ⚡ **Live usage** | VM and host CPU / RAM usage plus real disk fill (thin-provisioning aware); refreshed every ~3 minutes by a light job |
| 🐧 **Full OS version** | Detailed guest OS on VMware (e.g. *"Ubuntu 24.04.1 LTS"*, vSphere 8.0 U2+ with VMware Tools 11.2+); on Proxmox via the QEMU Guest Agent |
| ✍️ **Manual IP** | For VMs whose agent cannot be installed: type the IP yourself — searchable and exported, replaced automatically once an agent reports one |
| 🖧 **Hosts** | Sortable host table with CPU / RAM / disk bars, uptime and per-host VM list |
| 🏢 **Physical inventory** | Non-virtualised hardware (servers, storage, SAN switches, backup appliances) entered by hand; hypervisor hosts flow in automatically and keep your manual fields |
| 💽 **Per-disk view** | Every disk of a multi-disk VM is listed; a separate "Disks" sheet in exports |
| ⏱️ **Migration-aware uptime** | Proxmox resets uptime on live migration (bugzilla #499); the real guest uptime is read from the agent when possible, otherwise boot time is carried across the migration |
| 🗂️ **Pools / folders / tags** | vCenter resource pools & folders, Proxmox pools, platform tags (vCenter REST tags / Proxmox tags) — all searchable |
| 👥 **Role-based access** | Admin / Operator / Viewer + optional LDAP / AD login |
| 🔐 **Security** | Fernet-encrypted credentials, bcrypt, CSRF protection, sliding sessions, audit log |
| 🌐 **Bilingual UI** | English and Turkish, switchable in the top bar; works fully offline (no CDN) |

## 🏗 Architecture: how it works

```
┌─────────────┐   scheduled jobs           ┌──────────────────┐
│  vCenter(s) │◄──────(APScheduler)────────┤                  │
└─────────────┘   every 15 min,            │     FastAPI      │
┌─────────────┐   pyVmomi / proxmoxer      │   + SQLAlchemy   │──► PostgreSQL
│ Proxmox(es) │◄───────────────────────────┤                  │    (local cache)
└─────────────┘                            └────────┬─────────┘
                                                    │  every search hits the local DB
                                             ┌──────▼─────────┐
                                             │  Bootstrap 5   │
                                             │  + Chart.js    │
                                             └────────────────┘
```

**Core principle:** user searches **never** reach vCenter / Proxmox.

1. **Collector** — a background scheduler connects to every platform every 15 minutes (configurable). vCenter is read in bulk through one `ContainerView`, Proxmox through one `cluster/resources` call — no per-host or per-VM requests.
2. **Cache** — name, IP, MAC, OS, CPU / RAM / disk, VLAN, cluster, power state, Tools / agent state… are written to indexed tables. Any difference from the previous record goes into the **change history**.
3. **UI** — searches, reports and charts are served from the local database and answer instantly even at 500+ VMs. **Sync All** triggers an immediate sync when needed.

## 📋 Requirements

| Component | Requirement |
|---|---|
| Server | Linux (Ubuntu 22.04+ recommended), 2 vCPU / 2 GB RAM is enough |
| Software | Docker + Docker Compose **or** Python 3.11+ |
| Network | From the server to vCenter `443/tcp`, to Proxmox `8006/tcp` |
| vCenter | 6.7+ (8.x tested) — a read-only account is enough |
| Proxmox | 7.x / 8.x — API token; `PVEAuditor` is enough for the inventory. For **"who did it" / backup contents** add `Sys.Syslog` + `Datastore.Audit` (below) |
| Guests | For IP / OS details: VMware Tools or QEMU Guest Agent *(optional)* |

## 🚀 Installation (step by step)

### Option A — Docker Compose (recommended)

**1. Get the project**

```bash
git clone https://github.com/fatihdagdelenn/vm-inventory.git
cd vm-inventory
```

**2. Create the environment file**

```bash
cp .env.example .env
```

**3. Generate the secrets** and paste them into `.env`:

```bash
# ENCRYPTION_KEY (encrypts platform passwords / tokens):
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# SECRET_KEY (signs session cookies):
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Your `.env` should look like this:

```ini
SECRET_KEY=your-secret-key
ENCRYPTION_KEY=your-fernet-key
SYNC_INTERVAL_MINUTES=15
USAGE_SYNC_INTERVAL_MINUTES=3
SESSION_TIMEOUT_MINUTES=480
APP_TIMEZONE=Europe/Berlin
```

> ⚠️ **Back up `ENCRYPTION_KEY`!** If it is lost, the stored platform passwords / tokens cannot be decrypted and must be entered again.

**4. (Optional) Change the port** in `docker-compose.yml`:

```yaml
    ports:
      - "18443:8000"     # host port : container port (only change the left one)
```

**5. Start**

```bash
docker compose up -d --build
```

The first build takes 2–3 minutes. Follow it with `docker compose logs -f app`.

**6. Log in** — open `http://<server>:18443` (or the port you chose).

> 🔑 Default login: **admin / admin123** — change it right away.

### Option B — Manual install (without Docker)

```bash
# Python 3.11+ and a venv (avoids clashing with system packages)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # generate the keys as above
# SQLite is fine for small installs; in .env:
#   DATABASE_URL=sqlite:///./data/vminventory.db
mkdir -p data/reports

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For PostgreSQL, prepare the database first:

```sql
CREATE USER vminv WITH PASSWORD 'strong_password';
CREATE DATABASE vminventory OWNER vminv;
```

and set `DATABASE_URL=postgresql+psycopg2://vminv:strong_password@localhost:5432/vminventory` in `.env`.

Tables are created on first start; there are no migrations to run.

### Just want to look around?

Fill a throwaway SQLite database with the fictional demo inventory used for the screenshots:

```bash
DATABASE_URL=sqlite:///./data/demo.db SECRET_KEY=demo ENCRYPTION_KEY=demo python3 tools/demo_data.py
DATABASE_URL=sqlite:///./data/demo.db SECRET_KEY=demo ENCRYPTION_KEY=demo uvicorn app.main:app --port 8000
```

(The script refuses anything but a SQLite file, so it cannot touch a real database.)

## ⚙️ First-time setup

### Step 1 — Change the admin password

**Administration → Users**: edit `admin` and set a new password.

### Step 2 — Add vCenter

Create a read-only service account in vCenter first *(recommended — do not use a personal account)*:

1. vSphere Client → **Administration → Users and Groups** → new user, e.g. `svc-inventory@vsphere.local`
2. **Administration → Global Permissions** → give it the **Read-only** role with *"Propagate to children"* ticked

Then in the app: **Platforms → Add Platform**:

| Field | Value |
|---|---|
| Type | VMware vCenter |
| API address | `vcenter.company.local` or an IP — **without https:// and without a port** |
| Port | `443` |
| User / password | the service account |
| Verify SSL certificate | **off** for self-signed certificates |

**Test Connection** → if it succeeds, **Save**.

### Step 3 — Add Proxmox

Create an API token on a Proxmox node (SSH or web shell):

```bash
pveum user add svc-inventory@pve --comment "Inventory service account"
pveum acl modify / --users svc-inventory@pve --roles PVEAuditor
pveum user token add svc-inventory@pve inventory --privsep 0
```

> ⚠️ Save the **`value`** line of the last command right away — it is never shown again.

> ⚠️ `--privsep 0` is required; without it the token cannot see VMs (only node names come back).

**(Recommended) Extra privileges for "who did it" and backup contents.** `PVEAuditor` contains `Sys.Audit` and `VM.Audit` (task log and VMs) but **not `Sys.Syslog` or `Datastore.Audit`**, and as a built-in role it cannot be edited. Add them with a small extra role:

```bash
# Sys.Syslog      = the USER of config changes (RAM/CPU/network) is read from the cluster log
# Datastore.Audit = backup contents are listed
pveum role add InventoryExtra -privs "Sys.Syslog Datastore.Audit"
pveum acl modify / --users svc-inventory@pve --roles InventoryExtra
# If the token has privilege separation ON, give the same ACL to the token too:
pveum acl modify / --tokens 'svc-inventory@pve!inventory' --roles InventoryExtra
```

> ℹ️ Without these the inventory still works; only the **User column stays empty ("—") for config changes** in the change history, and backup contents are not listed. vCenter needs nothing extra for "who did it" (**Read-only / System.View** is enough).

In the app: **Platforms → Add Platform**:

| Field | Value |
|---|---|
| Type | Proxmox VE |
| API address | any node (cluster data comes from a single node) |
| Port | `8006` |
| Authentication | **API Token** |
| Token name | `svc-inventory@pve!inventory` |
| Token value | the `value` you saved |

### Step 4 — First sync

Click **Sync now** on the platform card. It runs in the background without blocking the UI and takes 1–5 minutes depending on size. When it finishes, the dashboard and VM list fill up. From then on it is automatic (every 15 minutes).

### Step 5 — (Recommended) Check guest agents

On the dashboard, **Needs Attention** → *"No Agent / Tools installed"*. These VMs report no IP and no exact OS name:

- **vCenter VMs** → install VMware Tools / open-vm-tools
- **Proxmox VMs** → `apt install qemu-guest-agent`, enable *QEMU Guest Agent* in the VM options, restart the VM

If an agent cannot be installed (appliances, locked-down OSes), type the IP in the VM detail panel's **Manual IP** field.

## 📖 User guide

| Screen | What you do there |
|---|---|
| **Dashboard** | Overall state: counts, resource totals, charts (click a slice to open the filtered list), capacity forecast, idle VMs, recent changes, platform health. **Top CPU / RAM / Disk VM** cards show the VM's IP and host on hover; a click opens the VM list sorted by the same metric with that VM highlighted. Layout is drag-and-drop and stored per user |
| **Virtual Machines** | Search + quick-filter menus + advanced panel + grouping. Live usage bars in the CPU / RAM / disk columns (yellow 75%+, red 90%+). **Columns** and **Export** are in the table header. Click a row for the detail panel (owner, tags, environment, notes, manual IP are edited there). Host / cluster / VLAN / pool / folder cells are clickable filters |
| **Hosts** | ESXi / PVE nodes in one table: management IP, hypervisor version, CPU model, cores, CPU / RAM / disk bars, cluster, VM count, uptime, state. Every column sorts; clicking the VM count lists that host's VMs, and a VM opens its detail panel on the same page |
| **Datastores** | Capacity, fill, type, connected hosts, resolved clusters. Card / type / node / table views; **hide local disks** to see shared capacity; capacity-overlap warning for shared stores seen by several clusters |
| **Snapshots** | Every snapshot in one list with age — sort by age to find the forgotten ones |
| **Backups** | Proxmox / PBS backups per VM. When a permission or configuration is missing it **says why** instead of showing an empty list. *(vCenter has no backup API, so this screen is Proxmox-only)* |
| **Networks** | Port groups / bridges / SDN vnets and host NICs, grouped by host, cluster, VLAN or physical cards |
| **Topology** | Live Cytoscape map: platform → cluster → host → VM, layer filters, node positions saved per account, reachable / unreachable VM links |
| **Physical Inventory** | Non-virtualised hardware: servers, storage, SAN switches, backup appliances, with location, management / iLO-BMC IP, brand, model, serial, role and state. Hypervisor hosts appear here **read-only**; the fields you add to them survive every sync |
| **Reports** | Instant Excel / CSV / PDF (with filters) + scheduled daily reports (written to `data/reports/`). Scope: **VM / Host / Datastore / Physical / Everything**; VM exports include allocation **and** usage columns and a separate **Disks** sheet |
| **Change History** | Added / deleted / cloned / migrated VMs, per-field **old → new** values, category, source and **who did it**, with date range and filters — see below |
| **Platforms** | Connections, manual sync, API error logs |
| **Administration** *(admin)* | Users, audit log, and the **Synchronization** tab: full and usage sync intervals (1–1440 min, applied immediately), console-access tracking switch |

## 🕵️ Change history: who, what, when?

Every sync is compared with the previous state of the inventory and the differences go to **Change History**:

| Column | Content |
|---|---|
| **Date** | When the change was detected |
| **Source** | Platform (vCenter / Proxmox) · cluster · host / node · VM ID |
| **Entity** | VM or host name |
| **Category** | Hardware (vCPU / RAM) · Disk · Network · Power · Migration · Lifecycle · OS · Console |
| **Operation** | Added / Updated / Deleted / Migrated / Access + the raw platform operation (e.g. `qmclone`, `VmReconfiguredEvent`) |
| **Field / value** | The changed field, **old → new** (e.g. RAM `8 GB → 16 GB`, host `esx01 → esx02`) |
| **User** | Who did it on the platform |

Tracked: **hardware** (vCPU, RAM, OS type), **disk & storage** (size, datastore), **network** (bridge / port group, VLAN, MAC, NIC), **power** (on / off / suspend / reboot), **lifecycle** (create, clone, delete, template), **migration** (live migration, source → target host).

**Where does "who did it" come from?** Not from this app's users — from the **platform's own task / event log**:
- **vCenter:** `eventManager` events — reconfigure, migrate, power, create, …
- **Proxmox:** node task logs (`/nodes/{node}/tasks`) + the cluster log (`/cluster/log`). Config changes (RAM / CPU / network) create no task on Proxmox, so their user is read **only from the cluster log** → the token's role needs **`Sys.Syslog`** (Step 3).

**The right person:** each field change is matched only with an operation of a **fitting category** (a RAM change only with a config operation, a power change only with a power operation). When nothing fits, the user is left empty — **a wrong name is never written**.

**Console access** *(optional, off by default)* — enabled under Administration → Synchronization. Users who opened a VM console are written as separate "Access" rows, grouped in 30-minute windows.

> **Honest limits:**
> - The operator's **client IP / user agent** is not present in vCenter events or Proxmox task / log records → these columns are usually empty for infrastructure changes. (In-app actions have a separate **Audit Log** with IP / UA.)
> - Rows recorded before the "who did it" feature keep `—` as the user; only new changes are enriched.
> - Detection delay equals the full sync interval (Administration → Synchronization).

## 🔍 Search syntax

| Syntax | Example | Meaning |
|---|---|---|
| free text | `web01` | Searches name, VM ID, IP (manual IPs included), MAC, OS, cluster, VLAN, network, pool, folder, owner, notes, platform note and platform tags (use `tag:` / `host:` for tags and hosts) |
| `name:` / `vm:` | `name:web` | VM name |
| `vmid:` / `id:` | `vmid:100` | VM ID (numeric on Proxmox / MoRef on VMware) |
| `ip:` | `ip:10.10.10.` | IP (partial); finds manual IPs too |
| `manuelip:` | `manuelip:any` `-manuelip:any` | VMs with / without a manually entered IP |
| `mac:` / `vlan:` / `network:` | `vlan:100` | MAC, VLAN (partial: `vlan:10` also finds 100), attached network / port group / bridge |
| `os:` | `os:linux` | OS name; `linux` / `windows` find every distro and version |
| `osfam:` | `osfam:windows,linux` `osfam:redhat` | OS family (same as the dashboard pie): `windows` `linux` `ubuntu` `debian` `redhat` `suse` `otherlinux` `bsd` `vmware` `macos` `other` |
| `status:` | `status:running,stopped` | running / stopped / suspended |
| `tools:` / `agent:` | `tools:none` | `running` = running; `none` = not installed or not running |
| `host:` / `node:` | `host:esx01` | ESXi host / Proxmox node |
| `cluster:` / `datastore:` | `cluster:"DC East"` `cluster:=Lab` | Quote values with spaces. A value starting with `=` is an exact match (`cluster:=Lab` does not find Lab2); `=` alone means empty (`cluster:=` = VMs without a cluster, `cluster:=,=Lab` both). A query containing `cluster:` also searches hidden clusters |
| `pool:` / `folder:` | `pool:Prod` | Resource pool (vCenter) / pool (Proxmox); VM folder (vCenter only) |
| `platform:` / `type:` / `location:` | `type:proxmox` | Platform name / type (`vcenter`, `proxmox`) / location |
| `env:` / `owner:` / `tag:` / `notes:` | `tag:critical` | Manual fields (environment, owner, tag, notes) |
| `desc:` | `desc:backup` | Platform note (vCenter annotation / Proxmox description) |
| `ptag:` | `ptag:gold` | Platform tags (vCenter REST tags / Proxmox tags) |
| **Numeric** | `ram:>=16` `cpu:>4` `disk:<100` | `> >= < <= =`; RAM / disk in GB. A bare number means exactly equal |
| **Live usage %** | `cpuuse:>=80` `ramuse:>90` `diskuse:>=85` | Latest sample; VMs without one (powered off / agentless disk) never match |
| **Exclude** | `-osfam:windows` | Prefix with `-` (or `!`) |
| **OR** | `status:running,stopped` | Comma-separated values in one field (not for numeric or none / any values) |
| **Empty / set** | `owner:none` · `-owner:none` | Field empty / field set (`ip:none`: neither a platform nor a manual IP). `yok`, `empty` and `null` work too |

Combined example: `type:proxmox status:running osfam:linux ram:>=16 -tag:test`

The **?** button next to the search box shows all of this in the app, and **every example there is clickable**. The quick-filter menus write the same syntax (choices in one menu share a comma token = OR; ⊘ / Shift+click writes `-`). The **bookmark** icon saves the search (with its sort order) to your account, and `/` focuses the search box. The query and a non-default sort are kept in the address bar (`&sort=…&order=desc`), so links can be shared; usage sorts without a column header (`cpu_usage`, `ram_usage`, `disk_usage`) show a removable **Sorted by** badge.

## 👥 Roles and permissions

| Role | Can |
|---|---|
| **Viewer** | See every screen and report |
| **Operator** | + edit notes / owner / tags / manual IP, cluster visibility and aliases, manual sync, scheduled reports |
| **Admin** | + platforms, users, audit log, sync settings |

## 🔗 LDAP / Active Directory (optional)

In `.env`:

```ini
LDAP_ENABLED=true
LDAP_SERVER=ldap://dc01.company.local
LDAP_USER_DN_TEMPLATE={username}@company.local
LDAP_DEFAULT_ROLE=viewer
```

LDAP users are created on first login (default role: viewer) and promoted from the Administration screen. The local `admin` account keeps working independently of LDAP.

## 🏭 Production notes

**HTTPS** — put a reverse proxy in front (nginx example):

```nginx
server {
    listen 443 ssl;
    server_name inventory.company.local;
    ssl_certificate     /etc/ssl/certs/inventory.crt;
    ssl_certificate_key /etc/ssl/private/inventory.key;
    location / {
        proxy_pass http://127.0.0.1:18443;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

**Backups** — two things are enough: the PostgreSQL database (`docker compose exec db pg_dump -U vminv vminventory > backup.sql`) and the `.env` file (above all `ENCRYPTION_KEY`).

**Upgrades** — pull the new version, then `docker compose up -d --build`, and Ctrl+F5 in the browser. Data lives in Docker volumes; new columns are added automatically.

**Offline / intranet** — all JavaScript, CSS and fonts are vendored (no CDN), so the UI works without internet access.

**Other** — change the PostgreSQL password in `docker-compose.yml`, tune the sync interval to your environment, and open only the chosen port in the firewall.

## 🔧 Troubleshooting

| Symptom | Fix |
|---|---|
| `Name or service not known` | Enter the API address **without** `https://` and port. If the container cannot resolve the hostname, use an IP or add `extra_hosts` to the compose file |
| `CERTIFICATE_VERIFY_FAILED` | Self-signed certificate: turn off "Verify SSL certificate" on the platform |
| Proxmox returns host names but no VMs | The token was created without `--privsep 0`. Fix: `pveum acl modify / --tokens 'user@realm!tokenname' --roles PVEAuditor` |
| `pveum user token list` fails | Pass only the user: `pveum user token list user@realm` (no `!tokenname`) |
| **"User" empty ("—") for config changes** | Proxmox config changes (RAM / CPU / network) create no task; the user comes from the cluster log → add **`Sys.Syslog`** to the token's role (Step 3). Check: `docker compose logs --since 30m \| grep "Cluster log came back EMPTY"` — if that line appears, the permission is missing |
| **User empty for a migration / clone** | The task may be outside the collection window or very old. Check the logs: `docker compose logs \| grep -iE "actor not found"` |
| **Client IP / user agent empty** | Expected — vCenter / Proxmox records do not store the operator's IP / UA. Use the in-app **Audit Log** (Administration) for that |
| **Too many console-access rows** | Turn off "Record console access in history" under Administration → Synchronization and use "Clear existing console history" |
| **Changes arrive late** | Detection delay = full sync interval. Lower it under Administration → Synchronization (3–5 min recommended); **Sync All** triggers one immediately |
| VM IPs empty | The guest needs QEMU Guest Agent / VMware Tools installed and running; list them with `ip:none`. If no agent can be installed, use the **Manual IP** field in the VM detail panel |
| OS shows "Linux (2.6+ kernel)" | No agent in that VM — Proxmox only knows the rough OS type. With an agent the full name appears ("Ubuntu 22.04.3 LTS") |
| Cluster shows **"(No cluster)"** / "—" | VMs on standalone ESXi hosts. **Clusters** (top bar) → **(No cluster)** → **Name it** gives those hosts a cluster name, or hide the group there; list them with `cluster:=` |
| Platform card shows "Error" | The card's **Sync Logs** button shows the full API error |
| Usage bars empty | Filled ~30 s after start and every `USAGE_SYNC_INTERVAL_MINUTES`; powered-off VMs have no live usage |
| UI looks old after an upgrade | Static files are versioned automatically; if it persists, press Ctrl+F5 once. If the footer version is still old, the Docker image was not rebuilt: `docker compose up -d --build` |
| `ENCRYPTION_KEY` error | `.env` needs a valid Fernet key (generator command above) |

## 📂 Project layout

```
vm-inventory/
├── app/
│   ├── main.py              # FastAPI app, page routes, startup
│   ├── config.py            # environment settings (pydantic-settings)
│   ├── database.py          # SQLAlchemy engine/session + automatic column migration
│   ├── models/              # ORM: User, Platform, Host, VM, Network, Tag, ChangeHistory, AuditLog, PhysicalDevice, …
│   ├── core/                # security (Fernet/bcrypt/CSRF), search engine, scheduler, version
│   ├── collectors/          # vmware_collector (pyVmomi), proxmox_collector (proxmoxer)
│   ├── services/            # sync (diffing, actor matching), reports (xlsx/csv/pdf), ldap
│   ├── api/                 # REST endpoints (auth, vms, hosts, clusters, platforms, physical, reports, admin, …)
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # custom.css, one JS file per page, i18n.js (TR/EN), vendor/ (no CDN)
├── tools/                   # demo_data.py (fictional inventory), screenshots.py (README images)
├── docs/screenshots/        # images used in this README
├── tests/                   # actor-detection regression suites (vmware / proxmox)
├── Dockerfile
├── docker-compose.yml       # app + PostgreSQL 16
├── requirements.txt
├── .env.example
└── CHANGELOG.md             # release history
```

## ❓ FAQ

**Does it load the live environment?** No. Every 15 minutes it makes bulk read API calls (one ContainerView on vCenter, one cluster/resources on Proxmox). User traffic never reaches the platforms.

**How fresh is the data?** The inventory is at most `SYNC_INTERVAL_MINUTES` behind (default 15 min); CPU / RAM / disk **usage** is refreshed by a separate light job every `USAGE_SYNC_INTERVAL_MINUTES` (default 3 min). **Sync All** refreshes everything immediately.

**How does hiding a cluster work?** The **Clusters** button in the top bar of the Dashboard, Virtual Machines, Snapshots and Topology pages (it shows how many are hidden) opens the visibility window, with search, **Show all** and **Only this**. A hidden cluster is left out of counts and charts and is not listed by default in the VM list, snapshot list and topology. The setting applies to **everyone** (operator and above can change it). Nothing is deleted — picking the cluster in the VM page's **Cluster** filter menu (hidden ones are marked), the "Include hidden clusters" switch, or a `cluster:` search still reaches it.

**Naming cluster-less hosts:** VMs on standalone ESXi hosts (outside any vCenter cluster) are grouped under "(No cluster)". In the visibility window, **Name it** on that row gives a name per host (or the same name to all hosts of a platform). The name is written to the host and its VMs as their cluster, so search, filters, hiding, charts, grouping and reports treat it like a real cluster (marked "alias"). The same name on several hosts merges them. If the platform later reports a real cluster for the host, **the real name wins**; if the host leaves the cluster, the alias comes back. A name given to a hidden group starts hidden. A real cluster's name cannot be used as an alias.

**How many platforms can I add?** No limit; each platform syncs independently and all of them merge into one inventory.

**Can it start / stop VMs?** No — by design. The app is read-only, which is why the platform accounts can be read-only too (Read-only / PVEAuditor).

**SQLite or PostgreSQL?** SQLite is fine for a small single-user install; PostgreSQL is recommended for teams and 500+ VMs (the Docker Compose default).

**Why is the full Linux version sometimes missing?** The exact version (e.g. "Ubuntu 24.04.1 LTS") needs **vSphere 8.0 U2+ and VMware Tools / open-vm-tools 11.2+** in the guest on VMware, and the **QEMU Guest Agent** on Proxmox. Otherwise the catalogue name ("Ubuntu Linux (64-bit)") is shown — not wrong, just without the patch level.

**vCenter tags missing?** vSphere tags cannot be read over pyVmomi / SOAP; a separate vCenter REST (vAPI tagging) session is used and the service account needs permission to read tags. If REST fails, tags stay empty and the rest of the sync is unaffected (a warning appears in the platform's Sync Logs). Proxmox tags need no extra permission.

**Can I change the sync interval from the UI?** Yes — **Administration → Synchronization** (1–1440 min), applied immediately without a restart. `SYNC_INTERVAL_MINUTES` in `.env` is only the initial default.

**Are LXC containers included?** Yes. Besides QEMU VMs, Proxmox LXC containers are collected with OS, IP (from the `interfaces` endpoint while running), disk, network and tags (no agent needed).

**Which languages does the UI support?** English and Turkish. Until you pick one, the UI follows your browser language (Turkish → Turkish, otherwise English); the language button in the top bar or on the login page switches it, and the choice is remembered per browser. Code comments, logs and release notes are in English.
