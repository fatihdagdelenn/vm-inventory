/**
 * snapshots.js — Snapshot ekranı: zengin arama + filtreler + yaş uyarıları.
 * Arama kutusu (söz dizimi) + platform/yaş/aktif filtreleri tek sorguda birleşir.
 * Yaş eşikleri: 30+ gün kırmızı, 14+ turuncu, 7+ sarı. Varsayılan: en eski üstte.
 */
const Snap = {
  sort: 'created_at',
  order: 'asc',
  items: [],
  pfLoaded: false,

  compose() {
    const parts = [];
    const txt = document.getElementById('snapSearch').value.trim();
    if (txt) parts.push(txt);
    const pf = document.getElementById('snapPlatform').value;
    if (pf) parts.push('platform:"' + pf + '"');
    const cl = document.getElementById('snapCluster').value;
    if (cl) parts.push('cluster:"' + cl + '"');
    const age = document.getElementById('snapAge').value;
    if (age) parts.push('age:>=' + age);
    if (document.getElementById('snapActive').checked) parts.push('current:yes');
    return parts.join(' ');
  },

  async load() {
    let data;
    try {
      data = await App.api('/api/snapshots?q=' + encodeURIComponent(this.compose()) +
                           '&sort=' + this.sort + '&order=' + this.order);
    } catch (e) { return; }
    this.items = data.items;
    if (!this.pfLoaded) {
      const fill = (id, vals) => {
        const sel = document.getElementById(id);
        (vals || []).forEach(v => {
          const o = document.createElement('option'); o.value = v; o.textContent = v;
          sel.appendChild(o);
        });
      };
      fill('snapPlatform', data.platforms);
      fill('snapCluster', data.clusters);
      this.pfLoaded = true;
    }
    this.render();
  },

  ageBadge(age) {
    if (age === null || age === undefined) return '<span class="text-muted">—</span>';
    let cls = 'text-bg-light text-dark border';
    if (age >= 30) cls = 'text-bg-danger';
    else if (age >= 14) cls = 'text-bg-warning text-dark';
    else if (age >= 7) cls = 'text-bg-info text-dark';
    return '<span class="badge ' + cls + '">' + age + ' gün</span>';
  },

  render() {
    const body = document.getElementById('snapBody');
    if (!this.items.length) {
      body.innerHTML = '<tr><td colspan="7" class="text-center text-muted p-4">Snapshot bulunamadı.</td></tr>';
      document.getElementById('snapCount').textContent = '';
      return;
    }
    body.innerHTML = this.items.map(s => {
      const pIcon = s.platform_type === 'vcenter'
        ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
        : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
      const cur = s.is_current
        ? ' <span class="badge text-bg-success" title="Aktif/çalışılan snapshot">aktif</span>' : '';
      const desc = s.description
        ? '<span class="text-muted small" title="' + App.esc(s.description) + '">' +
          App.esc(s.description.length > 60 ? s.description.slice(0, 60) + '…' : s.description) +
          '</span>' : '<span class="text-muted">—</span>';
      return '<tr>' +
        '<td><a href="/vms?q=' + encodeURIComponent(s.vm_name) + '" class="fw-semibold text-decoration-none">' +
          App.esc(s.vm_name) + '</a></td>' +
        '<td>' + App.esc(s.name) + cur + '</td>' +
        '<td>' + pIcon + ' <span class="small">' + App.esc(s.platform) + '</span></td>' +
        '<td class="small">' + App.esc(s.cluster || '—') + '</td>' +
        '<td class="small text-nowrap">' + (s.created_at ? App.fmtDate(s.created_at) : '—') + '</td>' +
        '<td>' + this.ageBadge(s.age_days) + '</td>' +
        '<td class="small text-muted">' + App.esc(s.parent || '—') + '</td>' +
        '<td>' + desc + '</td>' +
      '</tr>';
    }).join('');

    const old30 = this.items.filter(s => (s.age_days || 0) >= 30).length;
    document.getElementById('snapCount').innerHTML =
      this.items.length + ' snapshot' +
      (old30 ? ' · <span class="text-danger">' + old30 + ' adet 30+ gün</span>' : '');
  },

  setSort(col) {
    if (this.sort === col) this.order = (this.order === 'asc' ? 'desc' : 'asc');
    else { this.sort = col; this.order = 'asc'; }
    this.indicator();
    this.load();
  },

  indicator() {
    document.querySelectorAll('#snapTable th.sortable').forEach(th => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === this.sort)
        th.classList.add(this.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
    });
  },
};

(function () {
  if (new URLSearchParams(location.search).get('old') === '1')
    document.getElementById('snapAge').value = '30';
  const reload = App.debounce(() => Snap.load(), 300);
  document.getElementById('snapSearch').addEventListener('input', reload);
  document.getElementById('snapPlatform').addEventListener('change', () => Snap.load());
  document.getElementById('snapCluster').addEventListener('change', () => Snap.load());
  document.getElementById('snapAge').addEventListener('change', () => Snap.load());
  document.getElementById('snapActive').addEventListener('change', () => Snap.load());
  document.getElementById('snapHelpBtn').addEventListener('click', () =>
    document.getElementById('snapHelp').classList.toggle('d-none'));
  document.querySelectorAll('#snapTable th.sortable').forEach(th =>
    th.addEventListener('click', () => Snap.setSort(th.dataset.sort)));
  Snap.indicator();
  Snap.load();
})();
