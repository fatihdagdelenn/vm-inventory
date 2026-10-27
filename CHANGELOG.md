# Değişiklik Günlüğü (Changelog)

Bu projedeki tüm önemli değişiklikler bu dosyada belgelenir.
Sürümleme [Semantic Versioning](https://semver.org/lang/tr/) yaklaşımını izler.

### Sürümleme & release politikası

- **Faz sürümü** (`app/core/version.py`, footer'da görünür) her fazda artar; bu
  *dahili* bir damgadır, release değildir.
- **Release** = bu dosyadaki bir `## [vX.Y.Z]` bölümü + aynı adda **git tag** +
  GitHub release. Bu üçü birbirinden ayrılmaz; biri varsa üçü de olmalı.
  Release notu (`RELEASE_vX.Y.Z.md`) yalnız GitHub'a yapıştırılır, repoya
  **commit'lenmez** (`.gitignore`'da).
- **Ne zaman release?** Şu üçünden biri olduğunda: *(a)* son tag'den beri **10+ faz**
  birikti, *(b)* **yeni bir sayfa / yeni bir veri kaynağı** eklendi, *(c)* kullanıcıyı
  etkileyen **kırıcı bir değişiklik** veya veri göçü var. Takvim değil, birikim belirler.
- **Numaralandırma:** yeni sayfa veya belirgin yetenek → minor (`1.6` → `1.7`);
  yalnız düzeltme/iyileştirme → patch. Dahili faz damgaları release numarası ile
  aynı olmak zorunda değildir; her bölümün alt başlığı hangi dahili aralığı
  kapsadığını yazar.
- Her bölüm **dürüst sınırları** da yazar — bir şeyin platform yüzünden
  yapılamadığı, yapılabilmiş gibi görünmesin.

---

## [Yayınlanmamış]

Henüz release'e girmemiş fazlar (faz142–; dahili v1.7.1 →).

### 🏷️ Cluster'sız host'lara takma ad (faz149)
- Standalone ESXi host'ların (platform cluster bildirmiyor) VM'leri tek bir
  "(Cluster'sız)" grubunda toplanıyordu ve Sanal Makineler'deki Cluster
  menüsünde hiç görünmüyordu. Artık menüde **(Cluster'sız)** seçeneği var
  (yeni sözdizimi `cluster:=` = cluster'ı boş; `cluster:=,=Lab` ile birleşir).
- Görünürlük penceresinde **Ad ver**: host bazında (platform başlığında
  "Tümüne aynı ad") takma ad. Ad senkronda host'a ve VM'lerine cluster olarak
  yazılır (`cluster_is_alias` işaretiyle), kaydedince beklemeden uygulanır;
  arama, filtre, gizleme, dashboard grafikleri, gruplama, raporlar ve
  topoloji onu normal bir cluster olarak görür. Listelerde "takma ad" etiketi.
- **Platform kazanır:** host için gerçek bir cluster bildirildiğinde o ad
  kullanılır; host cluster'dan çıkarsa takma ad geri gelir. Takma ad
  Değişiklik Geçmişi'ne "cluster değişti" gürültüsü yazmaz (denetim kaydı yazılır).
- Gizli "(Cluster'sız)" grubuna (ya da gizli eski bir ada) verilen yeni ad
  **gizli başlar** — ad vermek grubu habersizce dashboard'a geri getirmez.
  Gerçek bir cluster adı takma ad olarak kullanılamaz (409). Artık kullanılmayan
  takma adın görünürlük kaydı silinir. Platform silinince kuralları da silinir.
- **Düzeltme:** dashboard'daki en çok CPU/RAM/Disk ve datastore kartları veri
  boşken tarayıcı konsoluna hata yazıyordu (renk fonksiyonu); giderildi.

### 👁 Cluster görünürlüğü her yerden (faz148)
- Cluster gizle/göster ayarı yalnızca dashboard'daki cluster grafiğinin "Yönet"
  düğmesinde kalıyordu. Artık **Dashboard, Sanal Makineler, Snapshot'lar ve
  Topoloji** sayfalarının üst çubuğunda **Cluster'lar** düğmesi var (gizli varsa
  turuncu "N gizli" rozetiyle). Ortak bileşen: `static/js/clusters.js`.
- Pencere geliştirildi: arama (8+ cluster'da), **Tümünü göster**, satır başına
  **Yalnız bu** (o cluster görünür, diğerleri gizli), "N görünür · N gizli"
  özeti, ayarın herkes için geçerli olduğu notu; görüntüleyici rolünde salt okunur.
  Her anahtarda sayfa yenilenmiyor — değişiklikler kaydedilir, sayfa pencere
  kapanınca bir kez tazelenir (VM sayfasında yeniden yükleme yok, liste yerinde
  güncellenir).
- **Sanal Makineler'e Cluster filtre menüsü:** araç çubuğunun başında, çoklu
  seçim, VM sayıları, gizli cluster'lar "gizli" işaretli (seçilirse yine
  listelenir), altta "Görünürlük" kısayolu. Gelişmiş paneldeki cluster seçimi bu
  menüye taşındı. Tablo hücresi ve grup kartı tıklamaları da aynı tam eşleşmeyi
  kullanır.
- **Yeni arama sözdizimi — tam eşleşme:** `=` ile başlayan değer alanın tamamıyla
  eşleşir (`cluster:=Lab`, Lab2'yi bulmaz); virgül ve tırnakla birleşir
  (`cluster:"=Ankara Prod,=Lab"`). Kısmi eşleşme varsayılan olarak aynen duruyor.
- Toplu görünürlük uç noktası: `POST /api/clusters/visibility/bulk`
  (`all` / `only` / `names`); her değişen cluster için ayrı denetim kaydı,
  değişmeyenler için kayıt yazılmaz.
- **Güvenlik düzeltmesi:** `POST /api/clusters/visibility` CSRF doğrulaması
  yapmıyordu (diğer tüm yazma uçları yapıyor); eklendi.

### 🧹 Sanal Makineler araç çubuğu sadeleşti (faz147)
- faz146'nın 14 çipi + sayıları + grup etiketleri tablodan önce 3 satır
  tutuyordu. Artık **tek satır**: Durum · Platform · OS · Eksikler · Kullanım
  birer **açılır menü** (onay kutulu, sayılı, çoklu seçim; ⊘ veya Shift+tık
  hariç tutar, menü altında "Temizle"). Düğme seçimi özetler
  ("Durum: Çalışan +1"); hariç tutulan kırmızı görünür. Menü seçim sırasında
  açık kalır. Davranış ve sorgu sözdizimi faz146 ile aynı.
- **Kolonlar** ve **Dışa aktar** (Excel/CSV/PDF tek menüde) filtre satırından
  çıkıp tablonun başlığına, sonuç sayısının yanına taşındı.
- **Düzeltme:** koyu temada tüm sayfalardaki açılır kutuların (select) ok
  simgesi görünmüyordu; geri geldi.

### 🔍 Sanal Makineler filtreleri (faz146)
- **Hızlı filtreler çoklu seçimli:** önceden bir çipe basmak aramanın tamamını
  değiştiriyordu. Artık çipler gruplu (Durum · Platform · OS · Eksikler · Kullanım)
  ve aç/kapa çalışıyor: aynı gruptakiler VEYA (Çalışan + Kapalı =
  `status:running,stopped`), farklı gruplar VE ile birleşir. **Shift+tık hariç
  tutar** (kırmızı, `-alan:değer`). Çipler arama kutusundan türetilir; elle
  yazılan sorgu da çiplerde görünür.
- Her çipte o filtrenin tek başına döndürdüğü **VM sayısı** (gizli cluster
  kuralı listeyle aynı). Yeni çipler: Askıda, VMware, Proxmox, Sahipsiz,
  Etiketsiz, CPU %80+, RAM %80+, Disk %85+.
- **Kayıtlı aramalar** (yer imi simgesi): sorgu + sıralama ada bağlanıp hesaba
  kaydedilir, her cihazdan açılır; listede güncel VM sayısı görünür.
- **Gelişmiş panel arama kutusuyla senkron:** çip ya da elle yazımla değişen
  durum/cluster/host… seçimleri panelde de görünür (önceden eski seçim kalıyordu).
- **Arama söz dizimi yardımı baştan yazıldı:** kurallar kartları, gruplu tam alan
  listesi (takma adlar dahil), değer sözlüğü, ipuçları; 43 örneğin her biri
  tıklanınca uygulanır. `/` tuşu arama kutusuna odaklanır.
- **Yeni arama alanları:** `cpuuse:` `ramuse:` `diskuse:` (anlık kullanım %).
- **Düzeltme:** `osfam:` virgülle VEYA desteklemiyordu (`osfam:windows,ubuntu`
  sessizce serbest metne düşüp hiçbir şey bulmuyordu); artık çalışıyor ve
  `osfam:linux` tüm Linux ailelerini kapsıyor. `tools:yok,running` da artık
  doğru VEYA'lanıyor.

### 📊 En çok kaynak kullanan VM kartları (faz145)
- CPU / RAM / Disk kartlarında bar üzerine gelince VM adının altında artık
  **VM'in IP'si** (birden fazlaysa `+N`, elle girilmişse "elle") ve ardından bağlı
  olduğu **host** görünüyor. Önceden yalnız host vardı.
- Bara tıklamak artık Sanal Makineler sayfasını **çalışan VM'ler, aynı metriğe
  göre büyükten küçüğe sıralı** açıyor ve tıklanan VM'in satırını vurguluyor
  (önceden yalnız o VM'in adıyla arama yapıyordu). Kart ile liste aynı SQL
  ifadesiyle sıralandığı için ilk satırlar karttaki sırayla birebir aynıdır.
- VM listesine kullanım sıralamaları eklendi (`sort=cpu_usage|ram_usage|disk_usage`);
  ölçümü olmayan VM'ler her iki yönde de sona düşer. Etkin olduğunda X'le
  kaldırılabilen bir **Sıralama** rozeti görünür; varsayılan dışı sıralama
  adres çubuğuna yazılır, sayfa yenilense de korunur.
- Bar üzerinde el imleci çıkıyor (tıklanabilir olduğu belli).

### 📸 Dashboard snapshot kartı (faz144)
- **Düzeltme:** Kart "0/1 — Hiç snapshot yok" gösterirken Snapshot'lar sayfası
  snapshot'ı listeliyordu. Sebep: kart en fazla 1000 kayıt alıyor, gizli cluster
  filtresini ise **bu 1000'i aldıktan sonra** uyguluyordu. Gizli (ör. cluster'sız
  Veeam replica restore point'leri) 1000+ snapshot olunca pencere tamamen onlarla
  doluyor, görünür snapshot dışarıda kalıyordu. Filtre artık limitten önce, SQL'de
  uygulanıyor; liste de limitten önce en eskiden yeniye sıralanıyor.
- **Düzeltme:** "30 günden eski snapshot" sayacı gizli cluster'ları da sayıyordu
  (tıklanınca açılan sayfa saymıyordu). Artık ikisi aynı kuralı kullanıyor.

### ✍️ Elle IP (faz143)
- Agent kurulamayan VM'ler için (özel/kapalı yapılandırılmış OS) VM detayındaki
  **Manuel Bilgiler** bölümüne **Elle IP** alanı eklendi. Birden fazla IP virgül,
  noktalı virgül veya boşlukla girilebilir; geçersiz adres reddedilir, `/24` gibi
  önek atılır.
- Elle IP; VM listesinin IP kolonunda **"elle"** rozetiyle, VM detayında, host /
  datastore VM listelerinde, topolojide ve Excel/CSV/PDF dışa aktarımlarında görünür.
- Arama: `ip:` ve serbest metin elle IP'yi de bulur; `manuelip:var` elle IP
  girilmiş VM'leri listeler. `ip:yok` ve dashboard'daki "IP adresi alınamayan VM"
  sayacı artık elle IP'si olanları saymaz (ikisi aynı kuralı kullanır).
- **Platform her zaman kazanır:** agent kurulup IP bildirdiğinde elle IP otomatik
  temizlenir; silinen değer Değişiklik Geçmişi'nde "Elle IP" satırı olarak kalır.
  Platform zaten IP bildiren bir VM'e elle IP girilemez (alan kilitli, API 409).
- **Düzeltme:** Proxmox'ta canlı migration sonrası VM yeni node'da yeni kayıt olarak
  oluştuğu için **sahip, notlar, ortam ve etiketler kayboluyordu**. Artık bu manuel
  alanlar (elle IP dahil) yeni kayda taşınıyor. Daha önce migration'da kaybolmuş
  değerler geri gelmez.

### 🧹 Repo (faz142)
- Commit'lenmiş `RELEASE_v1.7.0.md` kaldırıldı; `RELEASE_*.md` `.gitignore`'a eklendi.

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
