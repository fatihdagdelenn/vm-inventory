/**
 * dashboard.js — Premium ana ekran.
 *  - Modüler 12-kolon grid: kart sürükle / genişlik değiştir / gizle (LocalStorage)
 *  - Premium Chart.js: ince halka pasta, gradyan + neon glow barlar
 *  - Akıllı paneller: Kapasite Öngörüsü, Zombi VM'ler, Canlılık (live dot), sparkline
 * Tüm veriler lokal DB'den: /api/dashboard/summary + /api/dashboard/insights.
 */

/* ============================ Yardımcılar ============================ */
const CHARTS = [];                       // layout değişiminde resize için
const LS_KEY = 'vmi-dash-layout-v1';

/* Long-lived snapshots widget: age filter (7+/14+/30+) applied client-side. */
const SnapWidget = {
  items: [],
  minAge: parseInt(localStorage.getItem('vmi-snap-age') || '30', 10) || 30,
  render() {
    const osb = document.getElementById('oldSnapBody');
    if (!osb) return;
    const rows = this.items.filter(it => (it.days || 0) >= this.minAge);
    osb.innerHTML = rows.length ? rows.map(it =>
      '<tr><td>' + App.esc(it.vm || '—') + '</td><td class="small">' + App.esc(it.name || '') +
      '</td><td class="text-end"><span class="badge ' +
      ((it.days || 0) >= 90 ? 'text-bg-danger'
        : (it.days || 0) >= 30 ? 'text-bg-warning text-dark' : 'text-bg-secondary') + '">' +
      (it.days != null ? it.days + ' ' + t('unit.day','gün') : '—') + '</span></td></tr>').join('')
      : '<tr><td colspan="3" class="text-muted p-3">' +
        this.minAge + '+ ' + t('dash.noSnapsAge','gün yaşında snapshot yok 🎉') + '</td></tr>';
    document.querySelectorAll('.snap-age-chips [data-age]').forEach(b =>
      b.classList.toggle('active', parseInt(b.dataset.age, 10) === this.minAge));
  },
  bind() {
    document.querySelectorAll('.snap-age-chips [data-age]').forEach(b =>
      b.addEventListener('click', () => {
        SnapWidget.minAge = parseInt(b.dataset.age, 10) || 30;
        try { localStorage.setItem('vmi-snap-age', String(SnapWidget.minAge)); } catch (e) {}
        SnapWidget.render();
      }));
  },
};
document.addEventListener('DOMContentLoaded', () => SnapWidget.bind());
const WIDTHS = [2, 3, 4, 6, 12];          // genişlik döngüsü (12-kolon grid)

/** #rrggbb → rgba(r,g,b,a) */
function hexA(hex, a) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
  if (!m) return hex;
  return `rgba(${parseInt(m[1],16)},${parseInt(m[2],16)},${parseInt(m[3],16)},${a})`;
}

/** Çubuklar için yönüne göre yumuşak gradyan (chartArea hazır değilse düz renk). */
function barGrad(chart, base, horizontal) {
  const area = chart.chartArea, ctx = chart.ctx;
  if (!area) return hexA(base, .7);
  const g = horizontal
    ? ctx.createLinearGradient(area.left, 0, area.right, 0)
    : ctx.createLinearGradient(0, area.bottom, 0, area.top);
  g.addColorStop(0, hexA(base, .28));
  g.addColorStop(1, hexA(base, .96));
  return g;
}

/* ============================ Premium grafikler + akıllı paneller ============ */
(async function () {
  let d;
  try { d = await App.api('/api/dashboard/summary'); } catch (e) { return; }

  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? 0; };
  set('st-vcenter', d.vcenter_count);  set('st-proxmox', d.proxmox_count);
  set('st-host', d.host_count);        set('st-vm', d.vm_total);
  set('st-running', d.vm_running);     set('st-stopped', d.vm_stopped);
  set('st-suspended', d.vm_suspended);
  const P = d.phys || {};
  const el = id => document.getElementById(id);
  const setT = (id, v) => { const x = el(id); if (x) x.textContent = v || '—'; };
  // Assigned/Total ratio bar: fills toward 100%; overcommit (>100%) turns amber.
  const ratioBar = (id, alloc, tot) => {
    const b = el(id); if (!b) return;
    if (!tot) { b.parentElement.style.display = 'none'; return; }
    const pct = 100 * alloc / tot;
    b.style.width = Math.min(100, pct) + '%';
    b.classList.toggle('over', pct > 100);
    b.parentElement.title = t('fc.alloc','Tahsis') + ': %' + Math.round(pct);
  };
  set('st-vcpu', d.total_vcpu);
  setT('st-vcpu-total', P.cores);
  ratioBar('st-vcpu-bar', d.total_vcpu, P.cores);
  const gbf = g => g >= 1024 ? (g/1024).toFixed(1)+' TB' : g+' GB';
  set('st-ram', gbf(d.total_ram_gb));
  setT('st-ram-total', P.ram_gb ? gbf(P.ram_gb) : null);
  ratioBar('st-ram-bar', d.total_ram_gb, P.ram_gb);
  set('st-disk', d.total_disk_tb + ' TB');
  setT('st-disk-total', P.disk_tb ? P.disk_tb + ' TB' : null);
  ratioBar('st-disk-bar', d.total_disk_tb, P.disk_tb);
  set('at-noip', d.attention.no_ip);       set('at-notools', d.attention.no_tools);
  set('at-noowner', d.attention.no_owner);  set('at-oldsnap', d.attention.old_snapshots);
  set('at-nobackup', d.attention.no_backup);
  SnapWidget.items = d.old_snapshot_items || [];
  SnapWidget.render();

  const hi = document.getElementById('hiddenInfo');
  if (hi && d.hidden_clusters > 0) { hi.textContent = d.hidden_clusters + ' ' + t('dash.clustersHidden','cluster gizli'); hi.classList.remove('d-none'); }
  const uf = document.getElementById('usageFresh');
  if (uf) uf.textContent = d.usage_updated ? t('dash.usagePrefix','kullanım: ') + App.fmtDate(d.usage_updated)
                                           : t('dash.usageWaiting','kullanım: ilk senkronizasyon bekleniyor');

  /* ---- Premium grafik ortak ayarları (tema-duyarlı) ---- */
  const LIGHT = localStorage.getItem('vmi-dash-theme') === 'light';
  Chart.defaults.font.family = "'Inter','Segoe UI',system-ui,sans-serif";
  Chart.defaults.color = LIGHT ? '#475569' : '#94a8c4';
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.scale.grid.color = LIGHT ? 'rgba(15,29,46,.07)' : 'rgba(148,163,184,.10)';
  Chart.defaults.scale.grid.drawBorder = false;
  Chart.defaults.scale.ticks.color = LIGHT ? '#64748b' : '#7e93b3';
  Chart.defaults.plugins.legend.labels.color = LIGHT ? '#334155' : '#aebfd6';

  // Neon glow eklentisi (yalnız options.plugins.glow tanımlı grafiklerde)
  Chart.register({
    id: 'glow',
    beforeDatasetsDraw(chart, _a, opts) {
      if (!opts || !opts.color) return;
      const c = chart.ctx; c.save(); c.shadowColor = opts.color; c.shadowBlur = opts.blur || 14;
    },
    afterDatasetsDraw(chart, _a, opts) { if (opts && opts.color) chart.ctx.restore(); },
  });

  const CARD = LIGHT ? '#ffffff' : '#151f32';   // halka ayraç = kart arka planı
  const PALETTE = ['#3b9bff','#3fdc8f','#a371ff','#ffc24b','#ff6b6b','#39d3df','#ff7ac0','#8ea3c0'];
  const BLUE='#3b9bff', GREEN='#3fdc8f', ORANGE='#ffc24b', RED='#ff6b6b', PURPLE='#a371ff';
  const critColor = pct => pct >= 90 ? RED : pct >= 75 ? ORANGE : BLUE;

  const goVms = q => location.href = '/vms?q=' + encodeURIComponent(q);
  const clickHandler = (qFn) => (evt, els, chart) => {
    if (!els.length) return;
    const q = qFn(chart.data.labels[els[0].index]);
    if (q) goVms(q);
  };
  const track = c => { CHARTS.push(c); return c; };

  /** İnce halka pasta (premium doughnut). */
  const doughnut = (canvasId, labels, values, colors, onClick) => {
    const el = document.getElementById(canvasId); if (!el) return;
    track(new Chart(el, {
      type: 'doughnut',
      data: {labels, datasets: [{data: values, backgroundColor: colors,
              borderColor: CARD, borderWidth: 3, borderRadius: 6, spacing: 2, hoverOffset: 7}]},
      options: {cutout: '74%', plugins: {legend: {position: 'bottom',
                  labels: {boxWidth: 10, boxHeight: 10, padding: 12, usePointStyle: true}},
                glow: {color: 'rgba(59,155,255,.35)', blur: 10}}, onClick}
    }));
  };

  const envLabels = Object.keys(d.env_distribution);
  doughnut('chartEnv', envLabels, envLabels.map(k => d.env_distribution[k]),
    envLabels.map((_, i) => PALETTE[i % PALETTE.length]),
    clickHandler(l => l === '—' ? null : 'env:' + l));

  const osData = d.os_distribution || [];
  doughnut('chartOs', osData.map(o => o.label), osData.map(o => o.count),
    osData.map((_, i) => PALETTE[i % PALETTE.length]),
    clickHandler(label => { const f = osData.find(o => o.label === label); return f ? f.query : null; }));

  /** Premium bar (gradyan dolgu + yuvarlatılmış + neon glow). */
  const bar = (canvasId, labels, values, opts = {}) => {
    const el = document.getElementById(canvasId); if (!el) return;
    const horizontal = opts.horizontal !== false;     // varsayılan yatay
    const baseOf = opts.colorFn || (() => opts.base || BLUE);
    track(new Chart(el, {
      type: 'bar',
      data: {labels, datasets: [{label: opts.label || '', data: values,
              borderRadius: 8, borderSkipped: false,
              maxBarThickness: opts.thick || 26,
              backgroundColor: ctx => barGrad(ctx.chart, baseOf(ctx.dataIndex), horizontal)}]},
      options: {indexAxis: horizontal ? 'y' : 'x',
        plugins: {legend: {display: false}, glow: {color: hexA(opts.base || BLUE, .45), blur: 12},
                  tooltip: opts.tooltip},
        scales: opts.scales || {x: {beginAtZero: true, ticks: {precision: 0}}},
        onClick: opts.onClick}
    }));
  };

  bar('chartCluster', d.cluster_distribution.map(c => c.key), d.cluster_distribution.map(c => c.count),
    {base: BLUE, label: 'VM',
     onClick: clickHandler(l => l === '—' ? 'cluster:yok' : (/\s/.test(l) ? 'cluster:"'+l+'"' : 'cluster:'+l))});

  bar('chartTopOs', d.top_os.map(o => o.key), d.top_os.map(o => o.count),
    {base: PURPLE, colorFn: i => PALETTE[i % PALETTE.length]});

  /* Host CPU/RAM — dikey, kritik renkli gradyan + glow */
  const usageBar = (canvasId, key, base) => {
    const rows = [...d.host_usage].sort((a, b) => (b[key] || 0) - (a[key] || 0));
    bar(canvasId, rows.map(h => h.name), rows.map(h => h[key]),
      {horizontal: false, base, thick: 44,
       colorFn: i => critColor(rows[i][key] || 0),
       scales: {y: {beginAtZero: true, max: 100, ticks: {callback: v => v + '%'}}}});
  };
  usageBar('chartCpu', 'cpu_pct', BLUE);
  usageBar('chartRam', 'ram_pct', GREEN);

  /* En çok kaynak tüketen VM'ler */
  const topVm = (canvasId, items, valueFn, tipFn, colorFn) =>
    bar(canvasId, items.map(v => v.name), items.map(valueFn),
      {base: BLUE, thick: 22, colorFn,
       tooltip: {callbacks: {label: ctx => tipFn(items[ctx.dataIndex])}},
       onClick: (e, els) => { if (els.length) goVms(items[els[0].index].name); }});
  topVm('chartTopCpu', d.top_cpu_vms || [], v => v.pct,
    v => `CPU %${v.pct}` + (v.host ? ' · ' + v.host : ''), i => critColor((d.top_cpu_vms||[])[i].pct));
  topVm('chartTopRam', d.top_ram_vms || [], v => v.pct,
    v => `RAM %${v.pct} (${v.used_gb} GB)` + (v.host ? ' · ' + v.host : ''), i => critColor((d.top_ram_vms||[])[i].pct));
  topVm('chartTopDisk', d.top_disk_vms || [], v => (v.value_gb != null ? v.value_gb : v.used_gb),
    v => (v.is_used ? `${v.used_gb} / ${v.total_gb} GB kullanımda` : `${v.total_gb} GB ayrılan`) + (v.host ? ' · ' + v.host : ''),
    i => { const v = (d.top_disk_vms||[])[i]; return v.is_used ? critColor(v.total_gb ? 100*v.used_gb/v.total_gb : 0) : '#5f7799'; });

  bar('chartHostVm', (d.host_vm_dist || []).map(h => h.name), (d.host_vm_dist || []).map(h => h.count),
    {base: BLUE, thick: 24, label: 'VM',
     onClick: clickHandler(l => l === '—' ? null : (/\s/.test(l) ? 'host:"'+l+'"' : 'host:'+l))});

  const cr = d.cluster_resource || [];
  bar('chartClusterRes', cr.map(c => c.key), cr.map(c => c.vcpu),
    {base: PURPLE, thick: 24,
     tooltip: {callbacks: {label: ctx => { const c = cr[ctx.dataIndex];
       return `${c.vcpu} vCPU · ${c.ram_gb} GB RAM · ${c.vms} VM`; }}},
     onClick: clickHandler(l => l === '—' ? 'cluster:yok' : (/\s/.test(l) ? 'cluster:"'+l+'"' : 'cluster:'+l))});

  const dsf = d.datastore_fill || [];
  bar('chartDatastore', dsf.map(s => s.name), dsf.map(s => s.usage_pct),
    {base: BLUE, thick: 22, colorFn: i => critColor(dsf[i].usage_pct),
     scales: {x: {beginAtZero: true, max: 100, ticks: {callback: v => v + '%'}}},
     tooltip: {callbacks: {label: ctx => { const s = dsf[ctx.dataIndex];
       return `%${s.usage_pct} · ${s.used_gb} / ${s.capacity_gb} GB`; }}},
     onClick: () => { location.href = '/datastores'; }});

  /* ---- Son değişiklikler ---- */
  const typeBadge = ct => ({
    created: '<span class="badge text-bg-success">' + t('ct.created','Eklendi') + '</span>',
    updated: '<span class="badge text-bg-warning text-dark">' + t('ct.updated','Güncellendi') + '</span>',
    deleted: '<span class="badge text-bg-danger">' + t('ct.deleted','Silindi') + '</span>',
    migrated: '<span class="badge text-bg-info text-dark">' + t('ct.migrated','Göç') + '</span>',
    access: '<span class="badge text-bg-secondary">' + t('ct.access','Erişim') + '</span>',
  }[ct] || App.esc(ct));
  const rc = document.getElementById('recentChanges');
  if (rc) rc.innerHTML = d.recent_changes.length ? d.recent_changes.map(c => '<tr>' +
    '<td class="text-nowrap small text-muted">' + App.fmtDate(c.changed_at) + '</td>' +
    '<td><strong>' + App.esc(c.entity_name) + '</strong> <small class="text-muted">(' +
      (c.entity_type === 'vm' ? 'VM' : 'Host') + ')</small></td>' +
    '<td>' + typeBadge(c.change_type) + '</td>' +
    '<td class="small">' + (c.field ? App.esc(c.field) + ': <span class="text-muted">' +
      App.esc(c.old_value || '—') + '</span> → ' + App.esc(c.new_value || '—') : '—') +
    '</td></tr>').join('')
    : '<tr><td colspan="4" class="text-muted p-3">' + t('dash.noChanges','Henüz değişiklik kaydı yok.') + '</td></tr>';

  /* ---- Platform durumları ---- */
  const tbody = document.getElementById('platformStatus');
  if (tbody) tbody.innerHTML = d.platforms.length ? d.platforms.map(p => {
    const badge = p.status === '-' ? '<span class="badge text-bg-secondary">' + t('st.none','Henüz yok') + '</span>'
      : p.status === 'success' ? '<span class="badge text-bg-success">' + t('st.success','Başarılı') + '</span>'
      : '<span class="badge text-bg-danger">' + t('st.error','Hata') + '</span>';
    return '<tr><td>' + App.esc(p.name) + '</td><td>' + (p.type === 'vcenter' ? 'vCenter' : 'Proxmox') +
      '</td><td class="small">' + App.fmtDate(p.last_sync) + '</td><td>' + badge + '</td></tr>';
  }).join('')
    : '<tr><td colspan="4" class="text-muted p-3">' + t('dash.noPlatforms','Henüz platform eklenmemiş.') + ' ' +
      '<a href="/platforms">' + t('nav.platforms','Platformlar') + '</a> ' + t('dash.addFromPage','sayfasından ekleyebilirsiniz.') + '</td></tr>';

  /* ============== Akıllı paneller (insights) ============== */
  let ins;
  try { ins = await App.api('/api/dashboard/insights'); } catch (e) { ins = null; }
  if (ins) renderInsights(ins);

  /** Kapasite öngörüsü + zombi + canlılık + sparkline render. */
  function renderInsights(ins) {
    const STAT = {ok: ['text-success', 'bi-check-circle', t('fc.healthy','Sağlıklı')],
                  warn: ['text-warning', 'bi-exclamation-triangle', t('fc.warn','Yaklaşıyor')],
                  crit: ['text-danger', 'bi-exclamation-octagon', t('fc.crit','Kritik')],
                  stable: ['text-success', 'bi-check-circle', t('fc.stable','Kararlı')],
                  collecting: ['text-info', 'bi-hourglass-split', t('fc.collecting','Veri toplanıyor')],
                  none: ['text-muted', 'bi-dash-circle', t('fc.none','Yetersiz veri')]};
    const fc = ins.forecast;
    const fcWin = document.getElementById('fc-window');
    if (fcWin) fcWin.innerHTML = fc.method === 'trend'
      ? `<i class="bi bi-activity"></i> ${fc.window_days} ${t('fc.dayTrend','günlük gerçek trend')}`
      : `<i class="bi bi-hourglass-split"></i> ${t('fc.collectingShort','veri toplanıyor')} (${fc.days_collected}/${fc.days_needed} ${t('unit.day','gün')})`;

    // Gün sayısını insanca biçimle (çok büyükse abartılı görünmesin)
    const daysHuman = (d) => {
      if (d >= 1825) return '5+ ' + t('unit.year','yıl');
      if (d >= 365) return `~${(d / 365).toFixed(1).replace('.0', '')} ${t('unit.year','yıl')}`;
      if (d >= 60) return `~${Math.round(d / 30)} ${t('unit.month','ay')}`;
      return `~${d} ${t('unit.day','gün')}`;
    };
    const fcRow = (title, icon, f, unit, fmtFn) => {
      if (!f.capacity_gb) {
        return `<div class="forecast-row"><div class="d-flex align-items-center mb-1">
          <i class="bi ${icon} me-2"></i><strong>${title}</strong></div>
          <div class="small text-muted"><i class="bi bi-info-circle"></i> ${t('fc.noCap','Kapasite verisi yok — depolama toplanmadı veya izin (Datastore.Audit) eksik.')}</div></div>`;
      }
      const [cls, bi, txt] = STAT[f.status] || STAT.none;
      const fmt = fmtFn || ((gb) => gb >= 1024 ? (gb / 1024).toFixed(1) + ' TB' : Math.round(gb) + ' GB');
      let daysTxt;
      if (f.status === 'collecting')
        daysTxt = `<span class="text-info"><i class="bi bi-hourglass-split"></i> ${t('fc.collectingTrend','Doluluk trendi için veri toplanıyor.')}</span>`;
      else if (f.status === 'crit' && f.days_left == null)
        daysTxt = `<strong class="text-danger">${t('fc.full','Kapasite dolu/aşıldı.')}</strong>`;
      else if (f.days_left != null)
        daysTxt = `${t('fc.atCurrent','Mevcut')} <strong>${t('fc.usage','Doluluk').toLowerCase()}</strong> ${t('fc.rate','hızıyla')} <strong class="${cls}">${daysHuman(f.days_left)}</strong> ${t('fc.mayFill','sonra dolabilir')}`;
      else
        daysTxt = `<span class="text-success">${t('fc.negligible','Doluluk büyümesi kayda değer değil — kararlı.')}</span>`;
      const up = f.used_pct != null ? f.used_pct : 0;       // gerçek doluluk
      const barCls = up >= 90 ? 'bg-danger' : up >= 75 ? 'bg-warning' : 'bg-success';
      const rate = f.per_day_gb > 0 ? `<span>+${fmt(f.per_day_gb)}/gün</span>` : '<span></span>';
      // Tahsis (overcommit) satırı — ayrı kavram
      const ocCls = f.alloc_pct > 100 ? 'text-warning' : 'text-muted';
      const ocBadge = f.overcommit ? ` <span class="badge bg-warning-subtle text-warning-emphasis" title="${t('fc.overcommitHint','VM\'lere fizikselden fazla')} ${unit} ${t('fc.overcommitHint2','verilmiş — sanallastirmada olagan')}">overcommit</span>` : '';
      return `<div class="forecast-row">
        <div class="d-flex align-items-center mb-1">
          <i class="bi ${icon} me-2"></i><strong>${title}</strong>
          <span class="ms-auto small ${cls}"><i class="bi ${bi}"></i> ${txt}</span></div>
        <div class="progress forecast-bar"><div class="progress-bar ${barCls}" style="width:${Math.min(100,up)}%"></div></div>
        <div class="d-flex justify-content-between small mt-1">
          <span><strong>${t('fc.usage','Doluluk')}:</strong> ${fmt(f.used_gb)} / ${fmt(f.capacity_gb)} <span class="text-muted">(%${up})</span></span>
          ${rate}</div>
        <div class="small ${ocCls} mt-1"><strong>${t('fc.alloc','Tahsis')}:</strong> ${fmt(f.allocated_gb)}
          <span class="text-muted">(fizikselin %${f.alloc_pct ?? 0}'i)</span>${ocBadge}</div>
        <div class="small mt-1">${daysTxt}</div></div>`;
    };
    const fb = document.getElementById('forecastBody');
    if (fb) fb.innerHTML = fcRow(t('fc.diskTitle','Disk (Datastore)'), 'bi-device-hdd', fc.disk, 'disk') +
                           fcRow(t('fc.ramTitle','RAM (Fiziksel)'), 'bi-memory', fc.ram, 'RAM') +
      (fc.cpu && fc.cpu.capacity_gb ? fcRow(t('fc.cpuTitle','CPU (Çekirdek)'), 'bi-cpu', fc.cpu, 'vCPU', c => Math.round(c) + ' ' + t('unit.core','çekirdek')) : '') +
      `<div class="text-muted mt-1" style="font-size:.72rem; line-height:1.5">
        <i class="bi bi-info-circle"></i> ${t('fc.noteShort','Doluluk = gerçek kullanım, Tahsis = VM\'lere verilen. Öngörü doluluk artış hızına göredir')}` +
      (fc.method === 'trend' ? ` (${t('fc.lastN','son')} ${fc.window_days} ${t('unit.day','gün')}).` : `; ${t('fc.collectingShort','veri toplanıyor')}.`) +
      `</div>`;

    /* Zombi VM'ler */
    const zc = document.getElementById('zombieCount');
    const s = ins.zombie_savings;
    if (zc) zc.textContent = s.count + ' VM';
    const zb = document.getElementById('zombieBody');
    if (zb) {
      if (!ins.zombies.length) {
        zb.innerHTML = '<div class="text-success small p-2"><i class="bi bi-check-circle"></i> ' +
          (ins.zombie_basis === '14-30d'
            ? t('zb.none1','Çok metrikli analizde (CPU+RAM+Disk+Ağ) zombi/şüpheli VM yok.')
            : t('zb.none2','Boşta görünen çalışan VM yok. (Anlık örneğe göre)')) + '</div>';
      } else {
        const scoreBg = z => z.score == null ? '#64748b'
          : (z.score >= 80 ? '#ef4444' : (z.score >= 55 ? '#f59e0b' : '#22c55e'));
        const kcode = z => z.klass_code || ((z.klass || '').startsWith('Kesin') ? 'zombie'
          : (z.klass || '').startsWith('Şüpheli') ? 'suspect' : 'active');
        const klassBg = z => ({zombie: '#ef4444', suspect: '#f59e0b'}[kcode(z)] || '#22c55e');
        const klassLbl = z => t('zb.k.' + kcode(z), z.klass || '');
        const confLbl = z => z.confidence_code ? t('zb.conf.' + z.confidence_code, z.confidence) : (z.confidence || '');
        const reasonTxt = z => (z.reasons_s && z.reasons_s.length) ? z.reasons_s.map(r => {
          if (r.m === 'cpu') return t('zb.r.cpu','CPU ort') + ' %' + r.avg + ', ' + t('zb.r.peak','tepe') + ' %' + r.max + (r.idle ? ' ' + t('zb.r.idle','(idle)') : '');
          if (r.m === 'ram') return t('zb.r.ram','RAM dalgalanma') + ' %' + r.flat + (r.ok ? ' ' + t('zb.r.flat','(düz)') : '');
          if (r.m === 'disk') return r.none ? t('zb.r.diskNone','Disk verisi henüz yok') : t('zb.r.disk','Disk I/O') + ' ~' + r.kbps + ' KB/s' + (r.ok ? ' ' + t('zb.r.quiet','(boşta)') : '');
          if (r.m === 'net') return r.none ? t('zb.r.netNone','Ağ verisi henüz yok') : t('zb.r.net','Ağ') + ' ~' + r.kbps + ' KB/s' + (r.ok ? ' ' + t('zb.r.hb','(heartbeat)') : '');
          if (r.m === 'instant') return t('zb.r.instant','Anlık CPU (tarihsel veri yok)') + ' %' + r.cpu;
          return '';
        }).filter(Boolean) : (z.reasons || []);
        zb.innerHTML =
          `<div class="zombie-savings mb-2"><i class="bi bi-piggy-bank"></i>
            ${t('zb.recoverable','Geri kazanılabilir')}: <strong>${s.vcpu}</strong> vCPU ·
            <strong>${s.ram_gb}</strong> GB RAM · <strong>${s.disk_gb}</strong> GB disk</div>
          <div class="table-responsive"><table class="table table-sm table-hover align-middle mb-1">
            <thead><tr><th>VM</th><th class="text-center">${t('zb.score','Skor')}</th><th>${t('zb.class','Sınıf')}</th><th class="text-end">RAM</th></tr></thead>
            <tbody>` + ins.zombies.map(z =>
              `<tr>
                <td><strong>${App.esc(z.name)}</strong>
                  <div class="text-muted" style="font-size:.7rem">${App.esc(z.host || '—')} · ${reasonTxt(z).map(App.esc).join(' · ')}</div>
                </td>
                <td class="text-center"><span style="display:inline-block;min-width:38px;padding:2px 8px;border-radius:999px;font-weight:700;color:#fff;background:${scoreBg(z)}">${z.score == null ? '—' : z.score}</span></td>
                <td><span style="display:inline-block;padding:1px 8px;border-radius:6px;font-size:.72rem;font-weight:600;color:#fff;background:${klassBg(z)}">${App.esc(klassLbl(z))}</span>
                  <div class="text-muted" style="font-size:.68rem">${t('zb.confidence','güven')}: ${App.esc(confLbl(z))}</div></td>
                <td class="text-end small">${z.ram_gb} GB</td>
              </tr>`).join('') +
          `</tbody></table></div>
          <div class="text-muted fst-italic" style="font-size:.72rem">` +
          (ins.zombie_basis === '14-30d'
            ? t('zb.basis1','14-30 günlük CPU+RAM+Disk+Ağ korelasyonu. "Kesin Zombi" için 4 metrik birden idle + ≥7 gün veri gerekir; eksik metrik en fazla "Şüpheli" verir.')
            : t('zb.basis2','Anlık CPU < %2 (tarihsel veri birikiyor). Disk/Ağ örnekleri biriktikçe çok metrikli skora geçer.')) +
          `</div>`;
      }
    }

    /* Canlılık (live dot) */
    const lt = document.getElementById('liveText');
    if (lt) {
      const iv = ins.live.interval_minutes;
      const last = ins.live.last_sync ? App.fmtDate(ins.live.last_sync) : t('common.never','henüz yok');
      lt.innerHTML = `${t('dash.live','Canlı')} · ${t('dash.every','her')} <strong>${iv} ${t('unit.min','dk')}</strong> · ${t('dash.last','son')}: ${last}`;
    }

    /* Sparkline: Toplam VM kartı (14 günlük kümülatif) */
    const sp = document.getElementById('spark-vm');
    if (sp && ins.spark && ins.spark.vms) {
      track(new Chart(sp, {
        type: 'line',
        data: {labels: ins.spark.vms.map((_, i) => i),
               datasets: [{data: ins.spark.vms, borderColor: hexA(GREEN, .9), borderWidth: 2,
                 fill: true, tension: .42, pointRadius: 0,
                 backgroundColor: ctx => { const a = ctx.chart.chartArea; if (!a) return 'transparent';
                   const g = ctx.chart.ctx.createLinearGradient(0, a.top, 0, a.bottom);
                   g.addColorStop(0, hexA(GREEN, .35)); g.addColorStop(1, hexA(GREEN, 0)); return g; }}]},
        options: {plugins: {legend: {display: false}, tooltip: {enabled: false}},
                  scales: {x: {display: false}, y: {display: false}}, animation: false}
      }));
    }
  }
})();

/* ============================ Modüler grid yönetimi ============================ */
const ROWH = 100, ROW_GAP = 16;           // sabit-satır grid: satır yüksekliği + boşluk
const HMAX = 12, WMAX = 12;                // maksimum satır/kolon açıklığı
// Widget başına varsayılan yükseklik (satır). Belirtilmeyen = 3.
const DEFAULT_H = {
  oldSnapshots: 3,
  'stat-vcenter': 1, 'stat-proxmox': 1, 'stat-host': 1, 'stat-vm': 1,
  'stat-running': 1, 'stat-stopped': 1,
  'mini-vcpu': 1, 'mini-ram': 1, 'mini-disk': 1, 'mini-suspended': 1,
  'recentChanges': 4, 'platformStatus': 4,
};
const LS_KEY2 = 'vmi-dash-layout-v2';     // çoklu sayfa + masonry yerleşimi
let _uid = 0; const newId = () => 'p' + (Date.now().toString(36)) + (++_uid);

const DashGrid = {
  editing: false,
  state: null,

  /* ---- Durum yükle / kaydet / migrasyon ---- */
  loadRaw() { try { return JSON.parse(localStorage.getItem(LS_KEY2)); } catch (e) { return null; } },
  save() { try { localStorage.setItem(LS_KEY2, JSON.stringify(DashGrid.state)); } catch (e) {} },

  allWidgetIds() {
    return [...document.querySelectorAll('#dashGrid .dash-widget')].map(w => w.dataset.widget);
  },

  ensureState() {
    const ids = DashGrid.allWidgetIds();
    let st = DashGrid.loadRaw();
    if (!st || !st.pages) {
      // v1 (tek sayfa) yerleşimini taşı, yoksa varsayılan kur
      let v1 = null; try { v1 = JSON.parse(localStorage.getItem(LS_KEY)); } catch (e) {}
      const p1 = 'p1';
      st = { pages: [{ id: p1, name: 'Genel' }], active: p1,
             assign: {}, order: {}, width: {}, height: {}, hidden: [] };
      const ord = (v1 && v1.order && v1.order.length)
        ? v1.order.filter(id => ids.includes(id)) : ids.slice();
      ids.forEach(id => { if (!ord.includes(id)) ord.push(id); });
      st.order[p1] = ord;
      ids.forEach(id => { st.assign[id] = [p1]; });
      if (v1 && v1.width) st.width = { ...v1.width };
      if (v1 && v1.hidden) st.hidden = v1.hidden.filter(id => ids.includes(id));
    }
    st.height = st.height || {};
    // Multi-page widgets: assign values are ARRAYS of page ids (a widget can
    // live on several pages; only one page renders at a time, so one DOM node
    // is enough). Old single-string layouts migrate transparently.
    Object.keys(st.assign).forEach(k => {
      if (!Array.isArray(st.assign[k])) st.assign[k] = [st.assign[k]];
    });
    // Yeni eklenen widget'ları (kod güncellemesi) ilk sayfaya iliştir + varsayılan yükseklik
    const first = st.pages[0].id;
    ids.forEach(id => {
      if (!(id in st.assign)) st.assign[id] = [first];
      st.assign[id].forEach(pg => {
        st.order[pg] = st.order[pg] || [];
        if (!st.order[pg].includes(id)) st.order[pg].push(id);
      });
      if (!(id in st.height)) st.height[id] = DEFAULT_H[id] || 3;
    });
    if (!st.pages.some(p => p.id === st.active)) st.active = st.pages[0].id;
    DashGrid.state = st;
  },

  setWidth(w, val) { w.dataset.w = val; w.style.setProperty('--w', val); },
  setSize(w, cols, rows) {
    w.dataset.w = cols; w.style.setProperty('--w', cols);
    w.dataset.h = rows; w.style.setProperty('--h', rows);
  },

  /* ---- Görünüm: aktif sayfanın widget'larını sıraya diz, gerisini gizle ---- */
  applyView() {
    const grid = document.getElementById('dashGrid'); if (!grid) return;
    const st = DashGrid.state, act = st.active;
    (st.order[act] || []).forEach(id => {
      const w = grid.querySelector(`[data-widget="${id}"]`); if (w) grid.appendChild(w);
    });
    grid.querySelectorAll('.dash-widget').forEach(w => {
      const id = w.dataset.widget;
      const onPage = (st.assign[id] || [st.pages[0].id]).includes(act);
      const hidden = st.hidden.includes(id);
      w.style.display = (onPage && !hidden) ? '' : 'none';
      const cols = st.width[id] || parseInt(w.dataset.w, 10) || 4;
      const rows = st.height[id] || DEFAULT_H[id] || 3;
      DashGrid.setSize(w, cols, rows);
      w.querySelectorAll('.wt-pages-menu input').forEach(cb => {
        cb.checked = (st.assign[id] || []).includes(cb.value);
      });
    });
    DashGrid.refreshHiddenMenu();
    DashGrid.resizeCharts();
  },

  /* Sabit-satır grid: satır-açıklığı kullanıcı tarafından ayarlanır (masonry yok).
     Boyut değişince grafikleri yeniden ölçekle. */
  relayout() { DashGrid.resizeCharts(); },

  cycleWidth(w) {
    const cur = parseInt(w.dataset.w, 10);
    const next = WIDTHS[(WIDTHS.indexOf(cur) + 1) % WIDTHS.length] || 4;
    DashGrid.setWidth(w, next);
    DashGrid.state.width[w.dataset.widget] = next;
    DashGrid.save(); DashGrid.relayout();
  },

  /* ---- Köşeden sürükle-boyutlandırma (hem genişlik hem yükseklik) ---- */
  rz: null,
  startResize(e, w) {
    e.preventDefault(); e.stopPropagation();
    const grid = document.getElementById('dashGrid');
    const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length || 12;
    const gridRect = grid.getBoundingClientRect();
    const colUnit = (gridRect.width - (cols - 1) * ROW_GAP) / cols + ROW_GAP;  // 1 kolon + boşluk
    const rowUnit = ROWH + ROW_GAP;                                            // 1 satır + boşluk
    const wRect = w.getBoundingClientRect();
    w.draggable = false;                        // taşıma-sürüklemesiyle çakışmasın
    w.classList.add('resizing');
    DashGrid.rz = { w, wLeft: wRect.left, wTop: wRect.top, colUnit, rowUnit, cols };
    window.addEventListener('pointermove', DashGrid.onResize);
    window.addEventListener('pointerup', DashGrid.endResize, { once: true });
  },
  onResize(e) {
    const rz = DashGrid.rz; if (!rz) return;
    const nc = Math.min(rz.cols, Math.max(1, Math.round((e.clientX - rz.wLeft) / rz.colUnit)));
    const nr = Math.min(HMAX, Math.max(1, Math.round((e.clientY - rz.wTop) / rz.rowUnit)));
    DashGrid.setSize(rz.w, nc, nr);
  },
  endResize() {
    const rz = DashGrid.rz; if (!rz) return;
    window.removeEventListener('pointermove', DashGrid.onResize);
    const w = rz.w; w.classList.remove('resizing');
    if (DashGrid.editing) w.draggable = true;
    const id = w.dataset.widget;
    DashGrid.state.width[id] = parseInt(w.dataset.w, 10);
    DashGrid.state.height[id] = parseInt(w.dataset.h, 10);
    DashGrid.rz = null;
    DashGrid.save(); DashGrid.resizeCharts();
  },

  hide(w) {
    const id = w.dataset.widget;
    if (!DashGrid.state.hidden.includes(id)) DashGrid.state.hidden.push(id);
    DashGrid.save(); DashGrid.applyView();
  },
  unhide(id) {
    DashGrid.state.hidden = DashGrid.state.hidden.filter(x => x !== id);
    DashGrid.save(); DashGrid.applyView();
  },

  /* ---- Toggle a widget on/off a page (multi-page membership) ---- */
  togglePage(id, pid, on) {
    const st = DashGrid.state;
    let arr = st.assign[id] || [st.pages[0].id];
    if (on) {
      if (!arr.includes(pid)) arr.push(pid);
      st.order[pid] = st.order[pid] || [];
      if (!st.order[pid].includes(id)) st.order[pid].push(id);
    } else {
      if (arr.length <= 1) { DashGrid.applyView(); return; }  // keep at least one page
      arr = arr.filter(p => p !== pid);
      if (st.order[pid]) st.order[pid] = st.order[pid].filter(x => x !== id);
    }
    st.assign[id] = arr;
    DashGrid.save(); DashGrid.applyView();
  },

  refreshHiddenMenu() {
    const menu = document.getElementById('hiddenCardsMenu');
    const cnt = document.getElementById('hiddenCount');
    const st = DashGrid.state;
    // aktif sayfaya ait gizli kartlar
    const hidden = [...document.querySelectorAll('.dash-widget')].filter(w =>
      st.hidden.includes(w.dataset.widget) && (st.assign[w.dataset.widget] || [st.pages[0].id]).includes(st.active));
    if (cnt) cnt.textContent = hidden.length;
    if (!menu) return;
    menu.innerHTML = hidden.length ? hidden.map(w =>
      `<li><button class="dropdown-item" type="button" onclick="DashGrid.unhide('${w.dataset.widget}')">
        <i class="bi bi-plus-circle text-success"></i> ${App.esc(t('dashtitle.' + w.dataset.widget, w.dataset.title || w.dataset.widget))}</button></li>`).join('')
      : '<li><span class="dropdown-item-text text-muted small">' + t('dash.noHidden','Gizli kart yok') + '</span></li>';
  },

  resizeCharts() { requestAnimationFrame(() => CHARTS.forEach(c => { try { c.resize(); } catch (e) {} })); },

  /* ---- Sekme çubuğu ---- */
  renderTabs() {
    const bar = document.getElementById('dashTabs'); if (!bar) return;
    const st = DashGrid.state;
    let html = st.pages.map(p => {
      const act = p.id === st.active ? ' active' : '';
      const ed = DashGrid.editing
        ? ` <span class="tab-ren" title="${t('dash.rename','Yeniden adlandır')}" data-ren="${p.id}"><i class="bi bi-pencil"></i></span>`
          + (st.pages.length > 1 ? ` <span class="tab-x" title="${t('dash.deletePageT','Sayfayı sil')}" data-del="${p.id}"><i class="bi bi-x-lg"></i></span>` : '')
        : '';
      return `<button class="dash-tab${act}" data-page="${p.id}">${App.esc(p.name)}${ed}</button>`;
    }).join('');
    if (DashGrid.editing)
      html += `<button class="dash-tab dash-tab-add" id="dashAddPage" title="${t('dash.addPageT','Sayfa ekle')}"><i class="bi bi-plus-lg"></i> ${t('dash.pageWord','Sayfa')}</button>`;
    // Cycle (monitoring/kiosk) control: only meaningful with multiple pages
    // and while not editing the layout.
    if (!DashGrid.editing && st.pages.length > 1) {
      const on = Kiosk.running;
      html += `<span class="dash-cycle ms-2">` +
        `<button class="dash-tab dash-cycle-btn${on ? ' active' : ''}" id="dashCycle" ` +
        `title="${t('dash.cycleHint','Sayfalar arası otomatik geçiş (monitöring)')}">` +
        `<i class="bi bi-${on ? 'pause-fill' : 'play-fill'}"></i> ${t('dash.cycle','Döngü')}</button>` +
        `<select class="form-select form-select-sm dash-cycle-sec" id="dashCycleSec" ` +
        `title="${t('dash.cycleEvery','Geçiş aralığı')}">` +
        [10, 15, 30, 60, 120].map(n =>
          `<option value="${n}"${n === Kiosk.sec ? ' selected' : ''}>${n}s</option>`).join('') +
        `</select></span>`;
    }
    bar.innerHTML = html;
  },

  switchPage(pid) {
    if (!DashGrid.state.pages.some(p => p.id === pid)) return;
    DashGrid.state.active = pid; DashGrid.save();
    DashGrid.renderTabs(); DashGrid.applyView();
  },
  addPage() {
    const name = (prompt(t('dash.newPageName','Yeni sayfa adı:'), t('dash.pageWord','Sayfa') + ' ' + (DashGrid.state.pages.length + 1)) || '').trim();
    if (!name) return;
    const id = newId();
    DashGrid.state.pages.push({ id, name }); DashGrid.state.order[id] = [];
    DashGrid.state.active = id; DashGrid.save();
    DashGrid.renderTabs(); DashGrid.applyView();
  },
  renamePage(pid) {
    const p = DashGrid.state.pages.find(x => x.id === pid); if (!p) return;
    const name = (prompt(t('dash.pageName','Sayfa adı:'), p.name) || '').trim();
    if (name) { p.name = name; DashGrid.save(); DashGrid.renderTabs(); }
  },
  deletePage(pid) {
    const st = DashGrid.state;
    if (st.pages.length <= 1) return;
    if (!confirm(t('dash.deletePageConfirm','Bu sayfa silinsin mi? Kartları ilk sayfaya taşınır.'))) return;
    const target = st.pages.find(p => p.id !== pid).id;
    (st.order[pid] || []).forEach(id => {
      let arr = (st.assign[id] || []).filter(p => p !== pid);
      if (!arr.length) {
        arr = [target];
        st.order[target] = st.order[target] || [];
        if (!st.order[target].includes(id)) st.order[target].push(id);
      }
      st.assign[id] = arr;
    });
    delete st.order[pid];
    st.pages = st.pages.filter(p => p.id !== pid);
    if (st.active === pid) st.active = target;
    DashGrid.save(); DashGrid.renderTabs(); DashGrid.refreshPageSelectors(); DashGrid.applyView();
  },

  /* ---- Düzenleme modu ---- */
  toggleEdit() {
    DashGrid.editing = !DashGrid.editing;
    if (DashGrid.editing && Kiosk.running) Kiosk.stop(true);  // don't rotate while editing
    const grid = document.getElementById('dashGrid');
    grid.classList.toggle('editing', DashGrid.editing);
    document.getElementById('btnResetDash').classList.toggle('d-none', !DashGrid.editing);
    document.getElementById('hiddenCardsWrap').classList.toggle('d-none', !DashGrid.editing);
    const btn = document.getElementById('btnEditDash');
    btn.querySelector('span').textContent = DashGrid.editing ? t('dash.done','Bitti') : t('dash.edit',"Dashboard'u Düzenle");
    btn.querySelector('i').className = DashGrid.editing ? 'bi bi-check2' : 'bi bi-grid-1x2';
    grid.querySelectorAll('.dash-widget').forEach(w => { w.draggable = DashGrid.editing; });
    grid.querySelectorAll('.wt-pages').forEach(s => { s.classList.toggle('d-none', !DashGrid.editing); });
    DashGrid.renderTabs();
  },

  reset() {
    if (!confirm(t('dash.resetConfirm','Tüm dashboard yerleşimi (sayfalar dahil) sıfırlansın mı?'))) return;
    try { localStorage.removeItem(LS_KEY2); localStorage.removeItem(LS_KEY); } catch (e) {}
    location.reload();
  },

  /* ---- Sürükle-bırak (aktif sayfa içinde yeniden sırala) ---- */
  dragEl: null,
  initDnD() {
    const grid = document.getElementById('dashGrid'); if (!grid) return;
    grid.addEventListener('dragstart', e => {
      const w = e.target.closest('.dash-widget');
      if (!w || !DashGrid.editing) return;
      DashGrid.dragEl = w; w.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    grid.addEventListener('dragend', () => {
      if (!DashGrid.dragEl) return;
      DashGrid.dragEl.classList.remove('dragging'); DashGrid.dragEl = null;
      // yeni sırayı aktif sayfaya kaydet
      const act = DashGrid.state.active;
      DashGrid.state.order[act] = [...grid.querySelectorAll('.dash-widget')]
        .filter(w => w.style.display !== 'none').map(w => w.dataset.widget);
      DashGrid.save(); DashGrid.relayout();
    });
    grid.addEventListener('dragover', e => {
      if (!DashGrid.dragEl) return;
      e.preventDefault();
      const target = e.target.closest('.dash-widget');
      if (!target || target === DashGrid.dragEl || target.style.display === 'none') return;
      const r = target.getBoundingClientRect();
      const after = (e.clientY - r.top) > r.height / 2 || (e.clientX - r.left) > r.width / 2;
      grid.insertBefore(DashGrid.dragEl, after ? target.nextSibling : target);
    });
  },

  initHelp() {
    if (!window.bootstrap || !bootstrap.Popover) return;
    const HELP_TR = {
      forecast: {
        t: 'Kapasite öngörüsü nasıl çalışır',
        b: '<strong>Doluluk</strong> = fiziksel kapasitenin gerçekte kullanılan kısmı (asıl tükenecek olan). '
         + '<strong>Tahsis</strong> = VM\'lere verilen toplam; %100\'ü aşması (overcommit) sanallaştırmada normaldir.<br><br>'
         + '"X sonra dolabilir" tahmini, son N günün gerçek doluluk artış hızından (lineer trend) hesaplanır; '
         + 'yeterli yayılım yoksa "veri toplanıyor" yazar.<br><br>'
         + '<strong>Disk</strong> = datastore doluluğu, <strong>RAM</strong> = fiziksel host belleği.'
      },
      zombie: {
        t: 'Zombi tespiti nasıl çalışır',
        b: 'Her çalışan VM 14-30 günlük pencerede 4 metrikle puanlanır: <strong>CPU</strong> (%40), '
         + '<strong>RAM</strong> oynaklığı, <strong>Disk I/O</strong> ve <strong>Ağ</strong> (her biri %20). '
         + 'Yüksek skor = düşük aktivite.<br><br>'
         + '"Kesin Zombi" için dördü birden boşta olmalı ve ≥7 gün veri bulunmalı; metrik eksikse '
         + '(Disk/Ağ henüz birikiyorsa) en fazla "Şüpheli" denir. Tek başına CPU yanıltıcıdır; diski aktif ama '
         + 'CPU\'su boş VM zombi <em>sayılmaz</em>.<br><br>'
         + '<strong>Geri kazanılabilir</strong> = bu VM\'ler kapatılırsa boşalacak vCPU/RAM/disk.'
      },
    };
    document.querySelectorAll('.wt-help[data-help]').forEach(btn => {
      const k = btn.dataset.help, tr = HELP_TR[k] || {t: k, b: ''};
      bootstrap.Popover.getOrCreateInstance(btn, {
        html: true, trigger: 'focus', placement: 'left',
        title: t('help.' + k + '.t', tr.t),
        content: t('help.' + k + '.b', tr.b),
      });
    });
  },
  init() {
    if (!document.getElementById('dashGrid')) return;
    DashGrid.mountChrome();
    DashGrid.ensureState();
    // Her karta düzenleme araçları (sürükle / genişlik / kapat / sayfa) enjekte et
    document.querySelectorAll('#dashGrid .dash-widget').forEach(w => {
      const tools = document.createElement('div');
      tools.className = 'widget-tools';
      tools.innerHTML =
        '<span class="wt wt-drag" title="' + t('wt.move','Taşı (sürükle)') + '"><i class="bi bi-grip-vertical"></i></span>' +
        '<span class="wt wt-pages d-none dropdown"><button type="button" class="wt wt-pages-btn" ' +
          'title="' + t('wt.pages','Sayfalar (birden çok seçilebilir)') + '"><i class="bi bi-collection"></i></button>' +
          '<div class="wt-pages-menu"></div></span>' +
        '<button type="button" class="wt wt-size" title="' + t('wt.width','Genişliği hızlı değiştir') + '"><i class="bi bi-aspect-ratio"></i></button>' +
        '<button type="button" class="wt wt-hide" title="' + t('wt.hide','Kartı gizle') + '"><i class="bi bi-x-lg"></i></button>';
      w.appendChild(tools);
      // Köşe boyutlandırma kolu (hem genişlik hem yükseklik)
      const rz = document.createElement('span');
      rz.className = 'wt-resize'; rz.title = t('wt.resize','Boyutlandır (sürükle: yana/aşağı)');
      rz.innerHTML = '<i class="bi bi-arrows-angle-expand"></i>';
      w.appendChild(rz);
    });
    DashGrid.initHelp();
    Kiosk.bind();
    DashGrid.refreshPageSelectors();
    DashGrid.renderTabs();
    DashGrid.applyView();
    DashGrid.initDnD();
    document.getElementById('btnEditDash').addEventListener('click', DashGrid.toggleEdit);
    document.getElementById('btnResetDash').addEventListener('click', DashGrid.reset);

    // Kart araç düğmeleri
    const grid = document.getElementById('dashGrid');
    grid.addEventListener('click', e => {
      const w = e.target.closest('.dash-widget'); if (!w || !DashGrid.editing) return;
      if (e.target.closest('.wt-hide')) { e.preventDefault(); DashGrid.hide(w); }
      else if (e.target.closest('.wt-size')) { e.preventDefault(); DashGrid.cycleWidth(w); }
    });
    grid.addEventListener('pointerdown', e => {
      const h = e.target.closest('.wt-resize');
      if (!h || !DashGrid.editing) return;
      DashGrid.startResize(e, e.target.closest('.dash-widget'));
    });
    grid.addEventListener('change', e => {
      const cb = e.target.closest('.wt-pages-menu input'); if (!cb) return;
      const w = e.target.closest('.dash-widget');
      DashGrid.togglePage(w.dataset.widget, cb.value, cb.checked);
    });
    grid.addEventListener('click', e => {
      const btn = e.target.closest('.wt-pages-btn');
      document.querySelectorAll('.wt-pages.open').forEach(x => {
        if (!btn || x !== btn.parentElement) x.classList.remove('open');
      });
      if (btn) btn.parentElement.classList.toggle('open');
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('.wt-pages'))
        document.querySelectorAll('.wt-pages.open').forEach(x => x.classList.remove('open'));
    });

    // Sekme çubuğu olayları
    const bar = document.getElementById('dashTabs');
    bar.addEventListener('click', e => {
      if (e.target.closest('#dashAddPage')) { DashGrid.addPage(); return; }
      if (e.target.closest('#dashCycle')) { Kiosk.toggle(); return; }
      const ren = e.target.closest('[data-ren]'); if (ren) { e.stopPropagation(); DashGrid.renamePage(ren.dataset.ren); return; }
      const del = e.target.closest('[data-del]'); if (del) { e.stopPropagation(); DashGrid.deletePage(del.dataset.del); return; }
      const tab = e.target.closest('.dash-tab[data-page]');
      if (tab) { DashGrid.switchPage(tab.dataset.page); if (Kiosk.running) Kiosk._arm(); }
    });
    bar.addEventListener('change', e => {
      const sel = e.target.closest('#dashCycleSec');
      if (sel) Kiosk.setSec(parseInt(sel.value, 10) || 30);
    });

    // Async içerik/grafikler yüklendikçe ve pencere boyutlandıkça yeniden paketle
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        clearTimeout(DashGrid._roT); DashGrid._roT = setTimeout(() => DashGrid.relayout(), 60);
      });
      grid.querySelectorAll('.dash-widget').forEach(w => ro.observe(w));
    }
    window.addEventListener('resize', () => {
      clearTimeout(DashGrid._wT); DashGrid._wT = setTimeout(() => DashGrid.relayout(), 120);
    });
    window.addEventListener('dash:relayout', () => DashGrid.relayout());
    [200, 700, 1500].forEach(ms => setTimeout(() => DashGrid.relayout(), ms));  // ilk yükleme güvenlik ağı
  },

  refreshPageSelectors() {
    const st = DashGrid.state;
    document.querySelectorAll('#dashGrid .dash-widget').forEach(w => {
      const menu = w.querySelector('.wt-pages-menu'); if (!menu) return;
      const cur = st.assign[w.dataset.widget] || [];
      menu.innerHTML = st.pages.map(p =>
        `<label class="wt-pages-item"><input type="checkbox" value="${p.id}"` +
        (cur.includes(p.id) ? ' checked' : '') + `> ${App.esc(p.name)}</label>`).join('');
    });
  },

  /* Kontrolleri üst çubuğa taşı (tek satır). Tema global. */
  mountChrome() {
    const controls = document.getElementById('dashControls');
    const topRight = document.querySelector('.topbar .ms-auto');
    if (controls && topRight) topRight.insertBefore(controls, topRight.firstChild);
  },
};
// renderTabs içinde sayfa eklendiğinde/ad değişince seçicileri tazele
const _origRenderTabs = DashGrid.renderTabs;
DashGrid.renderTabs = function () { _origRenderTabs.call(DashGrid); DashGrid.refreshPageSelectors && DashGrid.refreshPageSelectors(); };
/* ============ Kiosk / monitoring: auto-cycle dashboard pages ============ */
const Kiosk = {
  running: false,
  sec: parseInt(localStorage.getItem('vmi-dash-cycle-sec') || '30', 10) || 30,
  _timer: null,

  bind() {
    // Restore "was cycling" across reloads (a wall monitor should resume).
    if (localStorage.getItem('vmi-dash-cycle-on') === '1'
        && DashGrid.state.pages.length > 1) {
      Kiosk.start(true);
    }
    // Pause on any real user interaction, resume shortly after they stop.
    ['click', 'keydown', 'wheel', 'touchstart', 'mousemove'].forEach(ev =>
      document.addEventListener(ev, Kiosk._nudge, { passive: true }));
  },

  start(silent) {
    if (DashGrid.state.pages.length < 2) return;
    Kiosk.running = true;
    localStorage.setItem('vmi-dash-cycle-on', '1');
    Kiosk._arm();
    DashGrid.renderTabs();
    if (!silent) App.toast(t('dash.cycleOn', 'Sayfa döngüsü açık — her ') +
      Kiosk.sec + 's', 'info');
  },

  stop(silent) {
    Kiosk.running = false;
    localStorage.setItem('vmi-dash-cycle-on', '0');
    clearTimeout(Kiosk._timer); Kiosk._timer = null;
    DashGrid.renderTabs();
    if (!silent) App.toast(t('dash.cycleOff', 'Sayfa döngüsü kapalı'), 'info');
  },

  toggle() { Kiosk.running ? Kiosk.stop() : Kiosk.start(); },

  setSec(n) {
    Kiosk.sec = n;
    localStorage.setItem('vmi-dash-cycle-sec', String(n));
    if (Kiosk.running) Kiosk._arm();
  },

  _arm() {
    clearTimeout(Kiosk._timer);
    Kiosk._timer = setTimeout(Kiosk._advance, Kiosk.sec * 1000);
  },

  _advance() {
    const st = DashGrid.state;
    if (!Kiosk.running || st.pages.length < 2) return;
    const i = st.pages.findIndex(p => p.id === st.active);
    const next = st.pages[(i + 1) % st.pages.length];
    st.active = next.id; DashGrid.save();
    DashGrid.renderTabs(); DashGrid.applyView();
    Kiosk._arm();
  },

  // Debounced pause: hold the rotation while the user is active, then resume.
  _nudge() {
    if (!Kiosk.running) return;
    clearTimeout(Kiosk._timer);
    Kiosk._timer = setTimeout(Kiosk._advance, Math.max(Kiosk.sec, 5) * 1000);
  },
};

DashGrid.init();

/* ============================ Cluster görünürlük yönetimi ============================ */
const Clusters = {
  async open() {
    bootstrap.Modal.getOrCreateInstance(document.getElementById('clusterModal')).show();
    await Clusters.render();
  },
  async render() {
    let data;
    try { data = await App.api('/api/clusters'); } catch (e) { return; }
    const ul = document.getElementById('clusterList');
    if (!data.items.length) {
      ul.innerHTML = '<li class="list-group-item text-muted">' + t('cl.noData','Henüz cluster verisi yok — önce bir platform senkronize edin.') + '</li>';
      return;
    }
    ul.innerHTML = data.items.map(c => {
      const label = c.is_none ? t('cl.noCluster',"(Cluster'sız)") : c.name;
      return '<li class="list-group-item d-flex align-items-center gap-2">' +
      '<div class="form-check form-switch mb-0">' +
      '<input class="form-check-input" type="checkbox" role="switch" ' + (c.visible ? 'checked ' : '') +
      'onchange="Clusters.toggle(\'' + App.esc(c.name).replace(/'/g, "\\'") + '\', this.checked)"></div>' +
      '<div class="flex-grow-1"><strong>' + App.esc(label) +
      (c.is_none ? ' <i class="bi bi-info-circle text-muted"></i>' : '') + '</strong>' +
      (!c.in_inventory ? ' <span class="badge text-bg-light border">' + t('cl.notInInv','envanterde yok') + '</span>' : '') +
      '<br><small class="text-muted">' + c.vm_count + ' VM · ' + c.host_count + ' host</small></div>' +
      (c.visible ? '<span class="badge text-bg-success">' + t('cl.visible','Görünür') + '</span>'
                 : '<span class="badge text-bg-secondary">' + t('cl.hidden','Gizli') + '</span>') + '</li>';
    }).join('');
  },
  async toggle(name, visible) {
    try {
      await App.api('/api/clusters/visibility', {method: 'POST', body: {name, visible}});
      const label = name === '__none__' ? t('cl.noCluster',"(Cluster'sız)") : name;
      App.toast('"' + label + '" ' + (visible ? t('cl.madeVisible','görünür yapıldı') : t('cl.hiddenDone','gizlendi')) + ' — ' + t('cl.updating','güncelleniyor'), 'info');
      await Clusters.render();
      setTimeout(() => location.reload(), 900);
    } catch (e) { Clusters.render(); }
  },
};
const _btnClusters = document.getElementById('btnClusters');
if (_btnClusters) _btnClusters.addEventListener('click', Clusters.open);
