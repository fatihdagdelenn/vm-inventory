/**
 * hosts.js — Host envanteri ekranı.
 *  - Arama (sunucu taraflı q) + yüklenen kümede istemci taraflı sıralama
 *  - Tüm kolon başlıkları tıklanabilir: metin (A-Z), sayısal, durum bazlı
 *  - VM sayısına tıklayınca o host'un VM'lerini gösteren modal
 *  - Modal'daki VM'e tıklayınca Sanal Makineler sayfasında detayına deep-link
 *  - Hardware brand / model can be set by hand (operator+): Proxmox cannot
 *    report the exact system model through its API (phase 152)
 */

/** Kaynak hücresi: üst satırda değer + satır içi yüzde, altında mini kullanım çubuğu.
 *  pct null ise yalnızca metin gösterilir (çubuk çizilmez). */
function resCell(topText, pct, label) {
  if (pct == null || isNaN(pct)) return '<div class="res-top">' + topText + '</div>';
  pct = Math.min(100, Math.round(pct));
  const cls = pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '';
  return '<div class="res-cell">' +
           '<div class="res-top">' + topText +
             ' <span class="res-pct">%' + pct + '</span></div>' +
           '<div class="usage-mini ' + cls + '" title="' + label + ' %' + pct + '">' +
             '<div style="width:' + pct + '%"></div></div>' +
         '</div>';
}

const Hosts = {
  items: [],            // sunucudan yüklenen ham host kayıtları
  mode: 'cards',        // cards | cluster | table
  sort: 'name',         // aktif sıralama kolonu
  order: 'asc',         // asc | desc

  setMode(mode) {
    Hosts.mode = mode;
    document.querySelectorAll('.net-modes button').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    Hosts.render();
  },

  /* ---------- Üst stat şeridi ---------- */
  renderStats() {
    const it = Hosts.items;
    const cores = it.reduce((s2, h) => s2 + (h.cpu_cores || 0), 0);
    const ram = it.reduce((s2, h) => s2 + (h.ram_total_mb || 0), 0);
    const vms = it.reduce((s2, h) => s2 + (h.vm_count || 0), 0);
    const off = it.filter(h => h.status !== 'online').length;
    const stat = (icon, val, label) =>
      '<div class="net-stat panel"><i class="bi ' + icon + '"></i>' +
      '<div><div class="net-stat-val">' + val + '</div>' +
      '<div class="net-stat-label">' + label + '</div></div></div>';
    document.getElementById('hostStats').innerHTML =
      stat('bi-hdd-rack', it.length, 'Host') +
      stat('bi-cpu', cores, t('hs.cores', 'Çekirdek')) +
      stat('bi-memory', App.fmtRam(ram), 'RAM') +
      (off
        ? stat('bi-exclamation-triangle', off, t('hs.stat.offline', 'Çevrimdışı / Bakım'))
        : stat('bi-display', vms, 'VM'));
  },

  /** IP'yi sayısal sıralanabilir bir değere çevir (10.10.9.x < 10.10.10.x). */
  ipKey(ip) {
    if (!ip) return -1;
    const parts = String(ip).split('.').map(Number);
    if (parts.length !== 4 || parts.some(isNaN)) return -1;
    return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
  },

  /** Durum sıralama rütbesi: online → maintenance → offline → diğer. */
  statusRank(s) {
    return ({online: 0, maintenance: 1, offline: 2}[s] ?? 3);
  },

  /** Açılıştan bu yana çalışma süresi (saniye); bilinmiyorsa -1 (en sona). */
  uptimeKey(iso) {
    if (!iso) return -1;
    const tm = new Date(iso).getTime();
    if (isNaN(tm)) return -1;
    return Math.max(0, Date.now() - tm);
  },

  /** Bir host kaydından aktif sıralama kolonunun karşılaştırma değerini üret. */
  sortVal(h, key) {
    switch (key) {
      case 'name':       return (h.name || '').toLowerCase();
      case 'mgmt_ip':    return Hosts.ipKey(h.mgmt_ip);
      case 'os_version': return (h.os_version || '').toLowerCase();
      case 'hw_model':   return (h.hw_model || '').toLowerCase();
      case 'cpu_model':  return (h.cpu_model || '').toLowerCase();
      case 'cpu_cores':  return h.cpu_cores || 0;
      case 'ram':        return h.ram_total_mb ? 100 * (h.ram_used_mb || 0) / h.ram_total_mb : -1;
      case 'disk':       return h.disk_total_gb ? 100 * (h.disk_used_gb || 0) / h.disk_total_gb : -1;
      case 'cluster':    return (h.cluster || '').toLowerCase();
      case 'vm_count':   return h.vm_count || 0;
      case 'uptime':     return Hosts.uptimeKey(h.last_boot);
      case 'status':     return Hosts.statusRank(h.status);
      default:           return (h.name || '').toLowerCase();
    }
  },

  /** items'ı aktif sort/order'a göre diz. Metin için locale, sayı için fark. */
  sorted() {
    const key = Hosts.sort, dir = Hosts.order === 'asc' ? 1 : -1;
    return [...Hosts.items].sort((a, b) => {
      const va = Hosts.sortVal(a, key), vb = Hosts.sortVal(b, key);
      let c;
      if (typeof va === 'string' || typeof vb === 'string')
        c = String(va).localeCompare(String(vb), 'tr');
      else c = va - vb;
      if (c === 0) c = (a.name || '').localeCompare(b.name || '', 'tr');  // sabit ikincil
      return c * dir;
    });
  },

  /** Başlıklardaki sıralama oklarını güncelle. */
  markHeaders() {
    document.querySelectorAll('#hostGroups th.sortable').forEach(th => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === Hosts.sort)
        th.classList.add(Hosts.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
    });
  },

  render() {
    const wrap = document.getElementById('hostGroups');
    if (!Hosts.items.length) {
      wrap.innerHTML = '<div class="net-empty panel"><i class="bi bi-hdd-rack"></i>' +
        '<div>' + t('vm.noResults','Sonuç bulunamadı.') + '</div></div>';
      return;
    }
    if (Hosts.mode === 'cards') Hosts.renderCards(wrap);
    else if (Hosts.mode === 'cluster') Hosts.renderClusters(wrap);
    else Hosts.renderTable(wrap);
  },

  _pIcon(h) {
    return h.platform_type === 'vcenter'
      ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
      : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
  },
  /** Hardware text + "manual" badge; for operators also an edit pencil. */
  _hwHtml(h, inCard) {
    const edit = App.role() !== 'viewer';
    const tip = h.hw_manual
      ? t('hs.hwManualTip', 'Elle girildi') + (h.hw_auto ? ' — ' + t('hs.hwDetected', 'Otomatik bulunan') + ': ' + h.hw_auto : '')
      : (h.hw_model ? t('hs.hwDetected', 'Otomatik bulunan') : '');
    const badge = h.hw_manual
      ? ' <span class="badge bg-warning-subtle text-warning-emphasis border ip-manual-badge">' +
        t('vm.ipManualBadge', 'elle') + '</span>' : '';
    if (inCard) {
      if (!h.hw_model && !edit) return '';
      if (!h.hw_model)
        return '<button type="button" class="net-chip hw-chip hw-chip-empty" onclick="Hosts.editHw(' + h.id + ')">' +
          '<i class="bi bi-plus"></i> ' + t('hs.hwAdd', 'Model ekle') + '</button>';
      const inner = App.esc(h.hw_model) + badge + (edit ? ' <i class="bi bi-pencil hw-pen"></i>' : '');
      return edit
        ? '<button type="button" class="net-chip hw-chip" title="' + App.esc(tip) + '" onclick="Hosts.editHw(' + h.id + ')">' + inner + '</button>'
        : '<span class="net-chip" title="' + App.esc(tip) + '">' + inner + '</span>';
    }
    return '<div class="hw-cell"><span title="' + App.esc(tip) + '">' + App.esc(h.hw_model || '—') + badge + '</span>' +
      (edit ? '<button type="button" class="btn btn-link btn-sm p-0 hw-edit" title="' +
        App.esc(t('hs.hwEdit', 'Donanım modelini düzenle')) + '" onclick="Hosts.editHw(' + h.id + ')">' +
        '<i class="bi bi-pencil"></i></button>' : '') + '</div>';
  },

  /** Brand / model editor (one modal, built on first use). */
  _hwModal() {
    let m = document.getElementById('hwModal');
    if (m) return m;
    m = document.createElement('div');
    m.className = 'modal fade'; m.id = 'hwModal'; m.tabIndex = -1;
    m.innerHTML =
      '<div class="modal-dialog"><div class="modal-content">' +
        '<div class="modal-header"><h5 class="modal-title"><i class="bi bi-hdd-rack"></i> ' +
          t('hs.hwEdit', 'Donanım modelini düzenle') + ' <small class="text-muted" id="hwHost"></small></h5>' +
          '<button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
        '<div class="modal-body">' +
          '<div class="hw-detected small mb-3" id="hwDetected"></div>' +
          '<div class="row g-2">' +
            '<div class="col-5"><label class="form-label small" for="hwBrand">' + t('hs.hwBrand', 'Marka') + '</label>' +
              '<input id="hwBrand" class="form-control form-control-sm" maxlength="64" placeholder="Dell Inc."></div>' +
            '<div class="col-7"><label class="form-label small" for="hwModelIn">' + t('hs.hwModelName', 'Model') + '</label>' +
              '<input id="hwModelIn" class="form-control form-control-sm" maxlength="128" placeholder="PowerEdge R650"></div>' +
          '</div>' +
          '<div class="form-text mt-2">' + t('hs.hwHelp',
            'Proxmox tam modeli API ile bildirmez. Sunucuda "dmidecode -s system-product-name" çıktısını yazabilirsiniz. ' +
            'Boş bırakıp kaydederseniz otomatik bulunan değere dönülür.') + '</div>' +
        '</div>' +
        '<div class="modal-footer">' +
          '<button type="button" class="btn btn-outline-secondary btn-sm me-auto" id="hwReset">' +
            '<i class="bi bi-arrow-counterclockwise"></i> ' + t('hs.hwUseAuto', 'Otomatiğe dön') + '</button>' +
          '<button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">' + t('action.cancel', 'İptal') + '</button>' +
          '<button type="button" class="btn btn-primary btn-sm" id="hwSave">' + t('action.save', 'Kaydet') + '</button>' +
        '</div>' +
      '</div></div>';
    document.body.appendChild(m);
    m.querySelector('#hwSave').addEventListener('click', () => Hosts.saveHw(false));
    m.querySelector('#hwReset').addEventListener('click', () => Hosts.saveHw(true));
    m.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') Hosts.saveHw(false); });
    return m;
  },

  editHw(id) {
    const h = Hosts.items.find(x => x.id === id);
    if (!h) return;
    const m = Hosts._hwModal();
    Hosts._hwId = id;
    m.querySelector('#hwHost').textContent = h.name;
    m.querySelector('#hwDetected').innerHTML = h.hw_auto
      ? '<i class="bi bi-cpu"></i> ' + t('hs.hwDetected', 'Otomatik bulunan') + ': <strong>' + App.esc(h.hw_auto) + '</strong>'
      : '<i class="bi bi-question-circle"></i> ' + t('hs.hwNone', 'Platform bu host için model bildirmedi.');
    // Pre-fill: the manual value, else the detected split - so the typical
    // fix is just correcting "Rx5xx" to "R650".
    m.querySelector('#hwBrand').value = h.hw_manual ? h.hw_manual_brand : (h.hw_brand || '');
    m.querySelector('#hwModelIn').value = h.hw_manual ? h.hw_manual_model : (h.hw_name || '');
    m.querySelector('#hwReset').classList.toggle('d-none', !h.hw_manual);
    const modal = bootstrap.Modal.getOrCreateInstance(m);
    m.addEventListener('shown.bs.modal', () => m.querySelector('#hwModelIn').focus(), {once: true});
    modal.show();
  },

  async saveHw(clear) {
    const m = document.getElementById('hwModal');
    const body = clear ? {brand: '', model: ''}
      : {brand: m.querySelector('#hwBrand').value.trim(), model: m.querySelector('#hwModelIn').value.trim()};
    const h = Hosts.items.find(x => x.id === Hosts._hwId);
    // Saving the untouched detected value would only pin it - treat as no-op.
    if (!clear && h && !h.hw_manual && body.brand === (h.hw_brand || '') && body.model === (h.hw_name || '')) {
      bootstrap.Modal.getOrCreateInstance(m).hide();
      return;
    }
    let res;
    try {
      res = await App.api('/api/hosts/' + Hosts._hwId + '/hardware', {method: 'PUT', body});
    } catch (e) { return; }
    const i = Hosts.items.findIndex(x => x.id === Hosts._hwId);
    if (i >= 0) Hosts.items[i] = Object.assign({}, Hosts.items[i], res);
    bootstrap.Modal.getOrCreateInstance(m).hide();
    App.toast(clear ? t('hs.hwCleared', 'Otomatik bulunan değere dönüldü')
                    : t('hs.hwSaved', 'Donanım modeli kaydedildi'), 'success');
    Hosts.render();
  },

  _vmCell(h) {
    return h.vm_count
      ? '<button type="button" class="vm-count-link" onclick="Hosts.showVms(' + h.id + ')" ' +
        'title="' + (h.vm_running || 0) + ' ' + t('hs.runningOpen','çalışıyor — VM listesini aç') + '">' +
        h.vm_count + ' <i class="bi bi-box-arrow-up-right"></i></button>'
      : '<span class="badge text-bg-light border">0</span>';
  },

  /* ---------- Kart görünümü (varsayılan) ---------- */
  renderCards(wrap) {
    wrap.innerHTML = '<div class="net-cards host-cards">' + Hosts.sorted().map(h => {
      const ramPct = h.ram_total_mb ? 100 * (h.ram_used_mb || 0) / h.ram_total_mb : null;
      const cpuPct = (h.cpu_usage_pct != null) ? h.cpu_usage_pct : null;
      const diskPct = h.disk_total_gb ? 100 * (h.disk_used_gb || 0) / h.disk_total_gb : null;
      return '<div class="net-card panel host-card">' +
        '<div class="net-card-head">' +
          '<span class="net-card-name" title="' + App.esc(h.name) + '">' + Hosts._pIcon(h) + ' ' + App.esc(h.name) + '</span>' +
          App.stateBadge(h.status) +
        '</div>' +
        '<div class="net-card-meta">' +
          (h.cluster ? '<span class="net-chip"><i class="bi bi-diagram-3"></i> ' + App.esc(h.cluster) + '</span>' : '') +
          (h.mgmt_ip ? '<span class="net-chip mono">' + App.esc(h.mgmt_ip) + '</span>' : '') +
          Hosts._hwHtml(h, true) +
        '</div>' +
        resCell((h.cpu_cores || '—') + ' ' + t('hs.coresLower','çekirdek'), cpuPct, 'CPU') +
        resCell(App.fmtRam(h.ram_used_mb) + ' / ' + App.fmtRam(h.ram_total_mb), ramPct, 'RAM') +
        (h.disk_total_gb ? resCell(App.fmtGb(h.disk_used_gb) + ' / ' + App.fmtGb(h.disk_total_gb), diskPct, 'Disk') : '') +
        '<div class="net-card-foot">' +
          '<span class="small text-muted">VM ' + Hosts._vmCell(h) + '</span>' +
          '<span class="small text-muted">' + App.fmtUptime(h.last_boot) + '</span>' +
        '</div>' +
        '<div class="net-card-platform">' + App.esc(h.platform || '') + '</div>' +
      '</div>';
    }).join('') + '</div>';
  },

  /* ---------- Cluster akordeonu ---------- */
  renderClusters(wrap) {
    const groups = {};
    Hosts.sorted().forEach(h => {
      const k = (h.cluster || '').trim() || t('nt.noCluster','(cluster atanmamış)');
      (groups[k] = groups[k] || []).push(h);
    });
    const keys = Object.keys(groups).sort((a, b) => a.localeCompare(b, 'tr'));
    const open = keys.length === 1 ? ' open' : '';
    wrap.innerHTML = keys.map(k => {
      const list = groups[k];
      const cores = list.reduce((s2, h) => s2 + (h.cpu_cores || 0), 0);
      const ram = list.reduce((s2, h) => s2 + (h.ram_total_mb || 0), 0);
      const vms = list.reduce((s2, h) => s2 + (h.vm_count || 0), 0);
      return '<details class="net-group panel"' + open + '>' +
        '<summary>' +
          '<span class="net-group-title"><i class="bi bi-diagram-3"></i> ' + App.esc(k) + '</span>' +
          '<span class="net-group-meta">' + cores + ' ' + t('hs.coresLower','çekirdek') +
            ' · ' + App.fmtRam(ram) + ' · ' + vms + ' VM</span>' +
          '<span class="net-group-count">' + list.length + '</span>' +
        '</summary>' +
        '<div class="table-responsive">' + Hosts._tableHtml(list, false) + '</div>' +
      '</details>';
    }).join('');
  },

  /* ---------- Tablo modu (tüm kolonlar + sıralama) ---------- */
  renderTable(wrap) {
    wrap.innerHTML = '<div class="card panel"><div class="table-responsive">' +
      Hosts._tableHtml(Hosts.sorted(), true) + '</div></div>';
    wrap.querySelectorAll('th.sortable').forEach(th => {
      th.style.cursor = 'pointer';
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (Hosts.sort === col) Hosts.order = Hosts.order === 'asc' ? 'desc' : 'asc';
        else { Hosts.sort = col; Hosts.order = 'asc'; }
        Hosts.render();
      });
    });
    Hosts.markHeaders();
  },

  _tableHtml(list, sortable) {
    const th = (label, key) => sortable
      ? '<th data-sort="' + key + '" class="sortable">' + label + '</th>'
      : '<th>' + label + '</th>';
    return '<table class="table table-hover align-middle mb-0" id="hostTable"><thead><tr>' +
      th(t('hs.name','Host Adı'), 'name') + th(t('hs.mgmtIp','Yönetim IP'), 'mgmt_ip') +
      th(t('vm.os','İşletim Sistemi'), 'os_version') + th(t('hs.hwModel','Donanım'), 'hw_model') +
      th(t('hs.cpuModel','CPU Modeli'), 'cpu_model') + th(t('hs.cores','Çekirdek'), 'cpu_cores') +
      th('RAM', 'ram') + th('Disk', 'disk') + th('Cluster', 'cluster') +
      th('VM', 'vm_count') + th('Uptime', 'uptime') + th(t('th.status','Durum'), 'status') +
      '</tr></thead><tbody>' + list.map(h => {
      const ramPct = h.ram_total_mb ? 100 * (h.ram_used_mb || 0) / h.ram_total_mb : null;
      const cpuPct = (h.cpu_usage_pct != null) ? h.cpu_usage_pct : null;
      const diskPct = h.disk_total_gb ? 100 * (h.disk_used_gb || 0) / h.disk_total_gb : null;
      return '<tr>' +
        '<td>' + Hosts._pIcon(h) + ' <strong>' + App.esc(h.name) + '</strong>' +
          '<br><small class="text-muted">' + App.esc(h.platform) + '</small></td>' +
        '<td>' + App.esc(h.mgmt_ip || '—') + '</td>' +
        '<td class="small">' + App.esc(h.os_version || '—') + '</td>' +
        '<td class="small">' + Hosts._hwHtml(h, false) + '</td>' +
        '<td class="small">' + App.esc(h.cpu_model || '—') + '</td>' +
        '<td>' + resCell((h.cpu_cores || '—') + ' ' + t('hs.coresLower','çekirdek'), cpuPct, 'CPU') + '</td>' +
        '<td>' + resCell(App.fmtRam(h.ram_used_mb) + ' / ' + App.fmtRam(h.ram_total_mb), ramPct, 'RAM') + '</td>' +
        '<td>' + resCell(h.disk_total_gb ? App.fmtGb(h.disk_used_gb) + ' / ' + App.fmtGb(h.disk_total_gb) : '—', diskPct, 'Disk') + '</td>' +
        '<td>' + App.esc(h.cluster || '—') + '</td>' +
        '<td>' + Hosts._vmCell(h) + '</td>' +
        '<td class="small text-nowrap">' + App.fmtUptime(h.last_boot) + '</td>' +
        '<td>' + App.stateBadge(h.status) + '</td></tr>';
    }).join('') + '</tbody></table>';
  },

  async load(q = '') {
    let data;
    try { data = await App.api('/api/hosts?q=' + encodeURIComponent(q)); } catch (e) { return; }
    Hosts.items = data.items || [];
    Hosts.renderStats();
    Hosts.render();
  },

  /** VM sayısına tıklanınca: ortak VM-listesi modalı (App.hostVms). */
  showVms(hostId) { App.hostVms(hostId); },

  /** (geriye dönük uyumluluk) modaldaki VM → ortak offcanvas. */
  openVm(vmId) { App.openVmFromModal(vmId); },
};

(function () {
  const input = document.getElementById('hostSearch');
  input.addEventListener('input', App.debounce(() => Hosts.load(input.value.trim()), 300));

  // Görünüm modu düğmeleri (Kartlar / Cluster'a göre / Tablo). Tablo
  // başlıklarının sıralama dinleyicileri renderTable içinde bağlanır.
  document.querySelectorAll('.net-modes button').forEach(b =>
    b.addEventListener('click', () => Hosts.setMode(b.dataset.mode)));

  Hosts.load();
})();
