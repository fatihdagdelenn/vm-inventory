/**
 * reports.js — Anlık dışa aktarma + zamanlanmış raporlar.
 * Anlık export: tarayıcı indirme olarak /api/reports/... adresine gider,
 * filtre (q) arama söz dizimiyle uygulanır.
 */
const Reports = {
  /** Anlık dışa aktarma — entity: 'vms' | 'hosts', fmt: xlsx | csv | pdf */
  export(entity, fmt) {
    const q = document.getElementById('repQuery').value.trim();
    location.href = '/api/reports/' + entity + '/export?fmt=' + fmt +
                    '&q=' + encodeURIComponent(q);
  },

  /** Zamanlanmış rapor oluştur (her gün belirtilen saatte sunucuya yazılır). */
  async schedule() {
    const payload = {
      hour:   parseInt(document.getElementById('schHour').value || '7', 10),
      minute: parseInt(document.getElementById('schMin').value || '0', 10),
      fmt:    document.getElementById('schFmt').value,
      q:      document.getElementById('schQuery').value.trim(),
    };
    try {
      await App.api('/api/reports/schedule', {method: 'POST', body: payload});
      App.toast('Zamanlanmış rapor oluşturuldu');
      Reports.loadSchedules();
    } catch (e) { /* hata gösterildi */ }
  },

  /** Kayıtlı zamanlanmış raporları listele. */
  async loadSchedules() {
    let data;
    try { data = await App.api('/api/reports/schedule'); } catch (e) { return; }
    const list = document.getElementById('schList');
    if (!data.items.length) {
      list.innerHTML = '<li class="list-group-item text-muted small">Zamanlanmış rapor yok.</li>';
      return;
    }
    list.innerHTML = data.items.map(j =>
      '<li class="list-group-item d-flex align-items-center">' +
      '<i class="bi bi-clock me-2 text-muted"></i>' +
      '<span class="small"><code>' + App.esc(j.id) + '</code>' +
      '<br><span class="text-muted">Sonraki çalışma: ' + App.esc(j.next_run) + '</span></span>' +
      '<button class="btn btn-sm btn-outline-danger ms-auto" title="Sil" ' +
      'onclick="Reports.remove(\'' + App.esc(j.id) + '\')"><i class="bi bi-trash"></i></button></li>').join('');
  },

  async remove(jobId) {
    if (!confirm('Zamanlanmış rapor silinsin mi?')) return;
    try {
      await App.api('/api/reports/schedule/' + jobId, {method: 'DELETE'});
      App.toast('Zamanlanmış rapor silindi');
      Reports.loadSchedules();
    } catch (e) { /* hata gösterildi */ }
  },
};

Reports.loadSchedules();
