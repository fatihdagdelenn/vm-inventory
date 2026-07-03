/**
 * app.js — Tüm sayfalarda kullanılan ortak yardımcılar.
 *  - App.api()   : CSRF header'ı otomatik ekleyen fetch sarmalayıcı
 *  - App.toast() : Bootstrap toast bildirimi
 *  - App.syncAll : "Tümünü Yenile" butonu (toplu veri yenileme)
 *  - Biçimlendirme yardımcıları (RAM, disk, tarih, durum rozeti)
 */
const App = {

  /** Çerezden değer oku (CSRF token için). */
  getCookie(name) {
    const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return m ? decodeURIComponent(m.pop()) : '';
  },

  /**
   * API çağrısı sarmalayıcı.
   * GET dışındaki isteklerde X-CSRF-Token header'ı otomatik eklenir.
   * Hata durumunda sunucudan gelen "detail" mesajı toast olarak gösterilir.
   */
  async api(url, options = {}) {
    options.headers = Object.assign({'Content-Type': 'application/json'}, options.headers);
    const method = (options.method || 'GET').toUpperCase();
    if (method !== 'GET') {
      options.headers['X-CSRF-Token'] = App.getCookie('csrf_token');
    }
    if (options.body && typeof options.body !== 'string') {
      options.body = JSON.stringify(options.body);
    }
    const res = await fetch(url, options);
    if (res.status === 401) {            // oturum süresi doldu → girişe yönlendir
      location.href = '/login';
      throw new Error('Oturum süresi doldu');
    }
    if (!res.ok) {
      let msg = 'İstek başarısız (' + res.status + ')';
      try { msg = (await res.json()).detail || msg; } catch (e) { /* gövde yoksa */ }
      App.toast(msg, 'danger');
      throw new Error(msg);
    }
    return res.json();
  },

  /** Bootstrap toast bildirimi göster. type: success | danger | info | warning */
  toast(message, type = 'success') {
    const wrap = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + type + ' border-0';
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + App.esc(message) +
      '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    wrap.appendChild(el);
    const t = new bootstrap.Toast(el, {delay: 4000});
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  },

  /** "Tümünü Yenile": tüm platformlar için arka plan senkronizasyonu tetikler. */
  async syncAll(btn) {
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Başlatılıyor…';
    try {
      const r = await App.api('/api/platforms/sync-all', {method: 'POST'});
      App.toast(r.message || 'Senkronizasyon başlatıldı', 'info');
    } catch (e) { /* hata zaten gösterildi */ }
    btn.disabled = false;
    btn.innerHTML = original;
  },

  /* ---------- Biçimlendirme yardımcıları ---------- */

  /** HTML kaçış — XSS koruması için tüm kullanıcı/API verisi bununla yazdırılır. */
  esc(s) {
    return String(s ?? '').replace(/[&<>"']/g,
      c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  },

  /** MB cinsinden RAM'i okunaklı yaz (örn: 16 GB). */
  fmtRam(mb) {
    if (!mb) return '—';
    return mb >= 1024 ? (mb / 1024).toFixed(mb % 1024 ? 1 : 0) + ' GB' : mb + ' MB';
  },

  /** GB cinsinden diski okunaklı yaz. */
  fmtGb(gb) {
    if (gb == null || gb === 0) return '—';
    return gb >= 1024 ? (gb / 1024).toFixed(1) + ' TB' : Math.round(gb) + ' GB';
  },

  /** ISO tarihi yerel TR biçiminde göster (UTC -> APP_TZ). */
  fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    return d.toLocaleString('tr-TR', {day: '2-digit', month: '2-digit', year: 'numeric',
                                      hour: '2-digit', minute: '2-digit',
                                      timeZone: window.APP_TZ || 'Europe/Istanbul'});
  },

  /** Açılış zamanından (ISO) canlı çalışma süresi: "12 gün 4 sa" / "3 sa 20 dk".
   *  Açılış bilgisi yoksa veya gelecekteyse "—". Senkronizasyondan bağımsız
   *  olarak her sayfa açılışında güncel hesaplanır (now - boot). */
  fmtUptime(iso) {
    if (!iso) return '—';
    const boot = new Date(iso);
    if (isNaN(boot)) return '—';
    let s = Math.floor((Date.now() - boot.getTime()) / 1000);
    if (s < 0) return '—';
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600);  s -= h * 3600;
    const m = Math.floor(s / 60);
    if (d > 0) return d + ' ' + t('unit.dayShort','gün') + ' ' + h + ' ' + t('unit.hr','sa');
    if (h > 0) return h + ' ' + t('unit.hr','sa') + ' ' + m + ' ' + t('unit.min','dk');
    return m + ' ' + t('unit.min','dk');
  },

  /** Güç/erişim durumu için renkli rozet üret. */
  stateBadge(state) {
    const map = {
      running:   [t('st.running','Çalışıyor'),  'state-running'],
      stopped:   [t('st.stopped','Kapalı'),     'state-stopped'],
      suspended: [t('st.suspended','Askıda'),   'state-suspended'],
      online:    ['Online',     'state-online'],
      offline:   ['Offline',    'state-offline'],
      maintenance: [t('st.maintenance','Bakımda'),  'state-suspended'],
      unknown:   [t('st.unknown','Bilinmiyor'), 'state-stopped'],
    };
    const [label, cls] = map[state] || [state || '—', 'state-stopped'];
    return '<span class="state-badge ' + cls + '">' + App.esc(label) + '</span>';
  },

  /** Kullanım yüzdesine göre renklenen ilerleme çubuğu. */
  usageBar(pct) {
    pct = Math.min(100, Math.round(pct || 0));
    const cls = pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '';
    return '<div class="usage-bar ' + cls + '" title="%' + pct + '">' +
           '<div class="usage-fill" style="width:' + pct + '%"></div>' +
           '<span>%' + pct + '</span></div>';
  },

  /** Basit debounce — arama kutularında gereksiz istekleri önler. */
  debounce(fn, ms = 300) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  },

  /* ---------- Ortak VM detay paneli (offcanvas) ----------
   * Hem Sanal Makineler hem Host'lar sayfası aynı paneli kullanır; panel
   * markup'ı base.html'dedir. opts.onSaved: manuel bilgiler kaydedildikten
   * sonra çağrılır (örn. listeyi tazelemek için). */
  _vmDetailId: null,
  _vmDetailOnSaved: null,

  async vmDetail(id, opts = {}) {
    let v;
    try { v = await App.api('/api/vms/' + id); } catch (e) { return; }
    App._vmDetailId = id;
    App._vmDetailOnSaved = opts.onSaved || null;
    document.getElementById('vmDetailTitle').textContent = v.name;

    const row = (label, value) =>
      '<div class="detail-row"><span class="detail-label">' + label + '</span>' +
      '<span class="detail-value">' + (value || '—') + '</span></div>';
    const disks = (v.disks || []).map(d =>
      App.esc(d.label || d.name || 'disk') + ': ' + App.fmtGb(d.size_gb)).join('<br>') || '—';

    const canEdit = document.querySelector('.role-badge')?.textContent.trim() !== 'Görüntüleyici';

    const agentMap = {running: ['Çalışıyor', 'text-bg-success'],
                      stopped: ['Kurulu, durmuş', 'text-bg-warning text-dark'],
                      none: ['Kurulu değil', 'text-bg-secondary']};
    const ab = agentMap[v.agent_state] || ['—', 'text-bg-light text-dark border'];
    const agentBadge = '<span class="badge ' + ab[1] + '">' + ab[0] + '</span>';

    const snapAge = a => {
      if (a == null) return '';
      let c = 'text-bg-light text-dark border';
      if (a >= 30) c = 'text-bg-danger'; else if (a >= 14) c = 'text-bg-warning text-dark';
      else if (a >= 7) c = 'text-bg-info text-dark';
      return ' <span class="badge ' + c + '">' + a + ' gün</span>';
    };
    const snapHtml = (v.snapshots && v.snapshots.length)
      ? '<h6 class="mb-2 mt-1"><i class="bi bi-camera"></i> Snapshot\'lar (' + v.snapshots.length + ')</h6>' +
        '<div class="mb-3 small">' + v.snapshots.map(s =>
          '<div class="d-flex justify-content-between align-items-center border-bottom py-1 gap-2">' +
          '<span>' + App.esc(s.name) +
            (s.is_current ? ' <span class="badge text-bg-success">aktif</span>' : '') +
            (s.parent ? ' <small class="text-muted">← ' + App.esc(s.parent) + '</small>' : '') + '</span>' +
          '<span class="text-muted text-nowrap">' + (s.created_at ? App.fmtDate(s.created_at) : '') +
            snapAge(s.age_days) + '</span></div>').join('') + '</div>'
      : '';

    document.getElementById('vmDetailBody').innerHTML =
      '<div class="d-flex align-items-center gap-2 mb-3">' + App.stateBadge(v.power_state) +
      '<span class="badge text-bg-light border">' + App.esc(v.platform) + '</span></div>' +
      '<div class="detail-grid">' +
      row('VM ID', App.esc(v.vmid)) +
      row('IP Adresleri', App.esc(v.ip_addresses).split(',').join('<br>')) +
      row('MAC Adresleri', App.esc(v.mac_addresses).split(',').join('<br>')) +
      row(t('vm.dns','DNS Sunucuları'), App.esc(v.dns_servers).split(',').join('<br>')) +
      row('İşletim Sistemi', App.esc(v.guest_os)) +
      row('Çekirdek / Mimari',
          [App.esc(v.kernel), App.esc(v.arch)].filter(Boolean).join(' · ') || '—') +
      row('CPU', (v.cpu_count || '—') +
          (v.cpu_usage_pct != null ? ' <small class="text-muted">(anlık %' +
           Math.round(v.cpu_usage_pct) + ')</small>' : '')) +
      row('RAM', App.fmtRam(v.ram_mb) +
          (v.ram_usage_mb ? ' <small class="text-muted">(anlık ' +
           App.fmtRam(v.ram_usage_mb) + ')</small>' : '')) +
      row('Diskler', disks +
          (v.disk_used_gb ? '<br><small class="text-muted">Gerçek kullanım: ' +
           App.fmtGb(v.disk_used_gb) + '</small>' : '')) +
      row('Host', App.esc(v.host)) +
      row('Cluster', App.esc(v.cluster)) +
      row('Pool', App.esc(v.pool)) +
      row('Klasör', App.esc(v.folder)) +
      row('Datastore', App.esc(v.datastore)) +
      row('VLAN', App.esc(v.vlans)) +
      row('Ağlar', App.esc(v.networks)) +
      row('Oluşturulma', App.fmtDate(v.created_date)) +
      row('Son Açılış', App.fmtDate(v.last_boot)) +
      row('Çalışma Süresi', App.fmtUptime(v.last_boot)) +
      row('Tools / Agent', agentBadge) +
      row('Platform Notu', App.esc(v.guest_notes).split('\n').join('<br>')) +
      row('Tags', v.platform_tags
        ? v.platform_tags.split(',').map(t => t.trim()).filter(Boolean).map(t =>
            '<span class="badge bg-info-subtle text-info-emphasis border me-1">' + App.esc(t) + '</span>').join('')
        : '—') +
      row('Son Güncelleme', App.fmtDate(v.updated_at)) +
      '</div>' + snapHtml + '<hr>' +
      '<h6 class="mb-3"><i class="bi bi-pencil-square"></i> Manuel Bilgiler</h6>' +
      '<div class="mb-2"><label class="form-label small">Sahip</label>' +
      '<input id="vmdOwner" class="form-control form-control-sm" value="' + App.esc(v.owner) + '"' + (canEdit ? '' : ' disabled') + '></div>' +
      '<div class="mb-2"><label class="form-label small">Ortam</label>' +
      '<select id="vmdEnv" class="form-select form-select-sm"' + (canEdit ? '' : ' disabled') + '>' +
      ['production', 'test', 'development'].map(e =>
        '<option value="' + e + '"' + (v.environment === e ? ' selected' : '') + '>' +
        e.charAt(0).toUpperCase() + e.slice(1) + '</option>').join('') + '</select></div>' +
      '<div class="mb-2"><label class="form-label small">Etiketler (virgülle ayırın)</label>' +
      '<input id="vmdTags" class="form-control form-control-sm" value="' +
      App.esc(v.tags.map(t => t.name).join(', ')) + '"' + (canEdit ? '' : ' disabled') + '></div>' +
      '<div class="mb-3"><label class="form-label small">Notlar</label>' +
      '<textarea id="vmdNotes" class="form-control form-control-sm" rows="3"' + (canEdit ? '' : ' disabled') + '>' +
      App.esc(v.notes) + '</textarea></div>' +
      (canEdit ? '<button class="btn btn-primary btn-sm" onclick="App.saveVmMeta()">' +
                 '<i class="bi bi-check-lg"></i> Kaydet</button>' : '');

    bootstrap.Offcanvas.getOrCreateInstance(document.getElementById('vmDetail')).show();
  },

  /** Manuel alanları kaydet (PATCH — operator+). Kaydedince onSaved tetiklenir. */
  async saveVmMeta() {
    const payload = {
      owner: document.getElementById('vmdOwner').value,
      environment: document.getElementById('vmdEnv').value,
      notes: document.getElementById('vmdNotes').value,
      tags: document.getElementById('vmdTags').value.split(',').map(s => s.trim()).filter(Boolean),
    };
    try {
      await App.api('/api/vms/' + App._vmDetailId, {method: 'PATCH', body: payload});
      App.toast('VM bilgileri güncellendi');
      if (typeof App._vmDetailOnSaved === 'function') App._vmDetailOnSaved();
    } catch (e) { /* hata gösterildi */ }
  },

  /* ===== Ortak drill-down modalları (Host'lar + Datastore'lar) ===== */
  /** VM dizisini ortak VM-listesi modalında göster; satır → VM detayı. */
  showVmList(title, vms) {
    document.getElementById('hostVmsTitle').textContent = title;
    const body = document.getElementById('hostVmsBody');
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('hostVmsModal'));
    modal.show();
    if (!vms || !vms.length) {
      body.innerHTML = '<tr><td colspan="5" class="text-center text-muted p-3">VM bulunmuyor.</td></tr>';
      return;
    }
    body.innerHTML = vms.map(v => {
      const ramPct = v.ram_mb ? Math.round(100 * (v.ram_usage_mb || 0) / v.ram_mb) : null;
      const cpu = (v.cpu_count != null ? v.cpu_count + ' vCPU' : '—') +
                  (v.cpu_usage_pct != null ? ' <span class="text-muted">%' + Math.round(v.cpu_usage_pct) + '</span>' : '');
      const ram = App.fmtRam(v.ram_mb) +
                  (ramPct != null ? ' <span class="text-muted">%' + ramPct + '</span>' : '');
      return '<tr class="vm-row" style="cursor:pointer" onclick="App.openVmFromModal(' + v.id + ')">' +
        '<td><strong>' + App.esc(v.name) + '</strong>' +
          (v.vmid ? ' <small class="text-muted">#' + App.esc(v.vmid) + '</small>' : '') + '</td>' +
        '<td class="small text-nowrap">' + App.esc((v.ip_addresses || '—').split(',')[0] || '—') + '</td>' +
        '<td>' + App.stateBadge(v.power_state) + '</td>' +
        '<td class="small text-nowrap">' + cpu + '</td>' +
        '<td class="small text-nowrap">' + ram + '</td></tr>';
    }).join('');
  },

  /** Modaldaki VM satırı → modalı kapat, ortak offcanvas'ta VM detayı. */
  openVmFromModal(vmId) {
    bootstrap.Modal.getOrCreateInstance(document.getElementById('hostVmsModal')).hide();
    App.vmDetail(vmId);
  },

  /** Bir host'un VM'lerini çekip ortak VM-listesi modalında göster. */
  async hostVms(hostId) {
    App.showVmList('Yükleniyor…', null);
    let h;
    try { h = await App.api('/api/hosts/' + hostId); } catch (e) { return; }
    App.showVmList(h.name + ' — ' + (h.vms || []).length + ' VM', h.vms || []);
  },

  /** Host dizisini liste modalında göster; tıklayınca o host'un VM'leri. */
  showHostList(title, hosts) {
    document.getElementById('hostListTitle').textContent = title;
    const body = document.getElementById('hostListBody');
    bootstrap.Modal.getOrCreateInstance(document.getElementById('hostListModal')).show();
    if (!hosts || !hosts.length) {
      body.innerHTML = '<div class="text-muted small p-2">Host bulunamadı.</div>';
      return;
    }
    body.innerHTML = hosts.map(h =>
      '<button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" ' +
      'onclick="App.openHostFromList(' + h.id + ')">' +
      '<span><i class="bi bi-server"></i> ' + App.esc(h.name) + '</span>' +
      '<i class="bi bi-chevron-right text-muted"></i></button>').join('');
  },

  /** Host listesinden host → liste modalını kapat, host'un VM'leri modalı. */
  openHostFromList(hostId) {
    bootstrap.Modal.getOrCreateInstance(document.getElementById('hostListModal')).hide();
    App.hostVms(hostId);
  },
};

/* ===== Global tema (tüm sayfalar): koyu/açık geçiş + kalıcı tercih ===== */
App.toggleTheme = function () {
  const next = localStorage.getItem('vmi-dash-theme') === 'light' ? 'dark' : 'light';
  try { localStorage.setItem('vmi-dash-theme', next); } catch (e) {}
  location.reload();
};
(function () {
  const btn = document.getElementById('btnThemeGlobal');
  if (!btn) return;
  const light = localStorage.getItem('vmi-dash-theme') === 'light';
  const i = btn.querySelector('i');
  if (i) i.className = light ? 'bi bi-sun' : 'bi bi-moon-stars';
  btn.title = light ? 'Koyu temaya geç' : 'Açık temaya geç';
  btn.addEventListener('click', App.toggleTheme);
})();
