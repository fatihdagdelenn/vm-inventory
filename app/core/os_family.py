"""
İşletim sistemi ailesi sınıflandırması (tek doğruluk kaynağı).

Hem dashboard OS pastası hem de VM sayfasındaki "İşletim Sistemi" filtre
menüsü buradan beslenir. Her ailenin tıklama/seçim sorgusu tek bir `osfam:<key>`
token'ıdır; arama motoru (core/search.py) bu token'ı buradaki anahtar
kelimelere göre SQL koşuluna çevirir. Böylece grafikteki/menüdeki sayı ile
filtreye tıklayınca gelen liste her zaman birebir aynıdır.

Sıra önemlidir: bir guest_os İLK eşleşen aileye atanır. Her ailenin koşulu,
kendisinden ÖNCEKİ ailelerin anahtar kelimelerini dışlar — böylece SQL filtresi
"ilk eşleşen kazanır" mantığını birebir yeniden üretir.
"""

# (key, etiket, anahtar kelimeler [küçük harf])
FAMILIES = [
    ("windows",    "Windows",            ["windows", "w2k"]),
    ("ubuntu",     "Ubuntu",             ["ubuntu"]),
    ("debian",     "Debian",             ["debian"]),
    ("redhat",     "Red Hat / CentOS",   ["rhel", "red hat", "redhat", "centos",
                                          "rocky", "almalinux", "alma", "fedora",
                                          "oracle linux"]),
    ("suse",       "SUSE",               ["suse", "sles"]),
    ("otherlinux", "Diğer Linux",        ["linux", "l26", "l24"]),
    ("bsd",        "BSD / Solaris",      ["bsd", "solaris", "openindiana",
                                          "aix", "unix"]),
    ("vmware",     "VMware / Appliance", ["vmware", "esxi", "photon"]),
    ("macos",      "macOS",              ["mac os", "macos", "darwin", "os x"]),
]

CATCHALL_KEY = "other"
CATCHALL_LABEL = "Diğer / Bilinmiyor"

LABELS = {k: lbl for k, lbl, _kw in FAMILIES}
LABELS[CATCHALL_KEY] = CATCHALL_LABEL


def classify(guest_os: str) -> str:
    """guest_os -> aile key'i (ilk eşleşen); eşleşme yoksa CATCHALL_KEY."""
    s = (guest_os or "").lower()
    for key, _label, kws in FAMILIES:
        if any(k in s for k in kws):
            return key
    return CATCHALL_KEY


def match_keywords(key: str):
    """
    Bir aile key'i için (include, exclude) anahtar kelime listeleri döndür.
    - include: bu aileyi seçen kelimeler (CATCHALL için None = "hepsi")
    - exclude: kendisinden önceki ailelerin kelimeleri (ilk-eşleşen mantığı)
    Bilinmeyen key için (None, None) döner.
    """
    key = (key or "").lower()
    before = []
    for idx, (k, _label, kws) in enumerate(FAMILIES):
        if k == key:
            return list(kws), list(before)
        before.extend(kws)
    if key == CATCHALL_KEY:
        return None, before          # hiçbir aileye uymayan (boş OS dahil)
    return None, None                # bilinmeyen key


def distribution(rows):
    """
    rows: (guest_os, count) ikilileri.
    Dönüş: sayıya göre azalan [{key, label, count, query}] listesi.
    query, tek token'lık `osfam:<key>` filtresidir.
    """
    agg = {}
    for os_name, count in rows:
        agg[classify(os_name)] = agg.get(classify(os_name), 0) + count
    out = [{"key": k, "label": LABELS.get(k, k), "count": c,
            "query": f"osfam:{k}"} for k, c in agg.items()]
    out.sort(key=lambda x: x["count"], reverse=True)
    return out
