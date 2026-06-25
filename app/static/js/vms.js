/**
 * vms.js — Sanal makineler ekranı.
 *  - Google benzeri arama (ip: vlan: os: host: cluster: status: …) — debounce'lu
 *  - Sunucu taraflı sayfalama + sıralama (500+ VM için performanslı)
 *  - Gruplama görünümü (cluster / os / vlan / ortam / lokasyon / etiket)
 *  - Offcanvas detay paneli + not/sahip/ortam/etiket düzenleme (operator+)
 *  - Filtrelenmiş Excel / CSV / PDF dışa aktarma
 */
const VMs = {
  q: '', page: 1, perPage: 50, sort: 'name', order: 'asc', total: 0,
  currentId: null, includeHidden: false, focusId: null,

  /** Anlık kullanım için mini çubuk (veri yoksa boş döner). */
  platformCell(ptype) {
    if (ptype === 'vcenter') return '<i class="bi bi-cloud text-primary"></i> VMware';
    if (ptype === 'proxmox') return '<i class="bi bi-box text-warning"></i> Proxmox';
    return '<span class="text-muted">—</span>';
  },

  agentCell(state) {
    const m = {running: ['Aktif', 'text-bg-success'],
               stopped: ['Pasif', 'text-bg-warning text-dark'],
               none: ['Yok', 'text-bg-secondary']};
    const a = m[state] || ['—', 'text-bg-light text-dark border'];
    return '<span class="badge ' + a[1] + '">' + a[0] + '</span>';
  },

  usageMini(pct, usedMb, usedGb) {
    if (pct == null || isNaN(pct)) return '';
    if (!usedMb && !usedGb && pct === 0) return '';   // veri henüz yoksa çubuk çizme
    pct = Math.min(100, Math.round(pct));
    const cls = (pct === 0 ? 'zero ' : '') +
                (pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '');
    const title = usedMb ? App.fmtRam(usedMb) + ' kullanımda (%' + pct + ')'
                : usedGb ? App.fmtGb(usedGb) + ' kullanımda (%' + pct + ')'
                : 'anlık kullanım %' + pct;
    return '<div class="usage-mini ' + cls + '" title="' + title + '">' +
           '<div style="width:' + pct + '%"></div></div>';
  },

  async load() {
    VMs.syncUrl();          // sorguyu adres çubuğuna yaz (paylaşılabilir link)
    VMs.renderActiveFilters();
    const groupBy = document.getElementById('groupBy').value;
    const params = new URLSearchParams({q: VMs.q, page: VMs.page, per_page: VMs.perPage,
                                        sort: VMs.sort, order: VMs.order});
    if (VMs.includeHidden) params.set('include_hidden', '1');
    if (groupBy) params.set('group_by', groupBy);

    let data;
    try { data = await App.api('/api/vms?' + params); } catch (e) { return; }

    const groupWrap = document.getElementById('groupResults');
    if (data.groups) {                       // ---- gruplama modu ----
      groupWrap.classList.remove('d-none');
      groupWrap.innerHTML = data.groups
        .sort((a, b) => b.count - a.count)
        .map(g => '<div class="col-6 col-md-4 col-xl-3">' +
          '<button class="group-card w-100" onclick="VMs.applyGroup(\'' +
          App.esc(groupBy) + '\',\'' + App.esc(g.key).replace(/'/g, "\\'") + '\')">' +
          '<span class="group-key">' + App.esc(g.key) + '</span>' +
          '<span class="group-count">' + g.count + ' VM</span></button></div>').join('');
      document.getElementById('vmBody').innerHTML =
        '<tr><td colspan="15" class="text-center text-muted p-4">' +
        'Gruplardan birine tıklayarak VM listesini filtreleyebilirsiniz.</td></tr>';
      document.getElementById('vmCount').textContent = data.groups.length + ' grup';
      document.getElementById('vmPager').innerHTML = '';
      return;
    }
    groupWrap.classList.add('d-none');

    // ---- normal liste modu ----
    VMs.total = data.total;
    const body = document.getElementById('vmBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="15" class="text-center text-muted p-4">Sonuç bulunamadı.</td></tr>';
    } else {
      body.innerHTML = data.items.map(v => {
        const pIcon = v.platform_type === 'vcenter'
          ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
          : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
        return '<tr class="vm-row" data-id="' + v.id + '" onclick="VMs.detail(' + v.id + ')">' +
          '<td data-col="name">' + pIcon + ' <strong>' + App.esc(v.name) + '</strong>' +
            (v.tags.length ? '<br><small>' + v.tags.map(t =>
              '<span class="badge text-bg-light border me-1">' + App.esc(t.name) + '</span>').join('') + '</small>' : '') + '</td>' +
          '<td data-col="vmid" class="small text-muted text-nowrap">' + App.esc(v.vmid || '—') + '</td>' +
          '<td data-col="ip" class="text-nowrap small">' + App.esc(v.ip_addresses || '—').split(',').join('<br>') + '</td>' +
          '<td data-col="guest_os" class="small">' + App.esc(v.guest_os || '—') + '</td>' +
          '<td data-col="platform" class="small text-nowrap">' + VMs.platformCell(v.platform_type) + '</td>' +
          '<td data-col="agent" class="text-nowrap">' + VMs.agentCell(v.agent_state) + '</td>' +
          '<td data-col="cpu">' + (v.cpu_count || '—') + VMs.usageMini(v.cpu_usage_pct) + '</td>' +
          '<td data-col="ram">' + App.fmtRam(v.ram_mb) +
            VMs.usageMini(v.ram_mb ? 100 * (v.ram_usage_mb || 0) / v.ram_mb : null,
                          v.ram_usage_mb) + '</td>' +
          '<td data-col="disk">' + App.fmtGb(v.disk_total_gb) +
            VMs.usageMini(v.disk_total_gb ? 100 * (v.disk_used_gb || 0) / v.disk_total_gb : null,
                          null, v.disk_used_gb) + '</td>' +
          '<td data-col="host" class="small cell-filter" onclick="VMs.cellFilter(event,\'host\',\'' + App.esc(v.host || '') + '\')" title="Bu host\'a göre filtrele">' + App.esc(v.host || '—') + '</td>' +
          '<td data-col="cluster" class="small cell-filter" onclick="VMs.cellFilter(event,\'cluster\',\'' + App.esc(v.cluster || '') + '\')" title="Bu cluster\'a göre filtrele">' + App.esc(v.cluster || '—') + '</td>' +
          '<td data-col="pool" class="small cell-filter" onclick="VMs.cellFilter(event,\'pool\',\'' + App.esc(v.pool || '') + '\')" title="Bu pool\'a göre filtrele">' + App.esc(v.pool || '—') + '</td>' +
          '<td data-col="folder" class="small cell-filter" onclick="VMs.cellFilter(event,\'folder\',\'' + App.esc(v.folder || '') + '\')" title="Bu klasöre göre filtrele">' + App.esc(v.folder || '—') + '</td>' +
          '<td data-col="vlan" class="cell-filter" onclick="VMs.cellFilter(event,\'vlan\',\'' + App.esc((v.vlans || '').split(',')[0]) + '\')" title="Bu VLAN\'a göre filtrele">' + App.esc(v.vlans || '—') + '</td>' +
          '<td data-col="ptags" class="small">' + (v.platform_tags
            ? v.platform_tags.split(',').map(t => t.trim()).filter(Boolean).map(t =>
                '<span class="badge bg-info-subtle text-info-emphasis border me-1">' + App.esc(t) + '</span>').join('')
            : '—') + '</td>' +
          '<td data-col="power_state">' + App.stateBadge(v.power_state) + '</td>' +
          '<td data-col="uptime" class="small text-nowrap">' + App.fmtUptime(v.last_boot) + '</td></tr>';
      }).join('');
    }
    VMs.applyCols();
    document.getElementById('vmCount').textContent =
      VMs.total + ' VM — sayfa ' + data.page + '/' + Math.max(1, Math.ceil(VMs.total / VMs.perPage));
    VMs.renderPager(data.page);
    VMs.applyFocus();
  },

  /** Deep-link: ?focus=<id> ile gelindiyse o VM'in detayını aç ve satırını
   *  vurgula. Yalnızca bir kez çalışır (sonraki yükleme/sıralamada tekrarlamaz). */
  applyFocus() {
    if (!VMs.focusId) return;
    const id = VMs.focusId;
    VMs.focusId = null;
    const row = document.querySelector('#vmBody tr[data-id="' + id + '"]');
    if (row) {
      row.classList.add('row-focus');
      row.scrollIntoView({behavior: 'smooth', block: 'center'});
      setTimeout(() => row.classList.remove('row-focus'), 2600);
    }
    VMs.detail(id);   // detay panelini (offcanvas) doğrudan id ile aç
  },

  /** Sayfalama bağlantılarını çiz (en fazla 7 sayfa numarası göster). */
  renderPager(page) {
    const pages = Math.max(1, Math.ceil(VMs.total / VMs.perPage));
    const ul = document.getElementById('vmPager');
    const li = (p, label, active, disabled) =>
      '<li class="page-item' + (active ? ' active' : '') + (disabled ? ' disabled' : '') +
      '"><a class="page-link" href="#" onclick="event.preventDefault();VMs.goto(' + p + ')">' + label + '</a></li>';
    let html = li(page - 1, '&laquo;', false, page <= 1);
    const start = Math.max(1, page - 3), end = Math.min(pages, start + 6);
    for (let p = start; p <= end; p++) html += li(p, p, p === page, false);
    html += li(page + 1, '&raquo;', false, page >= pages);
    ul.innerHTML = html;
  },

  goto(p) {
    const pages = Math.max(1, Math.ceil(VMs.total / VMs.perPage));
    if (p < 1 || p > pages) return;
    VMs.page = p;
    VMs.load();
  },

  /** Grup kartına tıklanınca arama kutusuna ilgili filtreyi yaz. */
  applyGroup(groupBy, key) {
    const fieldMap = {cluster: 'cluster', os: 'os', vlan: 'vlan',
                      environment: 'env', location: 'location', tag: 'tag'};
    const field = fieldMap[groupBy] || groupBy;
    const value = key.includes(' ') ? '"' + key + '"' : key;
    document.getElementById('groupBy').value = '';
    document.getElementById('vmSearch').value = field + ':' + value;
    VMs.q = field + ':' + value;
    VMs.page = 1;
    VMs.load();
  },

  /** Offcanvas detay panelini aç — ortak panel (App.vmDetail) kullanılır.
   *  Kaydetten sonra liste tazelensin diye onSaved verilir. */
  detail(id) {
    return App.vmDetail(id, {onSaved: () => VMs.load()});
  },

  /** Filtrelenmiş sonuçları dışa aktar — mevcut arama (q) aynen uygulanır. */
  exportNow(fmt) {
    location.href = '/api/reports/vms/export?fmt=' + fmt + '&q=' + encodeURIComponent(VMs.q);
  },

  /* ---------- Gelişmiş filtre paneli ---------- */

  /** Facets API'sinden ayrık değerleri çekip select'leri doldur. */
  async loadFacets() {
    let f;
    try {
      f = await App.api('/api/vms/facets' + (VMs.includeHidden ? '?include_hidden=1' : ''));
    } catch (e) { return; }
    const fill = (field, items, labelFn) => {
      const sel = document.querySelector('.adv-sel[data-field="' + field + '"]');
      if (!sel) return;
      sel.innerHTML = '<option value="">— Tümü —</option>' + items.map(i =>
        '<option value="' + App.esc(i.key) + '">' +
        App.esc(labelFn ? labelFn(i.key) : i.key) + ' (' + i.count + ')</option>').join('');
    };
    fill('platform', f.platforms);
    fill('cluster', f.clusters.map(c => ({key: c.key,
      count: c.count}))); // gizli cluster'lar da listede — seçilirse otomatik dahil edilir
    // gizli olanları işaretle
    const cSel = document.querySelector('.adv-sel[data-field="cluster"]');
    if (cSel) f.clusters.forEach((c, i) => {
      if (c.hidden && cSel.options[i + 1])
        cSel.options[i + 1].text += ' · gizli';
    });
    fill('host', f.hosts);
    fill('env', f.environments);
    fill('vlan', f.vlans);
    const osLabelMap = {};
    f.os_families.forEach(i => { osLabelMap[i.key] = i.label; });
    fill('osfam', f.os_families.map(i => ({key: i.key, count: i.count})),
         k => osLabelMap[k] || k);
    fill('tag', f.tags);
    fill('pool', f.pools || []);
    fill('folder', f.folders || []);
    fill('status', f.power_states, k =>
      ({running: 'Çalışıyor', stopped: 'Kapalı', suspended: 'Askıda'}[k] || k));
  },

  /**
   * Arama kutusundaki belirli bir alan token'ını değiştir/ekle/sil.
   * Panel seçimleri böylece söz dizimine yansır - kutu tek doğruluk kaynağıdır.
   */
  setToken(field, value) {
    const input = document.getElementById('vmSearch');
    // mevcut field:... token'ını kaldır (tırnaklı veya tırnaksız, negatifli dahil)
    const re = new RegExp('(^|\\s)-?' + field + ':("[^"]*"|\\S+)', 'gi');
    let q = input.value.replace(re, ' ').replace(/\s+/g, ' ').trim();
    if (value) {
      const v = /\s/.test(value) ? '"' + value + '"' : value;
      q = (q + ' ' + field + ':' + v).trim();
    }
    input.value = q;
    VMs.q = q; VMs.page = 1;
    VMs.updateAdvCount();
    VMs.load();
  },

  /** Aktif panel filtre sayısını rozette göster. */
  updateAdvCount() {
    let n = 0;
    document.querySelectorAll('.adv-sel').forEach(s => { if (s.value) n++; });
    document.querySelectorAll('.adv-num').forEach(s => { if (s.value) n++; });
    const badge = document.getElementById('advCount');
    badge.textContent = n;
    badge.classList.toggle('d-none', n === 0);
  },

  /** Panel filtrelerini ve ilgili token'ları temizle. */
  clearAdvanced() {
    document.querySelectorAll('.adv-sel').forEach(s => {
      if (s.value) { s.value = ''; }
      VMs.setTokenSilent(s.dataset.field);
    });
    document.querySelectorAll('.adv-num').forEach(s => {
      if (s.value) { s.value = ''; }
      VMs.setTokenSilent(s.dataset.field);
    });
    VMs.q = document.getElementById('vmSearch').value.trim();
    VMs.page = 1;
    VMs.updateAdvCount();
    VMs.load();
  },

  /** setToken'ın yeniden yükleme yapmayan hali (toplu temizlik için). */
  setTokenSilent(field) {
    const input = document.getElementById('vmSearch');
    const re = new RegExp('(^|\\s)-?' + field + ':("[^"]*"|\\S+)', 'gi');
    input.value = input.value.replace(re, ' ').replace(/\s+/g, ' ').trim();
  },

  /* ---------- URL senkronizasyonu ve aktif filtre rozetleri ---------- */

  /** Sorguyu adres çubuğuna yaz - sayfa yenilense de filtre korunur,
   *  link kopyalanıp paylaşılabilir. */
  syncUrl() {
    const url = VMs.q ? '/vms?q=' + encodeURIComponent(VMs.q) : '/vms';
    history.replaceState(null, '', url);
  },

  /** Sorgudaki her kriteri X'le kaldırılabilir rozet olarak göster. */
  renderActiveFilters() {
    const wrap = document.getElementById('activeFilters');
    const tokens = VMs.q.match(/-?\w+:"[^"]*"|-?\w+:\S+|-?\S+/g) || [];
    if (!tokens.length) { wrap.classList.add('d-none'); wrap.innerHTML = ''; return; }
    wrap.classList.remove('d-none');
    wrap.innerHTML = '<span class="text-muted small me-1">Aktif:</span>' +
      tokens.map((t, i) =>
        '<span class="filter-badge' + (t.startsWith('-') ? ' negative' : '') + '">' +
        App.esc(t) + '<button title="Kaldır" onclick="VMs.removeToken(' + i + ')">' +
        '<i class="bi bi-x"></i></button></span>').join('') +
      (tokens.length > 1 ? '<button class="btn btn-link btn-sm p-0 ms-1" ' +
        'onclick="VMs.clearAll()">tümünü temizle</button>' : '');
  },

  /** Rozetin X'ine basılınca o kriteri sorgudan çıkar. */
  removeToken(index) {
    const tokens = VMs.q.match(/-?\w+:"[^"]*"|-?\w+:\S+|-?\S+/g) || [];
    tokens.splice(index, 1);
    const q = tokens.join(' ');
    document.getElementById('vmSearch').value = q;
    VMs.q = q; VMs.page = 1;
    VMs.load();
  },

  clearAll() {
    document.getElementById('vmSearch').value = '';
    document.querySelectorAll('.adv-sel').forEach(s => s.value = '');
    document.querySelectorAll('.adv-num').forEach(s => s.value = '');
    VMs.q = ''; VMs.page = 1;
    VMs.updateAdvCount();
    VMs.load();
  },

  /** Tablo hücresinden tek tıkla filtre ekle (satır tıklamasını engeller). */
  /* ---------- Kolon seçici (görünür kolonlar; tarayıcıda hatırlanır) ---------- */
  COL_KEY: 'vmHiddenCols',

  /** Başlıktaki tüm kolonları döndür: [{id, label, defHidden}]. */
  allCols() {
    return [...document.querySelectorAll('#vmTable thead th[data-col]')].map(th => ({
      id: th.dataset.col,
      label: th.textContent.trim() || th.dataset.col,
      defHidden: th.dataset.colDefault === '0',
    }));
  },

  /** Gizli kolon kümesi: kayıt varsa ondan, yoksa varsayılan-gizli (data-col-default="0"). */
  hiddenCols() {
    try {
      const saved = localStorage.getItem(this.COL_KEY);
      if (saved !== null) return new Set(JSON.parse(saved));
    } catch (e) { /* yok say */ }
    return new Set(this.allCols().filter(c => c.defHidden).map(c => c.id));
  },

  /** Görünürlüğü hem başlığa hem (yeniden çizilen) hücrelere uygula. */
  applyCols() {
    const hidden = this.hiddenCols();
    this.allCols().forEach(c => {
      const show = !hidden.has(c.id);
      document.querySelectorAll('#vmTable [data-col="' + c.id + '"]')
        .forEach(el => { el.style.display = show ? '' : 'none'; });
    });
  },

  /** Menüyü kur (her kolon için onay kutusu). */
  buildColChooser() {
    const box = document.getElementById('colChooser');
    if (!box) return;
    const hidden = this.hiddenCols();
    box.innerHTML = this.allCols().map(c =>
      '<div class="form-check">' +
        '<input class="form-check-input" type="checkbox" id="col_' + c.id + '" ' +
          (hidden.has(c.id) ? '' : 'checked') + ' onchange="VMs.toggleCol(\'' + c.id + '\', this.checked)">' +
        '<label class="form-check-label small" for="col_' + c.id + '">' + c.label + '</label>' +
      '</div>').join('');
  },

  /** Bir kolonu aç/kapat, kaydet, uygula. */
  toggleCol(id, show) {
    const hidden = this.hiddenCols();
    if (show) hidden.delete(id); else hidden.add(id);
    try { localStorage.setItem(this.COL_KEY, JSON.stringify([...hidden])); } catch (e) { /* yok say */ }
    this.applyCols();
  },

  cellFilter(event, field, value) {
    event.stopPropagation();    // satırın detay açmasını önle
    if (!value || value === '—') return;
    VMs.setToken(field, value);
  },
};

/* ---------- Olay bağlama ---------- */
(function () {
  const input = document.getElementById('vmSearch');

  // Adres çubuğundaki ?q= parametresini al (dashboard tıklamaları,
  // paylaşılan linkler ve sayfa yenileme için)
  const urlQ = new URLSearchParams(location.search).get('q');
  if (urlQ) { input.value = urlQ; VMs.q = urlQ; }

  // ?focus=<id> ile gelindiyse (örn. Host modalından deep-link) ilk yüklemeden
  // sonra o VM'in detayını aç. Sorgu adres çubuğuna yazılırken focus düşürülür.
  const urlFocus = parseInt(new URLSearchParams(location.search).get('focus'), 10);
  if (urlFocus) VMs.focusId = urlFocus;

  // Debounce'lu arama: her tuş vuruşunda değil, 350 ms duraksamada sorgula
  input.addEventListener('input', App.debounce(() => {
    VMs.q = input.value.trim();
    VMs.page = 1;
    VMs.load();
  }, 350));

  document.getElementById('searchClear').addEventListener('click', () => {
    input.value = ''; VMs.q = ''; VMs.page = 1; VMs.load();
  });

  // Hızlı filtre chip'leri — arama kutusuna sorgu ekler
  document.querySelectorAll('.chip[data-q]').forEach(chip => {
    chip.addEventListener('click', () => {
      input.value = chip.dataset.q;
      VMs.q = chip.dataset.q; VMs.page = 1; VMs.load();
    });
  });

  document.getElementById('groupBy').addEventListener('change', () => { VMs.page = 1; VMs.load(); });

  // Yardım modalı
  document.getElementById('searchHelp').addEventListener('click', () =>
    bootstrap.Modal.getOrCreateInstance(document.getElementById('helpModal')).show());

  // Gelişmiş filtre paneli: seçimler arama kutusuna token olarak yansır
  document.querySelectorAll('.adv-sel').forEach(sel => {
    sel.addEventListener('change', () => VMs.setToken(sel.dataset.field, sel.value));
  });
  document.querySelectorAll('.adv-num').forEach(inp => {
    inp.addEventListener('change', () =>
      VMs.setToken(inp.dataset.field, inp.value ? '>=' + inp.value : ''));
  });
  document.getElementById('incHidden').addEventListener('change', e => {
    VMs.includeHidden = e.target.checked;
    VMs.page = 1;
    VMs.loadFacets();   // sayımlar da değişir
    VMs.load();
  });
  VMs.loadFacets();

  // Sıralanabilir başlıklar
  document.querySelectorAll('#vmTable th.sortable').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (VMs.sort === col) VMs.order = VMs.order === 'asc' ? 'desc' : 'asc';
      else { VMs.sort = col; VMs.order = 'asc'; }
      document.querySelectorAll('#vmTable th.sortable').forEach(x => x.classList.remove('sorted-asc', 'sorted-desc'));
      th.classList.add(VMs.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
      VMs.load();
    });
    // Açılışta aktif sıralama sütununu işaretle (varsayılan: name asc)
    if (th.dataset.sort === VMs.sort)
      th.classList.add(VMs.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
  });

  VMs.buildColChooser();
  VMs.applyCols();

  VMs.load();
})();
