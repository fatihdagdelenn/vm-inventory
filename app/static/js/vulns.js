/**
 * vulns.js — Kernel vulnerabilities page (phase 160): summary cards + CVE list.
 * One row per CVE that has at least one open finding; the VM count opens the
 * VM list filtered with cve:<id>. ?q= / ?vm= in the URL pre-fill the filters.
 */
const Vu = {
  vm: null,

  query() {
    const p = new URLSearchParams();
    const q = document.getElementById('vuSearch').value.trim();
    if (q) p.set('q', q);
    const sev = document.getElementById('vuSev').value;
    if (sev) p.set('severity', sev);
    const fix = document.getElementById('vuFix').value;
    if (fix) p.set('fix', fix);
    if (document.getElementById('vuKev').checked) p.set('kev', 'true');
    if (this.vm) p.set('vm', this.vm);
    return p.toString();
  },

  stats(s) {
    const card = (n, label, q, cls) =>
      '<div class="vu-stat card panel ' + (cls || '') + '" data-q="' + App.esc(q) + '">' +
      '<div class="vu-n">' + n + '</div><div class="vu-l">' + label + '</div></div>';
    document.getElementById('vuStats').innerHTML =
      card(s.vms_kev, t('vu.stKevVms', 'KEV etkili VM'), 'kev:evet', 'vu-stat-kev') +
      card(s.vms_open, t('vu.stOpenVms', 'Açık CVE\'li VM'), 'zafiyet:var') +
      card(s.cves_open, t('vu.stCves', 'Açık CVE (farklı)'), '') +
      card(s.vms_evaluated, t('vu.stEval', 'Değerlendirilen VM'), 'zafiyet:var,yok') +
      card(s.vms_unknown, t('vu.stUnknown', 'Değerlendirilemeyen VM'), 'zafiyet:bilinmiyor') +
      card(s.vms_skipped, t('vu.stSkipped', 'Kapsam dışı (EOL / bilinmiyor)'), 'zafiyet:kapsamdisi');
    document.querySelectorAll('#vuStats .vu-stat').forEach(el => el.addEventListener('click', () => {
      const q = el.dataset.q;
      if (q) location.href = '/vms?q=' + encodeURIComponent(q);
    }));
    document.getElementById('vuNoData').classList.toggle('d-none', !!s.has_data);
  },

  async load() {
    let data;
    try { data = await App.api('/api/vulns?' + this.query()); } catch (e) { return; }
    this.stats(data.summary);
    const vf = document.getElementById('vuVmFilter');
    if (data.vm) {
      vf.innerHTML = '<i class="bi bi-pc-display"></i> ' + App.esc(data.vm.name) +
        ' <a href="#" class="ms-1 text-decoration-none" id="vuVmClear">✕</a>';
      vf.title = data.vm.reason || '';
      vf.classList.remove('d-none');
      document.getElementById('vuVmClear').onclick = (e) => {
        e.preventDefault(); this.vm = null; history.replaceState(null, '', '/vulns'); this.load();
      };
    } else vf.classList.add('d-none');
    const body = document.getElementById('vuBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="6" class="text-center text-muted p-4">' +
        t('vu.empty', 'Açık çekirdek zafiyeti bulunamadı') + '</td></tr>';
    } else {
      body.innerHTML = data.items.map(r => {
        const parts = [];
        if (r.fixable) parts.push(r.fixable + ' ' + t('vu.cFix', 'düzeltilebilir'));
        if (r.nofix) parts.push(r.nofix + ' ' + t('vu.cNofix', 'düzeltmesiz'));
        if (r.uncertain) parts.push(r.uncertain + ' ' + t('vu.cUnc', 'belirsiz'));
        const vmQ = 'cve:' + r.cve;
        return '<tr>' +
          '<td class="text-nowrap"><a class="fw-semibold" target="_blank" rel="noopener" href="https://osv.dev/vulnerability/' +
            encodeURIComponent(r.cve) + '" title="osv.dev">' + App.esc(r.cve) + '</a></td>' +
          '<td class="text-nowrap">' + App.sevBadge(r.severity) +
            (r.score != null ? ' <small class="text-muted">' + r.score.toFixed(1) + '</small>' : '') + '</td>' +
          '<td class="vu-sumcell"><div title="' + App.esc(r.summary || '') + '">' + App.esc(r.summary || '—') + '</div></td>' +
          '<td class="text-end vu-vms"><a href="/vms?q=' + encodeURIComponent(vmQ) + '" class="fw-semibold">' + r.vms + '</a>' +
            '<div class="vu-reason text-muted">' + App.esc(parts.join(' · ')) + '</div></td>' +
          '<td class="text-nowrap">' + (r.kev ? App.kevBadge(r.kev_due) +
            (r.ransomware ? ' <i class="bi bi-lock-fill text-danger" title="' +
              App.esc(t('vu.ransom', 'Fidye yazılımı kampanyalarında kullanıldığı biliniyor')) + '"></i>' : '') : '') + '</td>' +
          '<td class="text-nowrap text-muted small">' + App.fmtDate(r.first_seen) + '</td></tr>';
      }).join('');
    }
    document.getElementById('vuCount').textContent = data.total + ' CVE';
  },

  init() {
    const p = new URLSearchParams(location.search);
    if (p.get('q')) document.getElementById('vuSearch').value = p.get('q');
    if (p.get('kev')) document.getElementById('vuKev').checked = true;
    this.vm = p.get('vm') ? parseInt(p.get('vm'), 10) || null : null;
    const reload = App.debounce(() => this.load(), 300);
    document.getElementById('vuSearch').addEventListener('input', reload);
    ['vuSev', 'vuFix', 'vuKev'].forEach(id =>
      document.getElementById(id).addEventListener('change', () => this.load()));
    this.load();
  },
};

document.addEventListener('DOMContentLoaded', () => Vu.init());
