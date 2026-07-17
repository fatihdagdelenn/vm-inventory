/**
 * datastores.js — Storage screen in the networks-page design language:
 * stat strip + view modes (Cards / By type / By node / Table).
 * Data is fetched ONCE; mode switches, grouping and table sorting are
 * client-side. Drill-down modals (host/VM lists) are unchanged.
 */
const DS = {
  items: [],
  mode: 'cards',
  sort: 'name',
  order: 'asc',

  async load() {
    const q = document.getElementById('dsSearch').value.trim();
    let data;
    try { data = await App.api('/api/datastores?q=' + encodeURIComponent(q)); }
    catch (e) { return; }
    DS.items = data.items || [];
    DS.renderStats();
    DS.render();
  },

  setMode(mode) {
    DS.mode = mode;
    document.querySelectorAll('.net-modes button').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    DS.render();
  },

  /* ---------- Stat strip ---------- */
  renderStats() {
    const it = DS.items;
    const cap = it.reduce((s, d) => s + (d.capacity_gb || 0), 0);
    const used = it.reduce((s, d) => s + (d.used_gb || 0), 0);
    const crit = it.filter(d => (d.usage_pct || 0) >= 90).length;
    const pct = cap ? Math.round(100 * used / cap) : 0;
    const stat = (icon, val, label, extra) =>
      '<div class="net-stat panel"><i class="bi ' + icon + '"></i>' +
      '<div><div class="net-stat-val">' + val + (extra || '') + '</div>' +
      '<div class="net-stat-label">' + label + '</div></div></div>';
    document.getElementById('dsStats').innerHTML =
      stat('bi-hdd-stack', it.length, 'Datastore') +
      stat('bi-database', App.fmtGb(cap), t('ds.stat.total', 'Toplam Kapasite')) +
      stat('bi-pie-chart', App.fmtGb(used),
           t('ds.stat.used', 'Kullanılan'),
           ' <span class="net-stat-sub">%' + pct + '</span>') +
      stat('bi-exclamation-triangle', crit, t('ds.stat.crit', 'Kritik (≥%90)'));
  },

  render() {
    const wrap = document.getElementById('dsGroups');
    if (!DS.items.length) {
      wrap.innerHTML = '<div class="net-empty panel"><i class="bi bi-hdd-stack"></i>' +
        '<div>' + t('vm.noResults', 'Sonuç bulunamadı.') + '</div></div>';
      document.getElementById('dsCount').textContent = '';
      return;
    }
    if (DS.mode === 'cards') DS.renderCards(wrap);
    else if (DS.mode === 'table') DS.renderTable(wrap);
    else DS.renderGroups(wrap);
    document.getElementById('dsCount').textContent = DS.items.length + ' datastore';
  },

  /* ---------- Shared cell builders ---------- */
  _usageBar(d) {
    const pct = d.usage_pct || 0;
    const cls = pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '';
    return '<div class="res-cell"><div class="res-top">' +
        App.fmtGb(d.used_gb) + ' / ' + App.fmtGb(d.capacity_gb) +
        ' <span class="res-pct">%' + pct + '</span></div>' +
      '<div class="usage-mini ' + cls + '" title="%' + pct + '">' +
        '<div style="width:' + Math.min(100, pct) + '%"></div></div></div>';
  },
  _pIcon(d) {
    return d.platform_type === 'vcenter'
      ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
      : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
  },
  _stBadge(d) {
    const stMap = {
      active: [t('ag.active','Aktif'), 'state-running'],
      inactive: [t('ag.passive','Pasif'), 'state-stopped'],
      maintenance: [t('st.maintenance','Bakım'), 'state-suspended'],
    };
    const st = stMap[d.status] || [d.status || '—', 'state-stopped'];
    return '<span class="state-badge ' + st[1] + '">' + App.esc(st[0]) + '</span>';
  },
  _cnt(d, n, kind) {
    return n > 0
      ? '<span class="badge text-bg-light border ds-count" style="cursor:pointer" ' +
        'onclick="DS.drill(' + d.id + ',\'' + kind + '\')" title="' + t('ds.viewDetails','Detayları gör') + '">' +
        n + ' <i class="bi bi-box-arrow-up-right"></i></span>'
      : '<span class="badge text-bg-light border">0</span>';
  },
  _sharedBadge(d) {
    return d.shared
      ? ' <span class="badge text-bg-light border" title="' + t('ds.sharedHint','Birden çok host/node tarafından paylaşılıyor') + '">' + t('ds.shared','paylaşımlı') + '</span>' : '';
  },

  /* ---------- Cards (default) ---------- */
  renderCards(wrap) {
    const cards = DS.items.slice().sort((a, b) =>
      (b.usage_pct || 0) - (a.usage_pct || 0) || (a.name || '').localeCompare(b.name || '', 'tr'));
    wrap.innerHTML = '<div class="net-cards">' + cards.map(d =>
      '<div class="net-card panel ds-card">' +
        '<div class="net-card-head">' +
          '<span class="net-card-name" title="' + App.esc(d.name) + '">' + App.esc(d.name) + '</span>' +
          DS._stBadge(d) +
        '</div>' +
        '<div class="net-card-meta">' +
          '<span class="net-chip">' + DS._pIcon(d) + ' ' + App.esc(d.platform || '—') + '</span>' +
          (d.type ? '<span class="net-chip">' + App.esc(d.type) + '</span>' : '') +
          (d.node ? '<span class="net-chip"><i class="bi bi-hdd-rack"></i> ' + App.esc(d.node) + '</span>' : '') +
          (d.shared ? '<span class="net-chip">' + t('ds.shared','paylaşımlı') + '</span>' : '') +
        '</div>' +
        DS._usageBar(d) +
        '<div class="net-card-foot">' +
          '<span class="small text-muted">Host ' + DS._cnt(d, d.host_count, 'host') + '</span>' +
          '<span class="small text-muted">VM ' + DS._cnt(d, d.vm_count, 'vm') + '</span>' +
        '</div>' +
      '</div>').join('') + '</div>';
  },

  /* ---------- Accordion groups (type / node) ---------- */
  renderGroups(wrap) {
    const keyFn = DS.mode === 'type'
      ? (d => (d.type || '').trim() || t('ds.noType','(tip yok)'))
      : (d => (d.node || '').trim() || t('ds.sharedGroup','Paylaşımlı / merkezi'));
    const groups = {};
    DS.items.forEach(d => { const k = keyFn(d); (groups[k] = groups[k] || []).push(d); });
    const keys = Object.keys(groups).sort((a, b) => a.localeCompare(b, 'tr'));
    const open = keys.length === 1 ? ' open' : '';
    wrap.innerHTML = keys.map(k => {
      const list = groups[k];
      const cap = list.reduce((s, d) => s + (d.capacity_gb || 0), 0);
      const used = list.reduce((s, d) => s + (d.used_gb || 0), 0);
      const pct = cap ? Math.round(100 * used / cap) : 0;
      return '<details class="net-group panel"' + open + '>' +
        '<summary>' +
          '<span class="net-group-title"><i class="bi ' +
            (DS.mode === 'type' ? 'bi-tags' : 'bi-hdd-rack') + '"></i> ' + App.esc(k) + '</span>' +
          '<span class="net-group-meta">' + App.fmtGb(cap) + ' · %' + pct + '</span>' +
          '<span class="net-group-count">' + list.length + '</span>' +
        '</summary>' +
        '<div class="table-responsive">' + DS._table(list, false) + '</div>' +
      '</details>';
    }).join('');
  },

  /* ---------- Sortable table mode ---------- */
  renderTable(wrap) {
    const dir = DS.order === 'asc' ? 1 : -1;
    const key = DS.sort;
    const val = d => key === 'usage' ? (d.usage_pct || 0)
      : (typeof d[key] === 'number' ? d[key] : String(d[key] || '').toLocaleLowerCase('tr'));
    const rows = DS.items.slice().sort((a, b) => {
      const x = val(a), y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    wrap.innerHTML = '<div class="card panel"><div class="table-responsive">' +
      DS._table(rows, true) + '</div></div>';
    wrap.querySelectorAll('th.sortable').forEach(th =>
      th.addEventListener('click', () => DS.setSort(th.dataset.sort)));
  },

  _table(list, sortable) {
    const th = (label, key) => sortable
      ? '<th data-sort="' + key + '" class="sortable' +
        (DS.sort === key ? (DS.order === 'asc' ? ' sorted-asc' : ' sorted-desc') : '') + '">' + label + '</th>'
      : '<th>' + label + '</th>';
    return '<table class="table table-hover align-middle mb-0"><thead><tr>' +
      th('Datastore', 'name') + th('Node', 'node') + th('Platform', 'platform') +
      th(t('th.type','Tip'), 'type') + th(t('ds.capacity','Kapasite'), 'capacity_gb') +
      th(t('ds.usage','Doluluk'), 'usage') + th('Host', 'host_count') +
      th('VM', 'vm_count') + th(t('th.status','Durum'), 'status') +
      '</tr></thead><tbody>' +
      list.map(d => '<tr>' +
        '<td><strong>' + App.esc(d.name) + '</strong>' + DS._sharedBadge(d) + '</td>' +
        '<td class="small text-muted">' + App.esc(d.node || '—') + '</td>' +
        '<td>' + DS._pIcon(d) + ' <span class="small">' + App.esc(d.platform) + '</span></td>' +
        '<td class="small">' + App.esc(d.type || '—') + '</td>' +
        '<td class="text-nowrap">' + App.fmtGb(d.capacity_gb) + '</td>' +
        '<td style="min-width:170px">' + DS._usageBar(d) + '</td>' +
        '<td>' + DS._cnt(d, d.host_count, 'host') + '</td>' +
        '<td>' + DS._cnt(d, d.vm_count, 'vm') + '</td>' +
        '<td>' + DS._stBadge(d) + '</td>' +
      '</tr>').join('') + '</tbody></table>';
  },

  setSort(col) {
    if (DS.sort === col) DS.order = (DS.order === 'asc' ? 'desc' : 'asc');
    else { DS.sort = col; DS.order = 'asc'; }
    DS.render();
  },

  /** Host/VM sayısına tıklanınca ortak modallarda listeyi göster. */
  async drill(dsId, kind) {
    let d;
    try { d = await App.api('/api/datastores/' + dsId); } catch (e) { return; }
    if (kind === 'vm') App.showVmList(d.name + ' — ' + t('nav.vms','Sanal Makineler'), d.vms);
    else App.showHostList(d.name + ' — ' + t('nav.hosts',"Host'lar"), d.hosts);
  },
};

(function () {
  document.getElementById('dsSearch').addEventListener('input', App.debounce(() => DS.load(), 300));
  document.querySelectorAll('.net-modes button').forEach(b =>
    b.addEventListener('click', () => DS.setMode(b.dataset.mode)));
  DS.load();
})();
