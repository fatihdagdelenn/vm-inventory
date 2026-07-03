"""
LDAP / Active Directory authentication (optional).
With LDAP_ENABLED=true, AD is queried when no local user matches.
"""
import logging
from ldap3 import Server, Connection, ALL

from ..config import get_settings

logger = logging.getLogger("ldap")


def ldap_authenticate(username: str, password: str) -> bool:
    """Authenticate against AD with a simple bind."""
    settings = get_settings()
    if not settings.ldap_enabled or not password:
        return False
    try:
        server = Server(settings.ldap_server, get_info=ALL)
        user_dn = settings.ldap_user_dn_template.format(username=username)
        conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        conn.unbind()
        return True
    except Exception as exc:
        logger.warning("LDAP authentication failed (%s): %s", username, exc)
        return False
