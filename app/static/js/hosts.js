/**
 * hosts.js — Host envanteri ekranı: arama + tablo (lokal DB'den).
 */

/** Kaynak hücresi: üst satırda değer + satır içi yüzde, altında mini kullanım çubuğu.
 *  pct null ise yalnızca metin gösterilir (çubuk çizilmez). */
function resCell(topText, pct, label) {
  if (pct == null || isNaN(pct)) return '<div class="res-top">' + topText + '</div>';
  pct = Math.min(100, Math.round(pct));
  const cls = pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '';
  return '<div class="res-cell">' +
           '<div class="res-top">' + topText +
             ' <span class="res-pct">%' + pct + '</span></div>' +
           '<div class="usage-mini ' + cls + '" title="' + label + ' %' + pct + '">' +
             '<div style="width:' + pct + '%"></div></div>' +
         '</div>';
}

const Hosts = {
  async load(q = '') {
    let data;
    try { data = await App.api('/api/hosts?q=' + encodeURIComponent(q)); } catch (e) { return; }
    const body = document.getElementById('hostBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="11" class="text-center text-muted p-4">Sonuç bulunamadı.</td></tr>';
      return;
    }
    body.innerHTML = data.items.map(h => {
      const ramPct = h.ram_total_mb ? 100 * (h.ram_used_mb || 0) / h.ram_total_mb : null;
      const cpuPct = (h.cpu_usage_pct != null) ? h.cpu_usage_pct : null;
      const diskPct = h.disk_total_gb ? 100 * (h.disk_used_gb || 0) / h.disk_total_gb : null;
      const pIcon = h.platform_type === 'vcenter'
        ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
        : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
      return '<tr>' +
        '<td>' + pIcon + ' <strong>' + App.esc(h.name) + '</strong>' +
          '<br><small class="text-muted">' + App.esc(h.platform) + '</small></td>' +
        '<td>' + App.esc(h.mgmt_ip || '—') + '</td>' +
        '<td class="small">' + App.esc(h.os_version || '—') + '</td>' +
        '<td class="small">' + App.esc(h.cpu_model || '—') + '</td>' +
        '<td>' + resCell((h.cpu_cores || '—') + ' çekirdek', cpuPct, 'CPU') + '</td>' +
        '<td>' + resCell(App.fmtRam(h.ram_used_mb) + ' / ' + App.fmtRam(h.ram_total_mb), ramPct, 'RAM') + '</td>' +
        '<td>' + resCell(h.disk_total_gb ? App.fmtGb(h.disk_used_gb) + ' / ' + App.fmtGb(h.disk_total_gb) : '—', diskPct, 'Disk') + '</td>' +
        '<td>' + App.esc(h.cluster || '—') + '</td>' +
        '<td><span class="badge text-bg-light border">' + h.vm_count + '</span></td>' +
        '<td class="small text-nowrap">' + App.fmtUptime(h.last_boot) + '</td>' +
        '<td>' + App.stateBadge(h.status) + '</td></tr>';
    }).join('');
  },
};

(function () {
  const input = document.getElementById('hostSearch');
  input.addEventListener('input', App.debounce(() => Hosts.load(input.value.trim()), 300));
  Hosts.load();
})();
