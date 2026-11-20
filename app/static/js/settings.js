/**
 * settings.js — Yönetim ekranı (sadece admin): kullanıcı CRUD + audit log.
 */
const Settings = {
  users: [],

  async loadUsers() {
    let data;
    try { data = await App.api('/api/admin/users'); } catch (e) { return; }
    Settings.users = data.items;
    const roleBadge = r => ({
      admin:    '<span class="badge text-bg-danger">Admin</span>',
      operator: '<span class="badge text-bg-warning text-dark">' + t('role.operator','Operatör') + '</span>',
      viewer:   '<span class="badge text-bg-secondary">' + t('role.viewer','Görüntüleyici') + '</span>',
    }[r] || r);
    document.getElementById('userBody').innerHTML = data.items.map(u => '<tr>' +
      '<td><strong>' + App.esc(u.username) + '</strong></td>' +
      '<td>' + App.esc(u.full_name || '—') + '</td>' +
      '<td>' + App.esc(u.email || '—') + '</td>' +
      '<td>' + roleBadge(u.role) + '</td>' +
      '<td>' + (u.is_ldap ? 'LDAP/AD' : t('st2.local','Lokal')) + '</td>' +
      '<td class="small">' + App.fmtDate(u.last_login) + '</td>' +
      '<td>' + (u.is_active
        ? '<span class="badge text-bg-success">' + t('ag.active','Aktif') + '</span>'
        : '<span class="badge text-bg-secondary">' + t('ag.passive','Pasif') + '</span>') + '</td>' +
      '<td class="text-end">' +
      '<button class="btn btn-sm btn-outline-secondary" onclick="Settings.openUserModal(' + u.id + ')">' +
      '<i class="bi bi-pencil"></i></button> ' +
      '<button class="btn btn-sm btn-outline-' + (u.is_active ? 'danger' : 'success') + '" ' +
      'title="' + (u.is_active ? t('st2.deactivate','Pasifleştir') : t('st2.activate','Aktifleştir')) + '" ' +
      'onclick="Settings.toggleActive(' + u.id + ',' + !u.is_active + ')">' +
      '<i class="bi bi-' + (u.is_active ? 'person-x' : 'person-check') + '"></i></button></td></tr>').join('');
  },

  openUserModal(id = null) {
    const u = id ? Settings.users.find(x => x.id === id) : null;
    document.getElementById('umTitle').textContent = u ? t('st2.editUser','Kullanıcıyı Düzenle') : t('st2.addUser','Kullanıcı Ekle');
    document.getElementById('umId').value = u ? u.id : '';
    document.getElementById('umUsername').value = u ? u.username : '';
    document.getElementById('umUsername').disabled = !!u;   // kullanıcı adı değişmez
    document.getElementById('umFullName').value = u ? (u.full_name || '') : '';
    document.getElementById('umEmail').value = u ? (u.email || '') : '';
    document.getElementById('umRole').value = u ? u.role : 'viewer';
    document.getElementById('umPassword').value = '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('userModal')).show();
  },

  async saveUser() {
    const id = document.getElementById('umId').value;
    const payload = {
      username: document.getElementById('umUsername').value.trim(),
      full_name: document.getElementById('umFullName').value.trim(),
      email: document.getElementById('umEmail').value.trim(),
      role: document.getElementById('umRole').value,
      password: document.getElementById('umPassword').value,
    };
    if (!payload.username) { App.toast(t('st2.usernameRequired','Kullanıcı adı zorunludur'), 'warning'); return; }
    if (!id && !payload.password) { App.toast(t('st2.passwordRequired','Yeni kullanıcı için parola zorunludur'), 'warning'); return; }
    try {
      if (id) await App.api('/api/admin/users/' + id, {method: 'PATCH', body: payload});
      else    await App.api('/api/admin/users', {method: 'POST', body: payload});
      App.toast(t('st2.userSaved','Kullanıcı kaydedildi'));
      bootstrap.Modal.getInstance(document.getElementById('userModal')).hide();
      Settings.loadUsers();
    } catch (e) { /* hata gösterildi */ }
  },

  async toggleActive(id, active) {
    try {
      await App.api('/api/admin/users/' + id, {method: 'PATCH', body: {is_active: active}});
      App.toast(active ? t('st2.userActivated','Kullanıcı aktifleştirildi') : t('st2.userDeactivated','Kullanıcı pasifleştirildi'));
      Settings.loadUsers();
    } catch (e) { /* hata gösterildi */ }
  },

  async loadAudit() {
    const q = document.getElementById('auditSearch').value.trim();
    const action = document.getElementById('auditAction').value;
    let data;
    try {
      data = await App.api('/api/admin/audit?q=' + encodeURIComponent(q) +
                           '&action=' + encodeURIComponent(action));
    } catch (e) { return; }
    if (!this.auditActionsLoaded && data.actions) {
      const sel = document.getElementById('auditAction');
      data.actions.forEach(a => {
        const o = document.createElement('option'); o.value = a; o.textContent = a;
        sel.appendChild(o);
      });
      this.auditActionsLoaded = true;
    }
    const roleBadge = r => r
      ? ' <span class="badge text-bg-light border text-muted" style="font-size:.65rem">' + App.esc(r) + '</span>' : '';
    const change = l => {
      if (l.old_value == null && l.new_value == null)
        return l.detail ? '<span class="text-muted small">' + App.esc(l.detail) + '</span>' : '—';
      return '<span class="small">' +
        (l.old_value ? '<span class="text-danger">' + App.esc(l.old_value) + '</span>' : '—') +
        ' <i class="bi bi-arrow-right text-muted"></i> ' +
        (l.new_value ? '<span class="text-success">' + App.esc(l.new_value) + '</span>' : '—') +
        '</span>';
    };
    document.getElementById('auditBody').innerHTML = data.items.length
      ? data.items.map(l => '<tr>' +
          '<td class="text-nowrap small">' + App.fmtDate(l.timestamp) + '</td>' +
          '<td class="small">' + App.esc(l.username) + roleBadge(l.role) + '</td>' +
          '<td><code>' + App.esc(l.action) + '</code></td>' +
          '<td class="small">' + App.esc(l.target || '—') + '</td>' +
          '<td>' + change(l) + '</td>' +
          '<td class="small text-muted">' + App.esc(l.ip_address || '') + '</td></tr>').join('')
      : '<tr><td colspan="6" class="text-muted p-3">' + t('st2.noRecords','Kayıt yok.') + '</td></tr>';
  },
  async loadSync() {
    const el = document.getElementById('syncFull');
    if (!el) return;
    let d;
    try { d = await App.api('/api/admin/sync-settings'); } catch (e) { return; }
    document.getElementById('syncFull').value = d.sync_interval_minutes;
    document.getElementById('syncUsage').value = d.usage_sync_interval_minutes;
    const tc = document.getElementById('trackConsole');
    if (tc) tc.checked = !!d.track_console_access;
  },

  async clearConsole() {
    const msg = document.getElementById('clearConsoleMsg');
    if (!confirm(t('st2.clearConsoleConfirm','Tüm konsol erişimi geçmiş satırları silinecek. Emin misiniz?'))) return;
    try {
      const r = await App.api('/api/admin/changes/clear-console', {method: 'POST', body: {}});
      msg.className = 'ms-2 small text-success';
      msg.textContent = '✓ ' + (r.deleted || 0) + ' ' + t('st2.rowsDeleted','satır silindi');
    } catch (e) {
      msg.className = 'ms-2 small text-danger';
      msg.textContent = 'Silinemedi';
    }
  },

  async saveSync() {
    const full = parseInt(document.getElementById('syncFull').value, 10);
    const usage = parseInt(document.getElementById('syncUsage').value, 10);
    const console_ = !!(document.getElementById('trackConsole') || {}).checked;
    const msg = document.getElementById('syncSaveMsg');
    const okRange = n => Number.isInteger(n) && n >= 1 && n <= 1440;
    if (!okRange(full) || !okRange(usage)) {
      msg.className = 'ms-2 small text-danger';
      msg.textContent = t('st2.rangeError','Değerler 1–1440 dakika arasında olmalı');
      return;
    }
    try {
      await App.api('/api/admin/sync-settings', {method: 'PUT',
        body: {sync_interval_minutes: full, usage_sync_interval_minutes: usage,
               track_console_access: console_}});
      msg.className = 'ms-2 small text-success';
      msg.textContent = '✓ ' + t('st2.savedLive','Kaydedildi — yeniden başlatmadan geçerli');
    } catch (e) {
      msg.className = 'ms-2 small text-danger';
      msg.textContent = 'Kaydedilemedi';
    }
  },

  /* ---------- OS lifecycle (phase 158) ---------- */
  lcNames: {},
  srcLabel(src) {
    return ({seed: t('lc.src.seed', 'Uygulamayla gelen'), 'endoflife.date': 'endoflife.date',
             manual: t('lc.src.manual', 'Yüklenen JSON')})[src] || (src || '—');
  },

  async loadLifecycle() {
    let d;
    try { d = await App.api('/api/lifecycle'); } catch (e) { return; }
    const m = d.meta;
    Settings.lcNames = d.product_names || {};
    const c = d.counts;
    const dt = iso => iso ? App.fmtDate(iso.length > 19 ? iso : iso + 'Z') : '—';
    const row = (k, v) => '<dt class="col-5 text-muted fw-normal">' + k + '</dt><dd class="col-7 mb-1">' + v + '</dd>';
    document.getElementById('lcMeta').innerHTML =
      row(t('lc.cycles', 'Sürüm'), m.cycles + ' (' + Object.entries(m.by_source || {})
        .map(([k, n]) => Settings.srcLabel(k) + ': ' + n).join(', ') + ')') +
      row(t('lc.dataDate', 'Veri tarihi'), dt(m.data_date)) +
      row(t('lc.lastSync', 'Son başarılı güncelleme'), m.last_sync ? dt(m.last_sync) : t('lc.never', 'hiç (internet yok)')) +
      (m.last_error ? row(t('lc.lastAttempt', 'Son deneme'), dt(m.last_attempt) +
        ' <span class="badge text-bg-light border" title="' + App.esc(m.last_error) + '">' +
        t('lc.offline', 'erişilemedi') + '</span>') : '') +
      row(t('lc.vmStatus', 'VM durumu'),
        ['eol', 'soon', 'extended', 'unknown', 'supported'].map(k =>
          '<a class="text-decoration-none me-2" href="/vms?q=destek:' + k + '">' +
          App.supportBadge({support_status: k}) + ' ' + (c[k] || 0) + '</a>').join(''));
    document.getElementById('lcSoon').value = m.soon_days;
    document.getElementById('lcProducts').innerHTML = (d.products || []).map(p =>
      '<tr><td>' + App.esc(p.label) + '</td><td>' + p.cycles + '</td>' +
      '<td class="small">' + dt(p.updated_at).split(' ')[0] + '</td>' +
      '<td class="small text-muted">' + App.esc((p.sources || []).map(Settings.srcLabel).join(' + ')) + '</td></tr>').join('');
    const sel = document.getElementById('ovDistro');
    sel.innerHTML = '<option value="">' + t('lc.anyProduct', 'Hepsi') + '</option>' +
      Object.entries(Settings.lcNames).sort((a, b) => a[1].localeCompare(b[1]))
        .map(([k, v]) => '<option value="' + k + '">' + App.esc(v) + '</option>').join('');
    Settings.loadOverrides();
  },

  async loadOverrides() {
    let d;
    try { d = await App.api('/api/lifecycle/overrides'); } catch (e) { return; }
    document.getElementById('ovTags').innerHTML = (d.tags || []).map(x => '<option value="' + App.esc(x) + '">').join('');
    const scope = {all: t('lc.sc.all', "Tüm VM'ler"), tag: t('lc.sc.tag', 'Etiket'), vm: t('lc.sc.vm', 'Tek VM')};
    document.getElementById('ovBody').innerHTML = d.items.length ? d.items.map(o => '<tr>' +
      '<td>' + scope[o.scope] + '</td><td>' + App.esc(o.scope === 'all' ? '—' : o.target_label) + '</td>' +
      '<td>' + App.esc(o.distro_label || t('lc.anyProduct', 'Hepsi')) + '</td>' +
      '<td>' + (o.extended ? '<span class="badge sp-badge sp-ext">' + t('lc.yes', 'Var') + '</span>'
                           : '<span class="badge sp-badge sp-unk">' + t('lc.no', 'Yok') + '</span>') + '</td>' +
      '<td class="small">' + App.esc(o.note || '') + '</td><td class="small text-muted">' + App.esc(o.created_by || '') + '</td>' +
      '<td class="text-end"><button class="btn btn-sm btn-outline-danger" title="' + t('action.delete', 'Sil') +
      '" onclick="Settings.ovDelete(' + o.id + ')"><i class="bi bi-trash"></i></button></td></tr>').join('')
      : '<tr><td colspan="7" class="text-muted small p-3">' + t('lc.noOverrides', 'İstisna yok.') + '</td></tr>';
  },

  ovScopeChanged() {
    const sc = document.getElementById('ovScope').value, inp = document.getElementById('ovTarget');
    inp.disabled = sc === 'all';
    inp.placeholder = sc === 'tag' ? t('lc.tagPh', 'etiket adı') : sc === 'vm' ? t('lc.vmPh', 'VM adı (tam)') : '';
    inp.setAttribute('list', sc === 'tag' ? 'ovTags' : '');
    if (sc === 'all') inp.value = '';
  },

  lcMsg(ok, text) {
    const el = document.getElementById('lcMsg');
    el.className = 'small mt-2 ' + (ok ? 'text-success' : 'text-danger');
    el.textContent = text;
  },

  async lcSync() {
    const btn = document.getElementById('lcSyncBtn');
    btn.disabled = true;
    try {
      const r = await App.api('/api/lifecycle/sync', {method: 'POST', body: {}});
      Settings.lcMsg(r.ok, r.ok
        ? '✓ ' + t('lc.synced', 'Güncellendi') + ': +' + r.added + ' / ~' + r.updated
        : t('lc.syncFail', 'endoflife.date\'e erişilemedi; mevcut veri kullanılmaya devam ediyor.'));
    } catch (e) { /* toast shown */ }
    btn.disabled = false;
    Settings.loadLifecycle();
  },

  async lcImport(input) {
    const f = input.files && input.files[0];
    input.value = '';
    if (!f) return;
    let body;
    try { body = JSON.parse(await f.text()); } catch (e) {
      Settings.lcMsg(false, t('lc.badJson', 'Dosya geçerli bir JSON değil')); return;
    }
    try {
      const r = await App.api('/api/lifecycle/import', {method: 'POST', body});
      Settings.lcMsg(true, '✓ ' + r.rows + ' ' + t('lc.rowsRead', 'sürüm okundu') + ': +' + r.added +
        ' / ~' + r.updated + ' / =' + r.kept);
    } catch (e) { return; }
    Settings.loadLifecycle();
  },

  async lcSaveSoon() {
    const n = parseInt(document.getElementById('lcSoon').value, 10);
    try {
      await App.api('/api/lifecycle/settings', {method: 'PUT', body: {soon_days: n}});
      Settings.lcMsg(true, '✓ ' + t('pl.saved', 'Kaydedildi'));
    } catch (e) { return; }
    Settings.loadLifecycle();
  },

  async ovAdd() {
    const body = {scope: document.getElementById('ovScope').value,
                  target: document.getElementById('ovTarget').value.trim(),
                  distro: document.getElementById('ovDistro').value,
                  extended: document.getElementById('ovExtended').checked,
                  note: document.getElementById('ovNote').value.trim()};
    try { await App.api('/api/lifecycle/overrides', {method: 'POST', body}); } catch (e) { return; }
    document.getElementById('ovTarget').value = '';
    document.getElementById('ovNote').value = '';
    Settings.loadLifecycle();
  },

  async ovDelete(id) {
    if (!confirm(t('lc.ovDeleteConfirm', 'Bu istisna silinsin mi?'))) return;
    try { await App.api('/api/lifecycle/overrides/' + id, {method: 'DELETE'}); } catch (e) { return; }
    Settings.loadLifecycle();
  },

  /* ---------- Kernel vulnerability data (phase 160) ---------- */
  _vdTimer: null,

  async loadVuln() {
    let d;
    try { d = await App.api('/api/vulns/status'); } catch (e) { return; }
    const dt = iso => iso ? App.fmtDate(iso.length > 19 ? iso : iso + 'Z') : '—';
    const row = (k, v) => '<dt class="col-5 text-muted fw-normal">' + k + '</dt><dd class="col-7 mb-1">' + v + '</dd>';
    const job = d.job || {};
    const jobTxt = job.running
      ? '<span class="spinner-border spinner-border-sm"></span> ' + t('vd2.running', 'çalışıyor') + ' (' + App.esc(job.kind || '') + ')'
      : job.finished ? (job.ok ? '<span class="text-success">✓</span> ' : '<span class="text-danger">✗</span> ') +
        dt(job.finished) + ' <span class="small text-muted">' + App.esc(job.ok ? Settings.vdJobText(job.message)
          : (job.message || '')) + '</span>' : '—';
    document.getElementById('vdMeta').innerHTML =
      row(t('vd2.rows', 'Zafiyet kaydı'), d.rows.toLocaleString() + ' · ' + d.cves.toLocaleString() + ' CVE') +
      row(t('vd2.dataDate', 'En yeni kayıt'), dt(d.data_date)) +
      row('CISA KEV', d.kev + (d.kev_version ? ' · ' + App.esc(d.kev_version) : '') +
        (d.kev_source ? ' <span class="text-muted">· ' + App.esc(d.kev_source) + '</span>' : '')) +
      (Object.keys(d.osv_sources || {}).length ? row(t('vd2.osvSrc', 'OSV kaynağı'),
        Object.entries(d.osv_sources).map(([e, s]) => App.esc(e) + ': ' + App.esc(s)).join(' · ')) : '') +
      row(t('lc.lastSync', 'Son başarılı güncelleme'), d.last_sync ? dt(d.last_sync) : t('lc.never', 'hiç (internet yok)')) +
      (d.last_error ? row(t('lc.lastAttempt', 'Son deneme'), dt(d.last_attempt) +
        ' <span class="badge text-bg-light border" title="' + App.esc(d.last_error) + '">' +
        t('lc.offline', 'erişilemedi') + '</span>') : '') +
      row(t('vd2.job', 'Son iş'), jobTxt) +
      row(t('vd2.vms', 'VM'), '<a href="/vms?q=zafiyet:var,yok">' + d.vms_evaluated + ' ' + t('vd2.evaluated', 'değerlendirildi') +
        '</a> · <a href="/vms?q=zafiyet:bilinmiyor">' + d.vms_unknown + ' ' + t('vd2.unknown', 'değerlendirilemedi') +
        '</a> · <a href="/vms?q=zafiyet:kapsamdisi">' + d.vms_skipped + ' ' + t('vd2.skipped', 'kapsam dışı') + '</a>');
    const ecoNames = [...new Set(Object.keys(d.by_ecosystem || {}).map(e => e.split(':')[0]))].sort();
    document.getElementById('vdBundleInfo').innerHTML = ecoNames.length
      ? '<i class="bi bi-box-seam"></i> ' + t('vd2.bundleHas', 'Paket bu sunucudaki verinin tamamını içerir:') + ' <b>' +
        App.esc(ecoNames.concat(d.kev ? ['CISA KEV'] : []).join(', ')) + '</b>. ' +
        t('vd2.bundleHas2', 'Yükleyen sunucuda kendi VM\'leriyle eşleştirilir; sonuçlar orada görünür.')
      : d.kev
        ? '<div class="alert alert-warning py-2 mb-0"><i class="bi bi-exclamation-triangle"></i> ' +
          t('vd2.bundleKevOnly', 'Bu sunucuda çekirdek verisi yok - paket yalnızca CISA KEV listesini içerir ve yüklendiği sunucuda hiçbir VM için bulgu üretmez. Önce "İndirilecek dağıtımlar"dan hedef sunucunun dağıtımlarını seçip "Şimdi indir" çalıştırın, sonra paketi alın.') + '</div>'
        : '<span class="text-muted">' + t('vd2.bundleEmpty', 'Henüz paketlenecek veri yok.') + '</span>';
    Settings.renderImportResult(job);
    document.getElementById('vdEcos').innerHTML = Object.keys(d.by_ecosystem || {}).length
      ? Object.entries(d.by_ecosystem).sort((a, b) => a[0].localeCompare(b[0])).map(([e, n]) =>
          '<tr><td>' + App.esc(e) + '</td><td class="text-end">' + n.toLocaleString() + '</td></tr>').join('')
      : '<tr><td colspan="2" class="text-muted small p-3">' + t('vd2.noData', 'Henüz veri yok.') + '</td></tr>';
    ['vdSyncBtn', 'vdKevBtn'].forEach(id => { document.getElementById(id).disabled = !!job.running; });
    clearTimeout(Settings._vdTimer);
    if (job.running) Settings._vdTimer = setTimeout(() => Settings.loadVuln(), 3000);
    else if (Settings._vdWasRunning) { Settings.loadSources(); Settings.loadUnverified(); }
    Settings._vdWasRunning = !!job.running;
  },

  /** After an upload: what the file contained and whether the VMs here got data. */
  renderImportResult(job) {
    const box = document.getElementById('vdImportResult');
    const m = job && job.kind === 'import' && !job.running ? job.message : null;
    if (!m || typeof m !== 'object' || job.ok === false) {
      box.classList.toggle('d-none', !(job && job.kind === 'import' && job.ok === false));
      if (job && job.kind === 'import' && job.ok === false)
        box.innerHTML = '<div class="alert alert-danger py-2 mb-0">' + App.esc(String(job.message || '')) + '</div>';
      return;
    }
    const nf = n => Number(n || 0).toLocaleString(window.I18N && I18N.lang === 'en' ? 'en' : 'tr');
    const lines = [];
    const typeTxt = {bundle: t('vd2.tBundle', 'Veri paketi'), 'osv-zip': 'OSV all.zip', 'osv-tar': 'OSV .tar.gz',
                     'osv-json': 'OSV JSON', kev: 'CISA KEV', msrc: t('vd2.tMsrc', 'Microsoft güncelleme verisi (CVRF)'),
                     'oracle-oval': 'Oracle OVAL', photon: 'Photon CVE'}[m.type] || m.type;
    if (m.contents) {
      const parts = Object.entries(m.contents).map(([k, v]) => k + ' ' + nf(v));
      lines.push('<b>' + App.esc(typeTxt) + '</b>' + (m.generated_at ? ' (' + App.fmtDate(m.generated_at) + ')' : '') + ': ' +
        (parts.length ? App.esc(parts.join(' · ')) : t('vd2.empty', 'boş')));
    } else {
      lines.push('<b>' + App.esc(typeTxt) + '</b>');
    }
    if (m.records != null) lines.push(t('vd2.newRecords', 'Yeni / güncellenen kayıt') + ': ' + nf(m.records) +
      (m.kept ? ' · ' + t('vd2.keptRecords', 'zaten yüklü (değişmedi)') + ': ' + nf(m.kept) : ''));
    if (m.match) lines.push(t('vd2.matched', 'Değerlendirilen VM') + ': ' + nf(m.vms_evaluated) + ' · ' +
      t('vd2.new', 'yeni bulgu') + ' ' + nf(m.match.new) + ' · ' + t('vd2.closed', 'kapanan') + ' ' + nf(m.match.closed));
    const kernelSources = Object.keys(m.contents || {}).filter(k => k !== 'CISA KEV');
    let cls = 'alert-success';
    if (m.contents && !kernelSources.length) {
      cls = 'alert-warning';
      lines.push(t('vd2.onlyKev', 'Dosyada çekirdek verisi yok (yalnızca KEV) - bu yüzden VM\'lerde değişiklik olmadı. İnternetli sunucuda dağıtımları seçip "Şimdi indir" ile veriyi indirin, paketi yeniden alın.'));
    } else if (m.records === 0 && m.kept) {
      lines.push(t('vd2.sameData', 'Paketteki veri zaten yüklüydü; yeni bir şey yok.'));
    }
    if ((m.missing || []).length) {
      cls = 'alert-warning';
      lines.push(t('vd2.stillMissing', 'Bu sunucuda VM\'i olup hâlâ verisi olmayan dağıtımlar:') + ' <b>' + m.missing.map(App.esc).join(', ') + '</b>');
    }
    box.innerHTML = '<div class="alert ' + cls + ' py-2 mb-0">' + lines.join('<br>') + '</div>';
    box.classList.remove('d-none');
  },

  /** Short text of a finished job result (import / sync dicts). */
  vdJobText(m) {
    if (!m || typeof m !== 'object') return m || '';
    const parts = [];
    if (m.records != null) parts.push('+' + m.records + ' ' + t('vd2.records', 'kayıt') +
      (m.kept ? ' · =' + m.kept : ''));
    if (m.kev && m.kev.kev != null) parts.push('KEV ' + (m.kev.kept ? '=' : m.kev.kev) +
      (m.kev.source ? ' (' + m.kev.source + ')' : ''));
    if (m.osv) parts.push('OSV ' + Object.keys(m.osv).filter(k => !m.osv[k].error).length + '/' + Object.keys(m.osv).length);
    if (m.match) parts.push(t('vd2.new', 'yeni bulgu') + ' ' + m.match.new + ' · ' + t('vd2.closed', 'kapanan') + ' ' + m.match.closed);
    const unk = (m.unrecognized || []).concat(...Object.values(m.osv || {}).map(x => x.unrecognized || []));
    if (unk.length) parts.push('⚠ ' + t('vd2.unrecognized', 'tanınmayan kayıtlar') + ': ' + unk.slice(0, 4).join(', '));
    return parts.join(' · ');
  },

  /** Which download hosts this server reaches (cisa.gov / GitHub / osv.dev). */
  async vdProbe() {
    const btn = document.getElementById('vdProbeBtn'), box = document.getElementById('vdProbe');
    btn.disabled = true;
    box.classList.remove('d-none');
    box.innerHTML = '<span class="spinner-border spinner-border-sm"></span> <span class="small text-muted">' +
      t('vd2.probing', 'Deneniyor…') + '</span>';
    let d;
    try { d = await App.api('/api/vulns/probe', {method: 'POST', body: {}}); }
    catch (e) { box.classList.add('d-none'); btn.disabled = false; return; }
    btn.disabled = false;
    box.innerHTML = '<table class="table table-sm small mb-0 vd-probe"><tbody>' + d.items.map(r =>
      '<tr><td class="text-muted text-nowrap">' + App.esc(r.group) + '</td>' +
      '<td class="text-nowrap" title="' + App.esc(r.url) + '">' + App.esc(r.name) + '</td>' +
      '<td class="text-nowrap">' + (r.ok ? '<span class="badge sp-badge sp-ok">' + t('vd2.reach', 'erişiliyor') + '</span>'
        : '<span class="badge sp-badge sp-eol">' + t('vd2.noReach', 'erişilemiyor') + '</span>') + '</td>' +
      '<td class="text-muted">' + App.esc(r.ok ? r.ms + ' ms' : r.detail) + '</td></tr>').join('') + '</tbody></table>';
    const iss = [...new Set(d.items.map(r => r.issuer).filter(Boolean))];
    if (iss.length) {
      box.innerHTML += '<div class="alert alert-warning small mt-2 mb-0"><i class="bi bi-shield-lock"></i> ' +
        t('vd2.caHint', 'Bu sunucuya gösterilen sertifikaları imzalayan:') + ' <b>' + iss.map(App.esc).join(', ') + '</b>. ' +
        t('vd2.caHint2', 'Bu, ağınızın SSL denetim sertifikası. Kök sertifikasını aşağıdaki "Kurum sertifikası" bölümünden yükleyin.') + '</div>';
    }
  },

  /* ---------- selectable OSV sources (phase 163) ---------- */
  _vdSrc: null,

  async loadSources() {
    let d;
    try { d = await App.api('/api/vulns/sources'); } catch (e) { return; }
    Settings._vdSrc = d;
    document.getElementById(d.mode === 'manual' ? 'vdModeManual' : 'vdModeAuto').checked = true;
    Settings.renderSources();
  },

  renderSources() {
    const d = Settings._vdSrc;
    const manual = document.getElementById('vdModeManual').checked;
    const admin = App.role() === 'admin';
    const size = {large: t('vd2.sizeLarge', 'büyük indirme (yüzlerce MB olabilir)'),
                  medium: t('vd2.sizeMedium', 'orta')};
    document.getElementById('vdSrcBody').innerHTML = d.rows.map(r => {
      // switching to "Choose" for the first time starts from the automatic picks
      const base = (d.mode === 'auto' && !d.manual.length) ? d.rows.filter(x => x.auto).map(x => x.name) : d.manual;
      const checked = manual ? base.includes(r.name) : r.auto;
      const notes = [];
      if (r.name === 'AlmaLinux') notes.push(t('vd2.noteAlma', 'RHEL ve Rocky VM\'leri de bununla eşleşir; osv.dev kapalıysa GitHub\'dan'));
      if (r.name === 'Red Hat' || r.name === 'Rocky Linux') notes.push(t('vd2.noteRh', 'isteğe bağlı - AlmaLinux verisi yeterli'));
      if (r.name === 'SUSE' || r.name === 'openSUSE') notes.push(t('vd2.noteSuse', 'yeni - biçim gerçek kayıtla doğrulanmadı'));
      if (r.name === 'Oracle Linux') notes.push(t('vd2.noteOracle', 'Oracle\'ın kendi OVAL verisi (linux.oracle.com) - UEK ve RHCK çekirdekleri'));
      if (r.name === 'Photon OS') notes.push(t('vd2.notePhoton', 'Broadcom\'un Photon CVE verisi (packages.broadcom.com)'));
      if (r.name === 'Windows') notes.push(t('vd2.noteWindows', 'Microsoft MSRC aylık güncellemeleri (api.msrc.microsoft.com), son 24 ay - yalnızca işletim sistemi, güncelleme numarası (UBR) gerekir'));
      if (r.size === 'large') notes.push(size.large);
      const vmTxt = r.vms ? '<b>' + r.vms + '</b>' + (r.vms_total > r.vms ? ' <span class="text-muted">/ ' + r.vms_total + '</span>' : '')
        : '<span class="text-muted">' + (r.vms_total ? '0 / ' + r.vms_total : '—') + '</span>';
      const dataTxt = r.cves ? r.cves.toLocaleString() + ' CVE'
        : (r.auto ? '<span class="badge sp-badge sp-eol">' + t('vd2.noDataShort', 'veri yok') + '</span>' : '<span class="text-muted">—</span>');
      return '<tr' + (checked ? '' : ' class="text-muted"') + '><td><input class="form-check-input vd-src" type="checkbox" value="' + App.esc(r.name) + '"' +
        (checked ? ' checked' : '') + (manual && admin ? '' : ' disabled') + '></td>' +
        '<td>' + App.esc(r.name) + (r.ecosystems.length ? ' <span class="text-muted small" title="' + App.esc(r.ecosystems.join(', ')) + '">(' + r.ecosystems.length + ' ' + (r.ecosystems.length === 1 ? t('vd2.release1', 'sürüm') : t('vd2.releases', 'sürüm')) + ')</span>' : '') + '</td>' +
        '<td class="text-end">' + vmTxt + '</td><td class="text-end">' + dataTxt + '</td>' +
        '<td class="small text-muted ps-4">' + App.esc(r.source || '—') + '</td>' +
        '<td class="small text-muted">' + App.esc(notes.join(' · ')) + '</td></tr>';
    }).join('');
    const warn = document.getElementById('vdSrcWarn');
    warn.classList.toggle('d-none', !d.missing.length);
    warn.innerHTML = d.missing.length ? '<i class="bi bi-exclamation-triangle"></i> ' +
      t('vd2.missing', 'Envanterde VM\'i olan ama verisi olmayan dağıtımlar:') + ' <b>' + d.missing.map(App.esc).join(', ') + '</b>. ' +
      t('vd2.missing2', '"Şimdi indir" ile indirin ya da internetli sunucudan bunları içeren bir paket yükleyin.') : '';
    document.getElementById('vdSrcSave').disabled = !admin;
  },

  vdModeChanged() { Settings.renderSources(); },

  /** Not-verifiable VMs grouped by reason (phase 170). */
  async loadUnverified() {
    let d;
    try { d = await App.api('/api/vulns/unverified'); } catch (e) { return; }
    const body = document.getElementById('vdUnvBody');
    if (!body) return;
    body.innerHTML = d.groups.length ? d.groups.map(g =>
      '<tr><td><div title="' + App.esc(g.detail || '') + '">' + App.esc(g.reason) + '</div>' +
        '<div class="small text-muted">' + g.examples.map(App.esc).join(', ') +
        (g.count > g.examples.length ? ' …' : '') + '</div></td>' +
      '<td class="text-end"><b>' + g.count + '</b></td>' +
      '<td class="small text-muted">' + App.esc(g.hint || '') + '</td></tr>').join('')
      : '<tr><td colspan="3" class="text-muted small p-3">' +
        t('vd2.unvNone', 'Değerlendirilemeyen VM yok.') + '</td></tr>';
  },

  async vdSrcSave() {
    const mode = document.getElementById('vdModeManual').checked ? 'manual' : 'auto';
    const manual = mode === 'manual'
      ? [...document.querySelectorAll('.vd-src:checked')].map(x => x.value) : (Settings._vdSrc.manual || []);
    try {
      Settings._vdSrc = await App.api('/api/vulns/sources', {method: 'PUT', body: {mode, manual}});
    } catch (e) { return; }
    App.toast(t('vd2.srcSaved', 'Kaydedildi.'));
    Settings.renderSources();
  },

  /* ---------- company CA for data downloads (phase 162) ---------- */
  async loadCa() {
    let d;
    try { d = await App.api('/api/vulns/ca'); } catch (e) { return; }
    const box = document.getElementById('vdCa');
    const parts = [];
    if (!d.sources.length) {
      parts.push('<span class="text-muted">' + t('vd2.caNone', 'Ek sertifika yok - yalnızca genel (herkese açık) kök sertifikalar kullanılıyor.') + '</span>');
    } else {
      parts.push(d.sources.map(s => '<div><i class="bi bi-file-earmark-lock"></i> ' +
        (s.uploaded ? t('vd2.caUploaded', 'Yüklenen dosya') : App.esc(s.path) + ' <span class="text-muted">(OUTBOUND_CA_BUNDLE)</span>') +
        ' · ' + s.count + ' ' + t('vd2.caCerts', 'sertifika') + '</div>').join(''));
      parts.push(d.extra.length
        ? '<div class="mt-1">' + t('vd2.caCompany', 'Kuruma özel olanlar:') + ' ' + d.extra.map(c =>
            '<span class="badge sp-badge sp-ext me-1" title="' + App.esc(t('vd2.caIssuer', 'Yayıncı') + ': ' + c.issuer + ' · SHA-256 ' + c.sha256) + '">' +
            App.esc(c.subject) + ' · ' + t('vd2.caUntil', 'bitiş') + ' ' + App.fmtDay(c.not_after) + '</span>').join('') + '</div>'
        : '<div class="mt-1 text-muted">' + t('vd2.caOnlyPublic', 'Dosyadaki sertifikaların hepsi zaten genel listede; SSL denetim sertifikası içermiyor olabilir.') + '</div>');
    }
    box.innerHTML = parts.join('');
    document.getElementById('vdCaDel').classList.toggle('d-none', !d.uploaded);
  },

  async vdCaUpload(input) {
    const f = input.files && input.files[0];
    input.value = '';
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    const res = await fetch('/api/vulns/ca', {method: 'POST', body: fd,
      headers: {'X-CSRF-Token': App.getCookie('csrf_token')}});
    let body = {};
    try { body = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) { App.toast(body.detail || ('HTTP ' + res.status), 'danger'); return; }
    App.toast(t('vd2.caSaved', 'Sertifika kaydedildi; "Kaynakları test et" ile deneyin.'));
    Settings.loadCa();
  },

  async vdCaRemove() {
    try { await App.api('/api/vulns/ca', {method: 'DELETE'}); } catch (e) { return; }
    Settings.loadCa();
  },

  vdMsg(ok, text) {
    const el = document.getElementById('vdMsg');
    el.className = 'small mt-2 ' + (ok ? 'text-success' : 'text-danger');
    el.textContent = text;
  },

  async vdSync(kevOnly) {
    try {
      await App.api('/api/vulns/sync' + (kevOnly ? '?kev_only=true' : ''), {method: 'POST', body: {}});
      Settings.vdMsg(true, t('vd2.started', 'Başladı; durum burada güncellenir.'));
    } catch (e) { return; }
    Settings.loadVuln();
  },

  /** Upload in pieces (< 1 MB each): a reverse proxy in front of the app
   *  often refuses larger request bodies with "413". */
  async vdImport(input) {
    const f = input.files && input.files[0];
    input.value = '';
    if (!f) return;
    const hdr = {'X-CSRF-Token': App.getCookie('csrf_token')};
    const fail = async (res, what) => {
      let msg = 'HTTP ' + res.status;
      try { msg = (await res.json()).detail || msg; } catch (e) {
        if (res.status === 413) msg = t('vd2.e413', 'Sunucunun önündeki proxy isteği çok büyük buldu (HTTP 413).');
      }
      Settings.vdMsg(false, (what ? what + ': ' : '') + msg);
    };
    let res = await fetch('/api/vulns/upload', {method: 'POST', body: JSON.stringify({size: f.size, name: f.name}),
      headers: Object.assign({'Content-Type': 'application/json'}, hdr)});
    if (!res.ok) return fail(res);
    const up = await res.json();
    const step = Math.min(up.chunk || 512 * 1024, 900 * 1024);
    for (let off = 0; off < f.size; off += step) {
      Settings.vdMsg(true, t('vd2.uploading', 'Yükleniyor…') + ' ' + f.name + ' · %' + Math.floor(off * 100 / f.size));
      let tries = 0;
      for (;;) {
        try {
          res = await fetch('/api/vulns/upload/' + up.upload_id + '?offset=' + off,
            {method: 'PUT', body: f.slice(off, off + step), headers: Object.assign({'Content-Type': 'application/octet-stream'}, hdr)});
          if (res.ok) break;
          if (res.status < 500 || ++tries >= 3) return fail(res);
        } catch (e) {
          if (++tries >= 3) { Settings.vdMsg(false, String(e)); return; }
        }
        await new Promise(r => setTimeout(r, 1000 * tries));
      }
    }
    res = await fetch('/api/vulns/upload/' + up.upload_id + '/finish', {method: 'POST',
      body: JSON.stringify({size: f.size, name: f.name}), headers: Object.assign({'Content-Type': 'application/json'}, hdr)});
    if (!res.ok) return fail(res);
    Settings.vdMsg(true, t('vd2.started', 'Başladı; durum burada güncellenir.'));
    Settings.loadVuln();
  },
};

Settings.loadUsers();
Settings.loadAudit();
Settings.loadSync();
Settings.loadLifecycle();
Settings.loadVuln();
Settings.loadSources();
Settings.loadUnverified();
Settings.loadCa();
document.getElementById('auditSearch').addEventListener('input', App.debounce(() => Settings.loadAudit(), 300));
document.getElementById('auditAction').addEventListener('change', () => Settings.loadAudit());
