"""Ağ envanteri API'si: VLAN, vSwitch/Bridge, Port Group, Subnet."""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Network, User
from ..core.security import get_current_user

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.get("")
def list_networks(q: str = "", db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    query = db.query(Network)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Network.name.ilike(like), Network.vlan.ilike(like),
                                 Network.vswitch.ilike(like), Network.subnet.ilike(like)))
    return {"items": [{"id": n.id, "name": n.name, "vlan": n.vlan,
                       "vswitch": n.vswitch, "portgroup": n.portgroup,
                       "subnet": n.subnet, "host_name": n.host_name}
                      for n in query.order_by(Network.vlan, Network.name).all()]}
