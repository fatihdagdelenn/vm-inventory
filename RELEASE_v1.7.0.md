# v1.7.0 — Fiziksel envanter, disk ve uptime doğruluğu, geriye dönük geçmiş

**v1.2.0'dan beri ilk yayınlanan release.** Aradaki 30 geliştirme adımı (faz112–faz140)
bu sürümde toplanıyor. Tüm şema değişiklikleri **otomatik** uygulanır (`ensure_schema`)
— manuel migration gerekmez.

## Öne çıkanlar

| | |
|---|---|
| 🏢 **Fiziksel Envanter (yeni sayfa)** | Sanallaştırma dışı donanım: fiziksel sunucu, storage, SAN switch, yedekleme ünitesi. Lokasyon, yönetim IP, iLO/BMC IP, marka, model, seri no, CPU, RAM, rol. Alanlar cihaz tipine göre değişir; sanallaştırma host'ları buraya salt-okunur akar ve elle girdiğiniz alanlar senkronizasyonda korunur |
| ⏱️ **Göç-farkında uptime** | Proxmox'un uptime sayacı canlı göçte sıfırlanıyordu (bugzilla #499) — 60 günlük misafir 20 gün görünüyordu. Gerçek misafir uptime'ı mümkünse QEMU ajanından okunur, değilse boot zamanı göç boyunca taşınır. Uptime artık sıralanabilir ve raporlarda var |
| 💾 **Disk boyutu artık donmuyor** | Disk toplamı ile disk listesi kilitli adım ilerliyor. Önceden toplam korunur, liste korunmazdı → 40→75 GB değişikliği Geçmiş'e doğru işlenirken liste 100 GB'da kalabiliyordu. Yöneticiler için tutarsızlık tarayan `disk-diag` ucu eklendi |
| 💽 **Disk disk görünürlük** | Çok diskli VM'lerde her diskin boyutu ayrı listelenir; export'ta ayrı **"Diskler"** sayfası (disk başına bir satır) — 16 diskli VM'lerde tabloyu şişirmiyor |
| 🕵️ **Geçmişte geriye gidebilmek** | Tarih aralığı filtresi (yerel saat, bitiş günü dahil) + 7g/30g/90g hızlı aralıkları + gerçek SQL sayfalama. Arayüzdeki 200 kayıt tavanı kaldırıldı; arşivin tamamı gezilebilir |
| 📄 **Raporlama elden geçti** | Kapsam seçici (VM / Host / Datastore / Fiziksel / **Tüm Envanter**), biçim düğmeleri, bağlama duyarlı filtre. VM export'una tahsis **ve** kullanım kolonları (CPU/RAM/disk), **Pool** ve Çalışma Süresi eklendi |
| ⏰ **Zamanlanmış raporlar** | Beş kapsamın tamamı, gerçek saat seçici (saat–dakika karışıklığı giderildi), hedef etiketleri. Üretilmiş dosyalar listesi 20 ile sınırlandı + dosya başına silme ve toplu temizlik |
| 📸 **Snapshot kartı dürüstleşti** | Tüm snapshot'lar listelenir, yaş filtresi (Tümü / 7+ / 14+ / 30+) kullanıcıda. Boş kart artık nedenini söylüyor: "daha yeniler var" / "hepsi taze" / "hiç yok" |
| 🗄️ **Datastore'lar & Host'lar** | Ortak tasarım dili, kart/tip/node/tablo görünümleri, **yerel diskleri gizle** filtresi, çok-cluster'lı paylaşımlı depolarda kapasite çakışma uyarısı, son yedek yaşı rozeti |
| 👤 **Hesap bazlı arayüz** | Dashboard yerleşimi ve topoloji düğüm konumları artık sunucuda, hesabınıza bağlı saklanıyor — tarayıcı değiştirince kaybolmuyor |
| 🏷️ **Sekme simgesi** | SVG favicon; oturum kapalıyken de görünür |

## Düzeltmeler

- Proxmox uptime saat dilimi hatası (`utcnow().timestamp()` → `time.time()`)
- Koyu temada disk listesi okunamıyordu; mini kart değerleri beyaz-üstü-beyaz kalıyordu
- Snapshot kartında "Tümü" seçilemiyordu (`parseInt("0")` falsy → sessizce 30+ seçiliyordu)
- Fiziksel envanterde cihaz tipi artık **zorunlu** — yanlış tipe kaydedilen cihazın
  listede "kaybolması" sınıfı hata kaynağında kapatıldı
- Platform silmede FK sırası, senkronizasyonda FK-güvenli VM silme
- Değişiklik Geçmişi aktör doğruluğu: vCenter guest-shutdown olay çifti, PVE `resize`
  görev tipi, 5000 satırlık cluster-log penceresi. İki platform için kalıcı regresyon testleri

## Dürüst sınırlar (bilerek böyle)

- **Disk kullanımı disk başına alınamıyor** — vCenter de Proxmox da yalnız VM geneli
  toplam veriyor. Disk *boyutu* disk başına var, *kullanım* yok; arayüzde böyle etiketli.
- **Tam Proxmox donanım modeli API'de yok.** Tavan, pci.ids jenerik dizesi
  (ör. "Dell Inc. PowerEdge Rx5xx"). Kesin model için iDRAC/Redfish gerekir.
  Yanlış gelen marka/model artık elle düzeltilebilir.
- **Ajan okuması her yerde mümkün değil:** RHEL türevi misafirlerde `guest-file-open`
  varsayılan olarak kapalı. O durumda uptime göç-taşıma yöntemiyle korunur.
- Geçmiş'teki "işlemi yapan" (kullanıcı/sistem) filtresi SQL'e birebir çevrilemiyor;
  20.000 satır tarar ve sınıra takılırsa sonucu `capped` bayrağıyla **açıkça işaretler**.
- Yedekler yalnız Proxmox/PBS (vCenter'ın yedek API'si yok).

## Güncelleme

```bash
cd vm-inventory
git pull
docker compose up -d --build
```

Şema değişiklikleri açılışta otomatik uygulanır. Proxmox tarafında agent durumu /
misafir IP / disk kullanımı için token rolünde **`VM.Monitor`**, config değişikliklerinin
kullanıcısı için **`Sys.Syslog`** gerekir (ayrıntı: README).

**Tam liste:** [CHANGELOG.md](CHANGELOG.md) · **Karşılaştırma:** `v1.2.0...v1.7.0`
