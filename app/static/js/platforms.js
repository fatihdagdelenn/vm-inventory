/**
 * platforms.js — vCenter / Proxmox bağlantı yönetimi.
 *  - Platform kartları (durum + son senkronizasyon)
 *  - Ekle/düzenle modalı, tip'e göre alan görünürlüğü (token vs parola)
 *  - Kaydetmeden önce bağlantı testi
 *  - Manuel senkronizasyon + senkronizasyon logları
 */
const Platforms = {
  items: [],

  async load() {
    let data;
    try { data = await App.api('/api/platforms'); } catch (e) { return; }
    Platforms.items = data.items;
    const wrap = document.getElementById('platformCards');
    if (!data.items.length) {
      wrap.innerHTML = '<div class="col-12"><div class="alert alert-info mb-0">' +
        'Henüz platform eklenmemiş. Sağ üstteki <strong>Platform Ekle</strong> ' +
        'butonuyla ilk vCenter veya Proxmox bağlantınızı oluşturun.</div></div>';
      return;
    }
    const isAdmin = document.querySelector('.role-badge')?.textContent.trim() === 'Admin';
    const isViewer = document.querySelector('.role-badge')?.textContent.trim() === 'Görüntüleyici';

    wrap.innerHTML = data.items.map(p => {
      const icon = p.type === 'vcenter'
        ? '<i class="bi bi-cloud fs-3 text-primary"></i>'
        : '<i class="bi bi-box fs-3 text-warning"></i>';
      const status = p.last_sync_status === 'success'
        ? '<span class="badge text-bg-success">Bağlantı OK</span>'
        : p.last_sync_status === 'error'
          ? '<span class="badge text-bg-danger" title="' + App.esc(p.last_sync_error || '') + '">Hata</span>'
          : '<span class="badge text-bg-secondary">Senkronize edilmedi</span>';
      return '<div class="col-md-6 col-xl-4"><div class="card panel h-100"><div class="card-body">' +
        '<div class="d-flex align-items-start">' + icon +
        '<div class="ms-3 flex-grow-1">' +
        '<h6 class="mb-0">' + App.esc(p.name) + (p.enabled ? '' :
          ' <span class="badge text-bg-secondary">Pasif</span>') + '</h6>' +
        '<small class="text-muted">' + App.esc(p.host) + ':' + p.port + '</small></div>' +
        status + '</div>' +
        '<div class="small text-muted mt-2">' +
        '<div><i class="bi bi-geo-alt"></i> ' + App.esc(p.location || '—') +
        ' &nbsp; <i class="bi bi-layers"></i> ' + App.esc(p.environment) + '</div>' +
        '<div><i class="bi bi-arrow-repeat"></i> Son senkronizasyon: ' + App.fmtDate(p.last_sync) + '</div>' +
        (p.last_sync_error ? '<div class="text-danger text-truncate" title="' +
          App.esc(p.last_sync_error) + '"><i class="bi bi-exclamation-triangle"></i> ' +
          App.esc(p.last_sync_error) + '</div>' : '') +
        '</div></div>' +
        '<div class="card-footer d-flex gap-1">' +
        (!isViewer ? '<button class="btn btn-sm btn-outline-primary" onclick="Platforms.sync(' + p.id + ',this)">' +
          '<i class="bi bi-arrow-repeat"></i> Senkronize Et</button>' : '') +
        '<button class="btn btn-sm btn-outline-secondary" onclick="Platforms.logs(' + p.id + ')">' +
          '<i class="bi bi-journal-text"></i> Loglar</button>' +
        (isAdmin ? '<button class="btn btn-sm btn-outline-secondary ms-auto" onclick="Platforms.openModal(' + p.id + ')">' +
          '<i class="bi bi-pencil"></i></button>' +
          '<button class="btn btn-sm btn-outline-danger" onclick="Platforms.remove(' + p.id + ')">' +
          '<i class="bi bi-trash"></i></button>' : '') +
        '</div></div></div>';
    }).join('');
  },

  /* ---------- Modal ---------- */
  openModal(id = null) {
    const p = id ? Platforms.items.find(x => x.id === id) : null;
    document.getElementById('pmTitle').textContent = p ? 'Platformu Düzenle' : 'Platform Ekle';
    document.getElementById('pmId').value = p ? p.id : '';
    document.getElementById('pmName').value = p ? p.name : '';
    document.getElementById('pmType').value = p ? p.type : 'vcenter';
    document.getElementById('pmHost').value = p ? p.host : '';
    document.getElementById('pmPort').value = p ? p.port : 443;
    document.getElementById('pmAuthMethod').value = p ? (p.auth_method || 'password') : 'token';
    document.getElementById('pmUser').value = p ? (p.username || '') : '';
    document.getElementById('pmPass').value = '';
    document.getElementById('pmTokenName').value = p ? (p.token_name || '') : '';
    document.getElementById('pmTokenValue').value = '';
    document.getElementById('pmLocation').value = p ? (p.location || '') : '';
    document.getElementById('pmEnv').value = p ? p.environment : 'production';
    document.getElementById('pmSsl').checked = p ? p.verify_ssl : true;
    document.getElementById('pmTestResult').innerHTML = '';
    Platforms.onTypeChange();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('platformModal')).show();
  },

  /** Tip değişince: Proxmox'ta token seçeneği + port 8006; vCenter'da parola + 443. */
  onTypeChange() {
    const type = document.getElementById('pmType').value;
    const authWrap = document.getElementById('pmAuthMethodWrap');
    const portEl = document.getElementById('pmPort');
    if (type === 'proxmox') {
      authWrap.style.display = '';
      if (portEl.value == 443) portEl.value = 8006;
    } else {
      authWrap.style.display = 'none';
      document.getElementById('pmAuthMethod').value = 'password';
      if (portEl.value == 8006) portEl.value = 443;
    }
    Platforms.onAuthChange();
  },

  /** Kimlik doğrulama yöntemine göre alanları göster/gizle. */
  onAuthChange() {
    const method = document.getElementById('pmAuthMethod').value;
    const isToken = document.getElementById('pmType').value === 'proxmox' && method === 'token';
    document.querySelectorAll('.pm-token').forEach(el => el.style.display = isToken ? '' : 'none');
    document.querySelectorAll('.pm-pass').forEach(el => el.style.display = isToken ? 'none' : '');
  },

  /** Modal alanlarından API payload'u üret. */
  _payload() {
    return {
      name: document.getElementById('pmName').value.trim(),
      type: document.getElementById('pmType').value,
      host: document.getElementById('pmHost').value.trim(),
      port: parseInt(document.getElementById('pmPort').value, 10),
      auth_method: document.getElementById('pmType').value === 'proxmox'
        ? document.getElementById('pmAuthMethod').value : 'password',
      username: document.getElementById('pmUser').value.trim(),
      password: document.getElementById('pmPass').value,
      token_name: document.getElementById('pmTokenName').value.trim(),
      token_value: document.getElementById('pmTokenValue').value,
      location: document.getElementById('pmLocation').value.trim(),
      environment: document.getElementById('pmEnv').value,
      verify_ssl: document.getElementById('pmSsl').checked,
    };
  },

  /** Bağlantı testi — kaydetmeden önce verilen bilgilerle dener.
   *  Düzenleme modunda parola boş bırakıldıysa kayıtlı bilgilerle test eder. */
  async test() {
    const out = document.getElementById('pmTestResult');
    out.innerHTML = '<div class="alert alert-info mb-0"><span class="spinner-border spinner-border-sm"></span> Bağlantı deneniyor…</div>';
    const payload = Platforms._payload();
    const id = document.getElementById('pmId').value;
    // Düzenlemede kimlik bilgisi girilmediyse kayıtlı (şifreli) bilgileri kullan
    if (id && !payload.password && !payload.token_value) payload.id = parseInt(id, 10);
    try {
      const r = await App.api('/api/platforms/test', {method: 'POST', body: payload});
      out.innerHTML = r.ok
        ? '<div class="alert alert-success mb-0"><i class="bi bi-check-circle"></i> ' +
          App.esc(r.message || 'Bağlantı başarılı') + '</div>'
        : '<div class="alert alert-danger mb-0"><i class="bi bi-x-circle"></i> ' +
          App.esc(r.message || 'Bağlantı başarısız') + '</div>';
    } catch (e) {
      out.innerHTML = '<div class="alert alert-danger mb-0"><i class="bi bi-x-circle"></i> ' +
        App.esc(e.message) + '</div>';
    }
  },

  async save() {
    const id = document.getElementById('pmId').value;
    const payload = Platforms._payload();
    if (!payload.name || !payload.host) {
      App.toast('Görünen ad ve API adresi zorunludur', 'warning');
      return;
    }
    try {
      if (id) await App.api('/api/platforms/' + id, {method: 'PUT', body: payload});
      else    await App.api('/api/platforms', {method: 'POST', body: payload});
      App.toast('Platform kaydedildi');
      bootstrap.Modal.getInstance(document.getElementById('platformModal')).hide();
      Platforms.load();
    } catch (e) { /* hata gösterildi */ }
  },

  async remove(id) {
    if (!confirm('Platform ve ilişkili envanter kayıtları silinecek. Emin misiniz?')) return;
    try {
      await App.api('/api/platforms/' + id, {method: 'DELETE'});
      App.toast('Platform silindi');
      Platforms.load();
    } catch (e) { /* hata gösterildi */ }
  },

  /** Manuel senkronizasyon — arka planda çalışır, sayfa kilitlenmez. */
  async sync(id, btn) {
    btn.disabled = true;
    try {
      const r = await App.api('/api/platforms/' + id + '/sync', {method: 'POST'});
      App.toast(r.message || 'Senkronizasyon başlatıldı', 'info');
      setTimeout(Platforms.load, 5000);   // bir süre sonra durumu tazele
    } catch (e) { /* hata gösterildi */ }
    btn.disabled = false;
  },

  /** Senkronizasyon / API hata logları modalı. */
  async logs(id) {
    let data;
    try { data = await App.api('/api/platforms/' + id + '/logs'); } catch (e) { return; }
    const body = document.getElementById('logsBody');
    body.innerHTML = data.items.length ? data.items.map(l => '<tr>' +
      '<td class="text-nowrap small">' + App.fmtDate(l.started_at) + '</td>' +
      '<td class="text-nowrap small">' + App.fmtDate(l.finished_at) + '</td>' +
      '<td>' + (l.status === 'success'
        ? '<span class="badge text-bg-success">Başarılı</span>'
        : l.status === 'running'
          ? '<span class="badge text-bg-info">Çalışıyor</span>'
          : '<span class="badge text-bg-danger">Hata</span>') + '</td>' +
      '<td>' + (l.hosts_found ?? '—') + '</td>' +
      '<td>' + (l.vms_found ?? '—') + '</td>' +
      '<td class="small">' + App.esc(l.message || '') + '</td></tr>').join('')
      : '<tr><td colspan="6" class="text-muted p-3">Log kaydı yok.</td></tr>';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('logsModal')).show();
  },
};

Platforms.load();
