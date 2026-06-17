"""Ağ envanteri API'si: VLAN, vSwitch/Bridge, Port Group, SDN vnet ve fiziksel NIC.

Gruplama (host / cluster / VLAN / fiziksel kart) istemci tarafında yapılır;
bu uç nokta tüm ağ kayıtlarını cluster ve platform bilgisiyle zenginleştirip
döndürür. Veri kümesi küçük olduğundan tek çağrı yeterlidir.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Network, Host, Platform, User
from ..core.security import get_current_user

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.get("")
def list_networks(q: str = "", db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    query = db.query(Network)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Network.name.ilike(like), Network.vlan.ilike(like),
            Network.vswitch.ilike(like), Network.subnet.ilike(like),
            Network.host_name.ilike(like), Network.mac.ilike(like)))

    # host adı -> cluster ve platform_id -> ad eşlemeleri (N+1 sorgusundan kaçın)
    host_cluster = {h.name: h.cluster for h in db.query(Host).all()}
    platform_name = {p.id: p.name for p in db.query(Platform).all()}

    items = []
    for n in query.order_by(Network.vlan, Network.name).all():
        items.append({
            "id": n.id, "name": n.name, "vlan": n.vlan,
            "vswitch": n.vswitch, "portgroup": n.portgroup,
            "subnet": n.subnet, "host_name": n.host_name,
            "kind": n.kind or "portgroup",
            "mac": n.mac, "link_speed": n.link_speed,
            "cluster": host_cluster.get(n.host_name, ""),
            "platform": platform_name.get(n.platform_id, ""),
        })
    return {"items": items}
