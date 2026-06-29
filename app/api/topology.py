"""
Topoloji (Infrastructure Topology Map) API'si.

Cytoscape.js'in beklediği {nodes:[{data:{...}}], edges:[{data:{...}}]} biçiminde
veri üretir. Performans için KADEMELİ (lazy) yapı:

  GET /api/topology
      → Platform (kök) → Cluster (compound/bounding box) → Host (donut düğüm).
        VM'LER DAHİL DEĞİL (500+ VM'i önden basmamak için). Her host'ta vm_count.

  GET /api/topology/host/{host_id}/vms?layers=storage,network
      → O host'un VM düğümleri + host→VM kenarları (kullanıcı host'a tıklayınca).
        layers=storage → datastore düğümleri + VM→datastore kenarları
        layers=network → VLAN düğümleri + VM→VLAN kenarları
        (Spaghetti efektini önlemek için katmanlar isteğe bağlı.)

  GET /api/topology/stream  (SSE)
      → Tam senkronizasyon bittiğinde "sync" olayı yayınlar; istemci haritayı
        yumuşakça tazeler / göç (migrate) animasyonunu tetikler.

Tüm veriler LOKAL DB'den gelir; canlı API çağrısı yapılmaz (hızlı erişim).
"""
import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Platform, Host, VirtualMachine, Datastore
from ..core.security import get_current_user
from ..core import events
from .clusters import hidden_cluster_names
from .vms import _agent_state

router = APIRouter(prefix="/api/topology", tags=["topology"])

_NO_CLUSTER = "(bağımsız)"


def _host_node(h: Host, vm_count: int, cluster_id: str) -> dict:
    ram_pct = (round(100 * (h.ram_used_mb or 0) / h.ram_total_mb)
               if h.ram_total_mb else None)
    return {"data": {
        "id": f"h{h.id}", "label": h.name or f"host-{h.id}",
        "type": "host", "parent": cluster_id, "db_id": h.id,
        "status": h.status or "unknown",
        "cpu_pct": round(h.cpu_usage_pct) if h.cpu_usage_pct is not None else None,
        "ram_pct": ram_pct,
        "vm_count": vm_count,
        "cpu_cores": h.cpu_cores, "ram_total_mb": h.ram_total_mb,
        "ip": h.mgmt_ip or "",
        "cluster": h.cluster or _NO_CLUSTER,
    }}


@router.get("")
def topology(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Platform → Cluster → Host hiyerarşisi (VM'ler lazy; burada yok)."""
    hidden = set(hidden_cluster_names(db))
    nodes, edges = [], []

    platforms = {p.id: p for p in db.query(Platform).all()}
    for p in platforms.values():
        nodes.append({"data": {
            "id": f"p{p.id}", "label": p.name, "type": "platform",
            "ptype": p.type or "", "collapsed": False}})

    # host başına VM sayısı (tek sorgu)
    vm_counts = dict(
        db.query(VirtualMachine.host_id, func.count(VirtualMachine.id))
          .filter(VirtualMachine.is_template == False)              # noqa: E712
          .group_by(VirtualMachine.host_id).all())

    seen_clusters = set()
    cluster_hosts = {}          # cid -> [host node id, ...]  (sunucular arası ağ için)
    host_total = 0
    for h in db.query(Host).all():
        if h.platform_id not in platforms:
            continue
        cl = h.cluster or _NO_CLUSTER
        if cl in hidden:
            continue
        cid = f"c{h.platform_id}_{cl}"
        if cid not in seen_clusters:
            nodes.append({"data": {
                "id": cid, "label": cl, "type": "cluster",
                "parent": f"p{h.platform_id}"}})
            seen_clusters.add(cid)
        nodes.append(_host_node(h, vm_counts.get(h.id, 0), cid))
        cluster_hosts.setdefault(cid, []).append(f"h{h.id}")
        host_total += 1

    # Sunucular arası ağ bağlantıları: aynı cluster'daki host'ları halka oluştur
    # (tam mesh yerine N kenar → spaghetti olmaz; 2 host'ta tek kenar, 1'de yok).
    for cid, hids in cluster_hosts.items():
        n = len(hids)
        if n < 2:
            continue
        for i in range(n if n > 2 else 1):
            a, b = hids[i], hids[(i + 1) % n]
            edges.append({"data": {
                "id": f"hl_{a}_{b}", "source": a, "target": b,
                "etype": "host-link"}})

    return {"nodes": nodes, "edges": edges,
            "stats": {"platforms": len(platforms),
                      "clusters": len(seen_clusters), "hosts": host_total}}


@router.get("/host/{host_id}/vms")
def host_vms(host_id: int, layers: str = "",
             db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Bir host'un VM düğümleri + kenarları (lazy expand). İsteğe bağlı katmanlar."""
    h = db.query(Host).filter_by(id=host_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Host bulunamadı")
    want = set(s.strip() for s in (layers or "").split(",") if s.strip())
    hid = f"h{host_id}"
    cl = h.cluster or _NO_CLUSTER
    cid = f"c{h.platform_id}_{cl}"           # VM'ler host ile aynı cluster kutusunda
    ptype = (db.query(Platform.type).filter_by(id=h.platform_id).scalar() or "")
    nodes, edges = [], []
    ds_seen, net_seen = set(), set()

    vms = (db.query(VirtualMachine)
             .filter(VirtualMachine.host_id == host_id,
                     VirtualMachine.is_template == False)            # noqa: E712
             .all())
    for v in vms:
        vid = f"v{v.id}"
        ip = (v.ip_addresses or "").split(",")[0].strip()
        agent = _agent_state(v.tools_status, ptype)       # running | stopped | none
        access = "ok" if agent == "running" else "no"     # erişim: yeşil/kırmızı kablo
        nodes.append({"data": {
            "id": vid, "label": v.name or f"vm-{v.id}", "type": "vm",
            "parent": cid, "host": hid, "db_id": v.id,
            "status": v.power_state or "unknown",
            "cpu_count": v.cpu_count, "ram_mb": v.ram_mb,
            "ip": ip, "agent": agent}})
        edges.append({"data": {
            "id": f"e_{hid}_{vid}", "source": hid, "target": vid,
            "etype": "host-vm", "access": access}})

        if "storage" in want and v.datastore:
            for ds in (t.strip() for t in v.datastore.split(",") if t.strip()):
                dsid = f"ds{h.platform_id}_{ds}"
                if dsid not in ds_seen:
                    nodes.append({"data": {"id": dsid, "label": ds,
                                           "type": "datastore"}})
                    ds_seen.add(dsid)
                edges.append({"data": {"id": f"e_{vid}_{dsid}", "source": vid,
                                       "target": dsid, "etype": "vm-datastore"}})

        if "network" in want and v.vlans:
            for vl in (t.strip() for t in v.vlans.split(",") if t.strip()):
                nid = f"net{h.platform_id}_{vl}"
                if nid not in net_seen:
                    nodes.append({"data": {"id": nid, "label": f"VLAN {vl}",
                                           "type": "network"}})
                    net_seen.add(nid)
                edges.append({"data": {"id": f"e_{vid}_{nid}", "source": vid,
                                       "target": nid, "etype": "vm-network"}})

    return {"nodes": nodes, "edges": edges, "host": hid, "vm_count": len(vms)}


@router.get("/locate")
def locate(q: str = "", db: Session = Depends(get_db),
           user=Depends(get_current_user)):
    """Ada göre VM ara → arama-odaklanma için host/cluster yolunu döndür.

    İstemci bu bilgiyle ilgili host'u (gerekirse lazy) açıp VM düğümüne zoom yapar.
    """
    q = (q or "").strip()
    if not q:
        return {"matches": []}
    rows = (db.query(VirtualMachine, Host.cluster, Host.platform_id)
              .join(Host, VirtualMachine.host_id == Host.id)
              .filter(VirtualMachine.name.ilike(f"%{q}%"),
                      VirtualMachine.is_template == False)           # noqa: E712
              .order_by(VirtualMachine.name).limit(20).all())
    out = []
    for v, cluster, pf_id in rows:
        cl = cluster or _NO_CLUSTER
        out.append({"vm_node": f"v{v.id}", "vm_name": v.name,
                    "host_node": f"h{v.host_id}", "host_id": v.host_id,
                    "cluster_node": f"c{pf_id}_{cl}",
                    "platform_node": f"p{pf_id}", "status": v.power_state or ""})
    return {"matches": out}


@router.get("/stream")
async def stream(request: Request, user=Depends(get_current_user)):
    """SSE: tam senkronizasyon bitince 'sync' olayı yayınlar (canlı tazeleme)."""
    async def gen():
        last = events.latest_seq()          # mevcut andan başla (eskiyi tekrar etme)
        yield "retry: 5000\n\n"
        while True:
            if await request.is_disconnected():
                break
            for seq, _ts, ev in events.read_since(last):
                last = seq
                kind = ev.get("kind", "message")
                yield f"event: {kind}\ndata: {json.dumps(ev)}\n\n"
            yield ": ping\n\n"              # heartbeat (proxy timeout'larına karşı)
            await asyncio.sleep(2)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
