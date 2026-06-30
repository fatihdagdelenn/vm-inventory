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
  set('st-vcpu', d.total_vcpu);
  set('st-ram', d.total_ram_gb >= 1024 ? (d.total_ram_gb/1024).toFixed(1)+' TB' : d.total_ram_gb+' GB');
  set('st-disk', d.total_disk_tb + ' TB');
  set('at-noip', d.attention.no_ip);       set('at-notools', d.attention.no_tools);
  set('at-noowner', d.attention.no_owner);  set('at-oldsnap', d.attention.old_snapshots);
  set('at-nobackup', d.attention.no_backup);

  const hi = document.getElementById('hiddenInfo');
  if (hi && d.hidden_clusters > 0) { hi.textContent = d.hidden_clusters + ' cluster gizli'; hi.classList.remove('d-none'); }
  const uf = document.getElementById('usageFresh');
  if (uf) uf.textContent = d.usage_updated ? 'kullanım: ' + App.fmtDate(d.usage_updated)
                                           : 'kullanım: ilk senkronizasyon bekleniyor';

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
  const typeBadge = t => ({
    created: '<span class="badge text-bg-success">Eklendi</span>',
    updated: '<span class="badge text-bg-warning text-dark">Güncellendi</span>',
    deleted: '<span class="badge text-bg-danger">Silindi</span>',
    migrated: '<span class="badge text-bg-info text-dark">Göç</span>',
    access: '<span class="badge text-bg-secondary">Erişim</span>',
  }[t] || App.esc(t));
  const rc = document.getElementById('recentChanges');
  if (rc) rc.innerHTML = d.recent_changes.length ? d.recent_changes.map(c => '<tr>' +
    '<td class="text-nowrap small text-muted">' + App.fmtDate(c.changed_at) + '</td>' +
    '<td><strong>' + App.esc(c.entity_name) + '</strong> <small class="text-muted">(' +
      (c.entity_type === 'vm' ? 'VM' : 'Host') + ')</small></td>' +
    '<td>' + typeBadge(c.change_type) + '</td>' +
    '<td class="small">' + (c.field ? App.esc(c.field) + ': <span class="text-muted">' +
      App.esc(c.old_value || '—') + '</span> → ' + App.esc(c.new_value || '—') : '—') +
    '</td></tr>').join('')
    : '<tr><td colspan="4" class="text-muted p-3">Henüz değişiklik kaydı yok.</td></tr>';

  /* ---- Platform durumları ---- */
  const tbody = document.getElementById('platformStatus');
  if (tbody) tbody.innerHTML = d.platforms.length ? d.platforms.map(p => {
    const badge = p.status === '-' ? '<span class="badge text-bg-secondary">Henüz yok</span>'
      : p.status === 'success' ? '<span class="badge text-bg-success">Başarılı</span>'
      : '<span class="badge text-bg-danger">Hata</span>';
    return '<tr><td>' + App.esc(p.name) + '</td><td>' + (p.type === 'vcenter' ? 'vCenter' : 'Proxmox') +
      '</td><td class="small">' + App.fmtDate(p.last_sync) + '</td><td>' + badge + '</td></tr>';
  }).join('')
    : '<tr><td colspan="4" class="text-muted p-3">Henüz platform eklenmemiş. ' +
      '<a href="/platforms">Platformlar</a> sayfasından ekleyebilirsiniz.</td></tr>';

  /* ============== Akıllı paneller (insights) ============== */
  let ins;
  try { ins = await App.api('/api/dashboard/insights'); } catch (e) { ins = null; }
  if (ins) renderInsights(ins);

  /** Kapasite öngörüsü + zombi + canlılık + sparkline render. */
  function renderInsights(ins) {
    const STAT = {ok: ['text-success', 'bi-check-circle', 'Sağlıklı'],
                  warn: ['text-warning', 'bi-exclamation-triangle', 'Yaklaşıyor'],
                  crit: ['text-danger', 'bi-exclamation-octagon', 'Kritik'],
                  stable: ['text-success', 'bi-check-circle', 'Kararlı'],
                  collecting: ['text-info', 'bi-hourglass-split', 'Veri toplanıyor'],
                  none: ['text-muted', 'bi-dash-circle', 'Yetersiz veri']};
    const fc = ins.forecast;
    const fcWin = document.getElementById('fc-window');
    if (fcWin) fcWin.innerHTML = fc.method === 'trend'
      ? `<i class="bi bi-activity"></i> ${fc.window_days} günlük gerçek trend`
      : `<i class="bi bi-hourglass-split"></i> veri toplanıyor (${fc.days_collected}/${fc.days_needed} gün)`;

    // Gün sayısını insanca biçimle (çok büyükse abartılı görünmesin)
    const daysHuman = (d) => {
      if (d >= 1825) return '5+ yıl';
      if (d >= 365) return `~${(d / 365).toFixed(1).replace('.0', '')} yıl`;
      if (d >= 60) return `~${Math.round(d / 30)} ay`;
      return `~${d} gün`;
    };
    const fcRow = (title, icon, f, unit) => {
      const [cls, bi, txt] = STAT[f.status] || STAT.none;
      const fmt = (gb) => gb >= 1024 ? (gb / 1024).toFixed(1) + ' TB' : Math.round(gb) + ' GB';
      let daysTxt;
      if (f.status === 'collecting')
        daysTxt = `<span class="text-info"><i class="bi bi-hourglass-split"></i> Doluluk trendi için veri toplanıyor.</span>`;
      else if (f.status === 'crit' && f.days_left == null)
        daysTxt = `<strong class="text-danger">Kapasite dolu/aşıldı.</strong>`;
      else if (f.days_left != null)
        daysTxt = `Mevcut <strong>doluluk</strong> hızıyla <strong class="${cls}">${daysHuman(f.days_left)}</strong> sonra dolabilir`;
      else
        daysTxt = `<span class="text-success">Doluluk büyümesi kayda değer değil — kararlı.</span>`;
      const up = f.used_pct != null ? f.used_pct : 0;       // gerçek doluluk
      const barCls = up >= 90 ? 'bg-danger' : up >= 75 ? 'bg-warning' : 'bg-success';
      const rate = f.per_day_gb > 0 ? `<span>+${fmt(f.per_day_gb)}/gün</span>` : '<span></span>';
      // Tahsis (overcommit) satırı — ayrı kavram
      const ocCls = f.alloc_pct > 100 ? 'text-warning' : 'text-muted';
      const ocBadge = f.overcommit ? ` <span class="badge bg-warning-subtle text-warning-emphasis" title="VM'lere fizikselden fazla ${unit} verilmiş — sanallaştırmada olağan">overcommit</span>` : '';
      return `<div class="forecast-row">
        <div class="d-flex align-items-center mb-1">
          <i class="bi ${icon} me-2"></i><strong>${title}</strong>
          <span class="ms-auto small ${cls}"><i class="bi ${bi}"></i> ${txt}</span></div>
        <div class="progress forecast-bar"><div class="progress-bar ${barCls}" style="width:${Math.min(100,up)}%"></div></div>
        <div class="d-flex justify-content-between small mt-1">
          <span><strong>Doluluk:</strong> ${fmt(f.used_gb)} / ${fmt(f.capacity_gb)} <span class="text-muted">(%${up})</span></span>
          ${rate}</div>
        <div class="small ${ocCls} mt-1"><strong>Tahsis:</strong> ${fmt(f.allocated_gb)}
          <span class="text-muted">(fizikselin %${f.alloc_pct ?? 0}'i)</span>${ocBadge}</div>
        <div class="small mt-1">${daysTxt}</div></div>`;
    };
    const fb = document.getElementById('forecastBody');
    if (fb) fb.innerHTML = fcRow('Disk (Datastore)', 'bi-device-hdd', fc.disk, 'disk') +
                           fcRow('RAM (Fiziksel)', 'bi-memory', fc.ram, 'RAM') +
      `<div class="text-muted mt-1" style="font-size:.72rem; line-height:1.5">
        <i class="bi bi-info-circle"></i> <strong>Doluluk</strong> = gerçekte kullanılan / fiziksel kapasite
        (asıl tükenecek olan). <strong>Tahsis</strong> = VM'lere verilen; %100'ü aşması (overcommit)
        sanallaştırmada normaldir. Öngörü yalnızca doluluğun büyüme hızına göredir` +
      (fc.method === 'trend' ? ` (son ${fc.window_days} gün).` : `; veri toplanıyor.`) +
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
            ? 'Çok metrikli analizde (CPU+RAM+Disk+Ağ) zombi/şüpheli VM yok.'
            : 'Boşta görünen çalışan VM yok. (Anlık örneğe göre)') + '</div>';
      } else {
        const scoreBg = z => z.score == null ? '#64748b'
          : (z.score >= 80 ? '#ef4444' : (z.score >= 55 ? '#f59e0b' : '#22c55e'));
        const klassBg = k => (k || '').startsWith('Kesin') ? '#ef4444'
          : ((k || '').startsWith('Şüpheli') ? '#f59e0b' : '#22c55e');
        zb.innerHTML =
          `<div class="zombie-savings mb-2"><i class="bi bi-piggy-bank"></i>
            Geri kazanılabilir: <strong>${s.vcpu}</strong> vCPU ·
            <strong>${s.ram_gb}</strong> GB RAM · <strong>${s.disk_gb}</strong> GB disk</div>
          <div class="table-responsive"><table class="table table-sm table-hover align-middle mb-1">
            <thead><tr><th>VM</th><th class="text-center">Skor</th><th>Sınıf</th><th class="text-end">RAM</th></tr></thead>
            <tbody>` + ins.zombies.map(z =>
              `<tr>
                <td><strong>${App.esc(z.name)}</strong>
                  <div class="text-muted" style="font-size:.7rem">${App.esc(z.host || '—')} · ${(z.reasons || []).map(App.esc).join(' · ')}</div>
                </td>
                <td class="text-center"><span style="display:inline-block;min-width:38px;padding:2px 8px;border-radius:999px;font-weight:700;color:#fff;background:${scoreBg(z)}">${z.score == null ? '—' : z.score}</span></td>
                <td><span style="display:inline-block;padding:1px 8px;border-radius:6px;font-size:.72rem;font-weight:600;color:#fff;background:${klassBg(z.klass)}">${App.esc(z.klass || '')}</span>
                  <div class="text-muted" style="font-size:.68rem">güven: ${App.esc(z.confidence || '')}</div></td>
                <td class="text-end small">${z.ram_gb} GB</td>
              </tr>`).join('') +
          `</tbody></table></div>
          <div class="text-muted fst-italic" style="font-size:.72rem">` +
          (ins.zombie_basis === '14-30d'
            ? `14-30 günlük CPU+RAM+Disk+Ağ korelasyonu. "Kesin Zombi" için 4 metrik birden idle + ≥7 gün veri gerekir; eksik metrik (Disk/Ağ örneği henüz birikiyorsa) en fazla "Şüpheli" verir.`
            : `Anlık CPU < %2 (tarihsel veri birikiyor). Disk/Ağ örnekleri biriktikçe çok metrikli skora geçer.`) +
          `</div>`;
      }
    }

    /* Canlılık (live dot) */
    const lt = document.getElementById('liveText');
    if (lt) {
      const iv = ins.live.interval_minutes;
      const last = ins.live.last_sync ? App.fmtDate(ins.live.last_sync) : 'henüz yok';
      lt.innerHTML = `Canlı · her <strong>${iv} dk</strong> · son: ${last}`;
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
const DashGrid = {
  editing: false,

  load() { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; } },
  save() {
    const grid = document.getElementById('dashGrid');
    const widgets = [...grid.querySelectorAll('.dash-widget')];
    const layout = {order: [], width: {}, hidden: []};
    widgets.forEach(w => {
      const id = w.dataset.widget;
      layout.order.push(id);
      layout.width[id] = parseInt(w.dataset.w, 10);
      if (w.classList.contains('is-hidden')) layout.hidden.push(id);
    });
    try { localStorage.setItem(LS_KEY, JSON.stringify(layout)); } catch (e) {}
  },

  applySaved() {
    const grid = document.getElementById('dashGrid'); if (!grid) return;
    const L = DashGrid.load();
    if (L.order && L.order.length) {            // kaydedilmiş sırayı uygula
      L.order.forEach(id => {
        const w = grid.querySelector(`[data-widget="${id}"]`);
        if (w) grid.appendChild(w);
      });
    }
    const all = grid.querySelectorAll('.dash-widget');
    all.forEach(w => {
      const id = w.dataset.widget;
      if (L.width && L.width[id]) w.dataset.w = L.width[id];
      w.style.setProperty('--w', w.dataset.w);
      w.classList.toggle('is-hidden', !!(L.hidden && L.hidden.includes(id)));
    });
    DashGrid.refreshHiddenMenu();
  },

  setWidth(w, val) { w.dataset.w = val; w.style.setProperty('--w', val); },

  cycleWidth(w) {
    const cur = parseInt(w.dataset.w, 10);
    const next = WIDTHS[(WIDTHS.indexOf(cur) + 1) % WIDTHS.length] || 4;
    DashGrid.setWidth(w, next);
    DashGrid.save();
    DashGrid.resizeCharts();
  },

  hide(w) { w.classList.add('is-hidden'); DashGrid.save(); DashGrid.refreshHiddenMenu(); DashGrid.resizeCharts(); },
  unhide(id) {
    const w = document.querySelector(`[data-widget="${id}"]`);
    if (w) { w.classList.remove('is-hidden'); DashGrid.save(); DashGrid.refreshHiddenMenu(); DashGrid.resizeCharts(); }
  },

  refreshHiddenMenu() {
    const menu = document.getElementById('hiddenCardsMenu');
    const cnt = document.getElementById('hiddenCount');
    const hidden = [...document.querySelectorAll('.dash-widget.is-hidden')];
    if (cnt) cnt.textContent = hidden.length;
    if (!menu) return;
    menu.innerHTML = hidden.length ? hidden.map(w =>
      `<li><button class="dropdown-item" type="button" onclick="DashGrid.unhide('${w.dataset.widget}')">
        <i class="bi bi-plus-circle text-success"></i> ${App.esc(w.dataset.title || w.dataset.widget)}</button></li>`).join('')
      : '<li><span class="dropdown-item-text text-muted small">Gizli kart yok</span></li>';
  },

  resizeCharts() { requestAnimationFrame(() => CHARTS.forEach(c => { try { c.resize(); } catch (e) {} })); },

  /* ---- Düzenleme modu ---- */
  toggleEdit() {
    DashGrid.editing = !DashGrid.editing;
    const grid = document.getElementById('dashGrid');
    grid.classList.toggle('editing', DashGrid.editing);
    document.getElementById('btnResetDash').classList.toggle('d-none', !DashGrid.editing);
    document.getElementById('hiddenCardsWrap').classList.toggle('d-none', !DashGrid.editing);
    const btn = document.getElementById('btnEditDash');
    btn.querySelector('span').textContent = DashGrid.editing ? 'Bitti' : "Dashboard'u Düzenle";
    btn.querySelector('i').className = DashGrid.editing ? 'bi bi-check2' : 'bi bi-grid-1x2';
    grid.querySelectorAll('.dash-widget').forEach(w => { w.draggable = DashGrid.editing; });
  },

  reset() {
    try { localStorage.removeItem(LS_KEY); } catch (e) {}
    location.reload();
  },

  /* ---- Sürükle-bırak (HTML5 DnD) ---- */
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
      DashGrid.save(); DashGrid.resizeCharts();
    });
    grid.addEventListener('dragover', e => {
      if (!DashGrid.dragEl) return;
      e.preventDefault();
      const target = e.target.closest('.dash-widget');
      if (!target || target === DashGrid.dragEl) return;
      const r = target.getBoundingClientRect();
      const after = (e.clientY - r.top) > r.height / 2 || (e.clientX - r.left) > r.width / 2;
      grid.insertBefore(DashGrid.dragEl, after ? target.nextSibling : target);
    });
  },

  init() {
    if (!document.getElementById('dashGrid')) return;
    DashGrid.mountChrome();
    // Her karta düzenleme araçlarını (sürükle / genişlik / kapat) enjekte et
    document.querySelectorAll('#dashGrid .dash-widget').forEach(w => {
      const tools = document.createElement('div');
      tools.className = 'widget-tools';
      tools.innerHTML =
        '<span class="wt wt-drag" title="Sürükle"><i class="bi bi-grip-vertical"></i></span>' +
        '<button type="button" class="wt wt-size" title="Genişliği değiştir"><i class="bi bi-aspect-ratio"></i></button>' +
        '<button type="button" class="wt wt-hide" title="Kartı gizle"><i class="bi bi-x-lg"></i></button>';
      w.appendChild(tools);
    });
    DashGrid.applySaved();
    DashGrid.initDnD();
    document.getElementById('btnEditDash').addEventListener('click', DashGrid.toggleEdit);
    document.getElementById('btnResetDash').addEventListener('click', DashGrid.reset);
    // Kart araç düğmeleri (event delegation)
    document.getElementById('dashGrid').addEventListener('click', e => {
      const w = e.target.closest('.dash-widget'); if (!w || !DashGrid.editing) return;
      if (e.target.closest('.wt-hide')) { e.preventDefault(); DashGrid.hide(w); }
      else if (e.target.closest('.wt-size')) { e.preventDefault(); DashGrid.cycleWidth(w); }
    });
  },

  /* Dashboard'a özel kontrolleri (canlı/gizli/sıfırla/düzenle) paylaşılan üst
     çubuğa taşı → tek satır. Tema artık global (base.html + App.toggleTheme). */
  mountChrome() {
    const controls = document.getElementById('dashControls');
    const topRight = document.querySelector('.topbar .ms-auto');
    if (controls && topRight) topRight.insertBefore(controls, topRight.firstChild);
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
      ul.innerHTML = '<li class="list-group-item text-muted">Henüz cluster verisi yok — ' +
        'önce bir platform senkronize edin.</li>';
      return;
    }
    ul.innerHTML = data.items.map(c => {
      const label = c.is_none ? "(Cluster'sız)" : c.name;
      return '<li class="list-group-item d-flex align-items-center gap-2">' +
      '<div class="form-check form-switch mb-0">' +
      '<input class="form-check-input" type="checkbox" role="switch" ' + (c.visible ? 'checked ' : '') +
      'onchange="Clusters.toggle(\'' + App.esc(c.name).replace(/'/g, "\\'") + '\', this.checked)"></div>' +
      '<div class="flex-grow-1"><strong>' + App.esc(label) +
      (c.is_none ? ' <i class="bi bi-info-circle text-muted"></i>' : '') + '</strong>' +
      (!c.in_inventory ? ' <span class="badge text-bg-light border">envanterde yok</span>' : '') +
      '<br><small class="text-muted">' + c.vm_count + ' VM · ' + c.host_count + ' host</small></div>' +
      (c.visible ? '<span class="badge text-bg-success">Görünür</span>'
                 : '<span class="badge text-bg-secondary">Gizli</span>') + '</li>';
    }).join('');
  },
  async toggle(name, visible) {
    try {
      await App.api('/api/clusters/visibility', {method: 'POST', body: {name, visible}});
      const label = name === '__none__' ? "(Cluster'sız)" : name;
      App.toast('"' + label + '" ' + (visible ? 'görünür yapıldı' : 'gizlendi') + ' — güncelleniyor', 'info');
      await Clusters.render();
      setTimeout(() => location.reload(), 900);
    } catch (e) { Clusters.render(); }
  },
};
const _btnClusters = document.getElementById('btnClusters');
if (_btnClusters) _btnClusters.addEventListener('click', Clusters.open);
