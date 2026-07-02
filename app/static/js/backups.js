/**
 * backups.js — Yedekler ekranı (Proxmox vzdump + PBS): arama + filtre + sıralama.
 * Yaş eşikleri: 30+ gün kırmızı, 14+ turuncu (eski yedek = dikkat). Varsayılan: en yeni üstte.
 */
const Bk = {
  sort: 'created_at',
  order: 'desc',
  items: [],
  facetsLoaded: false,

  async load() {
    const q = document.getElementById('bkSearch').value.trim();
    const storage = document.getElementById('bkStorage').value;
    const source = document.getElementById('bkSource').value;
    let data;
    try {
      data = await App.api('/api/backups?q=' + encodeURIComponent(q) +
        '&storage=' + encodeURIComponent(storage) + '&source=' + encodeURIComponent(source) +
        '&sort=' + this.sort + '&order=' + this.order);
    } catch (e) { return; }
    this.items = data.items;
    if (!this.facetsLoaded) {
      const fill = (id, vals) => {
        const sel = document.getElementById(id);
        (vals || []).forEach(v => {
          const o = document.createElement('option'); o.value = v; o.textContent = v;
          sel.appendChild(o);
        });
      };
      fill('bkStorage', data.storages);
      fill('bkSource', data.sources);
      this.facetsLoaded = true;
    }
    this.render();
  },

  ageBadge(age) {
    if (age === null || age === undefined) return '<span class="text-muted">—</span>';
    let cls = 'text-bg-light text-dark border';
    if (age >= 30) cls = 'text-bg-danger'; else if (age >= 14) cls = 'text-bg-warning text-dark';
    else if (age >= 7) cls = 'text-bg-info text-dark';
    return '<span class="badge ' + cls + '">' + age + ' ' + t('unit.day','gün') + '</span>';
  },

  render() {
    const protectedOnly = document.getElementById('bkProtected').checked;
    const rows = protectedOnly ? this.items.filter(b => b.protected) : this.items;
    const body = document.getElementById('bkBody');
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="9" class="text-center text-muted p-4">' +
        t('bk.notFound','Yedek bulunamadı.') + ' ' +
        '<button class="btn btn-sm btn-outline-secondary ms-2" id="bkDiag">' +
        '<i class="bi bi-search"></i> ' + t('bk.diagnose','Neden? Tanıla') + '</button>' +
        '<div id="bkDiagOut" class="mt-3 text-start small"></div></td></tr>';
      document.getElementById('bkCount').textContent = '';
      const btn = document.getElementById('bkDiag');
      if (btn) btn.addEventListener('click', () => this.diagnose());
      return;
    }
    body.innerHTML = rows.map(b => {
      const pIcon = b.platform_type === 'vcenter'
        ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
        : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
      const srcBadge = b.source === 'pbs'
        ? '<span class="badge text-bg-primary">PBS</span>'
        : '<span class="badge text-bg-secondary">vzdump</span>';
      const prot = b.protected
        ? ' <i class="bi bi-shield-lock-fill text-success" title="' + t('bk.protected','Korumalı') + '"></i>' : '';
      const notes = b.notes
        ? '<span class="text-muted small" title="' + App.esc(b.notes) + '">' +
          App.esc(b.notes.length > 50 ? b.notes.slice(0, 50) + '…' : b.notes) + '</span>'
        : '<span class="text-muted">—</span>';
      return '<tr>' +
        '<td><a href="/vms?q=' + encodeURIComponent(b.vm_name) + '" class="fw-semibold text-decoration-none">' +
          App.esc(b.vm_name) + '</a>' + prot + '</td>' +
        '<td>' + pIcon + ' <span class="small">' + App.esc(b.platform) + '</span></td>' +
        '<td class="small">' + App.esc(b.cluster || '—') + '</td>' +
        '<td class="small">' + App.esc(b.storage) + '</td>' +
        '<td>' + srcBadge + '</td>' +
        '<td class="small text-nowrap">' + (b.created_at ? App.fmtDate(b.created_at) : '—') + '</td>' +
        '<td>' + this.ageBadge(b.age_days) + '</td>' +
        '<td class="small text-nowrap">' + (b.size_gb != null ? App.fmtGb(b.size_gb) : '—') + '</td>' +
        '<td>' + notes + '</td>' +
      '</tr>';
    }).join('');

    const totalGb = rows.reduce((a, b) => a + (b.size_gb || 0), 0);
    document.getElementById('bkCount').innerHTML =
      rows.length + ' ' + t('bk.backups','yedek') + ' · ' + t('bk.total','toplam') + ' ' + App.fmtGb(Math.round(totalGb * 10) / 10);
  },

  async diagnose() {
    const out = document.getElementById('bkDiagOut');
    out.innerHTML = '<span class="text-muted">' + t('bk.scanning','Depolar taranıyor…') + '</span>';
    let d;
    try { d = await App.api('/api/backups/diagnose'); }
    catch (e) { out.innerHTML = '<span class="text-danger">' + t('bk.diagFail','Tanılama başarısız.') + '</span>'; return; }
    if (d.error) { out.innerHTML = '<span class="text-warning">' + App.esc(d.error) + '</span>'; return; }
    if (!d.platforms || !d.platforms.length) {
      out.innerHTML = '<span class="text-muted">' + App.esc(d.hint || t('bk.noProxmox','Proxmox platformu yok.')) + '</span>';
      return;
    }
    let html = '';
    d.platforms.forEach(p => {
      html += '<div class="fw-semibold mt-2">' + App.esc(p.platform) + '</div>';
      if (p.error) { html += '<div class="text-danger">' + App.esc(p.error) + '</div>'; return; }
      html += '<table class="table table-sm mb-1"><thead><tr><th>' + t('bk.storage','Depo') + '</th><th>' + t('th.type','Tip') + '</th><th>Node</th>' +
        '<th>' + t('bk.contentField','İçerik alanı') + '</th><th>' + t('bk.items','Öğe') + '</th><th>' + t('bk.backup','Yedek') + '</th><th>' + t('th.status','Durum') + '</th></tr></thead><tbody>';
      (p.storages || []).forEach(s => {
        const status = s.error ? '<span class="text-danger">' + App.esc(s.error) + '</span>'
          : (s.backups > 0 ? '<span class="text-success">' + s.backups + ' ' + t('bk.backups','yedek') + '</span>'
                           : '<span class="text-muted">' + t('bk.noBackup','yedek yok') + '</span>');
        const nodeTxt = App.esc(s.node || '') + (s.shared && s.nodes_tried > 1
          ? ' <span class="text-muted small">(' + s.nodes_tried + ' ' + t('bk.nodesTried','node denendi') + ')</span>' : '');
        html += '<tr><td>' + App.esc(s.storage || '—') + '</td>' +
          '<td class="small">' + App.esc(s.plugin || '—') + '</td><td>' + nodeTxt + '</td>' +
          '<td class="small">' + App.esc(s.content_field || '—') + '</td>' +
          '<td>' + (s.items || 0) + '</td><td>' + (s.backups || 0) + '</td><td>' + status + '</td></tr>';
        if (s.pernode) html += '<tr><td colspan="7" class="small" style="color:#94a3b8">' + t('bk.perNode','node başına') + ': ' + App.esc(s.pernode) + '</td></tr>';
        if (s.config) html += '<tr><td colspan="7" class="small" style="color:#0ea5e9">⚙ PBS: ' + App.esc(s.config) +
          (s.n_unfiltered != null ? '  ·  filtresiz=' + s.n_unfiltered + ' / content=backup=' + s.n_backup_filter : '') + '</td></tr>';
        if (s.ctypes) html += '<tr><td colspan="7" class="text-muted small">' + t('bk.content','içerik') + ': ' + App.esc(s.ctypes) + '</td></tr>';
        if (s.note) html += '<tr><td colspan="7" class="small" style="color:#f59e0b">↳ ' + App.esc(s.note) + '</td></tr>';
        if (s.sample) html += '<tr><td colspan="7" class="text-muted small">' + t('bk.sample','örnek') + ': ' + App.esc(s.sample) + '</td></tr>';
      });
      html += '</tbody></table>';
    });
    html += '<div class="text-muted mt-1">' + t('bk.permHint','İzin hatası görüyorsan API kullanıcı/token rolüne Datastore.Audit ekle.') + '</div>';
    out.innerHTML = html;
  },

  setSort(col) {
    if (this.sort === col) this.order = (this.order === 'asc' ? 'desc' : 'asc');
    else { this.sort = col; this.order = col === 'created_at' ? 'desc' : 'asc'; }
    this.indicator();
    this.load();
  },

  indicator() {
    document.querySelectorAll('#bkTable th.sortable').forEach(th => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === this.sort)
        th.classList.add(this.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
    });
  },
};

(function () {
  const reload = App.debounce(() => Bk.load(), 300);
  document.getElementById('bkSearch').addEventListener('input', reload);
  document.getElementById('bkStorage').addEventListener('change', () => Bk.load());
  document.getElementById('bkSource').addEventListener('change', () => Bk.load());
  document.getElementById('bkProtected').addEventListener('change', () => Bk.render());
  document.querySelectorAll('#bkTable th.sortable').forEach(th =>
    th.addEventListener('click', () => Bk.setSort(th.dataset.sort)));
  Bk.indicator();
  Bk.load();
})();
