/**
 * networks.js — Network inventory.
 * Default mode "Networks": identical networks (same platform+name+vlan+vswitch)
 * across hosts are DEDUPLICATED into one card with host chips + VM count
 * (kills the per-node repetition that made the page feel crowded).
 * Accordion modes (Host / Cluster / VLAN / Physical NICs) are kept but start
 * COLLAPSED with a rich summary line, so the page opens calm and scannable.
 * Data is fetched once; grouping/mode switches are client-side.
 */
const Networks = {
  items: [],
  mode: 'net',

  async load(q = '') {
    let data;
    try { data = await App.api('/api/networks?q=' + encodeURIComponent(q)); }
    catch (e) { return; }
    Networks.items = data.items || [];
    Networks.renderStats();
    Networks.render();
  },

  setMode(mode) {
    Networks.mode = mode;
    document.querySelectorAll('.net-modes button').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    document.getElementById('netAcc').hidden = (mode === 'net');
    Networks.render();
  },

  /* ---------- Top stat strip ---------- */
  renderStats() {
    const nets = Networks.items.filter(n => n.kind !== 'pnic');
    const uniq = new Set(nets.map(Networks._dedupKey));
    const vlans = new Set(nets.map(n => (n.vlan || '').toString().trim()).filter(Boolean));
    const sw = new Set(nets.map(n => (n.vswitch || '').trim()).filter(Boolean));
    const pnics = Networks.items.filter(n => n.kind === 'pnic').length;
    const stat = (icon, val, label) =>
      '<div class="net-stat panel"><i class="bi ' + icon + '"></i>' +
      '<div><div class="net-stat-val">' + val + '</div>' +
      '<div class="net-stat-label">' + label + '</div></div></div>';
    document.getElementById('netStats').innerHTML =
      stat('bi-hdd-network', uniq.size, t('nt.stat.nets', 'Ağ')) +
      stat('bi-tags', vlans.size, 'VLAN') +
      stat('bi-diagram-2', sw.size, 'vSwitch / Bridge') +
      stat('bi-ethernet', pnics, t('nt.stat.pnics', 'Fiziksel NIC'));
  },

  _dedupKey(n) {
    return [n.platform, n.name, n.vlan || '', n.vswitch || '', n.kind].join('|');
  },

  /** Deep-link to the VM list using the FIELD syntax the VM search actually
   *  supports: network:"<name>" (quoted - portgroup names may contain spaces).
   *  Plain q=<name> only scans name/ip/os columns, not the networks column. */
  _vmsUrl(name) {
    return '/vms?q=' + encodeURIComponent('network:"' + String(name || '').replace(/"/g, '') + '"');
  },

  /** Grouping (key fn, empty label, pnic rows?) for the accordion modes. */
  _grouping() {
    switch (Networks.mode) {
      case 'cluster': return { key: n => n.cluster, empty: t('nt.noCluster','(cluster atanmamış)'), pnic: false };
      case 'vlan':    return { key: n => (n.vlan || ''), empty: t('nt.noVlan','VLAN yok / native'), pnic: false };
      case 'pnic':    return { key: n => n.host_name, empty: t('nt.noHost','(host atanmamış)'), pnic: true };
      default:        return { key: n => n.host_name, empty: t('nt.noHost','(host atanmamış)'), pnic: false };
    }
  },

  render() {
    if (Networks.mode === 'net') { Networks.renderCards(); return; }
    const wrap = document.getElementById('netGroups');
    const g = Networks._grouping();
    const rows = Networks.items.filter(n =>
      g.pnic ? n.kind === 'pnic' : n.kind !== 'pnic');
    if (!rows.length) { wrap.innerHTML = Networks._empty(); return; }

    const groups = {};
    rows.forEach(n => {
      const k = (g.key(n) || '').toString().trim() || g.empty;
      (groups[k] = groups[k] || []).push(n);
    });
    const keys = Object.keys(groups).sort((a, b) => {
      const na = parseInt(a, 10), nb = parseInt(b, 10);
      if (!isNaN(na) && !isNaN(nb)) return na - nb;
      return a.localeCompare(b, 'tr');
    });
    // Collapsed by default: a single group opens itself, more stay closed.
    const open = keys.length === 1 ? ' open' : '';
    wrap.innerHTML = keys.map(k =>
      '<details class="net-group panel"' + open + '>' +
        '<summary>' +
          '<span class="net-group-title">' + Networks._groupIcon() + ' ' + App.esc(k) + '</span>' +
          '<span class="net-group-meta">' + Networks._groupMeta(groups[k], g.pnic) + '</span>' +
          '<span class="net-group-count">' + groups[k].length + '</span>' +
        '</summary>' +
        '<div class="table-responsive">' +
          (g.pnic ? Networks._pnicTable(groups[k]) : Networks._netTable(groups[k])) +
        '</div>' +
      '</details>').join('');
  },

  /** Quick facts on the closed summary line, so opening is optional. */
  _groupMeta(list, pnic) {
    if (pnic) {
      const up = list.filter(n => n.link_speed).length;
      return up ? up + ' ' + t('nt.linked', 'bağlantılı') : '';
    }
    const vl = new Set(list.map(n => (n.vlan || '').toString().trim()).filter(Boolean)).size;
    const vms = list.reduce((s, n) => s + (n.vm_count || 0), 0);
    const parts = [];
    if (vl) parts.push(vl + ' VLAN');
    if (vms) parts.push(vms + ' VM');
    return parts.join(' · ');
  },

  /* ---------- "Networks" mode: deduplicated card grid ---------- */
  renderCards() {
    const wrap = document.getElementById('netGroups');
    const nets = Networks.items.filter(n => n.kind !== 'pnic');
    if (!nets.length) { wrap.innerHTML = Networks._empty(); return; }

    const map = {};
    nets.forEach(n => {
      const k = Networks._dedupKey(n);
      if (!map[k]) map[k] = Object.assign({ hosts: new Set() }, n);
      if (n.host_name) map[k].hosts.add(n.host_name);
      if (!map[k].subnet && n.subnet) map[k].subnet = n.subnet;
    });
    const cards = Object.values(map).sort((a, b) =>
      (a.name || '').localeCompare(b.name || '', 'tr'));

    wrap.innerHTML = '<div class="net-cards">' + cards.map(c => {
      const hosts = Array.from(c.hosts).sort();
      const shown = hosts.slice(0, 3);
      const more = hosts.length - shown.length;
      const hostChips = shown.map(h =>
        '<span class="net-chip" title="' + App.esc(h) + '">' + App.esc(h) + '</span>').join('') +
        (more > 0 ? '<span class="net-chip net-chip-more" title="' +
          App.esc(hosts.slice(3).join(', ')) + '">+' + more + '</span>' : '');
      const vmLink = c.vm_count
        ? '<a class="net-vms" href="' + Networks._vmsUrl(c.name) + '" title="' +
            t('nt.showVms', 'VM listesinde göster') + '">' +
            '<i class="bi bi-display"></i> ' + c.vm_count + ' VM</a>'
        : '<span class="net-vms muted"><i class="bi bi-display"></i> 0 VM</span>';
      return '<div class="net-card panel">' +
        '<div class="net-card-head">' +
          '<span class="net-card-name" title="' + App.esc(c.name || '') + '">' +
            App.esc(c.name || '—') + '</span>' + Networks._kindBadge(c.kind) +
        '</div>' +
        '<div class="net-card-meta">' +
          (c.vlan ? '<span class="net-chip net-chip-vlan">VLAN ' + App.esc(c.vlan) + '</span>' : '') +
          (c.vswitch ? '<span class="net-chip" title="vSwitch / Bridge"><i class="bi bi-diagram-2"></i> ' + App.esc(c.vswitch) + '</span>' : '') +
          (c.subnet ? '<span class="net-chip mono" title="IP Subnet">' + App.esc(c.subnet) + '</span>' : '') +
        '</div>' +
        '<div class="net-card-foot">' +
          '<span class="net-hosts" title="Host">' +
            '<i class="bi bi-hdd-rack"></i>' + (hostChips || '—') + '</span>' +
          vmLink +
        '</div>' +
        '<div class="net-card-platform">' + App.esc(c.platform || '') + '</div>' +
      '</div>';
    }).join('') + '</div>';
  },

  _empty() {
    return '<div class="net-empty panel"><i class="bi bi-hdd-network"></i>' +
      '<div>' + t('vm.noResults', 'Sonuç bulunamadı.') + '</div></div>';
  },

  _groupIcon() {
    const m = { host: 'bi-hdd-rack', cluster: 'bi-diagram-3',
                vlan: 'bi-tags', pnic: 'bi-ethernet' };
    return '<i class="bi ' + (m[Networks.mode] || 'bi-hdd-network') + '"></i>';
  },

  _kindBadge(kind) {
    const map = { portgroup: ['Port Group', 'info'], bridge: ['Bridge', 'secondary'],
                  vnet: ['SDN vnet', 'primary'], pnic: ['NIC', 'dark'] };
    const x = map[kind] || [kind || '—', 'light'];
    return '<span class="badge text-bg-' + x[1] + ' net-kind">' + App.esc(x[0]) + '</span>';
  },

  _netTable(list) {
    const mode = Networks.mode;
    const showVlan = mode !== 'vlan';
    const showHost = mode !== 'host';
    const head = '<tr>' +
      '<th>' + t('hi.f.name','Ad') + '</th>' +
      (showVlan ? '<th>VLAN</th>' : '') +
      '<th>vSwitch / Bridge</th><th>IP Subnet</th><th>VM</th>' +
      (showHost ? '<th>Host</th>' : '') +
      '<th>Platform</th></tr>';
    const body = list.map(n => '<tr>' +
      '<td><strong>' + App.esc(n.name || '—') + '</strong> ' + Networks._kindBadge(n.kind) +
        (n.portgroup && n.portgroup !== n.name
          ? '<div class="small text-muted">' + App.esc(n.portgroup) + '</div>' : '') + '</td>' +
      (showVlan ? '<td>' + (n.vlan ? '<span class="net-chip net-chip-vlan">VLAN ' + App.esc(n.vlan) + '</span>' : '—') + '</td>' : '') +
      '<td>' + App.esc(n.vswitch || '—') + '</td>' +
      '<td class="mono small">' + App.esc(n.subnet || '—') + '</td>' +
      '<td>' + (n.vm_count
          ? '<a class="net-vms" href="' + Networks._vmsUrl(n.name) + '">' + n.vm_count + '</a>'
          : '<span class="text-muted">0</span>') + '</td>' +
      (showHost ? '<td class="small">' + App.esc(n.host_name || '—') + '</td>' : '') +
      '<td class="small text-muted">' + App.esc(n.platform || '—') + '</td></tr>').join('');
    return '<table class="table table-hover align-middle mb-0"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  },

  _pnicTable(list) {
    const body = list.map(n => '<tr>' +
      '<td><strong>' + App.esc(n.name || '—') + '</strong></td>' +
      '<td class="small mono">' + App.esc(n.mac || '—') + '</td>' +
      '<td>' + App.esc(n.link_speed || '—') + '</td>' +
      '<td>' + (n.vswitch === 'bond' ? '<span class="badge text-bg-secondary">Bond</span>' : t('nt.physical','Fiziksel')) + '</td>' +
      '<td class="small text-muted">' + App.esc(n.platform || '—') + '</td></tr>').join('');
    return '<table class="table table-hover align-middle mb-0"><thead><tr>' +
      '<th>' + t('nt.nic','Kart') + '</th><th>MAC</th><th>' + t('nt.speed','Hız') + '</th><th>' + t('th.type','Tür') + '</th><th>Platform</th>' +
      '</tr></thead><tbody>' + body + '</tbody></table>';
  },

  _toggleAll(open) {
    document.querySelectorAll('#netGroups details').forEach(d => d.open = open);
  },
};

(function () {
  const input = document.getElementById('netSearch');
  input.addEventListener('input', App.debounce(() => Networks.load(input.value.trim()), 300));
  document.querySelectorAll('.net-modes button').forEach(b =>
    b.addEventListener('click', () => Networks.setMode(b.dataset.mode)));
  document.getElementById('netExpandAll').addEventListener('click', () => Networks._toggleAll(true));
  document.getElementById('netCollapseAll').addEventListener('click', () => Networks._toggleAll(false));
  Networks.load();
})();
