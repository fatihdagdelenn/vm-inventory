/**
 * clusters.js — Cluster görünürlüğü (ortak bileşen, faz148).
 *
 * Gizlenen cluster'lar dashboard sayılarından/grafiklerinden, VM listesinden,
 * snapshot listesinden ve topolojiden düşer (ayar KÜRESEL: herkesi etkiler).
 * Bu dosyayı yükleyen her sayfanın üst çubuğunda "Cluster'lar" düğmesi çıkar;
 * modal buradan açılır. Değişiklikler anında kaydedilir ama sayfa verisi modal
 * kapanınca BİR KEZ tazelenir (ClusterVis.onChange; varsayılan: sayfayı yenile).
 */
const ClusterVis = {
  items: [],
  hiddenCount: 0,
  changed: false,
  filter: '',
  /** Sayfa kendi tazeleme yolunu verebilir (örn. VM listesi yeniden yüklenir). */
  onChange: () => location.reload(),

  canEdit() {
    return App.role() !== 'viewer';
  },

  label(c) { return c.is_none ? t('cl.noCluster', "(Cluster'sız)") : c.name; },

  /** Üst çubuğa düğmeyi ve gövdeye modalı yerleştir (bir kez). */
  mount() {
    const bar = document.querySelector('.topbar .ms-auto');
    if (bar && !document.getElementById('cvPill')) {
      const b = document.createElement('button');
      b.type = 'button'; b.id = 'cvPill'; b.className = 'btn btn-sm cv-pill';
      b.title = t('cv.pillTip', "Cluster görünürlüğü — gizlenen cluster'lar sayılara ve listelere dahil edilmez");
      b.innerHTML = '<i class="bi bi-eye"></i> <span class="d-none d-md-inline">' +
        t('cv.clusters', "Cluster'lar") + '</span><span class="cv-pill-badge d-none"></span>';
      b.addEventListener('click', () => ClusterVis.open());
      bar.insertBefore(b, bar.firstChild);
    }
    if (!document.getElementById('cvModal')) {
      const m = document.createElement('div');
      m.className = 'modal fade'; m.id = 'cvModal'; m.tabIndex = -1;
      m.innerHTML =
        '<div class="modal-dialog modal-dialog-scrollable"><div class="modal-content">' +
          '<div class="modal-header"><h5 class="modal-title"><i class="bi bi-eye"></i> ' +
            t('dash.clusterVisibility', 'Cluster Görünürlüğü') + '</h5>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
          '<div class="modal-body">' +
            '<div id="cvListView">' +
            '<p class="text-muted small mb-2">' + t('dash.clusterVisibilityDesc',
              "Kapattığınız cluster'lar dashboard sayılarına ve grafiklerine dahil edilmez, VM listesinde varsayılan olarak görünmez. Veri silinmez — anahtarı açınca her şey geri gelir.") + '</p>' +
            '<div class="cv-scope small mb-3"><i class="bi bi-people"></i> ' + t('cv.global',
              'Ayar herkes için geçerlidir. Yalnızca VM listesinde bakmak için Sanal Makineler sayfasındaki Cluster filtresini kullanın.') + '</div>' +
            '<div class="cv-tools">' +
              '<input type="search" class="form-control form-control-sm" id="cvSearch" placeholder="' +
                App.esc(t('cv.search', 'Cluster ara…')) + '">' +
              '<button class="btn btn-sm btn-outline-secondary" id="cvShowAll" type="button"><i class="bi bi-eye"></i> ' +
                t('cv.showAll', 'Tümünü göster') + '</button>' +
            '</div>' +
            '<div class="cv-summary small text-muted" id="cvSummary"></div>' +
            '<ul class="list-group cv-list" id="cvList"></ul>' +
            '</div>' +
            '<div id="cvAliasView" class="d-none"></div>' +
          '</div></div></div>';
      document.body.appendChild(m);
      m.addEventListener('hidden.bs.modal', () => {
        ClusterVis.showList();
        if (ClusterVis.changed) { ClusterVis.changed = false; ClusterVis.onChange(); }
      });
      document.getElementById('cvSearch').addEventListener('input', e => {
        ClusterVis.filter = e.target.value.trim().toLowerCase(); ClusterVis.render();
      });
      document.getElementById('cvShowAll').addEventListener('click', () => ClusterVis.bulk({all: true, visible: true}));
      document.getElementById('cvList').addEventListener('change', e => {
        const sw = e.target.closest('.cv-switch'); if (sw) ClusterVis.toggle(sw.dataset.name, sw.checked);
      });
      document.getElementById('cvList').addEventListener('click', e => {
        const only = e.target.closest('.cv-only'); if (only) ClusterVis.bulk({only: only.dataset.name, visible: true});
        if (e.target.closest('.cv-name-btn')) ClusterVis.showAlias();
      });
      document.getElementById('cvAliasView').addEventListener('click', e => {
        if (e.target.closest('.cv-back')) { ClusterVis.showList(); return; }
        if (e.target.closest('#cvAliasSave')) { ClusterVis.saveAliases(); return; }
        const fill = e.target.closest('.cv-ag-fill');
        if (fill) {
          const g = fill.closest('.cv-ag'), v = g.querySelector('.cv-ag-all').value;
          g.querySelectorAll('.cv-ah-input').forEach(i => { i.value = v; });
          ClusterVis.markDirty();
        }
      });
      document.getElementById('cvAliasView').addEventListener('input', () => ClusterVis.markDirty());
    }
    ClusterVis.refresh();
  },

  async refresh() {
    let d;
    try { d = await App.api('/api/clusters'); } catch (e) { return; }
    ClusterVis.items = d.items || [];
    ClusterVis.hiddenCount = d.hidden_count || 0;
    const badge = document.querySelector('#cvPill .cv-pill-badge');
    const pill = document.getElementById('cvPill');
    if (badge && pill) {
      badge.textContent = ClusterVis.hiddenCount + ' ' + t('cv.hiddenN', 'gizli');
      badge.classList.toggle('d-none', !ClusterVis.hiddenCount);
      pill.classList.toggle('has-hidden', ClusterVis.hiddenCount > 0);
    }
    if (document.getElementById('cvModal')?.classList.contains('show')) ClusterVis.render();
  },

  async open() {
    ClusterVis.mount();
    ClusterVis.showList();
    ClusterVis.filter = '';
    document.getElementById('cvSearch').value = '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('cvModal')).show();
    await ClusterVis.refresh();
    ClusterVis.render();
  },

  render() {
    const ul = document.getElementById('cvList'); if (!ul) return;
    const edit = ClusterVis.canEdit();
    const all = ClusterVis.items;
    document.getElementById('cvShowAll').disabled = !edit || !ClusterVis.hiddenCount;
    document.getElementById('cvSearch').classList.toggle('d-none', all.length < 8);
    document.getElementById('cvSummary').textContent = all.length
      ? t('cv.summary', '{v} görünür · {h} gizli').replace('{v}', all.length - ClusterVis.hiddenCount)
          .replace('{h}', ClusterVis.hiddenCount) + (edit ? '' : ' — ' + t('cv.readOnly', 'değiştirmek için operatör yetkisi gerekir'))
      : '';
    if (!all.length) {
      ul.innerHTML = '<li class="list-group-item text-muted">' +
        t('cl.noData', 'Henüz cluster verisi yok — önce bir platform senkronize edin.') + '</li>';
      return;
    }
    const rows = all.filter(c => !ClusterVis.filter || ClusterVis.label(c).toLowerCase().includes(ClusterVis.filter));
    ul.innerHTML = rows.length ? rows.map(c => {
      const nm = App.esc(c.name);
      return '<li class="list-group-item cv-row' + (c.visible ? '' : ' is-hidden') + '">' +
        '<div class="form-check form-switch mb-0"><input class="form-check-input cv-switch" type="checkbox" role="switch"' +
          ' data-name="' + nm + '"' + (c.visible ? ' checked' : '') + (edit ? '' : ' disabled') + '></div>' +
        '<div class="cv-main"><div class="cv-name">' + App.esc(ClusterVis.label(c)) +
          (c.is_alias ? ' <span class="cv-alias-tag" title="' + App.esc(t('vm.qf.aliasTip',
            'Platform cluster bildirmiyor; bu ad host için verilen takma ad')) + '">' + t('cv.aliasTag', 'takma ad') + '</span>' : '') +
          (!c.in_inventory ? ' <span class="badge text-bg-light border">' + t('cl.notInInv', 'envanterde yok') + '</span>' : '') +
          '</div><div class="cv-meta">' + c.vm_count + ' VM · ' + c.host_count + ' host' +
          ((c.is_none || c.is_alias) && (c.vm_count || c.host_count) ? ' · <button type="button" class="btn btn-link btn-sm p-0 cv-name-btn">' +
            '<i class="bi bi-tag"></i> ' + (c.is_none ? t('cv.nameIt', 'Ad ver') : t('cv.renameIt', 'Adı değiştir')) +
            '</button>' : '') + '</div></div>' +
        (edit && all.length > 1 ? '<button type="button" class="btn btn-link btn-sm cv-only" data-name="' + nm + '" title="' +
          App.esc(t('cv.onlyTip', "Bunu göster, diğer tüm cluster'ları gizle")) + '">' + t('cv.only', 'Yalnız bu') + '</button>' : '') +
        '<span class="cv-state ' + (c.visible ? 'on' : 'off') + '">' +
          (c.visible ? t('cl.visible', 'Görünür') : t('cl.hidden', 'Gizli')) + '</span>' +
      '</li>';
    }).join('') : '<li class="list-group-item text-muted small">' + t('cv.noMatch', 'Eşleşen cluster yok') + '</li>';
  },

  /* ---------- Cluster'sız (standalone) host'lara takma ad ---------- */
  showList() {
    document.getElementById('cvListView')?.classList.remove('d-none');
    document.getElementById('cvAliasView')?.classList.add('d-none');
  },

  async showAlias() {
    const view = document.getElementById('cvAliasView');
    document.getElementById('cvListView').classList.add('d-none');
    view.classList.remove('d-none');
    view.innerHTML = '<div class="text-muted small">' + t('common.loading', 'Yükleniyor…') + '</div>';
    let d;
    try { d = await App.api('/api/clusters/standalone'); } catch (e) { ClusterVis.showList(); return; }
    const edit = ClusterVis.canEdit();
    const known = [...new Set(ClusterVis.items.filter(c => c.is_alias).map(c => c.name))];
    const dis = edit ? '' : ' disabled';
    view.innerHTML =
      '<div class="cv-alias-head"><button type="button" class="btn btn-sm btn-link p-0 cv-back">' +
        '<i class="bi bi-arrow-left"></i> ' + t('cv.back', 'Geri') + '</button>' +
        '<strong>' + t('cv.aliasTitle', "Cluster'sız host'lara ad ver") + '</strong></div>' +
      '<p class="small text-muted mb-2">' + t('cv.aliasDesc',
        "Bu host'lar platformda bir cluster'a bağlı değil (ör. standalone ESXi), bu yüzden \"(Cluster'sız)\" altında toplanıyor. Verdiğiniz ad host'a ve VM'lerine cluster adı olarak yazılır: aramada, filtrede, gizlemede ve grafiklerde normal bir cluster gibi davranır. Aynı adı birden çok host'a verip birleştirebilirsiniz. Platform ileride gerçek bir cluster bildirirse o ad kullanılır. Boş bırakmak adı kaldırır.") + '</p>' +
      '<datalist id="cvAliasList">' + known.map(n => '<option value="' + App.esc(n) + '">').join('') + '</datalist>' +
      (d.groups.length ? d.groups.map(g =>
        '<div class="cv-ag">' +
          '<div class="cv-ag-head"><div class="cv-ag-title"><i class="bi bi-hdd-network"></i> ' + App.esc(g.platform) +
            (g.location ? ' <span class="cv-meta">· ' + App.esc(g.location) + '</span>' : '') + '</div>' +
            (g.hosts.length > 1 ? '<div class="cv-ag-bulk"><input class="form-control form-control-sm cv-ag-all" list="cvAliasList" placeholder="' +
              App.esc(t('cv.allSame', "Tümüne aynı ad…")) + '"' + dis + '>' +
              '<button type="button" class="btn btn-sm btn-outline-secondary cv-ag-fill"' + dis + '>' + t('cv.fill', 'Doldur') + '</button></div>' : '') +
          '</div>' +
          g.hosts.map(h =>
            '<div class="cv-ah"><div class="cv-ah-name">' + App.esc(h.host) +
              '<div class="cv-meta">' + h.vm_count + ' VM</div></div>' +
              '<input class="form-control form-control-sm cv-ah-input" list="cvAliasList" maxlength="128"' +
                ' data-pid="' + g.platform_id + '" data-host="' + App.esc(h.host) + '" data-orig="' + App.esc(h.alias) + '"' +
                ' value="' + App.esc(h.alias) + '" placeholder="' + App.esc(t('cl.noCluster', "(Cluster'sız)")) + '"' + dis + '>' +
            '</div>').join('') +
        '</div>').join('')
        : '<div class="text-muted small">' + t('cv.noStandalone', "Cluster'sız host yok.") + '</div>') +
      (d.hostless_vms ? '<div class="small text-muted mt-2"><i class="bi bi-info-circle"></i> ' +
        t('cv.hostless', "{n} VM'in host bilgisi yok; bunlara ad verilemez, (Cluster'sız) altında kalır.").replace('{n}', d.hostless_vms) + '</div>' : '') +
      '<div class="cv-alias-foot"><span class="small text-muted" id="cvAliasDirty"></span>' +
        '<button type="button" class="btn btn-sm btn-primary" id="cvAliasSave" disabled>' +
        '<i class="bi bi-check-lg"></i> ' + t('action.save', 'Kaydet') + '</button></div>';
    if (!edit) document.getElementById('cvAliasDirty').textContent = t('cv.readOnly', 'değiştirmek için operatör yetkisi gerekir');
  },

  aliasChanges() {
    return [...document.querySelectorAll('#cvAliasView .cv-ah-input')]
      .filter(i => i.value.trim() !== i.dataset.orig)
      .map(i => ({platform_id: +i.dataset.pid, host: i.dataset.host, alias: i.value.trim()}));
  },

  markDirty() {
    const n = ClusterVis.aliasChanges().length;
    const btn = document.getElementById('cvAliasSave'); if (!btn) return;
    btn.disabled = !n || !ClusterVis.canEdit();
    document.getElementById('cvAliasDirty').textContent = n ? t('cv.pending', '{n} değişiklik').replace('{n}', n) : '';
  },

  async saveAliases() {
    const items = ClusterVis.aliasChanges(); if (!items.length) return;
    let r;
    try { r = await App.api('/api/clusters/aliases', {method: 'PUT', body: {items}}); } catch (e) { return; }
    if (r.changed && r.changed.length) ClusterVis.changed = true;
    App.toast(t('cv.aliasSaved', 'Takma adlar kaydedildi') +
      (r.inherited_hidden && r.inherited_hidden.length
        ? ' — ' + t('cv.inheritedHidden', 'gizli kaldı: {n} (görünür yapmak için anahtarı açın)')
            .replace('{n}', r.inherited_hidden.join(', ')) : ''), 'success');
    await ClusterVis.refresh();
    ClusterVis.showList(); ClusterVis.render();
  },

  async toggle(name, visible) {
    try {
      await App.api('/api/clusters/visibility', {method: 'POST', body: {name, visible}});
      ClusterVis.changed = true;
    } catch (e) { /* hata toast'ı App.api'de */ }
    await ClusterVis.refresh(); ClusterVis.render();
  },

  async bulk(body) {
    try {
      const r = await App.api('/api/clusters/visibility/bulk', {method: 'POST', body});
      if (r && r.changed && r.changed.length) ClusterVis.changed = true;
    } catch (e) { /* hata toast'ı App.api'de */ }
    await ClusterVis.refresh(); ClusterVis.render();
  },
};
document.addEventListener('DOMContentLoaded', () => ClusterVis.mount());
