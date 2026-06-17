/**
 * networks.js — Ağ envanteri.
 * Dört gruplama modu (Host / Cluster / VLAN / Fiziksel Kartlar), her grup
 * açılır-kapanır akordeon (<details>). Veriler tek çağrıda alınır; gruplama
 * ve mod değişimi istemci tarafında yapılır (yeniden istek atmadan).
 */
const Networks = {
  items: [],
  mode: 'host',

  async load(q = '') {
    let data;
    try { data = await App.api('/api/networks?q=' + encodeURIComponent(q)); }
    catch (e) { return; }
    Networks.items = data.items || [];
    Networks.render();
  },

  setMode(mode) {
    Networks.mode = mode;
    document.querySelectorAll('.net-modes button').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    Networks.render();
  },

  /** Mod için (anahtar fonksiyonu, boş etiket, satır türü) belirle. */
  _grouping() {
    switch (Networks.mode) {
      case 'cluster': return { key: n => n.cluster, empty: '(cluster atanmamış)', pnic: false };
      case 'vlan':    return { key: n => (n.vlan || ''), empty: 'VLAN yok / native', pnic: false };
      case 'pnic':    return { key: n => n.host_name, empty: '(host atanmamış)', pnic: true };
      default:        return { key: n => n.host_name, empty: '(host atanmamış)', pnic: false };
    }
  },

  render() {
    const wrap = document.getElementById('netGroups');
    const g = Networks._grouping();
    const rows = Networks.items.filter(n =>
      g.pnic ? n.kind === 'pnic' : n.kind !== 'pnic');

    if (!rows.length) {
      wrap.innerHTML = '<div class="text-center text-muted p-4">Sonuç bulunamadı.</div>';
      return;
    }

    // Gruplara böl
    const groups = {};
    rows.forEach(n => {
      const k = (g.key(n) || '').toString().trim() || g.empty;
      (groups[k] = groups[k] || []).push(n);
    });

    // Anahtarları sırala (VLAN modunda sayısal)
    const keys = Object.keys(groups).sort((a, b) => {
      const na = parseInt(a, 10), nb = parseInt(b, 10);
      if (!isNaN(na) && !isNaN(nb)) return na - nb;
      return a.localeCompare(b, 'tr');
    });

    wrap.innerHTML = keys.map(k =>
      '<details class="net-group panel" open>' +
        '<summary>' +
          '<span class="net-group-title">' + Networks._groupIcon() + ' ' + App.esc(k) + '</span>' +
          '<span class="net-group-count">' + groups[k].length + '</span>' +
        '</summary>' +
        '<div class="table-responsive">' +
          (g.pnic ? Networks._pnicTable(groups[k]) : Networks._netTable(groups[k])) +
        '</div>' +
      '</details>').join('');
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
      '<th>Ad</th>' +
      (showVlan ? '<th>VLAN</th>' : '') +
      '<th>vSwitch / Bridge</th><th>Port Group</th><th>IP Subnet</th>' +
      (showHost ? '<th>Host</th>' : '') +
      '<th>Platform</th></tr>';
    const body = list.map(n => '<tr>' +
      '<td><strong>' + App.esc(n.name || '—') + '</strong> ' + Networks._kindBadge(n.kind) + '</td>' +
      (showVlan ? '<td>' + (n.vlan ? '<span class="badge text-bg-light border">VLAN ' + App.esc(n.vlan) + '</span>' : '—') + '</td>' : '') +
      '<td>' + App.esc(n.vswitch || '—') + '</td>' +
      '<td>' + App.esc(n.portgroup || '—') + '</td>' +
      '<td>' + App.esc(n.subnet || '—') + '</td>' +
      (showHost ? '<td class="small">' + App.esc(n.host_name || '—') + '</td>' : '') +
      '<td class="small text-muted">' + App.esc(n.platform || '—') + '</td></tr>').join('');
    return '<table class="table table-hover align-middle mb-0"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  },

  _pnicTable(list) {
    const body = list.map(n => '<tr>' +
      '<td><strong>' + App.esc(n.name || '—') + '</strong></td>' +
      '<td class="small mono">' + App.esc(n.mac || '—') + '</td>' +
      '<td>' + App.esc(n.link_speed || '—') + '</td>' +
      '<td>' + (n.vswitch === 'bond' ? '<span class="badge text-bg-secondary">Bond</span>' : 'Fiziksel') + '</td>' +
      '<td class="small text-muted">' + App.esc(n.platform || '—') + '</td></tr>').join('');
    return '<table class="table table-hover align-middle mb-0"><thead><tr>' +
      '<th>Kart</th><th>MAC</th><th>Hız</th><th>Tür</th><th>Platform</th>' +
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
