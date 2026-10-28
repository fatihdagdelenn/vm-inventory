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

Phases not yet in a release (phase 152 →; internal v1.8.1 →).

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
