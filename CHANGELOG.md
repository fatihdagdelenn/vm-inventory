# Değişiklik Günlüğü (Changelog)

Bu projedeki tüm önemli değişiklikler bu dosyada belgelenir.
Sürümleme [Semantic Versioning](https://semver.org/lang/tr/) yaklaşımını izler.

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
Ayrıntılı özellik listesi için `README.md` ve `docs/dokumantasyon.html`.
