/**
 * history.js — Envanter Değişiklik Geçmişi.
 * Senkronizasyonda saptanan altyapı değişiklikleri + platform görev/olay kaydından
 * "kim yaptı". Kaynak (platform/cluster/host/VM ID), kategori, eski→yeni değer ve
 * kullanıcı (varsa IP/User-Agent) gösterilir.
 */
const History = {
  FIELD_LABELS: {
    ram_mb: 'Bellek (RAM)', cpu_count: 'vCPU', guest_os: 'İşletim Sistemi',
    disk_total_gb: 'Disk Boyutu', datastore: 'Depolama (Datastore)',
    vlans: 'VLAN / Ağ', ip_addresses: 'IP Adresi', name: 'Ad',
    cluster: 'Cluster', power_state: 'Güç Durumu', host: 'Host (Göç)',
    console: 'Konsol Erişimi',
  },
  CATS: {
    hardware:  { l: 'Donanım',        i: 'cpu',              c: 'text-bg-primary' },
    disk:      { l: 'Disk',           i: 'hdd',              c: 'text-bg-info' },
    network:   { l: 'Ağ',             i: 'diagram-3',        c: 'text-bg-secondary' },
    power:     { l: 'Güç',            i: 'power',            c: 'text-bg-warning text-dark' },
    migrate:   { l: 'Göç',            i: 'arrow-left-right', c: 'text-bg-dark' },
    lifecycle: { l: 'Yaşam Döngüsü',  i: 'box-seam',         c: 'text-bg-success' },
    os:        { l: 'İşletim Sistemi', i: 'window-stack',    c: 'text-bg-info' },
    console:   { l: 'Konsol',         i: 'terminal',         c: 'text-bg-danger' },
    other:     { l: 'Diğer',          i: 'pencil-square',    c: 'text-bg-light text-dark border' },
  },
  TYPE_BADGE: {
    created:  '<span class="badge text-bg-success">Eklendi</span>',
    updated:  '<span class="badge text-bg-warning text-dark">Güncellendi</span>',
    deleted:  '<span class="badge text-bg-danger">Silindi</span>',
    migrated: '<span class="badge text-bg-dark">Göç</span>',
    access:   '<span class="badge text-bg-danger-subtle text-danger border border-danger-subtle">Erişim</span>',
  },
  POWER: { running: 'Çalışıyor', stopped: 'Kapalı', suspended: 'Askıda',
           poweredOn: 'Çalışıyor', poweredOff: 'Kapalı' },

  /** Alan değerini okunaklı biçimle (RAM→GB, disk→GB, güç→TR). */
  fmtVal(field, v) {
    if (v == null || v === '') return '—';
    if (field === 'ram_mb') return App.fmtRam(Number(v)) || App.esc(v);
    if (field === 'disk_total_gb') return App.fmtGb(Number(v)) || App.esc(v);
    if (field === 'power_state') return App.esc(History.POWER[v] || v);
    return App.esc(v);
  },

  /** Platform rozeti. */
  platformCell(r) {
    if (r.platform_type === 'vcenter')
      return '<span class="badge text-bg-light text-dark border"><i class="bi bi-vmware text-primary"></i> vCenter</span>';
    if (r.platform_type === 'proxmox')
      return '<span class="badge text-bg-light text-dark border"><i class="bi bi-hdd-network text-warning"></i> Proxmox</span>';
    return '';
  },

  /** Kaynak hücresi: platform + cluster + host + VM ID. */
  sourceCell(r) {
    const bits = [];
    const p = History.platformCell(r);
    if (p) bits.push(p);
    const sub = [];
    if (r.cluster) sub.push('<i class="bi bi-hdd-stack"></i> ' + App.esc(r.cluster));
    if (r.host)    sub.push('<i class="bi bi-server"></i> ' + App.esc(r.host));
    if (r.vm_external_id) sub.push('<span class="text-muted">ID:' + App.esc(r.vm_external_id) + '</span>');
    let html = bits.join(' ');
    if (sub.length) html += '<div class="small text-muted mt-1">' + sub.join(' &middot; ') + '</div>';
    return html || '<span class="text-muted">—</span>';
  },

  categoryCell(r) {
    const c = History.CATS[r.category] || History.CATS.other;
    return '<span class="badge ' + c.c + '"><i class="bi bi-' + c.i + '"></i> ' + c.l + '</span>';
  },

  /** İşlem hücresi: tip rozeti + ham platform op tipi. */
  opCell(r) {
    let html = History.TYPE_BADGE[r.change_type] || App.esc(r.change_type || '');
    if (r.op_type) html += '<div class="small text-muted mt-1"><code>' + App.esc(r.op_type) + '</code></div>';
    return html;
  },

  /** Alan/değer hücresi: alan etiketi + eski → yeni. */
  valueCell(r) {
    const label = History.FIELD_LABELS[r.field] || App.esc(r.field || '');
    if (r.category === 'console')
      return '<strong>Konsol erişimi</strong><div class="small text-muted">~ ' +
             App.fmtDate(r.new_value) + ' <span class="text-muted">(30 dk pencere)</span></div>';
    if (r.change_type === 'migrated')
      return '<strong>' + label + '</strong><div class="small">' +
             '<span class="text-muted">' + History.fmtVal(r.field, r.old_value) + '</span>' +
             ' <i class="bi bi-arrow-right"></i> ' +
             '<span class="text-success">' + History.fmtVal(r.field, r.new_value) + '</span></div>';
    if (r.change_type === 'created')
      return '<strong>' + label + '</strong>';
    // updated
    const hasBoth = (r.old_value != null) || (r.new_value != null);
    let html = '<strong>' + label + '</strong>';
    if (hasBoth)
      html += '<div class="small">' +
              '<span class="text-muted">' + History.fmtVal(r.field, r.old_value) + '</span>' +
              ' <i class="bi bi-arrow-right"></i> ' +
              '<span class="fw-semibold">' + History.fmtVal(r.field, r.new_value) + '</span></div>';
    return html;
  },

  /** Kullanıcı hücresi: aktör + (varsa) IP / User-Agent ipucu. */
  userCell(r) {
    if (!r.actor) return '<span class="text-muted">—</span>';
    const extra = [];
    if (r.actor_ip) extra.push('IP: ' + r.actor_ip);
    if (r.actor_agent) extra.push('UA: ' + r.actor_agent);
    const title = extra.length ? ' title="' + App.esc(extra.join(' · ')) + '"' : '';
    let html = '<span class="badge text-bg-light text-dark border"' + title + '>' +
               '<i class="bi bi-person"></i> ' + App.esc(r.actor) +
               (extra.length ? ' <i class="bi bi-info-circle text-muted"></i>' : '') + '</span>';
    if (r.actor_ip) html += '<div class="small text-muted mt-1">' + App.esc(r.actor_ip) + '</div>';
    return html;
  },

  async load() {
    const q = document.getElementById('histSearch').value.trim();
    const entity = document.getElementById('histEntity').value;
    const category = document.getElementById('histCategory').value;
    const body = document.getElementById('histBody');
    let data;
    try {
      data = await App.api('/api/admin/changes?entity=' + encodeURIComponent(entity) +
                           '&category=' + encodeURIComponent(category) +
                           '&q=' + encodeURIComponent(q));
    } catch (e) { return; }
    document.getElementById('histCount').textContent =
      data.items.length ? data.items.length + ' kayıt' : '';
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="7" class="text-center text-muted p-4">Kayıt bulunamadı.</td></tr>';
      return;
    }
    body.innerHTML = data.items.map(r => '<tr>' +
      '<td class="text-nowrap small">' + App.fmtDate(r.changed_at) + '</td>' +
      '<td>' + History.sourceCell(r) + '</td>' +
      '<td><strong>' + App.esc(r.entity_name) + '</strong>' +
        '<div class="small text-muted">' + (r.entity_type === 'vm' ? 'VM' : 'Host') + '</div></td>' +
      '<td>' + History.categoryCell(r) + '</td>' +
      '<td>' + History.opCell(r) + '</td>' +
      '<td>' + History.valueCell(r) + '</td>' +
      '<td class="small">' + History.userCell(r) + '</td>' +
      '</tr>').join('');
  },
};

(function () {
  document.getElementById('histSearch')
    .addEventListener('input', App.debounce(History.load, 300));
  document.getElementById('histEntity').addEventListener('change', History.load);
  document.getElementById('histCategory').addEventListener('change', History.load);
  History.load();
})();
