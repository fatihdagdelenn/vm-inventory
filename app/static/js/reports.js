/**
 * reports.js — Anlık dışa aktarma + zamanlanmış raporlar (kalıcı) + üretilmiş dosyalar.
 * Zamanlanmış raporlar artık DB'de saklanır; saatler uygulama zaman dilimine göredir.
 */
const Reports = {
  scope: 'vms',

  // Which scope accepts the free-text filter, and its description note.
  SCOPES: {
    vms:        { filter: true,  note: 'rp.scopeVms' },
    hosts:      { filter: false, note: 'rp.scopeHosts' },
    datastores: { filter: false, note: 'rp.scopeDs' },
    physical:   { filter: false, note: 'rp.scopePhysical' },
    all:        { filter: true,  note: 'rp.scopeAll' },
  },
  NOTE_TR: {
    'rp.scopeVms': 'Sanal makine envanteri dışa aktarılır.',
    'rp.scopeHosts': "Host envanteri dışa aktarılır.",
    'rp.scopeDs': "Datastore envanteri dışa aktarılır.",
    'rp.scopePhysical': 'Fiziksel envanter (sunucu, storage, SAN switch, yedekleme) dışa aktarılır.',
    'rp.scopeAll': 'Tüm envanter tek dosyada: VM + Host + Datastore + Fiziksel. Excel\'de ayrı sayfalar, CSV/PDF\'de ardışık bölümler.',
  },

  setScope(scope) {
    Reports.scope = scope;
    document.querySelectorAll('#repScope [data-scope]').forEach(b =>
      b.classList.toggle('active', b.dataset.scope === scope));
    const meta = Reports.SCOPES[scope] || Reports.SCOPES.vms;
    // Free-text filter only meaningful for VM-backed scopes
    const inp = document.getElementById('repQuery');
    const note = document.getElementById('repFilterNote');
    if (inp) { inp.disabled = !meta.filter; inp.classList.toggle('opacity-50', !meta.filter); }
    if (note) note.style.display = meta.filter ? '' : 'none';
    // Scope description line
    const sn = document.getElementById('repScopeNote');
    if (sn) sn.querySelector('span').textContent =
      window.t(meta.note, Reports.NOTE_TR[meta.note] || '');
  },

  /** Export the currently selected scope in the given format. */
  exportScope(fmt) {
    const meta = Reports.SCOPES[Reports.scope] || {};
    const q = meta.filter ? document.getElementById('repQuery').value.trim() : '';
    location.href = '/api/reports/' + Reports.scope + '/export?fmt=' + fmt +
                    (q ? '&q=' + encodeURIComponent(q) : '');
  },

  /** Anlık dışa aktarma — entity: 'vms' | 'hosts', fmt: xlsx | csv | pdf */
  export(entity, fmt) {
    const q = document.getElementById('repQuery').value.trim();
    location.href = '/api/reports/' + entity + '/export?fmt=' + fmt +
                    '&q=' + encodeURIComponent(q);
  },

  /** Zamanlanmış rapor oluştur (her gün belirtilen YEREL saatte sunucuya yazılır). */
  async schedule() {
    const payload = {
      name:   document.getElementById('schName').value.trim(),
      target: document.getElementById('schTarget').value,
      hour:   parseInt(document.getElementById('schHour').value || '7', 10),
      minute: parseInt(document.getElementById('schMin').value || '0', 10),
      fmt:    document.getElementById('schFmt').value,
      q:      document.getElementById('schQuery').value.trim(),
    };
    try {
      await App.api('/api/reports/schedule', {method: 'POST', body: payload});
      App.toast(t('rp.schedCreated','Zamanlanmış rapor oluşturuldu'));
      Reports.loadSchedules();
    } catch (e) { /* hata gösterildi */ }
  },

  _statusBadge(s) {
    if (s === 'success') return '<span class="badge text-bg-success">' + t('rp.ok','başarılı') + '</span>';
    if (s === 'error')   return '<span class="badge text-bg-danger">' + t('rp.err','hata') + '</span>';
    return '<span class="badge text-bg-secondary">' + t('rp.notRun','henüz çalışmadı') + '</span>';
  },

  /** Kayıtlı zamanlanmış raporları listele. */
  async loadSchedules() {
    let data;
    try { data = await App.api('/api/reports/schedule'); } catch (e) { return; }
    const list = document.getElementById('schList');
    if (!data.items.length) {
      list.innerHTML = '<li class="list-group-item text-muted small">' + t('rp.noSched','Zamanlanmış rapor yok.') + '</li>';
      return;
    }
    const canEdit = document.getElementById('schForm') !== null;
    list.innerHTML = data.items.map(j => {
      const hhmm = String(j.hour).padStart(2, '0') + ':' + String(j.minute).padStart(2, '0');
      const lastFile = j.last_file
        ? '<a href="/api/reports/files/' + encodeURIComponent(j.last_file) + '">' + App.esc(j.last_file) + '</a>'
        : '—';
      const actions = canEdit
        ? '<div class="btn-group btn-group-sm ms-auto">' +
            '<button class="btn btn-outline-primary" title="' + t('rp.runNow','Şimdi çalıştır') + '" onclick="Reports.runNow(' + j.id + ')"><i class="bi bi-play-fill"></i></button>' +
            '<button class="btn btn-outline-danger" title="' + t('rp.delete','Sil') + '" onclick="Reports.remove(' + j.id + ')"><i class="bi bi-trash"></i></button>' +
          '</div>'
        : '';
      return '<li class="list-group-item d-flex align-items-start">' +
        '<i class="bi bi-clock me-2 text-muted mt-1"></i>' +
        '<div class="small flex-grow-1">' +
          '<strong>' + App.esc(j.name || (j.target === 'hosts' ? 'Host raporu' : 'VM raporu')) + '</strong> ' +
          '<span class="badge text-bg-light border">' + App.esc(j.fmt.toUpperCase()) + '</span> ' +
          '<span class="badge text-bg-light border">' + App.esc(hhmm) + '</span>' +
          (j.query ? ' <code class="small">' + App.esc(j.query) + '</code>' : '') +
          '<br><span class="text-muted">Sonraki: ' + App.fmtDate(j.next_run) +
          ' · Son: ' + App.fmtDate(j.last_run) + ' ' + Reports._statusBadge(j.last_status) +
          ' · Dosya: ' + lastFile + '</span>' +
          (j.last_error ? '<br><span class="text-danger small">' + App.esc(j.last_error) + '</span>' : '') +
        '</div>' + actions + '</li>';
    }).join('');
  },

  async runNow(id) {
    try {
      await App.api('/api/reports/schedule/' + id + '/run', {method: 'POST'});
      App.toast(t('rp.ran','Rapor çalıştırıldı'));
      Reports.loadSchedules();
      Reports.loadFiles();
    } catch (e) { /* hata gösterildi */ }
  },

  async remove(id) {
    if (!confirm(t('rp.deleteConfirm','Zamanlanmış rapor silinsin mi?'))) return;
    try {
      await App.api('/api/reports/schedule/' + id, {method: 'DELETE'});
      App.toast(t('rp.deleted','Zamanlanmış rapor silindi'));
      Reports.loadSchedules();
    } catch (e) { /* hata gösterildi */ }
  },

  /** Sunucuda üretilmiş rapor dosyalarını listele. */
  async loadFiles() {
    const box = document.getElementById('fileList');
    if (!box) return;
    let data;
    try { data = await App.api('/api/reports/files'); } catch (e) { return; }
    if (!data.items.length) {
      box.innerHTML = '<li class="list-group-item text-muted small">' + t('rp.noFiles','Henüz üretilmiş dosya yok.') + '</li>';
      return;
    }
    box.innerHTML = data.items.map(f =>
      '<li class="list-group-item d-flex align-items-center">' +
      '<i class="bi bi-file-earmark-arrow-down me-2 text-muted"></i>' +
      '<a class="small" href="/api/reports/files/' + encodeURIComponent(f.name) + '">' + App.esc(f.name) + '</a>' +
      '<span class="text-muted small ms-auto">' + App.fmtDate(f.modified) + ' · ' + f.size_kb + ' KB</span></li>').join('');
  },
};

document.querySelectorAll('#repScope [data-scope]').forEach(b =>
  b.addEventListener('click', () => Reports.setScope(b.dataset.scope)));
Reports.setScope('vms');
Reports.loadSchedules();
Reports.loadFiles();
