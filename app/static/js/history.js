/**
 * history.js — Envanter Değişiklik Geçmişi.
 * Senkronizasyonda saptanan altyapı değişiklikleri + platform görev/olay kaydından
 * "kim yaptı". Kaynak (platform/cluster/host/VM ID), kategori, eski→yeni değer ve
 * kullanıcı (varsa IP/User-Agent) gösterilir.
 */
const History = {
  FIELD_LABELS: {
    ram_mb: t('hi.f.ram','Bellek (RAM)'), cpu_count: 'vCPU', guest_os: t('vm.os','İşletim Sistemi'),
    disk_total_gb: t('hi.f.disk','Disk Boyutu'), datastore: t('hi.f.ds','Depolama (Datastore)'),
    vlans: t('hi.f.vlan','VLAN / Ağ'), ip_addresses: t('th.ip','IP Adresi'), name: t('hi.f.name','Ad'),
    networks: t('hi.f.net','Ağ (Köprü/Portgrup)'),
    cluster: 'Cluster', power_state: t('hi.f.power','Güç Durumu'), host: t('hi.f.host','Host (Göç)'),
    console: t('hi.cat.console','Konsol Erişimi'),
  },
  CATS: {
    hardware:  { l: t('hi.c.hardware','Donanım'),        i: 'cpu',              c: 'cat-badge cat-hardware' },
    disk:      { l: 'Disk',           i: 'hdd',              c: 'cat-badge cat-disk' },
    network:   { l: t('hi.c.network','Ağ'),             i: 'diagram-3',        c: 'cat-badge cat-network' },
    power:     { l: t('hi.c.power','Güç'),            i: 'power',            c: 'cat-badge cat-power' },
    migrate:   { l: t('ct.migrated','Göç'),            i: 'arrow-left-right', c: 'cat-badge cat-migrate' },
    lifecycle: { l: t('hi.c.lifecycle','Yaşam Döngüsü'),  i: 'box-seam',         c: 'cat-badge cat-lifecycle' },
    os:        { l: t('vm.os','İşletim Sistemi'), i: 'window-stack',    c: 'cat-badge cat-os' },
    console:   { l: t('hi.c.console','Konsol'),         i: 'terminal',         c: 'cat-badge cat-console' },
    other:     { l: t('hi.c.other','Diğer'),          i: 'pencil-square',    c: 'cat-badge cat-other' },
  },
  TYPE_BADGE: {
    created:  '<span class="op-badge op-created">' + t('ct.created','Eklendi') + '</span>',
    updated:  '<span class="op-badge op-updated">' + t('ct.updated','Güncellendi') + '</span>',
    deleted:  '<span class="op-badge op-deleted">' + t('ct.deleted','Silindi') + '</span>',
    migrated: '<span class="op-badge op-migrated">' + t('ct.migrated','Göç') + '</span>',
    access:   '<span class="op-badge op-access">' + t('ct.access','Erişim') + '</span>',
  },
  POWER: { running: t('st.running','Çalışıyor'), stopped: t('st.stopped','Kapalı'), suspended: t('st.suspended','Askıda'),
           poweredOn: t('st.running','Çalışıyor'), poweredOff: t('st.stopped','Kapalı') },

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
      return '<strong>' + t('hi.consoleAccess','Konsol erişimi') + '</strong><div class="small text-muted">~ ' +
             App.fmtDate(r.new_value) + ' <span class="text-muted">(' + t('hi.window30','30 dk pencere') + ')</span></div>';
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
    // Platform-initiated (system) operations: machine accounts and automation
    // task types. Shown as a gear badge; the real account stays in the tooltip.
    const sysActor = /^(vpxd|com\.vmware|vcls|vpxuser|dcui|nobody)|vpxd-extension/i.test(r.actor);
    const sysOp = /^(ha[a-z]*|pvesr|replication|aptupdate)$/i.test(r.op_type || '');
    if (r.actor_system === true || (r.actor_system === undefined && (sysActor || sysOp))) {
      return '<span class="badge text-bg-secondary" title="' + App.esc(r.actor) +
             (r.op_type ? ' · ' + App.esc(r.op_type) : '') + '">' +
             '<i class="bi bi-gear"></i> ' + t('hi.system', 'sistem') + '</span>';
    }
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

  /** Aktif filtre kutusu: arama terimleri (dahil/dışla) + varlık + kategori. */
  renderFilters(q, entity, category, actorKind) {
    const wrap = document.getElementById('histFilters');
    const chips = [];
    const terms = q.match(/[-!]?"[^"]*"|[-!]?\S+/g) || [];
    terms.forEach((tok, i) => {
      const neg = tok.startsWith('-') || tok.startsWith('!');
      chips.push('<span class="filter-badge' + (neg ? ' negative' : '') + '">' +
        (neg ? '<i class="bi bi-dash-circle"></i> ' : '') + App.esc(tok) +
        '<button title="' + t('vm.remove','Kaldır') + '" onclick="History.removeTerm(' + i + ')"><i class="bi bi-x"></i></button></span>');
    });
    if (entity)
      chips.push('<span class="filter-badge">' + t('hi.entity','Varlık') + ': ' + (entity === 'vm' ? 'VM' : 'Host') +
        '<button title="' + t('vm.remove','Kaldır') + '" onclick="History.clearSel(\'histEntity\')"><i class="bi bi-x"></i></button></span>');
    if (category) {
      const lbl = (History.CATS[category] || {}).l || category;
      chips.push('<span class="filter-badge">' + t('hi.category','Kategori') + ': ' + App.esc(lbl) +
        '<button title="' + t('vm.remove','Kaldır') + '" onclick="History.clearSel(\'histCategory\')"><i class="bi bi-x"></i></button></span>');
    }
    if (actorKind) {
      const al = { user: t('hi.actorUser','Yaln\u0131z Kullan\u0131c\u0131'),
                   system: t('hi.actorSystem','Yaln\u0131z Sistem (otomatik)'),
                   none: t('hi.actorNone','Kullan\u0131c\u0131s\u0131z (\u2014)') }[actorKind] || actorKind;
      chips.push('<span class="filter-badge">' + t('hi.user','Kullan\u0131c\u0131') + ': ' + App.esc(al) +
        '<button title="' + t('vm.remove','Kald\u0131r') + '" onclick="History.clearSel(\'histActor\')"><i class="bi bi-x"></i></button></span>');
    }
    if (!chips.length) { wrap.classList.add('d-none'); wrap.innerHTML = ''; return; }
    wrap.classList.remove('d-none');
    wrap.innerHTML = '<span class="text-muted small me-1">' + t('vm.activeFilters','Aktif:') + '</span>' + chips.join('') +
      (chips.length > 1 ? '<button class="btn btn-link btn-sm p-0 ms-1" onclick="History.clearAllFilters()">' + t('vm.clearAll','tümünü temizle') + '</button>' : '');
  },

  removeTerm(i) {
    const inp = document.getElementById('histSearch');
    const terms = (inp.value.trim().match(/[-!]?"[^"]*"|[-!]?\S+/g) || []);
    terms.splice(i, 1);
    inp.value = terms.join(' ');
    History.load();
  },
  clearSel(id) { document.getElementById(id).value = ''; History.load(); },
  clearAllFilters() {
    document.getElementById('histSearch').value = '';
    document.getElementById('histEntity').value = '';
    document.getElementById('histCategory').value = '';
    document.getElementById('histActor').value = '';
    History.load();
  },

  async load() {
    const q = document.getElementById('histSearch').value.trim();
    const entity = document.getElementById('histEntity').value;
    const category = document.getElementById('histCategory').value;
    const actorKind = document.getElementById('histActor').value;
    History.renderFilters(q, entity, category, actorKind);
    const body = document.getElementById('histBody');
    let data;
    try {
      data = await App.api('/api/admin/changes?entity=' + encodeURIComponent(entity) +
                           '&category=' + encodeURIComponent(category) +
                           '&actor_kind=' + encodeURIComponent(actorKind) +
                           '&q=' + encodeURIComponent(q));
    } catch (e) { return; }
    document.getElementById('histCount').textContent =
      data.items.length ? data.items.length + ' ' + t('hi.records','kayıt') : '';
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="7" class="text-center text-muted p-4">' + t('hi.noRecords','Kayıt bulunamadı.') + '</td></tr>';
      return;
    }
    body.innerHTML = data.items.map(r => '<tr>' +
      '<td class="text-nowrap small">' + App.fmtDate(r.changed_at) + '</td>' +
      '<td>' + History.sourceCell(r) + '</td>' +
      '<td><strong>' + App.esc(r.entity_name) + '</strong>' +
        '<div class="small text-muted">' + ({vm:'VM', host:'Host', datastore:'Datastore', network:t('hi.cat.network','Ağ')}[r.entity_type] || r.entity_type) + '</div></td>' +
      '<td>' + History.categoryCell(r) + '</td>' +
      '<td>' + History.opCell(r) + '</td>' +
      '<td class="val-cell">' + History.valueCell(r) + '</td>' +
      '<td class="small usr-cell">' + History.userCell(r) + '</td>' +
      '</tr>').join('');
  },
};

(function () {
  document.getElementById('histSearch')
    .addEventListener('input', App.debounce(History.load, 300));
  document.getElementById('histEntity').addEventListener('change', History.load);
  document.getElementById('histCategory').addEventListener('change', History.load);
  document.getElementById('histActor').addEventListener('change', History.load);
  History.load();
})();
