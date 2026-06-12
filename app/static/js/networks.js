/**
 * networks.js — Ağ envanteri: VLAN, vSwitch/Bridge, Port Group, Subnet listesi.
 */
const Networks = {
  async load(q = '') {
    let data;
    try { data = await App.api('/api/networks?q=' + encodeURIComponent(q)); } catch (e) { return; }
    const body = document.getElementById('netBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="6" class="text-center text-muted p-4">Sonuç bulunamadı.</td></tr>';
      return;
    }
    body.innerHTML = data.items.map(n => '<tr>' +
      '<td><strong>' + App.esc(n.name || '—') + '</strong></td>' +
      '<td>' + (n.vlan ? '<span class="badge text-bg-light border">VLAN ' + App.esc(n.vlan) + '</span>' : '—') + '</td>' +
      '<td>' + App.esc(n.vswitch || '—') + '</td>' +
      '<td>' + App.esc(n.portgroup || '—') + '</td>' +
      '<td>' + App.esc(n.subnet || '—') + '</td>' +
      '<td class="small">' + App.esc(n.host_name || '—') + '</td></tr>').join('');
  },
};

(function () {
  const input = document.getElementById('netSearch');
  input.addEventListener('input', App.debounce(() => Networks.load(input.value.trim()), 300));
  Networks.load();
})();
