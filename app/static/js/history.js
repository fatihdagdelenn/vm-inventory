/**
 * history.js — Envanter değişiklik geçmişi (senkronizasyonlarda saptanan farklar).
 */
const History = {
  async load() {
    const q = document.getElementById('histSearch').value.trim();
    const entity = document.getElementById('histEntity').value;
    let data;
    try {
      data = await App.api('/api/admin/changes?entity=' + encodeURIComponent(entity) +
                           '&q=' + encodeURIComponent(q));
    } catch (e) { return; }
    const body = document.getElementById('histBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="8" class="text-center text-muted p-4">Kayıt bulunamadı.</td></tr>';
      return;
    }
    const typeBadge = t => ({
      created: '<span class="badge text-bg-success">Eklendi</span>',
      updated: '<span class="badge text-bg-warning text-dark">Güncellendi</span>',
      deleted: '<span class="badge text-bg-danger">Silindi</span>',
    }[t] || App.esc(t));
    body.innerHTML = data.items.map(r => '<tr>' +
      '<td class="text-nowrap small">' + App.fmtDate(r.changed_at) + '</td>' +
      '<td>' + (r.entity_type === 'vm' ? 'VM' : 'Host') + '</td>' +
      '<td><strong>' + App.esc(r.entity_name) + '</strong></td>' +
      '<td class="small">' + (r.actor
        ? '<span class="badge text-bg-light text-dark border"><i class="bi bi-person"></i> ' + App.esc(r.actor) + '</span>'
        : '<span class="text-muted">—</span>') + '</td>' +
      '<td>' + typeBadge(r.change_type) + '</td>' +
      '<td>' + App.esc(r.field || '—') + '</td>' +
      '<td class="small text-muted">' + App.esc(r.old_value || '—') + '</td>' +
      '<td class="small">' + App.esc(r.new_value || '—') + '</td></tr>').join('');
  },
};

(function () {
  document.getElementById('histSearch')
    .addEventListener('input', App.debounce(History.load, 300));
  document.getElementById('histEntity').addEventListener('change', History.load);
  History.load();
})();
