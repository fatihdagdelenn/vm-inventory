// Lightweight i18n: Turkish is the template default; English comes from EN below.
// Static DOM: elements carry data-i18n / data-i18n-title / data-i18n-ph keys.
// Dynamic JS strings: use window.t('key', 'Turkish fallback').
// Switching language stores the choice and reloads (guarantees JS-built text updates too).
const I18N = {
  lang: (function () { try { return localStorage.getItem('vmi-lang') || 'tr'; } catch (e) { return 'tr'; } })(),
  EN: {
    // Navigation
    'nav.dashboard': 'Dashboard', 'nav.vms': 'Virtual Machines', 'nav.hosts': 'Hosts',
    'nav.datastores': 'Datastores', 'nav.snapshots': 'Snapshots', 'nav.backups': 'Backups',
    'nav.networks': 'Networks', 'nav.platforms': 'Platforms', 'nav.reports': 'Reports',
    'nav.history': 'Change History', 'nav.topology': 'Topology', 'nav.settings': 'Administration',
    // Shell
    'role.admin': 'Admin', 'role.operator': 'Operator', 'role.viewer': 'Viewer',
    'action.logout': 'Log out', 'action.syncAll': 'Sync All',
    'theme.toggle': 'Light / Dark theme', 'lang.toggle': 'Language / Dil', 'version.title': 'App version',
    // Shared modals
    'modal.vmDetail': 'VM Details', 'modal.vms': 'Virtual Machines', 'modal.hosts': 'Hosts',
    'th.vmName': 'VM Name', 'th.ip': 'IP Address', 'th.status': 'Status', 'th.cpu': 'CPU', 'th.ram': 'RAM',
    'hint.clickRowVm': 'Click a row to view VM details.',
  },
  t: function (key, tr) {
    if (I18N.lang === 'en') { const v = I18N.EN[key]; if (v !== undefined) return v; }
    return tr !== undefined ? tr : key;
  },
  apply: function (root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      if (el.dataset.i18nOrig === undefined) el.dataset.i18nOrig = el.textContent;
      el.textContent = I18N.lang === 'en'
        ? (I18N.EN[el.dataset.i18n] !== undefined ? I18N.EN[el.dataset.i18n] : el.dataset.i18nOrig)
        : el.dataset.i18nOrig;
    });
    root.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      if (el.dataset.i18nTitleOrig === undefined) el.dataset.i18nTitleOrig = el.getAttribute('title') || '';
      const v = I18N.lang === 'en' ? I18N.EN[el.dataset.i18nTitle] : el.dataset.i18nTitleOrig;
      if (v !== undefined) el.setAttribute('title', v);
    });
    root.querySelectorAll('[data-i18n-ph]').forEach(function (el) {
      if (el.dataset.i18nPhOrig === undefined) el.dataset.i18nPhOrig = el.getAttribute('placeholder') || '';
      const v = I18N.lang === 'en' ? I18N.EN[el.dataset.i18nPh] : el.dataset.i18nPhOrig;
      if (v !== undefined) el.setAttribute('placeholder', v);
    });
    document.documentElement.lang = I18N.lang;
    const lbl = document.getElementById('langLabel');
    if (lbl) lbl.textContent = I18N.lang.toUpperCase();
  },
  set: function (lang) {
    try { localStorage.setItem('vmi-lang', lang); } catch (e) {}
    location.reload();
  },
  toggle: function () { I18N.set(I18N.lang === 'en' ? 'tr' : 'en'); },
};
window.t = function (k, tr) { return I18N.t(k, tr); };
window.I18N = I18N;
I18N.apply();
document.addEventListener('DOMContentLoaded', function () {
  I18N.apply();
  const b = document.getElementById('btnLang');
  if (b) b.addEventListener('click', I18N.toggle);
});
