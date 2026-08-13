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

  // Human label for a schedule/scope target
  TARGET_LABELS: {
    vms: 'Sanal Makineler', hosts: "Host'lar", datastores: "Datastore'lar",
    physical: 'Fiziksel Envanter', all: 'Tüm Envanter',
  },
  targetLabel(t2) {
    const k = { vms: 'nav.vms', hosts: 'nav.hosts', datastores: 'nav.datastores',
                physical: 'nav.physical', all: 'rp.allExport' }[t2];
    return k ? window.t(k, Reports.TARGET_LABELS[t2]) : t2;
  },

  // Show the filter field only for VM-backed schedule targets
  onSchTargetChange() {
    const t2 = document.getElementById('schTarget').value;
    const wrap = document.getElementById('schQueryWrap');
    if (wrap) wrap.style.display = (t2 === 'vms' || t2 === 'all') ? '' : 'none';
  },

  /** Zamanlanmış rapor oluştur (her gün belirtilen YEREL saatte sunucuya yazılır). */
  async schedule() {
    const time = (document.getElementById('schTime').value || '07:00').split(':');
    const target = document.getElementById('schTarget').value;
    const withFilter = (target === 'vms' || target === 'all');
    const payload = {
      name:   document.getElementById('schName').value.trim(),
      target: target,
      hour:   parseInt(time[0] || '7', 10),
      minute: parseInt(time[1] || '0', 10),
      fmt:    document.getElementById('schFmt').value,
      q:      withFilter ? document.getElementById('schQuery').value.trim() : '',
    };
    try {
      await App.api('/api/reports/schedule', {method: 'POST', body: payload});
      App.toast(t('rp.schedCreated','Zamanlanmış rapor oluşturuldu'));
      document.getElementById('schName').value = '';
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
          '<strong>' + App.esc(j.name || Reports.targetLabel(j.target)) + '</strong> ' +
          '<span class="badge text-bg-primary">' + App.esc(Reports.targetLabel(j.target)) + '</span> ' +
          '<span class="badge text-bg-light border">' + App.esc(j.fmt.toUpperCase()) + '</span> ' +
          '<span class="badge text-bg-light border"><i class="bi bi-clock"></i> ' + App.esc(hhmm) + '</span>' +
          (j.query ? ' <code class="small">' + App.esc(j.query) + '</code>' : '') +
          '<br><span class="text-muted">' + t('rp.next','Sonraki') + ': ' + App.fmtDate(j.next_run) +
          ' · ' + t('rp.last','Son') + ': ' + App.fmtDate(j.last_run) + ' ' + Reports._statusBadge(j.last_status) +
          (lastFile !== '—' ? ' · ' + lastFile : '') + '</span>' +
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

  /** Sunucuda üretilmiş rapor dosyalarını listele (en yeni 20). */
  async loadFiles() {
    const box = document.getElementById('fileList');
    if (!box) return;
    let data;
    try { data = await App.api('/api/reports/files?limit=20'); } catch (e) { return; }
    const cnt = document.getElementById('fileCount');
    if (cnt) {
      cnt.style.display = data.total ? '' : 'none';
      cnt.textContent = data.total;
    }
    if (!data.items.length) {
      box.innerHTML = '<li class="list-group-item text-muted small">' + t('rp.noFiles','Henüz üretilmiş dosya yok.') + '</li>';
      document.getElementById('fileMore').style.display = 'none';
      return;
    }
    const canEdit = document.getElementById('schForm') !== null;
    box.innerHTML = data.items.map(f =>
      '<li class="list-group-item d-flex align-items-center">' +
      '<i class="bi bi-file-earmark-arrow-down me-2 text-muted"></i>' +
      '<a class="small text-truncate" href="/api/reports/files/' + encodeURIComponent(f.name) + '">' + App.esc(f.name) + '</a>' +
      '<span class="text-muted small ms-auto text-nowrap">' + App.fmtDate(f.modified) + ' · ' + f.size_kb + ' KB</span>' +
      (canEdit ? '<button class="btn btn-sm btn-link text-danger p-0 ms-2" title="' + t('rp.delete','Sil') +
        '" onclick="Reports.removeFile(\'' + encodeURIComponent(f.name) + '\')"><i class="bi bi-x-lg"></i></button>' : '') +
      '</li>').join('');
    const more = document.getElementById('fileMore');
    if (data.total > data.shown) {
      more.style.display = '';
      document.getElementById('fileMoreText').textContent =
        t('rp.moreFiles', 'Toplam {n} dosyadan en yeni {s} tanesi gösteriliyor')
          .replace('{n}', data.total).replace('{s}', data.shown);
    } else {
      more.style.display = 'none';
    }
  },

  async removeFile(name) {
    if (!confirm(t('rp.deleteFileConfirm','Bu dosya silinsin mi?'))) return;
    try {
      await App.api('/api/reports/files/' + name, {method: 'DELETE'});
      Reports.loadFiles();
    } catch (e) { /* hata gösterildi */ }
  },

  async cleanupFiles() {
    if (!confirm(t('rp.cleanupConfirm','En yeni 20 dosya korunacak, gerisi silinecek. Devam edilsin mi?'))) return;
    try {
      const r = await App.api('/api/reports/files/cleanup', {method: 'POST', body: {keep: 20}});
      App.toast(t('rp.cleanedUp','{n} eski dosya silindi').replace('{n}', r.removed || 0));
      Reports.loadFiles();
    } catch (e) { /* hata gösterildi */ }
  },
};

document.querySelectorAll('#repScope [data-scope]').forEach(b =>
  b.addEventListener('click', () => Reports.setScope(b.dataset.scope)));
Reports.setScope('vms');
const _schT = document.getElementById('schTarget');
if (_schT) { _schT.addEventListener('change', Reports.onSchTargetChange); Reports.onSchTargetChange(); }
Reports.loadSchedules();
Reports.loadFiles();
