/**
 * app.js — Tüm sayfalarda kullanılan ortak yardımcılar.
 *  - App.api()   : CSRF header'ı otomatik ekleyen fetch sarmalayıcı
 *  - App.toast() : Bootstrap toast bildirimi
 *  - App.syncAll : "Tümünü Yenile" butonu (toplu veri yenileme)
 *  - Biçimlendirme yardımcıları (RAM, disk, tarih, durum rozeti)
 */
const App = {

  /** Çerezden değer oku (CSRF token için). */
  getCookie(name) {
    const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return m ? decodeURIComponent(m.pop()) : '';
  },

  /**
   * API çağrısı sarmalayıcı.
   * GET dışındaki isteklerde X-CSRF-Token header'ı otomatik eklenir.
   * Hata durumunda sunucudan gelen "detail" mesajı toast olarak gösterilir.
   */
  async api(url, options = {}) {
    options.headers = Object.assign({'Content-Type': 'application/json'}, options.headers);
    const method = (options.method || 'GET').toUpperCase();
    if (method !== 'GET') {
      options.headers['X-CSRF-Token'] = App.getCookie('csrf_token');
    }
    if (options.body && typeof options.body !== 'string') {
      options.body = JSON.stringify(options.body);
    }
    const res = await fetch(url, options);
    if (res.status === 401) {            // oturum süresi doldu → girişe yönlendir
      location.href = '/login';
      throw new Error('Oturum süresi doldu');
    }
    if (!res.ok) {
      let msg = 'İstek başarısız (' + res.status + ')';
      try { msg = (await res.json()).detail || msg; } catch (e) { /* gövde yoksa */ }
      App.toast(msg, 'danger');
      throw new Error(msg);
    }
    return res.json();
  },

  /** Bootstrap toast bildirimi göster. type: success | danger | info | warning */
  toast(message, type = 'success') {
    const wrap = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + type + ' border-0';
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + App.esc(message) +
      '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    wrap.appendChild(el);
    const t = new bootstrap.Toast(el, {delay: 4000});
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  },

  /** "Tümünü Yenile": tüm platformlar için arka plan senkronizasyonu tetikler. */
  async syncAll(btn) {
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Başlatılıyor…';
    try {
      const r = await App.api('/api/platforms/sync-all', {method: 'POST'});
      App.toast(r.message || 'Senkronizasyon başlatıldı', 'info');
    } catch (e) { /* hata zaten gösterildi */ }
    btn.disabled = false;
    btn.innerHTML = original;
  },

  /* ---------- Biçimlendirme yardımcıları ---------- */

  /** HTML kaçış — XSS koruması için tüm kullanıcı/API verisi bununla yazdırılır. */
  esc(s) {
    return String(s ?? '').replace(/[&<>"']/g,
      c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  },

  /** MB cinsinden RAM'i okunaklı yaz (örn: 16 GB). */
  fmtRam(mb) {
    if (!mb) return '—';
    return mb >= 1024 ? (mb / 1024).toFixed(mb % 1024 ? 1 : 0) + ' GB' : mb + ' MB';
  },

  /** GB cinsinden diski okunaklı yaz. */
  fmtGb(gb) {
    if (gb == null || gb === 0) return '—';
    return gb >= 1024 ? (gb / 1024).toFixed(1) + ' TB' : Math.round(gb) + ' GB';
  },

  /** ISO tarihi yerel TR biçiminde göster (UTC -> APP_TZ). */
  fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return '—';
    return d.toLocaleString('tr-TR', {day: '2-digit', month: '2-digit', year: 'numeric',
                                      hour: '2-digit', minute: '2-digit',
                                      timeZone: window.APP_TZ || 'Europe/Istanbul'});
  },

  /** Güç/erişim durumu için renkli rozet üret. */
  stateBadge(state) {
    const map = {
      running:   ['Çalışıyor',  'state-running'],
      stopped:   ['Kapalı',     'state-stopped'],
      suspended: ['Askıda',     'state-suspended'],
      online:    ['Online',     'state-online'],
      offline:   ['Offline',    'state-offline'],
      maintenance: ['Bakımda',  'state-suspended'],
      unknown:   ['Bilinmiyor', 'state-stopped'],
    };
    const [label, cls] = map[state] || [state || '—', 'state-stopped'];
    return '<span class="state-badge ' + cls + '">' + App.esc(label) + '</span>';
  },

  /** Kullanım yüzdesine göre renklenen ilerleme çubuğu. */
  usageBar(pct) {
    pct = Math.min(100, Math.round(pct || 0));
    const cls = pct >= 90 ? 'crit' : pct >= 75 ? 'warn' : '';
    return '<div class="usage-bar ' + cls + '" title="%' + pct + '">' +
           '<div class="usage-fill" style="width:' + pct + '%"></div>' +
           '<span>%' + pct + '</span></div>';
  },

  /** Basit debounce — arama kutularında gereksiz istekleri önler. */
  debounce(fn, ms = 300) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  },
};
