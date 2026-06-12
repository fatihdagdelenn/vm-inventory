/**
 * hosts.js — Host envanteri ekranı: arama + tablo (lokal DB'den).
 */
const Hosts = {
  async load(q = '') {
    let data;
    try { data = await App.api('/api/hosts?q=' + encodeURIComponent(q)); } catch (e) { return; }
    const body = document.getElementById('hostBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="10" class="text-center text-muted p-4">Sonuç bulunamadı.</td></tr>';
      return;
    }
    body.innerHTML = data.items.map(h => {
      const ramPct = h.ram_total_mb ? Math.round(100 * (h.ram_used_mb || 0) / h.ram_total_mb) : 0;
      const pIcon = h.platform_type === 'vcenter'
        ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
        : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
      return '<tr>' +
        '<td>' + pIcon + ' <strong>' + App.esc(h.name) + '</strong>' +
          '<br><small class="text-muted">' + App.esc(h.platform) + '</small></td>' +
        '<td>' + App.esc(h.mgmt_ip || '—') + '</td>' +
        '<td class="small">' + App.esc(h.os_version || '—') + '</td>' +
        '<td class="small">' + App.esc(h.cpu_model || '—') + '</td>' +
        '<td>' + (h.cpu_cores || '—') + '</td>' +
        '<td style="min-width:130px">' + App.fmtRam(h.ram_used_mb) + ' / ' + App.fmtRam(h.ram_total_mb) +
          App.usageBar(ramPct) + '</td>' +
        '<td>' + (h.disk_total_gb ? App.fmtGb(h.disk_used_gb) + ' / ' + App.fmtGb(h.disk_total_gb) : '—') + '</td>' +
        '<td>' + App.esc(h.cluster || '—') + '</td>' +
        '<td><span class="badge text-bg-light border">' + h.vm_count + '</span></td>' +
        '<td>' + App.stateBadge(h.status) + '</td></tr>';
    }).join('');
  },
};

(function () {
  const input = document.getElementById('hostSearch');
  input.addEventListener('input', App.debounce(() => Hosts.load(input.value.trim()), 300));
  Hosts.load();
})();
