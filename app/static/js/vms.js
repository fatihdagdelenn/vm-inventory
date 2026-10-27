/**
 * vms.js — Sanal makineler ekranı.
 *  - Google benzeri arama (ip: vlan: os: host: cluster: status: …) — debounce'lu
 *  - Sunucu taraflı sayfalama + sıralama (500+ VM için performanslı)
 *  - Gruplama görünümü (cluster / os / vlan / ortam / lokasyon / etiket)
 *  - Offcanvas detay paneli + not/sahip/ortam/etiket düzenleme (operator+)
 *  - Filtrelenmiş Excel / CSV / PDF dışa aktarma
 */
// Arayüz diline göre boş/dolu anahtar kelimesi (arama motoru ikisini de kabul eder:
// yok/boş/none/empty/null ve var/dolu/any/set).
const QF_EN = (typeof I18N !== 'undefined' && I18N.lang === 'en');
const QF_NONE = QF_EN ? 'none' : 'yok';
const QF_ANY = QF_EN ? 'any' : 'var';

const VMs = {
  q: '', page: 1, perPage: 50, sort: 'name', order: 'asc', total: 0,
  currentId: null, includeHidden: false, focusId: null, highlightId: null,

  /** Sütun başlığı olmayan sıralamalar (dashboard 'en çok kullanan' kartlarından
   *  gelinir). Etkinken bir 'Sıralama' rozetiyle görünür ve kaldırılabilir. */
  USAGE_SORTS: {cpu_usage: ['vm.sortCpuUsage', 'CPU kullanımı'],
                ram_usage: ['vm.sortRamUsage', 'RAM kullanımı (%)'],
                disk_usage: ['vm.sortDiskUsage', 'Disk kullanımı']},

  /** Anlık kullanım için mini çubuk (veri yoksa boş döner). */
  platformCell(ptype) {
    if (ptype === 'vcenter') return '<i class="bi bi-cloud text-primary"></i> VMware';
    if (ptype === 'proxmox') return '<i class="bi bi-box text-warning"></i> Proxmox';
    return '<span class="text-muted">—</span>';
  },

  agentCell(state) {
    const m = {running: [t('ag.active','Aktif'), 'text-bg-success'],
               stopped: [t('ag.passive','Pasif'), 'text-bg-warning text-dark'],
               none: [t('ag.none','Yok'), 'text-bg-secondary']};
    const a = m[state] || ['—', 'text-bg-light text-dark border'];
    return '<span class="badge ' + a[1] + '">' + a[0] + '</span>';
  },

  usageMini(pct, usedMb, usedGb) {
    if (pct == null || isNaN(pct)) return '';
    if (!usedMb && !usedGb && pct === 0) return '';   // veri henüz yoksa çubuk çizme
    pct = Math.min(100, Math.round(pct));
    const cls = (pct === 0 ? 'zero ' : '') +
                (pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '');
    const title = usedMb ? App.fmtRam(usedMb) + ' ' + t('vm.inUse','kullanımda') + ' (%' + pct + ')'
                : usedGb ? App.fmtGb(usedGb) + ' ' + t('vm.inUse','kullanımda') + ' (%' + pct + ')'
                : t('vm.instantUsage','anlık kullanım %') + pct;
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
        t('vm.groupHint','Gruplardan birine tıklayarak VM listesini filtreleyebilirsiniz.') + '</td></tr>';
      document.getElementById('vmCount').textContent = data.groups.length + ' ' + t('vm.groups','grup');
      document.getElementById('vmPager').innerHTML = '';
      return;
    }
    groupWrap.classList.add('d-none');

    // ---- normal liste modu ----
    VMs.total = data.total;
    const body = document.getElementById('vmBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="15" class="text-center text-muted p-4">' + t('vm.noResults','Sonuç bulunamadı.') + '</td></tr>';
    } else {
      body.innerHTML = data.items.map(v => {
        const pIcon = v.platform_type === 'vcenter'
          ? '<i class="bi bi-cloud text-primary" title="vCenter"></i>'
          : '<i class="bi bi-box text-warning" title="Proxmox"></i>';
        return '<tr class="vm-row" data-id="' + v.id + '" onclick="VMs.detail(' + v.id + ')">' +
          '<td data-col="name">' + pIcon + ' <strong>' + App.esc(v.name) + '</strong>' +
            (v.tags.length ? '<br><small>' + v.tags.map(tg =>
              '<span class="badge text-bg-light border me-1">' + App.esc(tg.name) + '</span>').join('') + '</small>' : '') + '</td>' +
          '<td data-col="vmid" class="small text-muted text-nowrap">' + App.esc(v.vmid || '—') + '</td>' +
          '<td data-col="ip" class="text-nowrap small">' + App.ipHtml(v) + '</td>' +
          '<td data-col="guest_os" class="small">' + App.esc(v.guest_os || '—') + '</td>' +
          '<td data-col="platform" class="small text-nowrap">' + VMs.platformCell(v.platform_type) + '</td>' +
          '<td data-col="agent" class="text-nowrap">' + VMs.agentCell(v.agent_state) + '</td>' +
          '<td data-col="cpu">' + (v.cpu_count || '—') + VMs.usageMini(v.cpu_usage_pct) + '</td>' +
          '<td data-col="ram">' + App.fmtRam(v.ram_mb) +
            VMs.usageMini(v.ram_mb ? 100 * (v.ram_usage_mb || 0) / v.ram_mb : null,
                          v.ram_usage_mb) + '</td>' +
          '<td data-col="disk"><div class="disk-cell">' +
            '<div class="disk-cell-top">' +
              '<span>' + App.fmtGb(v.disk_total_gb) + '</span>' +
              ((v.disks && v.disks.length > 1)
                ? '<span class="disk-count-badge" title="' +
                  t('vm.multiDisk', 'Bu VM\'de birden fazla disk var — ayrıntı için tıklayın') +
                  '">' + v.disks.length + ' <i class="bi bi-hdd-stack"></i></span>' : '') +
            '</div>' +
            VMs.usageMini(v.disk_total_gb ? 100 * (v.disk_used_gb || 0) / v.disk_total_gb : null,
                          null, v.disk_used_gb) +
          '</div></td>' +
          '<td data-col="host" class="small cell-filter" onclick="VMs.cellFilter(event,\'host\',\'' + App.esc(v.host || '') + '\')" title="' + t('vm.filterByHost','Bu host\'a göre filtrele') + '">' + App.esc(v.host || '—') + '</td>' +
          '<td data-col="cluster" class="small cell-filter" onclick="VMs.cellFilter(event,\'cluster\',\'' + App.esc(v.cluster || '') + '\')" title="' + t('vm.filterByCluster','Bu cluster\'a göre filtrele') + '">' + App.esc(v.cluster || '—') + '</td>' +
          '<td data-col="pool" class="small cell-filter" onclick="VMs.cellFilter(event,\'pool\',\'' + App.esc(v.pool || '') + '\')" title="' + t('vm.filterByPool','Bu pool\'a göre filtrele') + '">' + App.esc(v.pool || '—') + '</td>' +
          '<td data-col="folder" class="small cell-filter" onclick="VMs.cellFilter(event,\'folder\',\'' + App.esc(v.folder || '') + '\')" title="' + t('vm.filterByFolder','Bu klasöre göre filtrele') + '">' + App.esc(v.folder || '—') + '</td>' +
          '<td data-col="vlan" class="cell-filter" onclick="VMs.cellFilter(event,\'vlan\',\'' + App.esc((v.vlans || '').split(',')[0]) + '\')" title="' + t('vm.filterByVlan','Bu VLAN\'a göre filtrele') + '">' + App.esc(v.vlans || '—') + '</td>' +
          '<td data-col="ptags" class="small">' + (v.platform_tags
            ? v.platform_tags.split(',').map(tg => tg.trim()).filter(Boolean).map(tg =>
                '<span class="badge bg-info-subtle text-info-emphasis border me-1">' + App.esc(tg) + '</span>').join('')
            : '—') + '</td>' +
          '<td data-col="power_state">' + App.stateBadge(v.power_state) + '</td>' +
          '<td data-col="uptime" class="small text-nowrap">' + App.fmtUptime(v.last_boot) + '</td></tr>';
      }).join('');
    }
    VMs.applyCols();
    document.getElementById('vmCount').textContent =
      VMs.total + ' VM — ' + t('vm.page','sayfa') + ' ' + data.page + '/' + Math.max(1, Math.ceil(VMs.total / VMs.perPage));
    VMs.renderPager(data.page);
    VMs.applyFocus();
  },

  /** Deep-link: ?focus=<id> ile gelindiyse o VM'in detayını aç ve satırını
   *  vurgula. Yalnızca bir kez çalışır (sonraki yükleme/sıralamada tekrarlamaz). */
  applyFocus() {
    if (VMs.highlightId) {            // ?hl=<id>: vurgula ama detayı açma
      const hid = VMs.highlightId;
      VMs.highlightId = null;
      const hrow = document.querySelector('#vmBody tr[data-id="' + hid + '"]');
      if (hrow) {
        hrow.classList.add('row-focus');
        hrow.scrollIntoView({behavior: 'smooth', block: 'center'});
        setTimeout(() => hrow.classList.remove('row-focus'), 2600);
      }
    }
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
    let raw = key;
    if (field === 'cluster') raw = key === '(boş)' ? 'yok' : '=' + key;   // tam eşleşme
    const value = raw.includes(' ') ? '"' + raw + '"' : raw;
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

  /* ---------- Sorgu token'ları (arama kutusu tek doğruluk kaynağı) ---------- */

  tokenize(q) { return (q || '').match(/[-!]?\w+:"[^"]*"|[-!]?\w+:\S+|[-!]?\S+/g) || []; },

  /** 'field:value' / '-field:"a b"' → {neg, field, raw, quoted}; serbest kelime → null. */
  parseTok(tok) {
    const m = (tok || '').match(/^([-!]?)(\w+):(?:"([^"]*)"|(\S+))$/);
    if (!m) return null;
    return {neg: !!m[1], field: m[2].toLowerCase(),
            raw: m[3] != null ? m[3] : m[4], quoted: m[3] != null};
  },

  /** Virgülle VEYA'lanamayan değerler: boş/dolu kelimeleri ve sayısal karşılaştırmalar. */
  isSolo(value) {
    const v = value || '';
    return /^(yok|bos|boş|none|empty|null|var|dolu)$/i.test(v) || /^(>=|<=|>|<)/.test(v) || /^=\d/.test(v);
  },

  /** Arama kutusuna yeni sorgu yaz ve listeyi yükle. */
  applyQuery(q) {
    q = (q || '').replace(/\s+/g, ' ').trim();
    document.getElementById('vmSearch').value = q;
    VMs.q = q; VMs.page = 1;
    VMs.load();
  },

  /* ---------- Hızlı filtreler (çoklu seçim, açılır menüler) ---------- */

  /** Gruplar: [alan, değer, [i18n anahtarı, TR etiket]]. Aynı gruptakiler VEYA. */
  QF_GROUPS: [
    // Dinamik: seçenekler facets'ten gelir (setClusterItems). Değerler '=ad' →
    // tam eşleşme (Lab seçimi Lab2'yi getirmez). Filtredir; küresel görünürlüğü
    // değiştirmez — gizli bir cluster seçilirse o da listelenir.
    {id: 'cluster', icon: 'bi-diagram-3', label: ['vm.qf.cluster', 'Cluster'], dynamic: true, items: []},
    {id: 'status', icon: 'bi-power', label: ['vm.qf.status', 'Durum'], items: [
      ['status', 'running', ['vm.chipRunning', 'Çalışan']],
      ['status', 'stopped', ['vm.chipStopped', 'Kapalı']],
      ['status', 'suspended', ['st.suspended', 'Askıda']]]},
    {id: 'platform', icon: 'bi-hdd-network', label: ['vm.qf.platform', 'Platform'], items: [
      ['type', 'vcenter', [null, 'VMware']],
      ['type', 'proxmox', [null, 'Proxmox']]]},
    {id: 'os', icon: 'bi-pc-display', label: ['vm.qf.os', 'OS'], items: [
      ['osfam', 'windows', [null, 'Windows']],
      ['osfam', 'linux', [null, 'Linux']]]},
    {id: 'missing', icon: 'bi-exclamation-diamond', label: ['vm.qf.missing', 'Eksikler'], items: [
      ['ip', QF_NONE, ['vm.chipNoIp', "IP'siz"]],
      ['tools', QF_NONE, ['vm.chipNoAgent', "Agent'sız"]],
      ['owner', QF_NONE, ['vm.chipNoOwner', 'Sahipsiz']],
      ['tag', QF_NONE, ['vm.chipNoTag', 'Etiketsiz']]]},
    {id: 'usage', icon: 'bi-speedometer2', label: ['vm.qf.usage', 'Kullanım'], items: [
      ['cpuuse', '>=80', [null, 'CPU %80+']],
      ['ramuse', '>=80', [null, 'RAM %80+']],
      ['diskuse', '>=85', [null, 'Disk %85+']]]},
  ],

  qfLabel(pair) { return pair[0] ? t(pair[0], pair[1]) : pair[1]; },

  /** Tek menü satırı. it = [alan, değer, [i18n, etiket], sayı?, gizli?, takma ad?] */
  qfItemHtml(it, dyn) {
    return '<div class="qf qf-item' + (dyn ? ' qf-dyn' : '') + (it[4] ? ' is-hidden' : '') +
        '" role="button" tabindex="0" data-field="' + it[0] + '" data-value="' + App.esc(it[1]) + '">' +
      '<span class="qf-check"></span>' +
      '<span class="qf-text">' + App.esc(VMs.qfLabel(it[2])) + '</span>' +
      (it[5] ? '<span class="qf-alias-tag" title="' + App.esc(t('vm.qf.aliasTip',
        'Platform cluster bildirmiyor; bu ad host için verilen takma ad')) + '">' +
        t('cv.aliasTag', 'takma ad') + '</span>' : '') +
      (it[4] ? '<span class="qf-hidden-tag" title="' + App.esc(t('vm.qf.hiddenTip',
        'Dashboard ve listede gizli; seçerseniz yine listelenir')) + '"><i class="bi bi-eye-slash"></i> ' +
        t('vm.hiddenMark', 'gizli') + '</span>' : '') +
      '<span class="qf-count">' + (it[3] != null ? it[3] : '') + '</span>' +
      '<span class="qf-ex" title="' + App.esc(t('vm.qf.exclude', 'Hariç tut')) + '"><i class="bi bi-slash-circle"></i></span>' +
    '</div>';
  },

  /** Cluster menüsünü facets'ten doldur (sayılar dahil; gizliler işaretli). */
  setClusterItems(clusters) {
    const g = VMs.QF_GROUPS.find(x => x.id === 'cluster');
    // "(Cluster'sız)" = '=' (boş cluster, diğerleriyle VEYA'lanabilir: cluster:=,=Lab)
    g.items = (clusters || []).map(c => c.is_none
      ? ['cluster', '=', ['cl.noCluster', "(Cluster'sız)"], c.count, !!c.hidden, false]
      : ['cluster', '=' + c.key, [null, c.key], c.count, !!c.hidden, !!c.is_alias]);
    const box = document.querySelector('#quickFilters .qf-dd[data-group="cluster"] .qf-dyn-items');
    if (!box) return;
    box.innerHTML = g.items.length ? g.items.map(it => VMs.qfItemHtml(it, true)).join('')
      : '<div class="text-muted small px-2 py-1">' + t('cl.noData', 'Henüz cluster verisi yok — önce bir platform senkronize edin.') + '</div>';
    const search = document.querySelector('#quickFilters .qf-dd[data-group="cluster"] .qf-search');
    search.classList.toggle('d-none', g.items.length < 8);
    VMs.renderChips();
  },

  /** Menüleri bir kez çiz; durumlar renderChips ile güncellenir (menü açık kalır). */
  renderQuickFilters() {
    const wrap = document.getElementById('quickFilters');
    wrap.innerHTML = VMs.QF_GROUPS.map(g =>
      '<div class="dropdown qf-dd" data-group="' + g.id + '">' +
        '<button class="qf-btn" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside">' +
          '<i class="bi ' + g.icon + '"></i> <span class="qf-btn-text"><span class="qf-btn-label">' +
          VMs.qfLabel(g.label) + '</span><span class="qf-btn-val"></span></span>' +
          '<i class="bi bi-chevron-down qf-caret"></i></button>' +
        '<div class="dropdown-menu qf-menu' + (g.dynamic ? ' qf-menu-dyn' : '') + '">' +
          (g.dynamic
            ? '<input type="search" class="form-control form-control-sm qf-search d-none" placeholder="' +
                App.esc(t('cv.search', 'Cluster ara…')) + '">' +
              '<div class="qf-dyn-items"><div class="text-muted small px-2 py-1">' + t('common.loading', 'Yükleniyor…') + '</div></div>'
            : g.items.map(it => VMs.qfItemHtml(it, false)).join('')) +
          '<div class="qf-menu-foot"><span>' + t('vm.qf.hint', 'Çoklu seçim · Shift+tık: hariç tut') + '</span>' +
            '<span class="qf-foot-actions">' +
            (g.id === 'cluster' && typeof ClusterVis !== 'undefined'
              ? '<button type="button" class="btn btn-link btn-sm p-0 qf-manage" title="' +
                  App.esc(t('vm.qf.manageTip', "Cluster'ları dashboard ve listelerde herkes için gizle/göster")) + '">' +
                  '<i class="bi bi-eye"></i> ' + t('vm.qf.manage', 'Görünürlük') + '</button>' : '') +
            '<button type="button" class="btn btn-link btn-sm p-0 qf-clear">' + t('vm.qf.clearGroup', 'Temizle') + '</button>' +
            '</span></div>' +
        '</div>' +
      '</div>').join('');
    // Tıklama: satır = dahil et/çıkar, ⊘ veya Shift = hariç tut, Temizle = grubu sıfırla
    wrap.addEventListener('click', e => {
      if (e.target.closest('.qf-manage')) { ClusterVis.open(); return; }
      const clr = e.target.closest('.qf-clear');
      if (clr) { VMs.clearGroup(clr.closest('.qf-dd').dataset.group); return; }
      const item = e.target.closest('.qf-item'); if (!item) return;
      const ex = e.shiftKey || !!e.target.closest('.qf-ex');
      VMs.toggleChip(item.dataset.field, item.dataset.value, ex);
    });
    wrap.addEventListener('input', e => {
      const s = e.target.closest('.qf-search'); if (!s) return;
      const needle = s.value.trim().toLowerCase();
      s.closest('.qf-menu').querySelectorAll('.qf-item').forEach(it =>
        it.classList.toggle('d-none', !!needle && !it.querySelector('.qf-text').textContent.toLowerCase().includes(needle)));
    });
    wrap.addEventListener('keydown', e => {
      const item = e.target.closest('.qf-item');
      if (item && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault(); VMs.toggleChip(item.dataset.field, item.dataset.value, e.shiftKey);
      }
    });
  },

  /** Çipin bir sorgudaki durumu: 'on' (dahil) | 'not' (hariç) | 'off'. */
  chipState(field, value, q) {
    const v = value.toLowerCase(), solo = VMs.isSolo(value);
    let state = 'off';
    VMs.tokenize(q == null ? VMs.q : q).forEach(tok => {
      const p = VMs.parseTok(tok);
      if (!p || p.field !== field) return;
      const hit = solo ? p.raw.toLowerCase() === v
                       : p.raw.split(',').map(x => x.trim().toLowerCase()).includes(v);
      if (hit) state = p.neg ? 'not' : 'on';
    });
    return state;
  },

  /**
   * Saf fonksiyon: q sorgusunda (alan, değer) çiftini target durumuna getir
   * ('on' | 'not' | 'off') ve yeni sorguyu döndür. Aynı alanın değerleri tek
   * token'da virgülle birleşir (VEYA); farklı alanlar ayrı token (VE).
   */
  withChip(q, field, value, target) {
    const v = value.toLowerCase(), solo = VMs.isSolo(value);
    // Boşluk içeren değer (ör. "Ankara Prod") varsa token'ın tamamı tırnaklanır
    const fmt = (neg, vals) => (neg ? '-' : '') + field + ':' +
      (vals.some(x => /\s/.test(x)) ? '"' + vals.join(',') + '"' : vals.join(','));
    // 1) değeri bu alanın tüm token'larından çıkar (iki işaret için de)
    const toks = [];
    VMs.tokenize(q).forEach(tok => {
      const p = VMs.parseTok(tok);
      if (!p || p.field !== field) { toks.push(tok); return; }
      if (solo) { if (p.raw.toLowerCase() !== v) toks.push(tok); return; }
      const vals = p.raw.split(',').map(x => x.trim()).filter(Boolean);
      const rest = vals.filter(x => x.toLowerCase() !== v);
      if (rest.length === vals.length) { toks.push(tok); return; }
      if (rest.length) toks.push(fmt(p.neg, rest));
    });
    // 2) istenen işaretle geri ekle (varsa aynı işaretli token'a virgülle)
    if (target === 'on' || target === 'not') {
      const neg = target === 'not';
      const i = solo ? -1 : toks.findIndex(tok => {
        const p = VMs.parseTok(tok);
        return p && p.field === field && p.neg === neg && !VMs.isSolo(p.raw);
      });
      if (i >= 0) {
        const p = VMs.parseTok(toks[i]);
        toks[i] = fmt(neg, p.raw.split(',').map(x => x.trim()).filter(Boolean).concat([value]));
      } else toks.push(fmt(neg, [value]));
    }
    return toks.join(' ');
  },

  /** Aç/kapat: zaten istenen durumdaysa kapatır. exclude = Shift+tık / ⊘. */
  toggleChip(field, value, exclude) {
    const want = exclude ? 'not' : 'on';
    const target = VMs.chipState(field, value) === want ? 'off' : want;
    VMs.applyQuery(VMs.withChip(VMs.q, field, value, target));
  },

  /** Bir grubun bütün seçimlerini kaldır. */
  clearGroup(gid) {
    const g = VMs.QF_GROUPS.find(x => x.id === gid); if (!g) return;
    let q = VMs.q;
    g.items.forEach(it => { q = VMs.withChip(q, it[0], it[1], 'off'); });
    if (q !== VMs.q) VMs.applyQuery(q);
  },

  /** Menü satırlarını ve düğme özetlerini sorguyla eşitle (elle yazım da yansır). */
  renderChips() {
    VMs.QF_GROUPS.forEach(g => {
      const dd = document.querySelector('#quickFilters .qf-dd[data-group="' + g.id + '"]');
      if (!dd) return;
      const on = [], not = [];
      dd.querySelectorAll('.qf-item').forEach(it => {
        const st = VMs.chipState(it.dataset.field, it.dataset.value);
        it.classList.toggle('active', st === 'on');
        it.classList.toggle('excluded', st === 'not');
        it.setAttribute('aria-checked', st === 'on' ? 'true' : 'false');
        const label = it.querySelector('.qf-text').textContent;
        if (st === 'on') on.push(label);
        if (st === 'not') not.push('≠ ' + label);
      });
      const picked = on.concat(not);
      const btn = dd.querySelector('.qf-btn');
      btn.classList.toggle('has-on', on.length > 0);
      btn.classList.toggle('has-not', !on.length && not.length > 0);
      dd.querySelector('.qf-btn-val').textContent = picked.length
        ? ': ' + picked[0] + (picked.length > 1 ? ' +' + (picked.length - 1) : '') : '';
      btn.title = picked.join(', ');
      dd.querySelector('.qf-clear').classList.toggle('invisible', !picked.length);
    });
  },

  /** Her çipin tek başına kaç VM döndürdüğü (aynı gizli-cluster kuralıyla). */
  async loadChipCounts() {
    const chips = [...document.querySelectorAll('#quickFilters .qf:not(.qf-dyn)')];
    const sp = new URLSearchParams();
    chips.forEach(ch => sp.append('q', ch.dataset.field + ':' + ch.dataset.value));
    if (VMs.includeHidden) sp.set('include_hidden', '1');
    let r;
    try { r = await App.api('/api/vms/counts?' + sp); } catch (e) { return; }
    chips.forEach((ch, i) => {
      const n = (r.counts || [])[i];
      ch.querySelector('.qf-count').textContent = n == null ? '' : n;
      ch.classList.toggle('zero', n === 0);
    });
  },

  /** Gelişmiş panel seçimlerini sorgudan türet (çip/elle yazım panelle çelişmesin). */
  syncAdvFromQuery() {
    const pos = {};
    VMs.tokenize(VMs.q).forEach(tok => {
      const p = VMs.parseTok(tok);
      if (p && !p.neg) pos[p.field] = p.raw;
    });
    document.querySelectorAll('.adv-sel').forEach(sel => {
      const raw = pos[sel.dataset.field];
      const opt = raw == null ? null
        : [...sel.options].find(o => o.value && o.value.toLowerCase() === raw.toLowerCase());
      sel.value = opt ? opt.value : '';
    });
    document.querySelectorAll('.adv-num').forEach(inp => {
      const m = (pos[inp.dataset.field] || '').match(/^>=(\d+)$/);
      inp.value = m ? m[1] : '';
    });
    VMs.updateAdvCount();
  },

  /* ---------- Kayıtlı aramalar (hesaba bağlı, sunucuda saklanır) ---------- */
  SAVED_KEY: 'vms-saved-searches',
  saved: [],

  async loadSaved() {
    try { VMs.saved = JSON.parse(await App.userGet(VMs.SAVED_KEY) || '[]') || []; }
    catch (e) { VMs.saved = []; }
    if (!Array.isArray(VMs.saved)) VMs.saved = [];
  },

  persistSaved() { App.userSet(VMs.SAVED_KEY, JSON.stringify(VMs.saved)); },

  /** Menü: kayıtlı aramalar (adetleriyle) + mevcut aramayı kaydetme formu. */
  async renderSaved() {
    const menu = document.getElementById('savedMenu');
    const canSave = !!VMs.q || VMs.sort !== 'name' || VMs.order !== 'asc';
    const list = VMs.saved.length
      ? VMs.saved.map((s, i) =>
          '<div class="saved-item" onclick="VMs.applySaved(' + i + ')">' +
            '<div class="saved-main"><div class="saved-name">' + App.esc(s.n) +
              ' <span class="saved-count" data-i="' + i + '"></span></div>' +
              '<code class="saved-q">' + App.esc(s.q || '—') +
              (VMs.USAGE_SORTS[s.s] || (s.s && s.s !== 'name')
                ? ' · ' + App.esc(s.s) + (s.o === 'desc' ? ' ▼' : ' ▲') : '') + '</code></div>' +
            '<button class="btn btn-sm btn-link text-danger p-0" title="' + t('vm.remove', 'Kaldır') + '"' +
            ' onclick="event.stopPropagation();VMs.deleteSaved(' + i + ')"><i class="bi bi-trash"></i></button>' +
          '</div>').join('')
      : '<div class="text-muted small p-3">' +
        t('vm.savedEmpty', 'Henüz kayıtlı arama yok. Bir arama yapıp aşağıdan ad vererek kaydedin.') + '</div>';
    menu.innerHTML =
      '<div class="saved-head"><i class="bi bi-bookmark-star"></i> ' + t('vm.savedSearches', 'Kayıtlı aramalar') + '</div>' +
      '<div class="saved-list">' + list + '</div>' +
      '<div class="saved-form">' +
        '<input id="savedName" class="form-control form-control-sm" maxlength="60" placeholder="' +
          App.esc(canSave ? t('vm.savedNamePh', 'Bu aramaya bir ad verin…') : t('vm.savedNeedQuery', 'Önce bir arama yapın')) + '"' +
          (canSave ? '' : ' disabled') + ' onkeydown="if(event.key===\'Enter\'){event.preventDefault();VMs.saveCurrent();}">' +
        '<button class="btn btn-sm btn-primary" onclick="VMs.saveCurrent()"' + (canSave ? '' : ' disabled') + '>' +
          '<i class="bi bi-plus-lg"></i> ' + t('action.save', 'Kaydet') + '</button>' +
      '</div>';
    if (!VMs.saved.length) return;
    const sp = new URLSearchParams();
    VMs.saved.forEach(s => sp.append('q', s.q || ''));
    if (VMs.includeHidden) sp.set('include_hidden', '1');
    try {
      const r = await App.api('/api/vms/counts?' + sp);
      menu.querySelectorAll('.saved-count').forEach(el => {
        const n = (r.counts || [])[+el.dataset.i];
        if (n != null) el.textContent = n + ' VM';
      });
    } catch (e) { /* adetler opsiyonel */ }
  },

  saveCurrent() {
    const inp = document.getElementById('savedName');
    const name = (inp && inp.value || '').trim();
    if (!name) { if (inp) inp.focus(); return; }
    const entry = {n: name, q: VMs.q, s: VMs.sort, o: VMs.order};
    const i = VMs.saved.findIndex(s => s.n.toLowerCase() === name.toLowerCase());
    if (i >= 0) VMs.saved[i] = entry; else VMs.saved.unshift(entry);
    VMs.saved = VMs.saved.slice(0, 30);
    VMs.persistSaved();
    App.toast(t('vm.savedOk', 'Arama kaydedildi') + ': ' + name);
    VMs.renderSaved();
  },

  deleteSaved(i) {
    VMs.saved.splice(i, 1);
    VMs.persistSaved();
    VMs.renderSaved();
  },

  applySaved(i) {
    const s = VMs.saved[i]; if (!s) return;
    VMs.sort = s.s || 'name'; VMs.order = s.o === 'desc' ? 'desc' : 'asc';
    VMs.markSortHeader();
    bootstrap.Dropdown.getOrCreateInstance(document.getElementById('savedBtn')).hide();
    VMs.applyQuery(s.q || '');
  },

  /* ---------- Arama söz dizimi yardımı (tıklanabilir örnekler) ---------- */
  renderHelp() {
    const ex = (q) => '<code class="q-ex" data-q="' + App.esc(q) + '" title="' +
      App.esc(t('vh.tryIt', 'Tıkla: bu aramayı uygula')) + '">' + App.esc(q) + '</code>';
    const rules = [
      ['bi-fonts', t('vh.r.free', 'Serbest metin'), ['web01'],
       t('vh.r.freeD', 'Her kelime ad, VM ID, IP (elle girilen dahil), MAC, OS, cluster, VLAN, ağ, pool, klasör, sahip, notlar, platform notu ve platform etiketlerinde aranır. Etiket ve host için tag: / host: kullanın.')],
      ['bi-input-cursor-text', t('vh.r.field', 'Alan:değer'), ['os:linux', 'host:esx01'],
       t('vh.r.fieldD', 'Belirli bir alanda arar. Büyük/küçük harf duyarsızdır ve çoğu alan kısmi eşleşir (host:esx → esx01, esx02).')],
      ['bi-intersect', t('vh.r.and', 'VE — boşluk'), ['status:running os:linux'],
       t('vh.r.andD', 'Boşlukla ayrılan kriterlerin hepsi sağlanmalı.')],
      ['bi-union', t('vh.r.or', 'VEYA — virgül'), ['status:running,stopped', 'osfam:windows,linux'],
       t('vh.r.orD', 'Aynı alanda değerlerden herhangi biri. Sayısal ve yok/var değerlerinde virgül kullanılmaz.')],
      ['bi-dash-circle', t('vh.r.not', 'Hariç — eksi'), ['-cluster:test', '-osfam:windows'],
       t('vh.r.notD', 'Başına - (veya !) koyulan kriter dışlanır. Virgüllü değerle: hiçbiri olmayanlar.')],
      ['bi-quote', t('vh.r.quote', 'Tırnak ve tam eşleşme'), ['cluster:"DC East"', 'cluster:=Lab'],
       t('vh.r.quoteD', 'Boşluk içeren değerler çift tırnak içine alınır. = ile başlayan değer alanın tamamıyla eşleşir (cluster:=Lab, Lab2\'yi bulmaz).')],
      ['bi-circle', t('vh.r.empty', 'Boş / dolu'), ['owner:' + QF_NONE, '-owner:' + QF_NONE],
       t('vh.r.emptyD', 'yok (boş, none, empty, null) alanı boş olanları bulur; başına - koyunca dolu olanları.')],
      ['bi-123', t('vh.r.num', 'Sayısal'), ['ram:>=16', 'cpu:>4', 'cpuuse:>=80'],
       t('vh.r.numD', '> >= < <= = ile karşılaştırır; işaretsiz sayı tam eşitliktir (ram:16 = tam 16 GB).')],
    ];
    const F = (names, example, desc) => ({names, example, desc});
    const groups = [
      [t('vh.g.id', 'Kimlik ve ağ'), [
        F(['name', 'vm'], 'name:web', t('vh.f.name', 'VM adı.')),
        F(['vmid', 'id'], 'vmid:105', t('vh.f.vmid', 'VM ID — Proxmox sayısal, VMware MoRef (vm-123).')),
        F(['ip'], 'ip:10.20.', t('vh.f.ip', 'IP adresi (kısmi; elle girilen IP de aranır). ip:yok = ne platform ne elle IP var.')),
        F(['manuelip', 'ipmanuel'], 'manuelip:' + QF_ANY, t('vh.f.manualip', 'Elle girilen IP. manuelip:var = elle IP girilmiş VM\'ler.')),
        F(['mac'], 'mac:00:50:56', t('vh.f.mac', 'MAC adresi (kısmi).')),
        F(['vlan'], 'vlan:100', t('vh.f.vlan', 'VLAN — kısmi eşleşir: vlan:10, 100 ve 110\'u da bulur.')),
        F(['network'], 'network:vmbr0', t('vh.f.network', 'Bağlı ağ / portgroup / köprü adı.')),
      ]],
      [t('vh.g.sys', 'Sistem ve durum'), [
        F(['os'], 'os:ubuntu', t('vh.f.os', 'OS adı (kısmi). os:linux ve os:windows tüm dağıtımları/sürümleri bulur.')),
        F(['osfam', 'osailesi'], 'osfam:redhat', t('vh.f.osfam', 'OS ailesi — dashboard pastasıyla aynı sınıflandırma. Değerler aşağıda.')),
        F(['status'], 'status:running', t('vh.f.status', 'Güç durumu: running, stopped, suspended (TR: çalışan, kapalı, askıda).')),
        F(['tools', 'agent'], 'tools:' + QF_NONE, t('vh.f.tools', 'VMware Tools / QEMU Agent: running = çalışıyor; yok = kurulu değil veya çalışmıyor.')),
      ]],
      [t('vh.g.infra', 'Altyapı ve platform'), [
        F(['host', 'node'], 'host:esx01', t('vh.f.host', 'Bağlı ESXi host / Proxmox node. host:yok = host\'u bilinmeyen.')),
        F(['cluster'], 'cluster:prod', t('vh.f.cluster', 'Cluster (kısmi; tam eşleşme için cluster:=ad, cluster\'sız olanlar için cluster:=). Sorguda cluster: varsa gizli cluster\'lar da aranır.')),
        F(['datastore'], 'datastore:ssd', t('vh.f.datastore', 'Disklerin bulunduğu datastore / storage.')),
        F(['pool', 'havuz'], 'pool:prod', t('vh.f.pool', 'Resource pool (vCenter) / pool (Proxmox).')),
        F(['folder', 'klasor'], 'folder:web', t('vh.f.folder', 'VM klasörü (yalnız vCenter).')),
        F(['platform'], 'platform:"East vCenter"', t('vh.f.platform', 'Platform (bağlantı) adı.')),
        F(['type'], 'type:proxmox', t('vh.f.type', 'Platform tipi: vcenter veya proxmox.')),
        F(['location', 'lokasyon'], 'location:frankfurt', t('vh.f.location', 'Platformun lokasyonu.')),
      ]],
      [t('vh.g.manual', 'Manuel ve platform bilgileri'), [
        F(['env', 'environment'], 'env:production', t('vh.f.env', 'Ortam: production, test, development.')),
        F(['owner'], 'owner:alice', t('vh.f.owner', 'Sahip. owner:yok = sahibi atanmamış.')),
        F(['tag'], 'tag:critical', t('vh.f.tag', 'Manuel etiket. tag:yok = etiketsiz.')),
        F(['notes', 'not'], 'notes:patch', t('vh.f.notes', 'Manuel notlar.')),
        F(['desc', 'aciklama'], 'desc:backup', t('vh.f.desc', 'Platform notu (vCenter annotation / Proxmox description).')),
        F(['ptag', 'petiket'], 'ptag:backup', t('vh.f.ptag', 'Platform etiketleri (vCenter tag / Proxmox tags).')),
      ]],
      [t('vh.g.res', 'Kaynak (sayısal)'), [
        F(['cpu'], 'cpu:>=8', t('vh.f.cpu', 'vCPU sayısı.')),
        F(['ram'], 'ram:>=16', t('vh.f.ram', 'Atanan RAM, GB cinsinden.')),
        F(['disk'], 'disk:>500', t('vh.f.disk', 'Toplam disk boyutu, GB cinsinden.')),
      ]],
      [t('vh.g.use', 'Anlık kullanım (%)'), [
        F(['cpuuse'], 'cpuuse:>=80', t('vh.f.cpuuse', 'Son ölçülen CPU kullanımı. Ölçümü olmayan (kapalı) VM eşleşmez.')),
        F(['ramuse'], 'ramuse:>=90', t('vh.f.ramuse', 'Son ölçülen RAM kullanımı (kullanılan / atanan).')),
        F(['diskuse'], 'diskuse:>=85', t('vh.f.diskuse', 'Gerçek disk doluluğu. Kullanımı bilinmeyen (agent\'sız Proxmox) VM eşleşmez.')),
      ]],
    ];
    const values = [
      ['status', QF_EN ? 'running · stopped · suspended' : 'running · stopped · suspended — çalışan · kapalı · askıda'],
      ['tools', QF_EN ? 'running · none (not installed / not running)' : 'running (var, ok) · yok (notrunning, kapalı)'],
      ['osfam', 'windows · linux · ubuntu · debian · redhat · suse · otherlinux · bsd · vmware · macos · other'],
      ['type', 'vcenter · proxmox'],
      ['env', 'production · test · development'],
      [t('vh.v.empty', 'boş değeri'), QF_EN ? 'none · empty · null (Turkish: yok, boş)' : 'yok · boş · none · empty · null'],
      [t('vh.v.any', 'dolu değeri'), QF_EN ? 'any · set (manuelip:any); for other fields use -field:none' : 'var · dolu (manuelip:var); diğer alanlarda -alan:yok'],
    ];
    const tips = [
      t('vh.t.chips', 'Durum / Platform / OS / Eksikler / Kullanım menüleri çoklu seçimlidir: aynı menüdekiler VEYA (Çalışan + Kapalı = status:running,stopped), farklı menüler VE ile birleşir. ⊘ simgesi veya Shift+tık hariç tutar (kırmızı); tekrar tıklayınca kalkar. Menü düğmesi seçimi özetler.'),
      t('vh.t.counts', 'Menülerdeki sayı, o seçeneğin tek başına kaç VM döndürdüğüdür.'),
      t('vh.t.cells', 'Tablodaki Host, Cluster, Pool, Klasör ve VLAN hücrelerine tıklamak o değeri filtre olarak ekler.'),
      t('vh.t.saved', 'Yer imi simgesi: sık kullandığınız sorguyu (sıralamasıyla) hesabınıza kaydeder; her cihazdan erişilir.'),
      t('vh.t.url', 'Sorgu ve sıralama adres çubuğundadır — linki paylaşabilirsiniz. / tuşu arama kutusuna odaklanır.'),
      t('vh.t.hidden', 'Gizli cluster\'lardaki VM\'ler listelenmez. Hangi cluster\'ların gizli olduğu üst çubuktaki Cluster\'lar düğmesinden yönetilir (herkes için). Cluster menüsünden ya da sorguda cluster: ile seçilen cluster gizli olsa da listelenir; Gelişmiş\'teki "Gizli cluster\'ları dahil et" hepsini katar.'),
      t('vh.t.unknown', 'Tanınmayan alan adı (ör. abc:x) serbest metin olarak aranır.'),
    ];
    document.getElementById('helpBody').innerHTML =
      '<div class="help-rules">' + rules.map(r =>
        '<div class="help-rule"><div class="help-rule-title"><i class="bi ' + r[0] + '"></i> ' + r[1] + '</div>' +
        '<div class="help-rule-ex">' + r[2].map(ex).join(' ') + '</div>' +
        '<div class="help-rule-desc">' + App.esc(r[3]) + '</div></div>').join('') + '</div>' +
      '<h6 class="help-h"><i class="bi bi-list-columns"></i> ' + t('vh.fields', 'Alanlar') +
        ' <small class="text-muted fw-normal">' + t('vh.fieldsSub', '— örneğe tıklayınca arama uygulanır') + '</small></h6>' +
      '<div class="table-responsive"><table class="table table-sm help-table"><thead><tr>' +
        '<th>' + t('vh.col.field', 'Alan') + '</th><th>' + t('vm.example', 'Örnek') + '</th><th>' +
        t('vm.description', 'Açıklama') + '</th></tr></thead><tbody>' +
      groups.map(g => '<tr class="help-group"><td colspan="3">' + g[0] + '</td></tr>' +
        g[1].map(f => '<tr><td class="text-nowrap">' + f.names.map((n, i) =>
            '<code class="' + (i ? 'help-alias' : 'help-field') + '">' + n + ':</code>').join(' ') + '</td>' +
          '<td class="text-nowrap">' + ex(f.example) + '</td><td>' + App.esc(f.desc) + '</td></tr>').join('')).join('') +
      '</tbody></table></div>' +
      '<div class="row g-3">' +
        '<div class="col-lg-6"><h6 class="help-h"><i class="bi bi-card-list"></i> ' + t('vh.values', 'Değerler') + '</h6>' +
          '<table class="table table-sm help-table mb-0"><tbody>' + values.map(v =>
            '<tr><td class="text-nowrap"><code class="help-field">' + App.esc(v[0]) + '</code></td><td class="small">' +
            App.esc(v[1]) + '</td></tr>').join('') + '</tbody></table></div>' +
        '<div class="col-lg-6"><h6 class="help-h"><i class="bi bi-lightbulb"></i> ' + t('vh.tips', 'İpuçları') + '</h6>' +
          '<ul class="help-tips">' + tips.map(x => '<li>' + App.esc(x) + '</li>').join('') + '</ul></div>' +
      '</div>' +
      '<div class="help-combo"><span>' + t('vh.combo', 'Hepsi bir arada:') + '</span> ' +
        ex('type:proxmox status:running osfam:linux ram:>=16 -tag:test') + '</div>';
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
      sel.innerHTML = '<option value="">' + t('vm.allOption','— Tümü —') + '</option>' + items.map(i =>
        '<option value="' + App.esc(i.key) + '">' +
        App.esc(labelFn ? labelFn(i.key) : i.key) + ' (' + i.count + ')</option>').join('');
    };
    fill('platform', f.platforms);
    // Cluster seçimi araç çubuğundaki Cluster menüsünde (gizliler işaretli, tam eşleşme)
    VMs.setClusterItems(f.clusters);
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
      ({running: t('st.running','Çalışıyor'), stopped: t('st.stopped','Kapalı'), suspended: t('st.suspended','Askıda')}[k] || k));
    VMs.syncAdvFromQuery();   // seçenekler artık var: sorgudaki değerleri seçili göster
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
    const sp = new URLSearchParams();
    if (VMs.q) sp.set('q', VMs.q);
    if (VMs.sort !== 'name' || VMs.order !== 'asc') {   // varsayılan değilse sıralama da linkte
      sp.set('sort', VMs.sort); sp.set('order', VMs.order);
    }
    const qs = sp.toString();
    history.replaceState(null, '', '/vms' + (qs ? '?' + qs.replace(/%3A/gi, ':') : ''));
  },

  /** Başlıksız sıralamayı bırak, varsayılana (ada göre A→Z) dön. */
  resetSort() {
    VMs.sort = 'name'; VMs.order = 'asc'; VMs.page = 1;
    VMs.markSortHeader();
    VMs.load();
  },

  /** Aktif sıralama sütununun başlığına ▲/▼ koy. */
  markSortHeader() {
    document.querySelectorAll('#vmTable th.sortable').forEach(th => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === VMs.sort)
        th.classList.add(VMs.order === 'asc' ? 'sorted-asc' : 'sorted-desc');
    });
  },

  /** Sorgudaki her kriteri X'le kaldırılabilir rozet olarak göster. */
  renderActiveFilters() {
    VMs.renderChips();
    VMs.syncAdvFromQuery();
    const wrap = document.getElementById('activeFilters');
    const tokens = VMs.q.match(/[-!]?\w+:"[^"]*"|[-!]?\w+:\S+|[-!]?\S+/g) || [];
    const us = VMs.USAGE_SORTS[VMs.sort];
    const sortBadge = us
      ? '<span class="filter-badge sort-badge"><i class="bi bi-sort-' +
        (VMs.order === 'desc' ? 'down' : 'up') + '"></i> ' +
        t('vm.sortedBy', 'Sıralama') + ': ' + t(us[0], us[1]) + ' ' +
        (VMs.order === 'desc' ? '▼' : '▲') +
        '<button title="' + t('vm.remove','Kaldır') + '" onclick="VMs.resetSort()">' +
        '<i class="bi bi-x"></i></button></span>'
      : '';
    if (!tokens.length && !sortBadge) { wrap.classList.add('d-none'); wrap.innerHTML = ''; return; }
    wrap.classList.remove('d-none');
    wrap.innerHTML = sortBadge + (!tokens.length ? '' :
      '<span class="text-muted small me-1">' + t('vm.activeFilters','Aktif:') + '</span>' +
      tokens.map((tok, i) =>
        '<span class="filter-badge' + ((tok.startsWith('-') || tok.startsWith('!')) ? ' negative' : '') + '">' +
        App.esc(tok) + '<button title="' + t('vm.remove','Kaldır') + '" onclick="VMs.removeToken(' + i + ')">' +
        '<i class="bi bi-x"></i></button></span>').join('') +
      (tokens.length > 1 ? '<button class="btn btn-link btn-sm p-0 ms-1" ' +
        'onclick="VMs.clearAll()">' + t('vm.clearAll','tümünü temizle') + '</button>' : ''));
  },

  /** Rozetin X'ine basılınca o kriteri sorgudan çıkar. */
  removeToken(index) {
    const tokens = VMs.q.match(/[-!]?\w+:"[^"]*"|[-!]?\w+:\S+|[-!]?\S+/g) || [];
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
    VMs.setToken(field, field === 'cluster' ? '=' + value : value);   // cluster: tam eşleşme
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

  // ?sort=&order= (dashboard "en çok kullanan" kartları, paylaşılan linkler) ve
  // ?hl=<id> (tıklanan VM'in satırını vurgula, detayı açmadan).
  const sp = new URLSearchParams(location.search);
  const known = new Set([...document.querySelectorAll('#vmTable th.sortable')]
    .map(th => th.dataset.sort).concat(Object.keys(VMs.USAGE_SORTS)));
  if (known.has(sp.get('sort'))) VMs.sort = sp.get('sort');
  if (sp.get('order') === 'asc' || sp.get('order') === 'desc') VMs.order = sp.get('order');
  const urlHl = parseInt(sp.get('hl'), 10);
  if (urlHl) VMs.highlightId = urlHl;

  // Debounce'lu arama: her tuş vuruşunda değil, 350 ms duraksamada sorgula
  input.addEventListener('input', App.debounce(() => {
    VMs.q = input.value.trim();
    VMs.page = 1;
    VMs.load();
  }, 350));

  document.getElementById('searchClear').addEventListener('click', () => {
    input.value = ''; VMs.q = ''; VMs.page = 1; VMs.load();
  });

  // Hızlı filtreler: grup başına açılır menü (çoklu seçim, Shift+tık hariç tutar)
  VMs.renderQuickFilters();
  // Cluster görünürlüğü (üst çubuk / Cluster menüsü) değişince sayfayı yenilemeden tazele
  if (typeof ClusterVis !== 'undefined') ClusterVis.onChange = () => { VMs.loadFacets(); VMs.loadChipCounts(); VMs.load(); };
  VMs.loadChipCounts();

  // Kayıtlı aramalar: menü açılırken güncel liste + adetler çizilir
  VMs.loadSaved();
  document.getElementById('savedBtn').addEventListener('show.bs.dropdown', () => VMs.renderSaved());
  document.getElementById('savedBtn').addEventListener('shown.bs.dropdown', () => {
    const n = document.getElementById('savedName'); if (n && !n.disabled) n.focus();
  });

  // '/' tuşu arama kutusuna odaklanır (bir alana yazarken değil)
  document.addEventListener('keydown', e => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    e.preventDefault(); input.focus(); input.select();
  });

  document.getElementById('groupBy').addEventListener('change', () => { VMs.page = 1; VMs.load(); });

  // Yardım modalı (içerik ilk açılışta çizilir); örneğe tıklamak aramayı uygular
  document.getElementById('searchHelp').addEventListener('click', () => {
    const body = document.getElementById('helpBody');
    if (!body.childElementCount) VMs.renderHelp();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('helpModal')).show();
  });
  document.getElementById('helpBody').addEventListener('click', e => {
    const ex = e.target.closest('.q-ex'); if (!ex) return;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('helpModal')).hide();
    VMs.applyQuery(ex.dataset.q);
  });

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
    VMs.loadChipCounts();
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
  });
  VMs.markSortHeader();   // açılışta aktif sıralama sütununu işaretle (varsayılan: name asc)

  VMs.buildColChooser();
  VMs.applyCols();

  VMs.load();
})();
