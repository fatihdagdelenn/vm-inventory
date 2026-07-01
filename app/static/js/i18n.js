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
    // Common
    'common.loading': 'Loading…', 'common.all': 'All', 'common.never': 'never',
    'th.date': 'Date', 'th.object': 'Object', 'th.change': 'Change', 'th.field': 'Field',
    'th.platform': 'Platform', 'th.type': 'Type', 'th.lastSync': 'Last Sync',
    // Dashboard shell
    'dash.live': 'Live', 'dash.hiddenCards': 'Hidden Cards', 'dash.noHidden': 'No hidden cards',
    'dash.reset': 'Reset', 'dash.edit': 'Edit Dashboard', 'dash.done': 'Done',
    'dash.host': 'Host', 'dash.totalVm': 'Total VMs', 'dash.runningVm': 'Running VMs',
    'dash.stoppedVm': 'Stopped VMs', 'dash.totalVcpu': 'Total vCPU', 'dash.allocRam': 'Allocated RAM',
    'dash.allocDisk': 'Allocated Disk', 'dash.suspendedVm': 'Suspended VMs',
    'dash.forecast': 'Capacity Forecast', 'dash.zombie': 'Zombie (Idle) VMs', 'dash.attention': 'Needs Attention',
    'dash.at.noip': 'VMs without an IP address', 'dash.at.notools': 'No Agent / Tools installed',
    'dash.at.noowner': 'VMs without an owner', 'dash.at.oldsnap': 'Snapshots older than 30 days',
    'dash.at.nobackup': 'VMs without a backup',
    'dash.envDist': 'Environment Distribution', 'dash.osFamily': 'Operating System Family',
    'dash.topCpu': 'Top CPU-Using VMs', 'dash.topRam': 'Top RAM-Using VMs', 'dash.topDisk': 'Top Disk-Using VMs',
    'dash.vmByCluster': 'VM Distribution by Cluster', 'dash.manage': 'Manage',
    'dash.topOs': 'Most Used Operating Systems', 'dash.hostCpu': 'Host CPU Usage (%)',
    'dash.hostRam': 'Host RAM Usage (%)', 'dash.vmByHost': 'VM Distribution by Host',
    'dash.clusterRes': 'Resources by Cluster (vCPU / RAM)', 'dash.datastoreUsage': 'Datastore Usage (%)',
    'dash.recentChanges': 'Recent Inventory Changes', 'dash.platformStatus': 'Platform Connection Status',
    'dash.clusterVisibility': 'Cluster Visibility',
    'dash.clusterVisibilityDesc': 'Clusters you turn off are excluded from dashboard counts and charts and hidden by default in the VM list. No data is deleted — turning the switch back on restores everything.',
    'dash.usagePrefix': 'usage: ', 'dash.usageWaiting': 'usage: waiting for first sync',
    'dash.clustersHidden': 'clusters hidden', 'dash.noChanges': 'No change records yet.',
    'dash.noPlatforms': 'No platforms added yet.', 'dash.addFromPage': 'page to add one.',
    'dash.newPageName': 'New page name:', 'dash.pageName': 'Page name:', 'dash.pageWord': 'Page',
    'dash.deletePageConfirm': 'Delete this page? Its cards move to the first page.',
    'dash.resetConfirm': 'Reset the entire dashboard layout (including pages)?',
    'dash.rename': 'Rename', 'dash.deletePageT': 'Delete page', 'dash.addPageT': 'Add page',
    'dash.every': 'every', 'dash.last': 'last',
    // Change types / status badges
    'ct.created': 'Added', 'ct.updated': 'Updated', 'ct.deleted': 'Deleted',
    'ct.migrated': 'Migrated', 'ct.access': 'Access',
    'st.none': 'Not yet', 'st.success': 'Success', 'st.error': 'Error',
    // Forecast
    'fc.healthy': 'Healthy', 'fc.warn': 'Approaching', 'fc.crit': 'Critical', 'fc.stable': 'Stable',
    'fc.collecting': 'Collecting data', 'fc.none': 'Insufficient data',
    'fc.dayTrend': '-day real trend', 'fc.collectingShort': 'collecting data',
    'fc.collectingTrend': 'Collecting data for the usage trend.', 'fc.full': 'Capacity full/exceeded.',
    'fc.atCurrent': 'At current', 'fc.usage': 'Usage', 'fc.rate': 'rate,', 'fc.mayFill': 'it may fill up',
    'fc.negligible': 'Usage growth is negligible — stable.',
    'fc.overcommitHint': 'VMs are given more', 'fc.overcommitHint2': 'than physical — normal in virtualization',
    'fc.alloc': 'Allocation', 'fc.diskTitle': 'Disk (Datastore)', 'fc.ramTitle': 'RAM (Physical)',
    // Zombie
    'zb.none1': 'No zombie/suspect VMs in the multi-metric analysis (CPU+RAM+Disk+Net).',
    'zb.none2': 'No idle running VMs. (Based on the latest sample)',
    'zb.recoverable': 'Recoverable', 'zb.score': 'Score', 'zb.class': 'Class', 'zb.confidence': 'confidence',
    // Units
    'unit.year': 'yr', 'unit.month': 'mo', 'unit.day': 'days', 'unit.min': 'min',
    // Widget tools
    'wt.move': 'Move (drag)', 'wt.page': 'Move to page', 'wt.width': 'Quick width change',
    'wt.hide': 'Hide card', 'wt.resize': 'Resize (drag: right/down)',
    // Cluster modal
    'cl.noData': 'No cluster data yet — sync a platform first.', 'cl.noCluster': '(No cluster)',
    'cl.notInInv': 'not in inventory', 'cl.visible': 'Visible', 'cl.hidden': 'Hidden',
    'cl.madeVisible': 'made visible', 'cl.hiddenDone': 'hidden', 'cl.updating': 'updating',
    // Hidden-cards menu (card titles)
    'dashtitle.stat-vcenter': 'vCenter count', 'dashtitle.stat-proxmox': 'Proxmox count',
    'dashtitle.stat-host': 'Host count', 'dashtitle.stat-vm': 'Total VMs (trend)',
    'dashtitle.stat-running': 'Running VMs', 'dashtitle.stat-stopped': 'Stopped VMs',
    'dashtitle.mini-vcpu': 'Total vCPU', 'dashtitle.mini-ram': 'Allocated RAM',
    'dashtitle.mini-disk': 'Allocated Disk', 'dashtitle.mini-suspended': 'Suspended VMs',
    'dashtitle.forecast': 'Capacity Forecast', 'dashtitle.zombie': 'Zombie (Idle) VMs',
    'dashtitle.attention': 'Needs Attention', 'dashtitle.chartEnv': 'Environment Distribution',
    'dashtitle.chartOs': 'OS Family', 'dashtitle.chartTopCpu': 'Top CPU VMs',
    'dashtitle.chartTopRam': 'Top RAM VMs', 'dashtitle.chartTopDisk': 'Top Disk VMs',
    'dashtitle.chartCluster': 'VMs by Cluster', 'dashtitle.chartTopOs': 'Most Used OS',
    'dashtitle.chartCpu': 'Host CPU Usage', 'dashtitle.chartRam': 'Host RAM Usage',
    'dashtitle.chartHostVm': 'VMs by Host', 'dashtitle.chartClusterRes': 'Resources by Cluster',
    'dashtitle.chartDatastore': 'Datastore Usage', 'dashtitle.recentChanges': 'Recent Inventory Changes',
    'dashtitle.platformStatus': 'Platform Connection Status',
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
