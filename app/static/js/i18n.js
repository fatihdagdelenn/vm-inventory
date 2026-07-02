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
    // VMs page
    'vm.searchPh': 'Search…  e.g.: ip:10.10.10.15  os:linux  ram:>=16  -cluster:test  status:running',
    'vm.searchHelp': 'Search syntax', 'vm.clear': 'Clear', 'vm.quickFilters': 'Quick filters:',
    'vm.chipRunning': 'Running', 'vm.chipStopped': 'Stopped', 'vm.chipNoIp': 'No IP', 'vm.chipNoAgent': 'No Agent',
    'vm.advanced': 'Advanced', 'vm.groupBy': 'Group by:', 'vm.noGrouping': '— No grouping —',
    'vm.byCluster': 'By cluster', 'vm.byOs': 'By operating system', 'vm.byVlan': 'By VLAN',
    'vm.byEnv': 'By environment', 'vm.byLocation': 'By location', 'vm.byTag': 'By tag',
    'vm.chooseCols': 'Choose visible columns', 'vm.columns': 'Columns',
    'vm.env': 'Environment', 'vm.os': 'Operating System', 'vm.tag': 'Tag', 'vm.folder': 'Folder',
    'vm.allOption': '— All —', 'vm.notInstalled': 'Not installed', 'vm.eg4': 'e.g.: 4', 'vm.eg16': 'e.g.: 16',
    'vm.includeHidden': 'Include hidden clusters', 'vm.clearFilters': 'Clear Filters',
    'vm.searchSyntax': 'Search Syntax', 'vm.example': 'Example', 'vm.description': 'Description',
    'vm.h.free': 'Free text: searches name, IP, MAC, OS, cluster, owner and notes',
    'vm.h.ip': 'By IP address (partial match:', 'vm.h.os': 'OS family: finds Ubuntu, CentOS, RHEL, Debian…',
    'vm.h.or': 'Comma = OR: Windows or Linux', 'vm.h.not': 'Exclusion: those that are NOT Windows',
    'vm.h.num': 'Numeric comparison (RAM and disk in GB)',
    'vm.h.status': 'Power state: running / stopped / suspended',
    'vm.h.empty': 'Empty-field search — VMs without IP, without tags…',
    'vm.h.tools': 'VMs without VMware Tools / QEMU Agent',
    'vm.h.infra': 'By infrastructure location', 'vm.h.platform': 'By platform name (use quotes if it has spaces)',
    'vm.h.ptype': 'By platform type / location', 'vm.h.tagenv': 'Tag, environment, datastore',
    'vm.h.and': 'Criteria are combined with spaces (AND logic):',
    'vm.ipAddresses': 'IP Addresses',
    'vm.inUse': 'in use', 'vm.instantUsage': 'instant usage %',
    'vm.groupHint': 'Click a group to filter the VM list.', 'vm.groups': 'groups',
    'vm.noResults': 'No results found.', 'vm.page': 'page',
    'vm.filterByHost': 'Filter by this host', 'vm.filterByCluster': 'Filter by this cluster',
    'vm.filterByPool': 'Filter by this pool', 'vm.filterByFolder': 'Filter by this folder',
    'vm.filterByVlan': 'Filter by this VLAN', 'vm.hiddenMark': 'hidden',
    'vm.activeFilters': 'Active:', 'vm.clearAll': 'clear all', 'vm.remove': 'Remove',
    'st.running': 'Running', 'st.stopped': 'Stopped', 'st.suspended': 'Suspended',
    'ag.active': 'Active', 'ag.passive': 'Passive', 'ag.none': 'None',
    'st.maintenance': 'Maintenance', 'st.unknown': 'Unknown',
    // Hosts page
    'hs.searchPh': 'Search host name, IP, cluster or CPU model…',
    'hs.name': 'Host Name', 'hs.mgmtIp': 'Mgmt IP', 'hs.cpuModel': 'CPU Model', 'hs.cores': 'Cores',
    'hs.runningOpen': 'running — open VM list', 'hs.coresLower': 'cores',
    // Datastores page
    'ds.searchPh': 'Search datastore name, type, node or platform…',
    'ds.capacity': 'Capacity', 'ds.usage': 'Usage',
    'ds.shared': 'shared', 'ds.sharedHint': 'Shared by multiple hosts/nodes',
    'ds.viewDetails': 'View details',
    // History page
    'hi.searchPh': 'Search VM/host…  prefix with - or ! to exclude',
    'hi.searchHint': 'You can type multiple words. Records CONTAINING a word prefixed with - or ! are hidden (e.g. -backup to exclude a noisy backup machine).',
    'hi.allEntities': 'All Entities', 'hi.allCats': 'All Categories',
    'hi.cat.hardware': 'Hardware (vCPU/RAM)', 'hi.cat.disk': 'Disk & Storage', 'hi.cat.network': 'Network',
    'hi.cat.power': 'Power', 'hi.cat.migrate': 'Migration', 'hi.cat.lifecycle': 'Lifecycle',
    'hi.cat.console': 'Console Access',
    'hi.source': 'Source', 'hi.entity': 'Entity', 'hi.category': 'Category',
    'hi.operation': 'Operation', 'hi.fieldValue': 'Field / Value', 'hi.user': 'User',
    'hi.footnote': 'The "User" comes from the platform\'s own task/event log (not the app user). Rows recorded before the fix may keep "\u2014"; vCenter and Proxmox task logs usually do not provide client IP/User-Agent.',
    'hi.f.ram': 'Memory (RAM)', 'hi.f.disk': 'Disk Size', 'hi.f.ds': 'Storage (Datastore)',
    'hi.f.vlan': 'VLAN / Network', 'hi.f.name': 'Name', 'hi.f.net': 'Network (Bridge/Portgroup)',
    'hi.f.power': 'Power State', 'hi.f.host': 'Host (Migration)',
    'hi.c.hardware': 'Hardware', 'hi.c.network': 'Network', 'hi.c.power': 'Power',
    'hi.c.lifecycle': 'Lifecycle', 'hi.c.console': 'Console', 'hi.c.other': 'Other',
    'hi.consoleAccess': 'Console access', 'hi.window30': '30 min window',
    'hi.records': 'records', 'hi.noRecords': 'No records found.',
    // Topology page
    'tp.searchPh': 'Search VM name \u2192 locate and focus on the map\u2026',
    'tp.expandAllT': 'Expand all hosts\' VMs', 'tp.expandAll': 'Expand All',
    'tp.collapseT': 'Hide all VMs', 'tp.collapse': 'Collapse',
    'tp.fit': 'Fit map to screen', 'tp.relayout': 'Re-layout', 'tp.liveT': 'Live connection status',
    'tp.connecting': 'connecting\u2026', 'tp.viewFilters': 'View Filters',
    'tp.hw': 'Hardware Hierarchy', 'tp.storage': 'Storage Relations', 'tp.net': 'Network Relations',
    'tp.flow': 'Animated cables', 'tp.lazyHint': 'VMs load when you click a host (lazy).',
    'tp.legend': 'Legend', 'tp.lgHost': 'Host (server, border=CPU load)',
    'tp.lgHostNet': 'Inter-server network', 'tp.lgVmOk': 'VM reachable (agent)',
    'tp.lgVmBad': 'VM unreachable', 'tp.lgVmRun': 'VM running', 'tp.lgVmStop': 'VM stopped',
    'tp.lgVmSusp': 'VM suspended', 'tp.loading': 'Loading topology\u2026',
    'tp.cdnFail': 'Cytoscape library failed to load (CDN).', 'tp.dataFail': 'Failed to fetch topology data.',
    'tp.noMatch': 'No match', 'tp.migSim': 'Migration simulation',
    'tp.migNote': 'real migrate in a future release',
    'tp.liveNo': 'no live feed', 'tp.liveOn': 'live', 'tp.reconnecting': 'reconnecting\u2026',
    'unit.dayShort': 'd', 'unit.hr': 'h',
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
