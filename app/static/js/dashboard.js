/**
 * dashboard.js — Ana ekran: özet kartları, 7 grafik, dikkat listesi,
 * son değişiklikler ve platform durumları.
 * Grafik dilimlerine tıklayınca ilgili filtreyle VM listesine gidilir.
 * Tüm veriler tek istekle /api/dashboard/summary'den gelir (lokal DB).
 */
(async function () {
  let d;
  try { d = await App.api('/api/dashboard/summary'); } catch (e) { return; }

  /* ---- Kartlar ---- */
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v ?? 0;       // eksik element tüm sayfayı düşürmesin
  };
  set('st-vcenter', d.vcenter_count);  set('st-proxmox', d.proxmox_count);
  set('st-host', d.host_count);        set('st-vm', d.vm_total);
  set('st-running', d.vm_running);     set('st-stopped', d.vm_stopped);
  set('st-suspended', d.vm_suspended);
  set('st-vcpu', d.total_vcpu);
  set('st-ram', d.total_ram_gb >= 1024 ? (d.total_ram_gb/1024).toFixed(1)+' TB' : d.total_ram_gb+' GB');
  set('st-disk', d.total_disk_tb + ' TB');
  set('at-noip', d.attention.no_ip);
  set('at-notools', d.attention.no_tools);
  set('at-noowner', d.attention.no_owner);
  set('at-oldsnap', d.attention.old_snapshots);
  set('at-nobackup', d.attention.no_backup);

  // Gizli cluster bilgisi ve kullanım verisi tazeliği
  const hi = document.getElementById('hiddenInfo');
  if (hi && d.hidden_clusters > 0) {
    hi.textContent = d.hidden_clusters + ' cluster gizli';
    hi.classList.remove('d-none');
  }
  const uf = document.getElementById('usageFresh');
  if (uf) uf.textContent =
    d.usage_updated ? 'kullanım verisi: ' + App.fmtDate(d.usage_updated)
                    : 'kullanım verisi: ilk senkronizasyon bekleniyor';

  /* ---- Grafik ortak ayarları ---- */
  Chart.defaults.font.family = "'Inter','Segoe UI',system-ui,sans-serif";
  Chart.defaults.color = '#57606a';
  const PALETTE = ['#2f81f7','#3fb950','#8957e5','#d29922','#f85149',
                   '#39c5cf','#db61a2','#768390'];
  const BLUE='#2f81f7', GREEN='#3fb950', ORANGE='#d29922', RED='#f85149';
  const PURPLE='#8957e5';
  /** Kullanım yüzdesine göre kritik renk: %90+ kırmızı, %75+ turuncu. */
  const critColor = pct => pct >= 90 ? RED : pct >= 75 ? ORANGE : BLUE;

  /** Dilime tıklanınca filtreli VM listesine git. */
  const goVms = q => location.href = '/vms?q=' + encodeURIComponent(q);
  const clickHandler = (qFn) => (evt, els, chart) => {
    if (!els.length) return;
    const label = chart.data.labels[els[0].index];
    const q = qFn(label);
    if (q) goVms(q);
  };

  /* ---- Ortam dağılımı (pasta) ---- */
  const envLabels = Object.keys(d.env_distribution);
  new Chart(document.getElementById('chartEnv'), {
    type: 'doughnut',
    data: {labels: envLabels,
           datasets: [{data: envLabels.map(k => d.env_distribution[k]),
                       backgroundColor: PALETTE, borderWidth: 2, borderColor: '#fff'}]},
    options: {plugins: {legend: {position: 'bottom'}}, cutout: '62%',
              onClick: clickHandler(l => l === '—' ? null : 'env:' + l)}
  });

  /* ---- OS ailesi (pasta) ---- */
  // os_distribution artık [{label, count, query}] listesi (ayrıntılı aileler)
  const osData = d.os_distribution || [];
  new Chart(document.getElementById('chartOs'), {
    type: 'doughnut',
    data: {labels: osData.map(o => o.label),
           datasets: [{data: osData.map(o => o.count),
                       backgroundColor: osData.map((_, i) => PALETTE[i % PALETTE.length]),
                       borderWidth: 2, borderColor: '#fff'}]},
    options: {plugins: {legend: {position: 'bottom'}}, cutout: '62%',
              onClick: clickHandler(label => {
                const f = osData.find(o => o.label === label);
                return f ? f.query : null;
              })}
  });

  /* ---- Cluster bazında VM (yatay bar) ---- */
  new Chart(document.getElementById('chartCluster'), {
    type: 'bar',
    data: {labels: d.cluster_distribution.map(c => c.key),
           datasets: [{label: 'VM', data: d.cluster_distribution.map(c => c.count),
                       backgroundColor: BLUE, borderRadius: 6, maxBarThickness: 26}]},
    options: {indexAxis: 'y', plugins: {legend: {display: false}},
              scales: {x: {beginAtZero: true, ticks: {precision: 0}}},
              onClick: clickHandler(l => l === '—' ? 'cluster:yok' :
                (/\s/.test(l) ? 'cluster:"' + l + '"' : 'cluster:' + l))}
  });

  /* ---- En çok kullanılan OS'ler (yatay bar) ---- */
  new Chart(document.getElementById('chartTopOs'), {
    type: 'bar',
    data: {labels: d.top_os.map(o => o.key),
           datasets: [{label: 'VM', data: d.top_os.map(o => o.count),
                       backgroundColor: PALETTE, borderRadius: 6, maxBarThickness: 26}]},
    options: {indexAxis: 'y', plugins: {legend: {display: false}},
              scales: {x: {beginAtZero: true, ticks: {precision: 0}}}}
  });

  /* ---- Host CPU / RAM (bar, büyükten küçüğe, kritik renkli) ---- */
  const usageBar = (canvasId, key, base) => {
    const rows = [...d.host_usage].sort((a, b) => (b[key] || 0) - (a[key] || 0));
    new Chart(document.getElementById(canvasId), {
    type: 'bar',
    data: {labels: rows.map(h => h.name),
           datasets: [{label: '%', data: rows.map(h => h[key]),
                       borderRadius: 6, maxBarThickness: 40,
                       backgroundColor: rows.map(h =>
                         h[key] >= 90 ? RED : h[key] >= 75 ? ORANGE : base)}]},
    options: {plugins: {legend: {display: false}},
              scales: {y: {beginAtZero: true, max: 100, ticks: {callback: v => v + '%'}}}}
  });
  };
  usageBar('chartCpu', 'cpu_pct', BLUE);
  usageBar('chartRam', 'ram_pct', GREEN);

  /* ---- En çok kaynak tüketen VM'ler (yatay bar, kritik renkli, zengin hover) ---- */
  const topVmChart = (canvasId, items, valueFn, tipFn, colorFn) => {
    const el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: 'bar',
      data: {labels: items.map(v => v.name),
             datasets: [{data: items.map(valueFn), backgroundColor: items.map(colorFn),
                         borderRadius: 6, maxBarThickness: 22}]},
      options: {indexAxis: 'y',
        plugins: {legend: {display: false},
                  tooltip: {callbacks: {label: ctx => tipFn(items[ctx.dataIndex])}}},
        scales: {x: {beginAtZero: true}},
        onClick: (e, els) => { if (els.length) goVms(items[els[0].index].name); }}
    });
  };
  topVmChart('chartTopCpu', d.top_cpu_vms || [], v => v.pct,
    v => `CPU %${v.pct}` + (v.host ? ' · ' + v.host : '') + (v.cluster ? ' · ' + v.cluster : ''),
    v => critColor(v.pct));
  topVmChart('chartTopRam', d.top_ram_vms || [], v => v.pct,
    v => `RAM %${v.pct} (${v.used_gb} GB)` + (v.host ? ' · ' + v.host : ''),
    v => critColor(v.pct));
  topVmChart('chartTopDisk', d.top_disk_vms || [], v => (v.value_gb != null ? v.value_gb : v.used_gb),
    v => (v.is_used ? `${v.used_gb} / ${v.total_gb} GB kullanımda`
                    : `${v.total_gb} GB ayrılan (kullanım için agent gerekli)`)
         + (v.host ? ' · ' + v.host : ''),
    v => v.is_used ? critColor(v.total_gb ? 100 * v.used_gb / v.total_gb : 0) : '#8aa0c0');

  /* ---- Host bazında VM dağılımı (yatay bar) ---- */
  new Chart(document.getElementById('chartHostVm'), {
    type: 'bar',
    data: {labels: (d.host_vm_dist || []).map(h => h.name),
           datasets: [{label: 'VM', data: (d.host_vm_dist || []).map(h => h.count),
                       backgroundColor: BLUE, borderRadius: 6, maxBarThickness: 24}]},
    options: {indexAxis: 'y', plugins: {legend: {display: false}},
              scales: {x: {beginAtZero: true, ticks: {precision: 0}}},
              onClick: clickHandler(l => l === '—' ? null :
                (/\s/.test(l) ? 'host:"' + l + '"' : 'host:' + l))}
  });

  /* ---- Cluster bazında kaynak (vCPU bar, RAM/VM hover'da) ---- */
  const cr = d.cluster_resource || [];
  new Chart(document.getElementById('chartClusterRes'), {
    type: 'bar',
    data: {labels: cr.map(c => c.key),
           datasets: [{label: 'vCPU', data: cr.map(c => c.vcpu),
                       backgroundColor: PURPLE, borderRadius: 6, maxBarThickness: 24}]},
    options: {indexAxis: 'y',
      plugins: {legend: {display: false},
        tooltip: {callbacks: {label: ctx => {
          const c = cr[ctx.dataIndex];
          return `${c.vcpu} vCPU · ${c.ram_gb} GB RAM · ${c.vms} VM`;
        }}}},
      scales: {x: {beginAtZero: true, ticks: {precision: 0}}},
      onClick: clickHandler(l => l === '—' ? 'cluster:yok' :
        (/\s/.test(l) ? 'cluster:"' + l + '"' : 'cluster:' + l))}
  });

  /* ---- Datastore doluluk (%) (yatay bar, kritik renkli) ---- */
  const dsf = d.datastore_fill || [];
  new Chart(document.getElementById('chartDatastore'), {
    type: 'bar',
    data: {labels: dsf.map(s => s.name),
           datasets: [{label: 'Doluluk %', data: dsf.map(s => s.usage_pct),
                       backgroundColor: dsf.map(s => critColor(s.usage_pct)),
                       borderRadius: 6, maxBarThickness: 22}]},
    options: {indexAxis: 'y',
      plugins: {legend: {display: false},
        tooltip: {callbacks: {label: ctx => {
          const s = dsf[ctx.dataIndex];
          return `%${s.usage_pct} · ${s.used_gb} / ${s.capacity_gb} GB`;
        }}}},
      scales: {x: {beginAtZero: true, max: 100, ticks: {callback: v => v + '%'}}},
      onClick: () => { location.href = '/datastores'; }}
  });

  /* ---- Son değişiklikler ---- */
  const typeBadge = t => ({
    created: '<span class="badge text-bg-success">Eklendi</span>',
    updated: '<span class="badge text-bg-warning text-dark">Güncellendi</span>',
    deleted: '<span class="badge text-bg-danger">Silindi</span>',
  }[t] || App.esc(t));
  const rc = document.getElementById('recentChanges');
  rc.innerHTML = d.recent_changes.length ? d.recent_changes.map(c => '<tr>' +
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
  tbody.innerHTML = d.platforms.length ? d.platforms.map(p => {
    const badge = p.status === '-' ? '<span class="badge text-bg-secondary">Henüz yok</span>'
      : p.status === 'success' ? '<span class="badge text-bg-success">Başarılı</span>'
      : '<span class="badge text-bg-danger">Hata</span>';
    return '<tr><td>' + App.esc(p.name) + '</td>' +
      '<td>' + (p.type === 'vcenter' ? 'vCenter' : 'Proxmox') + '</td>' +
      '<td class="small">' + App.fmtDate(p.last_sync) + '</td><td>' + badge + '</td></tr>';
  }).join('')
    : '<tr><td colspan="4" class="text-muted p-3">Henüz platform eklenmemiş. ' +
      '<a href="/platforms">Platformlar</a> sayfasından ekleyebilirsiniz.</td></tr>';
})();

/* ---------- Cluster görünürlük yönetimi ---------- */
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
      '<input class="form-check-input" type="checkbox" role="switch" ' +
      (c.visible ? 'checked ' : '') +
      'onchange="Clusters.toggle(\'' + App.esc(c.name).replace(/'/g, "\\'") + '\', this.checked)"></div>' +
      '<div class="flex-grow-1"><strong>' + App.esc(label) +
      (c.is_none ? ' <i class="bi bi-info-circle text-muted" title="Cluster\'a bağlı olmayan (standalone host) VM ve host\'lar"></i>' : '') + '</strong>' +
      (!c.in_inventory ? ' <span class="badge text-bg-light border">envanterde yok</span>' : '') +
      '<br><small class="text-muted">' + c.vm_count + ' VM · ' + c.host_count + ' host</small></div>' +
      (c.visible ? '<span class="badge text-bg-success">Görünür</span>'
                 : '<span class="badge text-bg-secondary">Gizli</span>') +
      '</li>';
    }).join('');
  },

  async toggle(name, visible) {
    try {
      await App.api('/api/clusters/visibility', {method: 'POST', body: {name, visible}});
      const label = name === '__none__' ? "(Cluster'sız)" : name;
      App.toast('"' + label + '" ' + (visible ? 'görünür yapıldı' : 'gizlendi') +
                ' — dashboard güncelleniyor', 'info');
      await Clusters.render();
      setTimeout(() => location.reload(), 900);   // sayıları/grafikleri tazele
    } catch (e) { Clusters.render(); }
  },
};

// Buton şablonda inline onclick ile de bağlı; burası yedek bağlama.
const _btnClusters = document.getElementById('btnClusters');
if (_btnClusters) _btnClusters.addEventListener('click', Clusters.open);
