<div align="center">

# 🖥️ VM Envanter Yönetim Sistemi

**VMware vCenter ve Proxmox VE ortamlarınızı tek panelden izleyin**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Lisans](https://img.shields.io/badge/Arayüz-Türkçe-red)](#)

*500+ VM ve 20+ host ölçeğinde milisaniye hızında arama — tüm veriler lokal cache'den, canlı API çağrısı yok.*

</div>

---

## 📑 İçindekiler

- [Ne İşe Yarar?](#-ne-i̇şe-yarar)
- [Özellikler](#-özellikler)
- [Mimari: Nasıl Çalışır?](#-mimari-nasıl-çalışır)
- [Gereksinimler](#-gereksinimler)
- [Kurulum (Adım Adım)](#-kurulum-adım-adım)
- [İlk Yapılandırma](#-i̇lk-yapılandırma)
- [Kullanım Kılavuzu](#-kullanım-kılavuzu)
- [Arama Söz Dizimi](#-arama-söz-dizimi)
- [Roller ve Yetkiler](#-roller-ve-yetkiler)
- [LDAP / Active Directory](#-ldap--active-directory-opsiyonel)
- [Üretim Ortamı Notları](#-üretim-ortamı-notları)
- [Sorun Giderme](#-sorun-giderme)
- [Proje Yapısı](#-proje-yapısı)
- [SSS](#-sss)

---

## 🎯 Ne İşe Yarar?

Birden fazla **VMware vCenter** ve **Proxmox VE** ortamı işleten ekipler için merkezi envanter:

> *"10.10.10.15 IP'li makine hangi host'ta?"* — *"VLAN 100'de kaç Windows sunucu var?"* — *"Geçen hafta hangi VM'lerin RAM'i değişti?"* — *"Agent kurulu olmayan VM'ler hangileri?"*

Bu soruların hepsi tek arama kutusundan, saniyeden kısa sürede yanıtlanır. SSH erişimi veya misafir ajan dağıtımı **gerekmez** — yalnızca platformların resmî API'leri kullanılır.

## ✨ Özellikler

| | |
|---|---|
| 🔍 **Google benzeri arama** | `ip:` `os:` `vlan:` `cluster:` `ram:>=16` `-tag:test` `ip:yok` … kriterler birleştirilebilir |
| 🎛️ **Gelişmiş filtre paneli** | Mevcut değerlerden (sayılarıyla) seçim, X'le kaldırılabilir filtre rozetleri, tıklanabilir tablo hücreleri |
| 📊 **Detaylı dashboard** | Kaynak toplamları, OS/ortam/cluster dağılımları, host CPU-RAM grafikleri, depolama, "dikkat gerektirenler" |
| 🔗 **Çoklu platform** | Sınırsız sayıda vCenter + Proxmox (QEMU VM **ve LXC konteyner**) aynı envanterde |
| 📄 **Raporlama** | Filtrelenmiş Excel / CSV / PDF; her gün otomatik üretilen zamanlanmış raporlar |
| 🕓 **Değişiklik takibi** | Her senkronizasyonda fark analizi: ne, ne zaman, neyden neye değişti |
| 👁️ **Cluster göster/gizle** | Eski/test cluster'ları — standalone host'lardaki "(Cluster'sız)" VM'ler dahil — dashboard sayılarından tek anahtarla çıkarın; veri silinmez |
| ⚡ **Anlık kullanım oranları** | VM ve host CPU/RAM kullanımı + gerçek disk doluluğu (thin-provision farkındalıklı); hafif görevle ~3 dk'da bir ve her açılışta tazelenir |
| 🐧 **Tam OS sürümü** | VMware'de ayrıntılı misafir OS verisi (ör. *"Ubuntu 24.04.1 LTS"*) — vSphere 8.0 U2+ ve VMware Tools 11.2+ ile; Proxmox'ta QEMU Guest Agent ile |
| 🆔 **VM ID & çalışma süresi** | VM ID (Proxmox sayısal / VMware MoRef) ve host+VM **uptime** kolonları; host'larda CPU/RAM/Disk kullanım çubukları |
| 🗂️ **Pool / klasör / etiket** | vCenter resource pool & klasör, Proxmox pool; platform etiketleri (vCenter REST tag / Proxmox tags) — hepsi aranır, filtrelenir ve gösterilir |
| 🧰 **Kolon seçici** | VM listesinde görünür kolonları tek menüden seçme (tercih tarayıcıda hatırlanır) |
| 👥 **Rol bazlı yetki** | Admin / Operatör / Görüntüleyici + opsiyonel LDAP/AD girişi |
| 🏷️ **Manuel zenginleştirme** | VM'lere not, sahip, ortam ve etiket atama; ayrıca platformdan gelen açıklama (vCenter annotation / Proxmox description) "Platform Notu" olarak gösterilir |
| 🔐 **Güvenlik** | Fernet ile şifreli kimlik bilgisi saklama, bcrypt, CSRF koruması, kayan oturum (son hareketten itibaren zaman aşımı), audit log |
| 🇹🇷 **Türkçe** | Arayüz ve kod yorumları tamamen Türkçe |

## 🏗 Mimari: Nasıl Çalışır?

```
┌─────────────┐   zamanlanmış görevler     ┌──────────────────┐
│  vCenter(s) │◄──────(APScheduler)────────┤                  │
└─────────────┘     15 dk'da bir,          │     FastAPI      │
┌─────────────┐     pyVmomi/proxmoxer      │   + SQLAlchemy   │──► PostgreSQL
│ Proxmox(es) │◄───────────────────────────┤                  │    (lokal cache)
└─────────────┘                            └────────┬─────────┘
                                                    │  tüm aramalar lokal DB'den
                                             ┌──────▼─────────┐
                                             │  Bootstrap 5   │
                                             │  + Chart.js    │
                                             └────────────────┘
```

**Temel ilke:** Kullanıcı aramaları **asla** vCenter/Proxmox'a gitmez.

1. **Toplayıcı** — Arka plandaki zamanlayıcı her 15 dakikada (ayarlanabilir) tüm platformlara bağlanır. vCenter'da `ContainerView` ile tek seferde toplu okuma, Proxmox'ta tek `cluster/resources` çağrısı yapılır — host/VM başına ayrı istek atılmaz.
2. **Cache** — VM adı, IP, MAC, OS, CPU/RAM/disk, VLAN, cluster, güç durumu, Tools/Agent durumu… hepsi indeksli tablolara yazılır. Önceki kayıtla fark varsa **Değişiklik Geçmişi**'ne işlenir.
3. **Arayüz** — Aramalar, raporlar ve grafikler lokal veritabanından sunulur; 500+ VM'de dahi anlık yanıt verir. "Tümünü Yenile" butonu acil durumda anında senkronizasyon tetikler.

## 📋 Gereksinimler

| Bileşen | Gereksinim |
|---|---|
| Sunucu | Linux (Ubuntu 22.04+ önerilir), 2 vCPU / 2 GB RAM yeterli |
| Yazılım | Docker + Docker Compose **veya** Python 3.11+ |
| Ağ | Sunucudan vCenter'a `443/tcp`, Proxmox'a `8006/tcp` erişimi |
| vCenter | 6.7+ (8.x test edildi) — salt-okunur hesap yeterli |
| Proxmox | 7.x / 8.x — `PVEAuditor` rollü API token yeterli |
| Misafirler | IP/OS detayı için: VMware Tools veya QEMU Guest Agent *(opsiyonel)* |

## 🚀 Kurulum (Adım Adım)

### Yöntem A — Docker Compose (önerilen)

**1. Projeyi indirin**

```bash
git clone https://github.com/fatihdagdelenn/vm-inventory.git
cd vm-inventory
```

**2. Ortam dosyasını oluşturun**

```bash
cp .env.example .env
```

**3. Güvenlik anahtarlarını üretin** ve `.env` içine yapıştırın:

```bash
# ENCRYPTION_KEY için (platform parolalarını şifreler):
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# SECRET_KEY için (oturum çerezlerini imzalar):
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` dosyanız şöyle görünmeli:

```ini
SECRET_KEY=ürettiğiniz-secret-key
ENCRYPTION_KEY=ürettiğiniz-fernet-anahtarı
SYNC_INTERVAL_MINUTES=15
USAGE_SYNC_INTERVAL_MINUTES=3
SESSION_TIMEOUT_MINUTES=480
APP_TIMEZONE=Europe/Istanbul
```

> ⚠️ **ENCRYPTION_KEY'i yedekleyin!** Bu anahtar kaybedilirse kayıtlı platform parolaları/token'ları çözülemez ve yeniden girilmesi gerekir.

**4. (İsteğe bağlı) Portu değiştirin** — `docker-compose.yml` içinde:

```yaml
    ports:
      - "18443:8000"     # dış port : konteyner portu (sadece soldakini değiştirin)
```

**5. Başlatın**

```bash
docker compose up -d --build
```

İlk build 2-3 dakika sürer. Durumu izlemek için: `docker compose logs -f app`

**6. Giriş yapın** — Tarayıcıda `http://sunucu-adresi:8000` (veya seçtiğiniz port)

> 🔑 Varsayılan giriş: **admin / admin123**

### Yöntem B — Manuel Kurulum (Docker'sız)

```bash
# Python 3.11+ ve venv gerekir (sistem paketleriyle çakışmayı önler)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # anahtarları yukarıdaki gibi üretin
# Küçük kurulumlar için SQLite yeterli; .env içinde:
#   DATABASE_URL=sqlite:///./data/vminventory.db
mkdir -p data/reports

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PostgreSQL kullanacaksanız önce veritabanını hazırlayın:

```sql
CREATE USER vminv WITH PASSWORD 'guclu_parola';
CREATE DATABASE vminventory OWNER vminv;
```

ve `.env`'de: `DATABASE_URL=postgresql+psycopg2://vminv:guclu_parola@localhost:5432/vminventory`

Tablolar ilk açılışta otomatik oluşturulur, migration gerekmez.

## ⚙️ İlk Yapılandırma

### Adım 1 — Admin parolasını değiştirin

**Yönetim → Kullanıcılar** sekmesinden `admin` kullanıcısını düzenleyip yeni parola verin.

### Adım 2 — vCenter ekleyin

Önce vCenter tarafında salt-okunur servis hesabı açın *(önerilen — kişisel hesap kullanmayın)*:

1. vSphere Client → **Administration → Users and Groups** → yeni kullanıcı: `svc-envanter@vsphere.local`
2. **Administration → Global Permissions** → bu kullanıcıya **Read-only** rolü verin, *"Propagate to children"* işaretli olsun

Sonra envanter arayüzünde **Platformlar → Platform Ekle**:

| Alan | Değer |
|---|---|
| Tip | VMware vCenter |
| API Adresi | `vcenter.sirket.local` veya IP — **https:// ve port olmadan** |
| Port | `443` |
| Kullanıcı / Parola | servis hesabı bilgileri |
| SSL doğrula | self-signed sertifikada **kapalı** |

**Bağlantıyı Test Et** → başarılıysa **Kaydet**.

### Adım 3 — Proxmox ekleyin

Proxmox node'unda (SSH veya web Shell) API token üretin:

```bash
pveum user add svc-envanter@pve --comment "Envanter servis hesabı"
pveum acl modify / --users svc-envanter@pve --roles PVEAuditor
pveum user token add svc-envanter@pve envanter --privsep 0
```

> ⚠️ Son komutun çıktısındaki **`value`** satırını hemen kaydedin — bir daha gösterilmez!


> ⚠️ `--privsep 0` zorunludur; verilmezse token VM'leri göremez (sadece node adları gelir).

Arayüzde **Platformlar → Platform Ekle**:

| Alan | Değer |
|---|---|
| Tip | Proxmox VE |
| API Adresi | herhangi bir node'un adresi (cluster verisi tek node'dan gelir) |
| Port | `8006` |
| Kimlik doğrulama | **API Token** |
| Token adı | `svc-envanter@pve!envanter` |
| Token değeri | kaydettiğiniz `value` |

### Adım 4 — İlk senkronizasyon

Platform kartındaki **"Senkronize Et"** butonuna basın. Arka planda çalışır, arayüz kilitlenmez; ortam büyüklüğüne göre 1-5 dakika sürer. Tamamlanınca Dashboard ve VM listesi dolar. Sonrası otomatiktir (15 dk'da bir).

### Adım 5 — (Önerilen) Misafir ajanlarını kontrol edin

Dashboard'daki **"Dikkat Gerektirenler"** kartından *"Agent/Tools kurulu olmayan"* listesine bakın. Bu VM'lerin IP'si ve gerçek OS adı alınamaz:

- **vCenter VM'leri** → VMware Tools / open-vm-tools kurun
- **Proxmox VM'leri** → `apt install qemu-guest-agent` + VM Options'ta *QEMU Guest Agent: Enabled* + VM'i yeniden başlatın

## 📖 Kullanım Kılavuzu

| Ekran | Ne yapılır? |
|---|---|
| **Dashboard** | Genel durum: sayılar, kaynak toplamları, grafikler (dilime tıklayınca filtreli liste açılır), son değişiklikler, platform sağlığı. Cluster grafiğindeki **Yönet** butonu görünürlük ayarlarını açar |
| **Sanal Makineler** | Arama + gelişmiş filtre + gruplama. CPU/RAM/disk kolonlarında anlık kullanım çubukları (sarı %75+, kırmızı %90+); ayrıca VM ID, Pool, Klasör, Tags ve Uptime kolonları. **Kolonlar** menüsünden görünür sütunları seçebilirsiniz (tercih tarayıcıda saklanır). Satıra tıklayınca detay paneli; not/sahip/etiket buradan düzenlenir. Host/cluster/VLAN/pool/klasör hücreleri tıklanabilir filtredir |
| **Host'lar** | ESXi/PVE node'ları: CPU modeli, CPU/RAM/Disk kullanım çubukları, çalışma süresi (uptime), VM sayısı |
| **Ağlar** | Port group / bridge / SDN vnet ve host fiziksel kartları (NIC). Açılır-kapanır gruplama: Host'a göre, Cluster'a göre, VLAN'a göre veya Fiziksel Kartlar; ad/VLAN/vSwitch/subnet/MAC araması |
| **Raporlar** | Anlık Excel/CSV/PDF (filtre destekler) + her gün belirli saatte çalışan zamanlanmış raporlar (`data/reports/` klasörüne yazılır) |
| **Geçmiş** | Envanter değişiklikleri: eklenen/silinen VM'ler, alan bazında eski→yeni değerler |
| **Platformlar** | Bağlantı yönetimi, manuel senkronizasyon, API hata logları |
| **Yönetim** *(admin)* | Kullanıcı CRUD + audit log (kim, ne zaman, ne yaptı) |

## 🔍 Arama Söz Dizimi

| Sözdizimi | Örnek | Açıklama |
|---|---|---|
| serbest metin | `web01` | Ad, VM ID, IP, MAC, OS, cluster, sahip, notlar, platform notu, pool, klasör ve platform etiketlerinde arar |
| `ip:` | `ip:10.10.10.` | IP'ye göre (kısmi eşleşir) |
| `mac:` | `mac:00:50:56` | MAC'e göre |
| `os:` | `os:linux` | OS ailesi — Ubuntu/CentOS/RHEL/Debian… hepsini bulur |
| `osfam:` | `osfam:windows` `osfam:other` | Tek bir OS ailesi (dashboard pastası ve filtre menüsüyle aynı) |
| `vmid:` / `id:` | `vmid:100` | VM ID (Proxmox sayısal / VMware MoRef) |
| `vlan:` / `host:` / `node:` | `vlan:100` | Altyapı konumuna göre |
| `cluster:` / `datastore:` | `cluster:"Ankara Prod"` | Boşluklu değerler tırnaklanır |
| `status:` | `status:running` | running / stopped / suspended (TR: `çalışan`, `kapalı`) |
| `tag:` / `env:` / `owner:` | `tag:kritik` | Manuel alanlara göre |
| `pool:` / `havuz:` | `pool:Prod` | Resource pool (vCenter) / pool (Proxmox) |
| `folder:` / `klasor:` | `folder:Web` | VM klasörü (vCenter); Proxmox'ta yok |
| `ptag:` / `petiket:` | `ptag:kritik` | Platform etiketleri (vCenter REST tag / Proxmox tags) |
| `aciklama:` / `desc:` | `aciklama:bakım` | Platform notu (vCenter annotation / Proxmox description) |
| `platform:` / `type:` / `location:` | `type:proxmox` | Platforma göre |
| `tools:` | `tools:yok` | Agent/Tools kurulu olmayanlar |
| **Sayısal** | `ram:>=16` `cpu:>4` `disk:<100` | Karşılaştırma (RAM/disk GB) |
| **Dışlama** | `-os:windows` | Önüne `-` koyulan dışlanır |
| **VEYA** | `os:windows,linux` | Virgülle çoklu değer |
| **Boş alan** | `ip:yok` `tag:yok` | Alanı boş olanlar |

Birleştirme örneği: `cluster:production os:linux status:running ram:>=16 -tag:test`

Arama kutusundaki **?** butonu bu tabloyu arayüzde gösterir. Sorgu adres çubuğuna yansır — linki kopyalayıp paylaşabilirsiniz.

## 👥 Roller ve Yetkiler

| Rol | Yetkiler |
|---|---|
| **Görüntüleyici** | Tüm ekranları ve raporları görüntüleme |
| **Operatör** | + Not/sahip/etiket düzenleme, manuel senkronizasyon, zamanlanmış rapor |
| **Admin** | + Platform yönetimi, kullanıcı yönetimi, audit log |

## 🔗 LDAP / Active Directory (opsiyonel)

`.env` dosyasına:

```ini
LDAP_ENABLED=true
LDAP_SERVER=ldap://dc01.sirket.local
LDAP_USER_DN_TEMPLATE={username}@sirket.local
LDAP_DEFAULT_ROLE=viewer
```

LDAP kullanıcıları ilk girişte otomatik oluşturulur (varsayılan rol: viewer); rolleri Yönetim ekranından yükseltilir. Lokal `admin` hesabı LDAP'tan bağımsız çalışmaya devam eder.

## 🏭 Üretim Ortamı Notları

**HTTPS** — Uygulamanın önüne reverse proxy koyun (nginx örneği):

```nginx
server {
    listen 443 ssl;
    server_name envanter.sirket.local;
    ssl_certificate     /etc/ssl/certs/envanter.crt;
    ssl_certificate_key /etc/ssl/private/envanter.key;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

**Yedekleme** — İki şey yeterli: PostgreSQL veritabanı (`docker compose exec db pg_dump -U vminv vminventory > yedek.sql`) ve `.env` dosyası (özellikle `ENCRYPTION_KEY`).

**Güncelleme** — Yeni sürümü açın, ardından `docker compose up -d --build`; tarayıcıda Ctrl+F5. Veriler volume'lerde korunur.

**Diğer** — `docker-compose.yml` içindeki PostgreSQL parolasını değiştirin; senkronizasyon aralığını ortamınıza göre ayarlayın (`SYNC_INTERVAL_MINUTES`); güvenlik duvarında yalnızca seçtiğiniz portu açın.

## 🔧 Sorun Giderme

| Belirti | Çözüm |
|---|---|
| `Name or service not known` | API adresini `https://` ve port **olmadan** yazın. Hostname konteynerden çözülemiyorsa IP kullanın veya compose'a `extra_hosts` ekleyin |
| `CERTIFICATE_VERIFY_FAILED` | Self-signed sertifika: platformda "SSL doğrula" anahtarını kapatın |
| Proxmox sadece host adları geliyor, VM yok | Token `--privsep 0` ile üretilmemiş. Çözüm: `pveum acl modify / --tokens 'kullanici@realm!tokenadi' --roles PVEAuditor` |
| `pveum user token list` çalışmıyor | Komuta yalnızca kullanıcıyı verin: `pveum user token list kullanici@realm` (`!tokenadi` kısmı yazılmaz) |
| VM IP'leri boş | Misafirde QEMU Guest Agent / VMware Tools kurulu ve çalışır olmalı. `ip:yok` aramasıyla eksikleri listeleyin |
| OS "Linux (2.6+ çekirdek)" görünüyor | O VM'de agent yok — Proxmox yalnızca kaba OS tipini bilir. Agent kurulunca tam ad gelir ("Ubuntu 22.04.3 LTS" gibi) |
| Cluster kolonu boş | Eski sürüm davranışı; güncel sürümde cluster adı (tek node'da node adı) otomatik atanır. Senkronize edin |
| Platform kartında "Hata" | Karttaki **Loglar** butonu API hatasının tam mesajını gösterir |
| Cluster grafiğinde "—" görünüyor | Cluster'a bağlı olmayan (standalone host) VM'lerdir. Yönet modalındaki **(Cluster'sız)** anahtarıyla gizlenebilir; `cluster:yok` aramasıyla listelenir |
| Kullanım çubukları boş | Veri açılıştan ~30 sn sonra ve her `USAGE_SYNC_INTERVAL_MINUTES` aralığında dolar. Kapalı VM'lerde çubuk çizilmez (anlık kullanım yoktur) |
| Güncelleme sonrası arayüz eski görünüyor | Statik dosyalar otomatik sürümlenir; sorun sürerse bir kez Ctrl+F5 yapın |
| `ENCRYPTION_KEY` hatası | `.env`'de geçerli bir Fernet anahtarı olmalı (üretme komutu yukarıda) |
| cryptography ImportError (host'ta) | Sistem paketi bozuk; anahtar üretiminde `base64+os.urandom` komutunu kullanın veya venv açın |

## 📂 Proje Yapısı

```
vm-inventory/
├── app/
│   ├── main.py              # FastAPI uygulaması, sayfa rotaları, başlangıç
│   ├── config.py            # Ortam değişkenleri (pydantic-settings)
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models/              # ORM: User, Platform, Host, VM, Network, Tag, ChangeHistory, AuditLog
│   ├── core/                # security (Fernet/bcrypt/CSRF), search (sorgu motoru), scheduler
│   ├── collectors/          # vmware_collector (pyVmomi), proxmox_collector (proxmoxer)
│   ├── services/            # sync (fark analizi), report (xlsx/csv/pdf), ldap
│   ├── api/                 # REST endpoint'leri (auth, vms, hosts, platforms, reports, admin…)
│   ├── templates/           # Jinja2 HTML şablonları (Türkçe arayüz)
│   └── static/              # custom.css + sayfa başına JS
├── Dockerfile
├── docker-compose.yml       # app + PostgreSQL 16
├── requirements.txt
├── .env.example
└── docs/dokumantasyon.html  # bu dokümanın HTML sürümü
```

## ❓ SSS

**Canlı ortama yük bindirir mi?** Hayır. 15 dakikada bir, toplu-okuma API çağrıları yapılır (vCenter'da tek ContainerView, Proxmox'ta tek cluster/resources). Kullanıcı trafiği platformlara hiç ulaşmaz.

**Verileri ne kadar güncel?** Envanter en fazla `SYNC_INTERVAL_MINUTES` kadar geride (varsayılan 15 dk); CPU/RAM/disk **kullanım oranları** ise ayrı hafif bir görevle `USAGE_SYNC_INTERVAL_MINUTES` aralığında (varsayılan 3 dk) tazelenir. "Tümünü Yenile" ile her şey anında güncellenir.

**Cluster gizleme nasıl çalışır?** Dashboard'da cluster grafiğinin yanındaki **Yönet** butonundan istediğiniz cluster'ı kapatın: sayılara/grafiklere girmez, VM listesinde varsayılan görünmez. Veri silinmez — gelişmiş paneldeki "gizli cluster'ları dahil et" kutusu veya doğrudan `cluster:` araması yine erişir; anahtarı açınca her şey geri gelir.

**Kaç platform eklenebilir?** Sınır yok; her platform bağımsız senkronize edilir, hepsi aynı envanterde birleşir.

**VM'lere müdahale edebilir mi (başlat/durdur)?** Hayır — bu bilinçli bir tasarım kararı. Sistem salt-okunur çalışır; bu yüzden platform hesapları da salt-okunur (Read-only / PVEAuditor) olabilir.

**SQLite mi PostgreSQL mi?** Tek kullanıcılı küçük kurulumda SQLite yeterli; ekip kullanımı ve 500+ VM için PostgreSQL önerilir (Docker Compose varsayılanı).

**Linux VM'lerinin tam sürümü neden bazen gelmiyor?** Tam sürüm (ör. "Ubuntu 24.04.1 LTS") VMware'de **vSphere 8.0 U2+ ve misafirde VMware Tools / open-vm-tools 11.2+** gerektirir; Proxmox'ta ise **QEMU Guest Agent**. Bunlar yoksa katalog adı ("Ubuntu Linux (64-bit)") gösterilir — yanlış değil, yalnızca yama sürümü içermez.

**vCenter etiketleri (Tags) gelmiyor?** vSphere etiketleri pyVmomi/SOAP ile alınamaz; ayrı bir vCenter REST (vAPI tagging) oturumu kullanılır. Servis hesabının etiketleri okuma yetkisi olmalı. REST erişimi başarısız olursa etiketler boş kalır, senkronizasyonun geri kalanı etkilenmez (Platform → Loglar'da uyarı görünür). Proxmox etiketleri (VM `tags` alanı) için ek yetki gerekmez.

**LXC konteynerleri görünüyor mu?** Evet. Proxmox QEMU VM'lerinin yanı sıra LXC konteynerleri de toplanır; OS, IP (çalışırken `interfaces` ucundan), disk, ağ ve etiketleri envantere girer (konteynerlerde agent gerekmez).
