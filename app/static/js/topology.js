/**
 * topology.js — Infrastructure Topology Map (Cytoscape.js + fcose).
 *
 * MİMARİ
 *  - Canvas tabanlı render (Cytoscape) → 500+ düğümde SVG'nin aksine donmaz.
 *  - Compound (bounding box) hiyerarşi: Platform > Cluster ; Host'lar cluster
 *    kutusunda donut (CPU halkası) düğüm; VM'ler de aynı cluster kutusunda,
 *    host'a KENARLA bağlı (host donut'u korunur).
 *  - LAZY: VM'ler önden basılmaz; host'a tıklayınca /host/{id}/vms ile çekilir.
 *  - Katman filtreleri (Donanım/Depolama/Ağ) spaghetti efektini önler.
 *  - SSE (/stream) ile tam senkronizasyon sonrası canlı tazeleme + göç yansıması.
 */
const Topo = {
  cy: null,
  es: null,
  expanded: new Set(),        // VM'leri GÖRÜNÜR host id'leri ("h5")
  loaded: new Set(),          // VM'leri bir kez ÇEKİLMİŞ host id'leri (grafikte kalır)
  layerLoaded: { storage: new Set(), network: new Set() },  // host bazlı katman verisi yüklendi mi
  layers: { storage: false, network: false },
  flow: true,                 // hareketli kablolar
  _dash: 0, _flowTimer: null,
  _refreshTimer: null,
  _POS_KEY: 'topo_pos_v1',
  pos: {},                    // kayıtlı düğüm konumları {id:{x,y}}
  _saveT: null,

  /* ---------------- Tema-duyarlı renkler ---------------- */
  dark() { return !document.documentElement.classList.contains('theme-light'); },
  colors() {
    const d = this.dark();
    return {
      text: d ? '#e8eef7' : '#1f2a3a',
      boxText: d ? '#aab8cc' : '#475569',
      edge: d ? 'rgba(148,163,184,.45)' : 'rgba(100,116,139,.45)',
      hostTrack: d ? '#27384f' : '#e2e8f0',
      hostBorder: d ? '#3a4f6d' : '#cbd5e1',
      platBg: '#6366f1', clusterBg: '#0ea5e9',
    };
  },

  /* ---------------- SVG ikonlar (data URI) ---------------- */
  icon(kind, color) {
    const c = (color || '#2f81f7').replace('#', '%23');
    let svg;
    if (kind === 'server') {
      svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' " +
        "stroke='" + c + "' stroke-width='1.6' stroke-linecap='round'>" +
        "<rect x='3' y='3.5' width='18' height='7' rx='1.6'/>" +
        "<rect x='3' y='13.5' width='18' height='7' rx='1.6'/>" +
        "<circle cx='6.6' cy='7' r='0.9' fill='" + c + "' stroke='none'/>" +
        "<circle cx='6.6' cy='17' r='0.9' fill='" + c + "' stroke='none'/>" +
        "<line x1='15.5' y1='7' x2='18' y2='7'/><line x1='15.5' y1='17' x2='18' y2='17'/></svg>";
    } else if (kind === 'datastore') {
      svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' " +
        "stroke='" + c + "' stroke-width='1.6'>" +
        "<ellipse cx='12' cy='5.5' rx='7' ry='3'/>" +
        "<path d='M5 5.5v13c0 1.6 3.1 3 7 3s7-1.4 7-3v-13'/>" +
        "<path d='M5 12c0 1.6 3.1 3 7 3s7-1.4 7-3'/></svg>";
    }
    return "data:image/svg+xml;utf8," + svg.replace(/#/g, '%23');
  },

  buildStyle() {
    const c = this.colors();
    const d = this.dark();
    const hostBg = d ? '#13243a' : '#ffffff';
    const dsColor = '#f59e0b';
    return [
      // --- Compound: Platform (kök kutu) ---
      { selector: 'node[type="platform"]', style: {
          'shape': 'round-rectangle', 'background-color': c.platBg,
          'background-opacity': 0.06, 'border-width': 1.5,
          'border-color': c.platBg, 'border-opacity': 0.5,
          'label': 'data(label)', 'text-valign': 'top', 'text-halign': 'center',
          'font-size': 13, 'font-weight': 'bold', 'color': c.text,
          'text-margin-y': 4, 'padding': 18 } },
      // --- Compound: Cluster (kutu) ---
      { selector: 'node[type="cluster"]', style: {
          'shape': 'round-rectangle', 'background-color': c.clusterBg,
          'background-opacity': 0.07, 'border-width': 1, 'border-style': 'dashed',
          'border-color': c.clusterBg, 'border-opacity': 0.6,
          'label': 'data(label)', 'text-valign': 'top', 'text-halign': 'center',
          'font-size': 11, 'color': c.boxText, 'text-margin-y': 3, 'padding': 14 } },
      { selector: 'node[type="cluster"].collapsed', style: {
          'background-opacity': 0.16, 'label': 'data(clabel)' } },
      // --- Host: SUNUCU ikonu + CPU yüküne göre sınır rengi ---
      { selector: 'node[type="host"]', style: {
          'shape': 'round-rectangle', 'width': 46, 'height': 40,
          'background-color': hostBg, 'background-opacity': 1,
          'background-image': this.icon('server', c.text),
          'background-fit': 'none', 'background-width': '64%',
          'background-height': '64%', 'background-position-x': '50%',
          'background-position-y': '42%',
          'border-width': 3,
          'border-color': 'mapData(cpu_pct, 0, 100, #22c55e, #ef4444)',
          'label': 'data(hlabel)', 'text-wrap': 'wrap', 'text-max-width': 130,
          'text-valign': 'bottom', 'text-margin-y': 4,
          'font-size': 9.5, 'font-weight': 'bold', 'color': c.text } },
      { selector: 'node[type="host"][status="offline"]', style: {
          'border-color': '#ef4444', 'border-style': 'double' } },
      { selector: 'node[type="host"][status="maintenance"]', style: {
          'border-color': '#f59e0b' } },
      // --- VM: durum rengi ---
      { selector: 'node[type="vm"]', style: {
          'shape': 'round-rectangle', 'width': 'label', 'height': 16,
          'padding': '5px', 'background-color': '#94a3b8',
          'border-width': 1.5, 'border-color': '#64748b',
          'label': 'data(label)', 'font-size': 9, 'color': '#0b1220',
          'text-valign': 'center', 'text-halign': 'center',
          'text-max-width': 120, 'text-wrap': 'ellipsis' } },
      { selector: 'node[type="vm"][status="running"]', style: {
          'background-color': '#22c55e', 'border-color': '#16a34a' } },
      { selector: 'node[type="vm"][status="stopped"]', style: {
          'background-color': '#ef4444', 'border-color': '#dc2626', 'color': '#fff' } },
      { selector: 'node[type="vm"][status="suspended"]', style: {
          'background-color': '#f59e0b', 'border-color': '#d97706' } },
      // --- Datastore: silindir ikonu ---
      { selector: 'node[type="datastore"]', style: {
          'shape': 'round-rectangle', 'width': 40, 'height': 40,
          'background-color': d ? '#2a1f08' : '#fffaf0', 'background-opacity': 1,
          'background-image': this.icon('datastore', dsColor),
          'background-fit': 'none', 'background-width': '62%',
          'background-height': '62%', 'background-position-y': '40%',
          'border-width': 2, 'border-color': dsColor,
          'label': 'data(label)', 'font-size': 9, 'color': c.text,
          'text-valign': 'bottom', 'text-margin-y': 3, 'text-max-width': 90,
          'text-wrap': 'ellipsis' } },
      { selector: 'node[type="network"]', style: {
          'shape': 'diamond', 'background-color': '#14b8a6', 'width': 26, 'height': 26,
          'label': 'data(label)', 'font-size': 9, 'color': c.text,
          'text-valign': 'bottom', 'text-margin-y': 2 } },
      // --- Kenarlar ---
      { selector: 'edge', style: {
          'width': 1.4, 'line-color': c.edge, 'curve-style': 'bezier',
          'target-arrow-shape': 'none' } },
      // host → VM kablosu: erişim (agent) varsa yeşil, yoksa kırmızı; kesikli (akış)
      { selector: 'edge[etype="host-vm"]', style: {
          'width': 2, 'line-style': 'dashed', 'line-dash-pattern': [6, 4],
          'line-color': '#94a3b8', 'opacity': 0.9 } },
      { selector: 'edge[etype="host-vm"][access="ok"]', style: {
          'line-color': '#22c55e' } },
      { selector: 'edge[etype="host-vm"][access="no"]', style: {
          'line-color': '#ef4444' } },
      // sunucular arası ağ bağlantısı (cluster fabriği)
      { selector: 'edge[etype="host-link"]', style: {
          'width': 2.2, 'line-color': '#14b8a6', 'line-style': 'dashed',
          'line-dash-pattern': [8, 5], 'opacity': 0.6, 'curve-style': 'bezier' } },
      { selector: 'edge[etype="vm-datastore"]', style: {
          'line-color': '#f59e0b', 'line-style': 'dashed', 'opacity': 0.7 } },
      { selector: 'edge[etype="vm-network"]', style: {
          'line-color': '#14b8a6', 'line-style': 'dashed', 'opacity': 0.7 } },
      // --- Arama-odak ---
      { selector: '.faded', style: { 'opacity': 0.12, 'text-opacity': 0.12 } },
      { selector: '.highlight', style: {
          'border-width': 4, 'border-color': '#2f81f7',
          'shadow-blur': 18, 'shadow-color': '#2f81f7', 'shadow-opacity': 0.8 } },
      { selector: 'node.drop-target', style: {
          'border-width': 4, 'border-color': '#2f81f7', 'border-style': 'dashed' } },
    ];
  },

  /* ---------------- Düğüm dönüştürme (null güvenli) ---------------- */
  prep(nodes) {
    nodes.forEach(n => {
      const d = n.data;
      if (d.type === 'host') {
        d.cpu_pct = (d.cpu_pct == null ? 0 : d.cpu_pct);
        const ram = (d.ram_pct == null ? '—' : d.ram_pct + '%');
        const ipline = d.ip ? '\n' + d.ip : '';
        d.hlabel = d.label + ipline + '\nCPU ' + d.cpu_pct + '% · RAM ' + ram +
                   ' · ' + (d.vm_count || 0) + ' VM';
      } else if (d.type === 'cluster') {
        d.clabel = d.label + ' (gizli)';
      }
    });
    return nodes;
  },

  async init() {
    if (!window.cytoscape) { this.fatal('Cytoscape kütüphanesi yüklenemedi (CDN).'); return; }
    try { cytoscape.use(window.cytoscapeFcose || window.fcose); } catch (e) { /* fcose ops. */ }

    this.cy = cytoscape({
      container: document.getElementById('cy'),
      elements: [], style: this.buildStyle(),
      wheelSensitivity: 0.25, minZoom: 0.05, maxZoom: 3,
      boxSelectionEnabled: false,
    });

    this.pos = this.loadPos();
    this.bindEvents();
    await this.loadBase();
    this.connectSSE();
    this.startFlow();

    // Tema değişiminde stilleri yeniden uygula
    const themeBtn = document.getElementById('btnThemeGlobal');
    if (themeBtn) themeBtn.addEventListener('click',
      () => setTimeout(() => this.cy.style(this.buildStyle()), 60));
  },

  fatal(msg) {
    const l = document.getElementById('topoLoading');
    if (l) l.innerHTML = '<div class="text-danger"><i class="bi bi-exclamation-triangle"></i> ' +
      App.esc(msg) + '</div>';
  },

  /** Hareketli kablolar: görünür kenarların kesik desenini akıt. Performans için
   *  yalnız GÖRÜNÜR kenarlara uygulanır ve çok kenar varsa (>260) otomatik durur. */
  startFlow() {
    clearInterval(this._flowTimer);
    this._flowTimer = setInterval(() => {
      if (!this.flow) return;
      const vis = this.cy.edges(':visible');
      if (vis.length === 0 || vis.length > 260) return;   // perf koruması
      this._dash = (this._dash + 1) % 18;
      vis.style('line-dash-offset', -this._dash);          // tek toplu güncelleme
    }, 90);
  },

  async loadBase() {
    let data;
    try { data = await App.api('/api/topology'); }
    catch (e) { this.fatal('Topoloji verisi alınamadı.'); return; }
    this.cy.add({ nodes: this.prep(data.nodes), edges: data.edges });
    document.getElementById('topoLoading').classList.add('d-none');
    const s = data.stats || {};
    document.getElementById('topoStats').textContent =
      (s.platforms || 0) + ' platform · ' + (s.clusters || 0) + ' cluster · ' +
      (s.hosts || 0) + ' host';

    // Kayıtlı konumlar tüm host'ları kapsıyorsa onları uygula (düzen korunur);
    // değilse yalnız İLK açılışta otomatik yerleştir.
    const leafBase = this.cy.nodes('node[type="host"]');
    const haveAll = leafBase.length &&
      leafBase.toArray().every(n => this.pos[n.id()]);
    if (haveAll) {
      this.cy.nodes().forEach(n => { if (this.pos[n.id()]) n.position(this.pos[n.id()]); });
      this.cy.fit(null, 50);
    } else {
      this.runLayout(true);
    }
  },

  runLayout(fit) {
    const opts = {
      name: (window.cytoscapeFcose || window.fcose) ? 'fcose' : 'cose',
      animate: true, animationDuration: 500, randomize: false,
      fit: !!fit, padding: 40, nodeSeparation: 90,
      nodeRepulsion: 9000, idealEdgeLength: 70, gravityCompound: 1.2,
    };
    this.cy.one('layoutstop', () => this.savePos());
    this.cy.layout(opts).run();
  },

  /* ---------------- Konum kalıcılığı (manuel düzen sıfırlanmasın) ---------------- */
  loadPos() {
    try { return JSON.parse(localStorage.getItem(this._POS_KEY)) || {}; }
    catch (e) { return {}; }
  },
  savePos() {
    clearTimeout(this._saveT);
    this._saveT = setTimeout(() => {
      const m = {};
      this.cy.nodes().forEach(n => {
        if (n.isParent()) return;                  // compound kutular otomatik boyutlanır
        const p = n.position();
        m[n.id()] = { x: Math.round(p.x), y: Math.round(p.y) };
      });
      this.pos = m;
      try { localStorage.setItem(this._POS_KEY, JSON.stringify(m)); } catch (e) {}
    }, 400);
  },
  /** Yeni eklenen düğümleri host'un yanına yerleştir (global relayout YAPMADAN). */
  placeNear(host, eles) {
    const hp = host.position(); let k = 0;
    eles.forEach(n => {
      if (n.isParent()) return;
      if (this.pos[n.id()]) { n.position(this.pos[n.id()]); return; }
      const col = k % 5, row = Math.floor(k / 5);
      n.position({ x: hp.x - 92 + col * 46, y: hp.y + 58 + row * 26 });
      k++;
    });
  },

  bindEvents() {
    const cy = this.cy;
    // Host'a tıkla → VM'leri aç/kapat (lazy)
    cy.on('tap', 'node[type="host"]', (e) => this.toggleHost(e.target.id()));
    // Cluster'a tıkla → daralt/genişlet
    cy.on('tap', 'node[type="cluster"]', (e) => this.toggleCluster(e.target));
    // VM'e tıkla → mevcut ortak VM detay paneli
    cy.on('tap', 'node[type="vm"]', (e) => {
      const id = e.target.data('db_id'); if (id) App.vmDetail(id);
    });
    // Boşluğa tıkla → odak temizle
    cy.on('tap', (e) => { if (e.target === cy) this.clearFocus(); });
    // Göç simülasyonu: VM'i host üzerine sürükle-bırak
    cy.on('drag', 'node[type="vm"]', (e) => this.dragOver(e.target));
    cy.on('free', 'node[type="vm"]', (e) => this.dropVm(e.target));
    // Herhangi bir düğüm sürüklenip bırakıldığında konumu kalıcı kaydet
    cy.on('free', 'node', () => this.savePos());

    // Arama
    const inp = document.getElementById('topoSearch');
    inp.addEventListener('input', App.debounce(() => this.search(inp.value.trim()), 250));
    inp.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); this.pickFirst(); }
      if (ev.key === 'Escape') this.hideSuggest();
    });
    // Katman filtreleri (sil-yok modeli: konum korunur)
    document.getElementById('lyStorage').addEventListener('change', (ev) =>
      this.setLayer('storage', ev.target.checked));
    document.getElementById('lyNetwork').addEventListener('change', (ev) =>
      this.setLayer('network', ev.target.checked));
    const fl = document.getElementById('lyFlow');
    if (fl) fl.addEventListener('change', (ev) => {
      this.flow = ev.target.checked;
      if (!this.flow) this.cy.edges().style('line-dash-offset', 0);
    });
    // Eylem düğmeleri
    document.getElementById('topoFit').addEventListener('click', () => cy.fit(null, 50));
    document.getElementById('topoRelayout').addEventListener('click', () => this.runLayout(true));
    document.getElementById('topoExpandAll').addEventListener('click', () => this.expandAll());
    document.getElementById('topoCollapseAll').addEventListener('click', () => this.collapseAll());
  },

  layerParam() {
    const l = [];
    if (this.layers.storage) l.push('storage');
    if (this.layers.network) l.push('network');
    return l.join(',');
  },

  /* ---------------- Host VM aç/kapat (lazy + gizle, SİLME) ----------------
     VM'ler bir kez çekilip grafikte KALIR; aç/kapa yalnız GÖRÜNÜRLÜK değiştirir.
     Böylece elle ayarlanan konumlar kapatıp açınca KORUNUR. */
  async toggleHost(hid) {
    if (this.expanded.has(hid)) {            // açıksa → gizle (silme!)
      this.expanded.delete(hid);
      this.applyVisibility();
      return;
    }
    if (!this.loaded.has(hid)) {             // ilk kez → çek + ekle + yerleştir
      const host = this.cy.getElementById(hid);
      host.addClass('loading');
      let data;
      try {
        data = await App.api('/api/topology/host/' + host.data('db_id') +
                             '/vms?layers=' + encodeURIComponent(this.layerParam()));
      } catch (e) { host.removeClass('loading'); return; }
      host.removeClass('loading');
      const existing = new Set(this.cy.nodes().map(n => n.id()));
      const nodes = data.nodes.filter(n => !existing.has(n.data.id));   // datastore/net tekil
      const added = this.cy.add({ nodes: this.prep(nodes), edges: data.edges });
      this.placeNear(host, added.nodes());   // host yanına yerleştir (relayout YOK)
      this.loaded.add(hid);
      if (this.layers.storage) this.layerLoaded.storage.add(hid);   // bu çekimde geldi
      if (this.layers.network) this.layerLoaded.network.add(hid);
      this.savePos();
    }
    this.expanded.add(hid);                  // göster (konumlar zaten kayıtlı)
    this.applyVisibility();
  },

  /** Görünürlüğü uygula. Düğümler SİLİNMEZ; sadece display değişir → konum korunur.
   *  - VM: host'u expanded ise görünür.
   *  - datastore/network: ilgili KATMAN açık VE görünür bir VM'e bağlıysa görünür. */
  applyVisibility() {
    this.cy.nodes('node[type="vm"]').forEach(v =>
      v.style('display', this.expanded.has(v.data('host')) ? 'element' : 'none'));
    const showLayer = { datastore: this.layers.storage, network: this.layers.network };
    this.cy.nodes('node[type="datastore"], node[type="network"]').forEach(n => {
      if (!showLayer[n.data('type')]) { n.style('display', 'none'); return; }
      const anyVis = n.connectedEdges().some(e => {
        const o = e.source().same(n) ? e.target() : e.source();
        return o.data('type') === 'vm' && o.style('display') !== 'none';
      });
      n.style('display', anyVis ? 'element' : 'none');
    });
  },

  /** Katman aç/kapat: düğümleri SİLMEZ (konum korunur), sadece görünürlük; açılınca
   *  o katman verisi henüz çekilmemiş yüklü host'lar için lazy çeker. */
  async setLayer(layer, on) {
    this.layers[layer] = on;
    if (on) {
      for (const hid of this.loaded) {
        if (this.layerLoaded[layer].has(hid)) continue;
        const host = this.cy.getElementById(hid);
        if (host.empty()) continue;
        let data;
        try {
          data = await App.api('/api/topology/host/' + host.data('db_id') +
                               '/vms?layers=' + layer);
        } catch (e) { continue; }
        const ntype = (layer === 'storage') ? 'datastore' : 'network';
        const etype = (layer === 'storage') ? 'vm-datastore' : 'vm-network';
        const existing = new Set(this.cy.nodes().map(n => n.id()));
        const newNodes = data.nodes.filter(n => n.data.type === ntype &&
                                                !existing.has(n.data.id));
        const newEdges = data.edges.filter(e => e.data.etype === etype &&
                                                this.cy.getElementById(e.data.id).empty());
        const added = this.cy.add({ nodes: this.prep(newNodes), edges: newEdges });
        this.placeNear(host, added.nodes());
        this.layerLoaded[layer].add(hid);
      }
    }
    this.applyVisibility();
    this.savePos();
  },

  async expandAll() {
    const hosts = this.cy.nodes('node[type="host"]').map(n => n.id());
    for (const hid of hosts) {
      if (this.loaded.has(hid)) { this.expanded.add(hid); continue; }
      await this.toggleHost(hid);            // çeker + açar
    }
    this.applyVisibility();
  },
  collapseAll() {
    this.expanded.clear();
    this.applyVisibility();
  },

  /* ---------------- Cluster daralt/genişlet ---------------- */
  toggleCluster(cl) {
    const desc = cl.descendants();
    if (cl.hasClass('collapsed')) {
      cl.removeClass('collapsed'); desc.style('display', 'element');
    } else {
      cl.addClass('collapsed'); desc.style('display', 'none');
    }
    this.savePos();
  },

  /* ---------------- Arama & Odaklanma ---------------- */
  async search(q) {
    if (!q) { this.hideSuggest(); return; }
    let res;
    try { res = await App.api('/api/topology/locate?q=' + encodeURIComponent(q)); }
    catch (e) { return; }
    this._matches = res.matches || [];
    const box = document.getElementById('topoSuggest');
    if (!this._matches.length) {
      box.innerHTML = '<div class="topo-sg-empty">Eşleşme yok</div>';
      box.classList.remove('d-none'); return;
    }
    box.innerHTML = this._matches.slice(0, 10).map((m, i) =>
      '<div class="topo-sg" onclick="Topo.focusMatch(' + i + ')">' +
      '<i class="bi bi-pc-display"></i> ' + App.esc(m.vm_name) +
      '<span class="text-muted small"> · ' + App.esc(m.host_node) + '</span></div>').join('');
    box.classList.remove('d-none');
  },
  hideSuggest() { document.getElementById('topoSuggest').classList.add('d-none'); },
  pickFirst() { if (this._matches && this._matches.length) this.focusMatch(0); },

  async focusMatch(i) {
    const m = this._matches[i]; if (!m) return;
    this.hideSuggest();
    document.getElementById('topoSearch').value = m.vm_name;
    // Hedef VM'in host'unu (gerekirse) aç
    if (!this.expanded.has(m.host_node)) await this.toggleHost(m.host_node);
    const vm = this.cy.getElementById(m.vm_node);
    if (!vm || vm.empty()) return;
    // Yolu vurgula, gerisini soluklaştır
    const keep = vm.union(vm.connectedEdges()).union(vm.ancestors())
                   .union(this.cy.getElementById(m.host_node));
    this.cy.elements().addClass('faded');
    keep.removeClass('faded');
    vm.addClass('highlight');
    this.cy.animate({ fit: { eles: vm.union(this.cy.getElementById(m.host_node)), padding: 120 } },
                    { duration: 600 });
    setTimeout(() => vm.removeClass('highlight'), 2500);
  },
  clearFocus() {
    this.cy.elements().removeClass('faded'); this.cy.elements().removeClass('highlight');
    this.hideSuggest();
  },

  /* ---------------- Göç simülasyonu (sürükle-bırak) ---------------- */
  dragOver(vm) {
    const host = this.hostUnder(vm);
    this.cy.nodes('.drop-target').removeClass('drop-target');
    if (host && host.id() !== vm.data('host')) host.addClass('drop-target');
  },
  dropVm(vm) {
    const host = this.hostUnder(vm);
    this.cy.nodes('.drop-target').removeClass('drop-target');
    if (!host || host.id() === vm.data('host')) { return; }   // sadece yerinde kaldı
    // GERÇEK migrate ÇAĞRILMAZ — yalnız simülasyon/ön-tasarım. Görsel olarak
    // kenarı yeni host'a bağla; backend tetikleme burada eklenecek (gelecek).
    const fromName = this.cy.getElementById(vm.data('host')).data('label');
    vm.connectedEdges('[etype="host-vm"]').remove();
    this.cy.add({ group: 'edges', data: {
      id: 'e_' + host.id() + '_' + vm.id(), source: host.id(), target: vm.id(),
      etype: 'host-vm' } });
    vm.move({ parent: host.data('parent') });
    vm.data('host', host.id());
    App.toast('Göç simülasyonu: ' + vm.data('label') + ' → ' + host.data('label') +
              ' (gerçek migrate gelecek sürümde; ' + fromName + '’tan taşındı)');
    this.savePos();
  },
  hostUnder(vm) {   // VM merkezinin üzerine geldiği host düğümü
    const p = vm.position();
    let hit = null;
    this.cy.nodes('node[type="host"]').forEach(h => {
      const b = h.boundingBox();
      if (p.x >= b.x1 && p.x <= b.x2 && p.y >= b.y1 && p.y <= b.y2) hit = h;
    });
    return hit;
  },

  /* ---------------- Canlı akış (SSE) ---------------- */
  connectSSE() {
    if (!window.EventSource) return;
    const live = document.getElementById('topoLive');
    const setLive = (ok, txt) => {
      live.className = 'topo-live small ' + (ok ? 'on' : 'off');
      live.querySelector('span').textContent = txt;
    };
    try { this.es = new EventSource('/api/topology/stream'); }
    catch (e) { setLive(false, 'canlı yok'); return; }
    this.es.onopen = () => setLive(true, 'canlı');
    this.es.onerror = () => setLive(false, 'yeniden bağlanıyor…');
    this.es.addEventListener('sync', () => {
      clearTimeout(this._refreshTimer);
      this._refreshTimer = setTimeout(() => this.softRefresh(), 800);
    });
  },

  /** Tam senkronizasyon sonrası: host doluluk/sayılarını tazele; açık host'ların
   *  VM üyeliğini KONUMLARI BOZMADAN uzlaştır (yeni VM eklenir, gideni silinir,
   *  durum güncellenir). Mevcut VM'ler yerinde kalır. */
  async softRefresh() {
    let data;
    try { data = await App.api('/api/topology'); } catch (e) { return; }
    data.nodes.forEach(n => {
      if (n.data.type !== 'host') return;
      const el = this.cy.getElementById(n.data.id);
      if (el && !el.empty()) {
        el.data('cpu_pct', n.data.cpu_pct == null ? 0 : n.data.cpu_pct);
        el.data('ram_pct', n.data.ram_pct);
        el.data('vm_count', n.data.vm_count);
        const ram = (n.data.ram_pct == null ? '—' : n.data.ram_pct + '%');
        const ipline = el.data('ip') ? '\n' + el.data('ip') : '';
        el.data('hlabel', n.data.label + ipline + '\nCPU ' + el.data('cpu_pct') + '% · RAM ' +
                          ram + ' · ' + (n.data.vm_count || 0) + ' VM');
      }
    });
    // Yalnız GÖRÜNÜR host'ları uzlaştır (konumlar korunur)
    for (const hid of [...this.expanded]) {
      const host = this.cy.getElementById(hid);
      if (host.empty()) continue;
      let hd;
      try {
        hd = await App.api('/api/topology/host/' + host.data('db_id') +
                           '/vms?layers=' + encodeURIComponent(this.layerParam()));
      } catch (e) { continue; }
      const incoming = new Set(hd.nodes.filter(n => n.data.type === 'vm').map(n => n.data.id));
      // giden VM'leri sil
      this.cy.nodes('node[type="vm"][host="' + hid + '"]').forEach(v => {
        if (!incoming.has(v.id())) v.remove();
      });
      // yeni düğümleri ekle + durum güncelle
      const existing = new Set(this.cy.nodes().map(n => n.id()));
      const newNodes = hd.nodes.filter(n => !existing.has(n.data.id));
      const newEdges = hd.edges.filter(e => this.cy.getElementById(e.data.id).empty());
      const added = this.cy.add({ nodes: this.prep(newNodes), edges: newEdges });
      this.placeNear(host, added.nodes());
      hd.nodes.forEach(n => {
        const el = this.cy.getElementById(n.data.id);
        if (el.nonempty() && n.data.status) el.data('status', n.data.status);
      });
    }
    this.applyVisibility();
    this.savePos();
  },
};

document.addEventListener('DOMContentLoaded', () => Topo.init());
