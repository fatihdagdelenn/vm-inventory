/**
 * hosts.js — Host envanteri ekranı.
 *  - Arama (sunucu taraflı q) + yüklenen kümede istemci taraflı sıralama
 *  - Tüm kolon başlıkları tıklanabilir: metin (A-Z), sayısal, durum bazlı
 *  - VM sayısına tıklayınca o host'un VM'lerini gösteren modal
 *  - Modal'daki VM'e tıklayınca Sanal Makineler sayfasında detayına deep-link
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
  items: [],            // sunucudan yüklenen ham host kayıtları
  sort: 'name',         // aktif sıralama kolonu
  order: 'asc',         // asc | desc

  /** IP'yi sayısal sıralanabilir bir değere çevir (10.10.9.x < 10.10.10.x). */
  ipKey(ip) {
    if (!ip) return -1;
    const parts = String(ip).split('.').map(Number);
    if (parts.length !== 4 || parts.some(isNaN)) return -1;
    return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
  },

  /** Durum sıralama rütbesi: online → maintenance → offline → diğer. */
  statusRank(s) {
    return ({online: 0, maintenance: 1, offline: 2}[s] ?? 3);
  },

  /** Açılıştan bu yana çalışma süresi (saniye); bilinmiyorsa -1 (en sona). */
  uptimeKey(iso) {
    if (!iso) return -1;
    const t = new Date(iso).getTime();
    if (isNaN(t)) return -1;
    return Math.max(0, Date.now() - t);
  },

  /** Bir host kaydından aktif sıralama kolonunun karşılaştırma değerini üret. */
  sortVal(h, key) {
    switch (key) {
      case 'name':       return (h.name || '').toLowerCase();
      case 'mgmt_ip':    return Hosts.ipKey(h.mgmt_ip);
      case 'os_version': return (h.os_version || '').toLowerCase();
      case 'cpu_model':  return (h.cpu_model || '').toLowerCase();
      case 'cpu_cores':  return h.cpu_cores || 0;
      case 'ram':        return h.ram_total_mb ? 100 * (h.ram_used_mb || 0) / h.ram_total_mb : -1;
      case 'disk':       return h.disk_total_gb ? 100 * (h.disk_used_gb || 0) / h.disk_total_gb : -1;
      case 'cluster':    return (h.cluster || '').toLowerCase();
      case 'vm_count':   return h.vm_count || 0;
      case 'uptime':     return Hosts.uptimeKey(h.last_boot);
      case 'status':     return Hosts.statusRank(h.status);
      default:           return (h.name || '').toLowerCase();
    }
  },

  /** items'ı aktif sort/order'a göre diz. Metin için locale, sayı için fark. */
  sorted() {
    const key = Hosts.sort, dir = Hosts.order === 'asc' ? 1 : -1;
    return [...Hosts.items].sort((a, b) => {
      const va = Hosts.sortVal(a, key), vb = Hosts.sortVal(b, key);
      let c;
      if (typeof va === 'string' || typeof vb === 'string')
        c = String(va).localeCompare(String(vb), 'tr');
      else c = va - vb;
      if (c === 0) c = (a.name || '').localeCompare(b.name || '', 'tr');  // sabit ikincil
      return c * dir;
    });
  },

  /** Başlıklardaki sıralama oklarını güncelle. */
  markHeaders() {
    document.querySelectorAll('#hostTable th.sortable').forEach(th => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === Hosts.sort)
        th.classList.add(Hosts.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
    });
  },

  /** Tabloyu (yeniden) çiz — yalnızca sıralanmış kümeyi basar. */
  render() {
    const body = document.getElementById('hostBody');
    if (!Hosts.items.length) {
      body.innerHTML = '<tr><td colspan="11" class="text-center text-muted p-4">Sonuç bulunamadı.</td></tr>';
      Hosts.markHeaders();
      return;
    }
    body.innerHTML = Hosts.sorted().map(h => {
      const ramPct = h.ram_total_mb ? 100 * (h.ram_used_mb || 0) / h.ram_total_mb : null;
      const cpuPct = (h.cpu_usage_pct != null) ? h.cpu_usage_pct : null;
      const diskPct = h.disk_total_gb ? 100 * (h.disk_used_gb || 0) / h.disk_total_gb : null;
      const pIcon = h.platform_type === 'vcenter'
        ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
        : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
      const vmCell = h.vm_count
        ? '<button type="button" class="vm-count-link" ' +
            'onclick="Hosts.showVms(' + h.id + ')" ' +
            'title="' + (h.vm_running || 0) + ' çalışıyor — VM listesini aç">' +
            h.vm_count + ' <i class="bi bi-box-arrow-up-right"></i></button>'
        : '<span class="badge text-bg-light border">0</span>';
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
        '<td>' + vmCell + '</td>' +
        '<td class="small text-nowrap">' + App.fmtUptime(h.last_boot) + '</td>' +
        '<td>' + App.stateBadge(h.status) + '</td></tr>';
    }).join('');
    Hosts.markHeaders();
  },

  async load(q = '') {
    let data;
    try { data = await App.api('/api/hosts?q=' + encodeURIComponent(q)); } catch (e) { return; }
    Hosts.items = data.items || [];
    Hosts.render();
  },

  /** VM sayısına tıklanınca: host'un VM'lerini çek, modal mini tablosunu doldur. */
  async showVms(hostId) {
    const modalEl = document.getElementById('hostVmsModal');
    const body = document.getElementById('hostVmsBody');
    document.getElementById('hostVmsTitle').textContent = 'Sanal Makineler';
    body.innerHTML = '<tr><td colspan="5" class="text-center text-muted p-3">Yükleniyor…</td></tr>';
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();

    let h;
    try { h = await App.api('/api/hosts/' + hostId); } catch (e) { modal.hide(); return; }
    document.getElementById('hostVmsTitle').textContent = h.name + ' — ' + (h.vms || []).length + ' VM';

    if (!h.vms || !h.vms.length) {
      body.innerHTML = '<tr><td colspan="5" class="text-center text-muted p-3">Bu host\'ta VM bulunmuyor.</td></tr>';
      return;
    }
    body.innerHTML = h.vms.map(v => {
      const ramPct = v.ram_mb ? Math.round(100 * (v.ram_usage_mb || 0) / v.ram_mb) : null;
      const cpu = (v.cpu_count != null ? v.cpu_count + ' vCPU' : '—') +
                  (v.cpu_usage_pct != null ? ' <span class="text-muted">%' + Math.round(v.cpu_usage_pct) + '</span>' : '');
      const ram = App.fmtRam(v.ram_mb) +
                  (ramPct != null ? ' <span class="text-muted">%' + ramPct + '</span>' : '');
      return '<tr class="vm-row" onclick="Hosts.openVm(' + v.id + ')">' +
        '<td><strong>' + App.esc(v.name) + '</strong>' +
          (v.vmid ? ' <small class="text-muted">#' + App.esc(v.vmid) + '</small>' : '') + '</td>' +
        '<td class="small text-nowrap">' + App.esc((v.ip_addresses || '—').split(',')[0] || '—') + '</td>' +
        '<td>' + App.stateBadge(v.power_state) + '</td>' +
        '<td class="small text-nowrap">' + cpu + '</td>' +
        '<td class="small text-nowrap">' + ram + '</td></tr>';
    }).join('');
  },

  /** Modal'daki VM'e tıklanınca: host modalını kapat, VM detayını AYNI sayfada
   *  ortak offcanvas panelinde göster (Sanal Makineler sayfasına gitmeden). */
  openVm(vmId) {
    bootstrap.Modal.getOrCreateInstance(document.getElementById('hostVmsModal')).hide();
    App.vmDetail(vmId);
  },
};

(function () {
  const input = document.getElementById('hostSearch');
  input.addEventListener('input', App.debounce(() => Hosts.load(input.value.trim()), 300));

  // Sıralanabilir başlıklar — yüklenen kümede istemci taraflı sıralama
  document.querySelectorAll('#hostTable th.sortable').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (Hosts.sort === col) Hosts.order = Hosts.order === 'asc' ? 'desc' : 'asc';
      else { Hosts.sort = col; Hosts.order = 'asc'; }
      Hosts.render();
    });
  });

  Hosts.load();
})();
