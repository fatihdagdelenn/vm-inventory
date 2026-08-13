/* Physical inventory — manual CRUD for servers, storage, SAN switches, backup
   appliances. Single form; CPU/RAM/OS fields show only for servers. */
const Physical = {
  items: [],
  filterType: '',
  filterLoc: '',
  q: '',
  sortKey: 'name',
  sortDir: 1,   // 1 asc, -1 desc

  TYPES: {
    server:     { i: 'server',     c: 'text-bg-primary',   k: 'ph.t.server' },
    storage:    { i: 'hdd-stack',  c: 'text-bg-info',      k: 'ph.t.storage' },
    san_switch: { i: 'diagram-3',  c: 'text-bg-warning',   k: 'ph.t.san_switch' },
    backup:     { i: 'archive',    c: 'text-bg-secondary', k: 'ph.t.backup' },
  },
  STATUS: {
    active:  { c: 'text-bg-success',        k: 'ph.s.active' },
    passive: { c: 'text-bg-secondary',      k: 'ph.s.passive' },
    faulty:  { c: 'text-bg-danger',         k: 'ph.s.faulty' },
    spare:   { c: 'text-bg-info',           k: 'ph.s.spare' },
    retired: { c: 'text-bg-dark',           k: 'ph.s.retired' },
  },

  typeLabel(t2) { const m = Physical.TYPES[t2]; return m ? window.t(m.k, t2) : t2; },
  statusLabel(s) { const m = Physical.STATUS[s]; return m ? window.t(m.k, s) : s; },

  async load() {
    let data;
    const qs = new URLSearchParams();
    if (Physical.q) qs.set('q', Physical.q);
    if (Physical.filterType) qs.set('device_type', Physical.filterType);
    if (Physical.filterLoc) qs.set('location', Physical.filterLoc);
    try { data = await App.api('/api/physical?' + qs.toString()); } catch (e) { return; }
    Physical.items = data.items || [];
    Physical.fillLocations(data.locations || []);
    Physical.renderStats(data.counts || {}, data.total || 0);
    Physical.renderTable();
  },

  fillLocations(locs) {
    // Filter dropdown (preserve current selection) + form datalist
    const sel = document.getElementById('phLocFilter');
    if (sel) {
      const cur = Physical.filterLoc;
      sel.innerHTML = '<option value="">' + window.t('ph.allLocations', 'Tüm lokasyonlar') + '</option>' +
        locs.map(l => '<option value="' + App.esc(l) + '"' + (l === cur ? ' selected' : '') + '>' + App.esc(l) + '</option>').join('');
    }
    const dl = document.getElementById('phLocList');
    if (dl) dl.innerHTML = locs.map(l => '<option value="' + App.esc(l) + '">').join('');
  },

  renderStats(counts, total) {
    const el = document.getElementById('phStats');
    const card = (icon, val, labelKey, labelTr) =>
      '<div class="net-stat card panel"><i class="bi bi-' + icon + '"></i>' +
      '<div><div class="net-stat-val">' + val + '</div>' +
      '<div class="net-stat-label" data-i18n="' + labelKey + '">' + labelTr + '</div></div></div>';
    el.innerHTML =
      card('hdd-network', total, 'ph.total', 'Toplam Cihaz') +
      card('server', counts.server || 0, 'ph.t.server', 'Fiziksel Sunucu') +
      card('hdd-stack', counts.storage || 0, 'ph.t.storage', 'Storage') +
      card('diagram-3', counts.san_switch || 0, 'ph.t.san_switch', 'SAN Switch') +
      card('archive', counts.backup || 0, 'ph.t.backup', 'Yedekleme');
    if (window.I18N) window.I18N.apply(el);
  },

  sortVal(d, key) {
    if (key === 'specs') return (d.device_type === 'server' ? (d.ram_gb || 0) : -1);
    if (key === 'device_type') return Physical.typeLabel(d.device_type);
    if (key === 'status') return Physical.statusLabel(d.status);
    const v = d[key];
    return v == null ? '' : v;
  },

  sortItems() {
    const k = Physical.sortKey, dir = Physical.sortDir;
    Physical.items.sort((a, b) => {
      let va = Physical.sortVal(a, k), vb = Physical.sortVal(b, k);
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
      va = String(va).toLocaleLowerCase('tr'); vb = String(vb).toLocaleLowerCase('tr');
      return va < vb ? -dir : va > vb ? dir : 0;
    });
  },

  renderTable() {
    const body = document.getElementById('phBody');
    if (!Physical.items.length) {
      body.innerHTML = '<tr><td colspan="10" class="text-center text-muted p-4">' +
        window.t('ph.empty', 'Kayıt yok. "Cihaz Ekle" ile başlayın.') + '</td></tr>';
      Physical.markSort();
      return;
    }
    Physical.sortItems();
    const canEdit = document.querySelector('[onclick^="Physical.openForm"]') !== null;
    body.innerHTML = Physical.items.map(d => {
      const tm = Physical.TYPES[d.device_type] || {};
      const sm = Physical.STATUS[d.status] || {};
      const specs = d.device_type === 'server'
        ? [(d.cpu || ''), (d.ram_gb ? d.ram_gb + ' GB' : '')].filter(Boolean).join(' · ') || '—'
        : '—';
      const actions = canEdit
        ? '<button class="btn btn-sm btn-link p-0 me-2" title="' + window.t('action.edit', 'Düzenle') +
            '" onclick=\'Physical.openForm(' + d.id + ')\'><i class="bi bi-pencil"></i></button>' +
          '<button class="btn btn-sm btn-link p-0 text-danger" title="' + window.t('action.delete', 'Sil') +
            '" onclick="Physical.remove(' + d.id + ')"><i class="bi bi-trash"></i></button>'
        : '';
      return '<tr>' +
        '<td><span class="badge ' + (tm.c || 'text-bg-secondary') + '"><i class="bi bi-' + (tm.i || 'box') + '"></i> ' + App.esc(Physical.typeLabel(d.device_type)) + '</span></td>' +
        '<td class="fw-semibold">' + App.esc(d.name) + '</td>' +
        '<td>' + App.esc(d.location || '—') + '</td>' +
        '<td><span class="badge ' + (sm.c || 'text-bg-secondary') + '">' + App.esc(Physical.statusLabel(d.status)) + '</span></td>' +
        '<td>' + App.esc(d.mgmt_ip || '—') + '</td>' +
        '<td>' + App.esc(d.ilo_ip || '—') + '</td>' +
        '<td>' + App.esc(d.brand || '—') + '</td>' +
        '<td>' + App.esc(d.model || '—') + '</td>' +
        '<td class="small text-muted">' + App.esc(specs) + '</td>' +
        '<td class="text-end text-nowrap">' + actions + '</td>' +
        '</tr>';
    }).join('');
    Physical.markSort();
  },

  markSort() {
    document.querySelectorAll('#phTable th.ph-sort').forEach(th => {
      const on = th.dataset.sort === Physical.sortKey;
      th.classList.toggle('sorted', on);
      let ic = th.querySelector('.sort-ic');
      if (!ic) { ic = document.createElement('i'); ic.className = 'sort-ic bi'; th.appendChild(document.createTextNode(' ')); th.appendChild(ic); }
      ic.className = 'sort-ic bi ' + (on ? (Physical.sortDir === 1 ? 'bi-caret-up-fill' : 'bi-caret-down-fill') : 'bi-arrow-down-up');
    });
  },

  toggleServerFields() {
    const type = document.querySelector('input[name="phType"]:checked').value;
    document.getElementById('phServerFields').style.display = type === 'server' ? '' : 'none';
  },

  openForm(id) {
    const d = id ? Physical.items.find(x => x.id === id) : null;
    document.getElementById('phId').value = d ? d.id : '';
    document.getElementById('phModalTitle').textContent =
      d ? window.t('ph.edit', 'Cihaz Düzenle') : window.t('ph.add', 'Cihaz Ekle');
    const type = d ? d.device_type : 'server';
    document.getElementById('pt_' + type).checked = true;
    const set = (f, v) => { document.getElementById('f_' + f).value = v == null ? '' : v; };
    set('name', d && d.name); set('location', d && d.location);
    set('mgmt_ip', d && d.mgmt_ip); set('ilo_ip', d && d.ilo_ip);
    set('brand', d && d.brand); set('model', d && d.model);
    set('serial_no', d && d.serial_no); set('cpu', d && d.cpu);
    set('ram_gb', d && d.ram_gb); set('os', d && d.os); set('notes', d && d.notes);
    document.getElementById('f_status').value = (d && d.status) || 'active';
    Physical.toggleServerFields();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('phModal')).show();
  },

  async save() {
    const val = f => document.getElementById('f_' + f).value.trim();
    const payload = {
      device_type: document.querySelector('input[name="phType"]:checked').value,
      name: val('name'), location: val('location'), status: document.getElementById('f_status').value,
      mgmt_ip: val('mgmt_ip'), ilo_ip: val('ilo_ip'), brand: val('brand'),
      model: val('model'), serial_no: val('serial_no'), cpu: val('cpu'),
      ram_gb: val('ram_gb'), os: val('os'), notes: val('notes'),
    };
    if (!payload.name) { App.toast(window.t('ph.nameRequired', 'Ad zorunludur'), 'danger'); return; }
    const id = document.getElementById('phId').value;
    try {
      await App.api(id ? '/api/physical/' + id : '/api/physical',
                    { method: id ? 'PUT' : 'POST', body: payload });
    } catch (e) { return; }
    bootstrap.Modal.getInstance(document.getElementById('phModal')).hide();
    App.toast(window.t('ph.saved', 'Kaydedildi'), 'success');
    Physical.load();
  },

  async remove(id) {
    const d = Physical.items.find(x => x.id === id);
    if (!confirm(window.t('ph.confirmDelete', 'Bu cihazı silmek istediğinize emin misiniz?') +
                 '\n\n' + (d ? d.name : ''))) return;
    try { await App.api('/api/physical/' + id, { method: 'DELETE' }); } catch (e) { return; }
    App.toast(window.t('ph.deleted', 'Silindi'), 'success');
    Physical.load();
  },

  async showHistory() {
    let data;
    try { data = await App.api('/api/physical/history'); } catch (e) { return; }
    const body = document.getElementById('phHistBody');
    const AL = { created: window.t('ct.created', 'Eklendi'),
                 updated: window.t('ct.updated', 'Güncellendi'),
                 deleted: window.t('ct.deleted', 'Silindi') };
    const AC = { created: 'text-bg-success', updated: 'text-bg-info', deleted: 'text-bg-danger' };
    body.innerHTML = (data.items || []).length ? data.items.map(h => {
      let ch = '—';
      if (h.changes) {
        ch = Object.entries(h.changes).slice(0, 6).map(([f, ov]) =>
          '<code>' + App.esc(f) + '</code>: ' + App.esc(String(ov[0] ?? '∅')) +
          ' → ' + App.esc(String(ov[1] ?? '∅'))).join('<br>');
      }
      return '<tr><td class="small text-nowrap">' + App.esc((h.changed_at || '').replace('T', ' ').slice(0, 16)) + '</td>' +
        '<td><span class="badge ' + (AC[h.action] || 'text-bg-secondary') + '">' + (AL[h.action] || h.action) + '</span></td>' +
        '<td>' + App.esc(h.device_name || '—') + '</td>' +
        '<td>' + App.esc(h.actor || '—') + '</td>' +
        '<td class="small">' + ch + '</td></tr>';
    }).join('') : '<tr><td colspan="5" class="text-center text-muted p-4">' +
      window.t('ph.noHistory', 'Geçmiş kaydı yok.') + '</td></tr>';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('phHistModal')).show();
  },

  export(fmt) {
    const qs = new URLSearchParams({ fmt });
    if (Physical.q) qs.set('q', Physical.q);
    if (Physical.filterType) qs.set('device_type', Physical.filterType);
    if (Physical.filterLoc) qs.set('location', Physical.filterLoc);
    location = '/api/physical/export?' + qs.toString();
  },

  init() {
    document.getElementById('phSearch').addEventListener('input', e => {
      Physical.q = e.target.value.trim();
      clearTimeout(Physical._t);
      Physical._t = setTimeout(() => Physical.load(), 250);
    });
    document.querySelectorAll('#phTypeFilter [data-type]').forEach(b =>
      b.addEventListener('click', () => {
        document.querySelectorAll('#phTypeFilter [data-type]').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        Physical.filterType = b.dataset.type;
        Physical.load();
      }));
    const loc = document.getElementById('phLocFilter');
    if (loc) loc.addEventListener('change', e => {
      Physical.filterLoc = e.target.value; Physical.load();
    });
    // Sortable columns: click toggles asc/desc; re-render locally (no refetch)
    document.querySelectorAll('#phTable th.ph-sort').forEach(th =>
      th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (Physical.sortKey === k) Physical.sortDir *= -1;
        else { Physical.sortKey = k; Physical.sortDir = 1; }
        Physical.renderTable();
      }));
    document.querySelectorAll('input[name="phType"]').forEach(r =>
      r.addEventListener('change', Physical.toggleServerFields));
    Physical.load();
  },
};
document.addEventListener('DOMContentLoaded', Physical.init);
