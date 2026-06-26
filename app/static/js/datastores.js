/**
 * datastores.js — Depolama (Datastore) ekranı: arama + sıralama + tablo.
 * Veriler lokal DB'den; paylaşımlı depolar tek satır, yerel depolar node bazında.
 */
const DS = {
  sort: 'name',
  order: 'asc',

  async load() {
    const q = document.getElementById('dsSearch').value.trim();
    let data;
    try {
      data = await App.api('/api/datastores?q=' + encodeURIComponent(q) +
                           '&sort=' + this.sort + '&order=' + this.order);
    } catch (e) { return; }
    const body = document.getElementById('dsBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="9" class="text-center text-muted p-4">Sonuç bulunamadı.</td></tr>';
      document.getElementById('dsCount').textContent = '';
      return;
    }
    const stMap = {
      active: ['Aktif', 'state-running'],
      inactive: ['Pasif', 'state-stopped'],
      maintenance: ['Bakım', 'state-suspended'],
    };
    body.innerHTML = data.items.map(d => {
      const pIcon = d.platform_type === 'vcenter'
        ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
        : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
      const pct = d.usage_pct;
      const cls = pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '';
      const usage =
        '<div class="res-cell"><div class="res-top">' +
          App.fmtGb(d.used_gb) + ' / ' + App.fmtGb(d.capacity_gb) +
          ' <span class="res-pct">%' + pct + '</span></div>' +
        '<div class="usage-mini ' + cls + '" title="%' + pct + '">' +
          '<div style="width:' + Math.min(100, pct) + '%"></div></div></div>';
      const shared = d.shared
        ? ' <span class="badge text-bg-light border" title="Birden çok host/node tarafından paylaşılıyor">paylaşımlı</span>' : '';
      const st = stMap[d.status] || [d.status || '—', 'state-stopped'];
      const cnt = (n, kind) => n > 0
        ? '<span class="badge text-bg-light border ds-count" style="cursor:pointer" ' +
          'onclick="DS.drill(' + d.id + ',\'' + kind + '\')" title="Detayları gör">' +
          n + ' <i class="bi bi-box-arrow-up-right"></i></span>'
        : '<span class="badge text-bg-light border">0</span>';
      return '<tr>' +
        '<td><strong>' + App.esc(d.name) + '</strong>' + shared + '</td>' +
        '<td class="small text-muted">' + App.esc(d.node || '—') + '</td>' +
        '<td>' + pIcon + ' <span class="small">' + App.esc(d.platform) + '</span></td>' +
        '<td class="small">' + App.esc(d.type || '—') + '</td>' +
        '<td class="text-nowrap">' + App.fmtGb(d.capacity_gb) + '</td>' +
        '<td style="min-width:170px">' + usage + '</td>' +
        '<td>' + cnt(d.host_count, 'host') + '</td>' +
        '<td>' + cnt(d.vm_count, 'vm') + '</td>' +
        '<td><span class="state-badge ' + st[1] + '">' + App.esc(st[0]) + '</span></td>' +
      '</tr>';
    }).join('');
    document.getElementById('dsCount').textContent = data.items.length + ' datastore';
  },

  /** Host/VM sayısına tıklanınca: bu datastore'un host'larını/VM'lerini ortak
   *  modallarda göster (Host'lar sayfasındaki detay modallarının aynısı). */
  async drill(dsId, kind) {
    let d;
    try { d = await App.api('/api/datastores/' + dsId); } catch (e) { return; }
    if (kind === 'vm') App.showVmList(d.name + ' — Sanal Makineler', d.vms);
    else App.showHostList(d.name + ' — Host\'lar', d.hosts);
  },

  setSort(col) {
    if (this.sort === col) this.order = (this.order === 'asc' ? 'desc' : 'asc');
    else { this.sort = col; this.order = 'asc'; }
    this.indicator();
    this.load();
  },

  indicator() {
    document.querySelectorAll('#dsTable th.sortable').forEach(th => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === this.sort)
        th.classList.add(this.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
    });
  },
};

(function () {
  document.getElementById('dsSearch').addEventListener('input', App.debounce(() => DS.load(), 300));
  document.querySelectorAll('#dsTable th.sortable').forEach(th =>
    th.addEventListener('click', () => DS.setSort(th.dataset.sort)));
  DS.indicator();
  DS.load();
})();
