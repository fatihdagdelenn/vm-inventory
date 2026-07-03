"""
VM Inventory Management System - FastAPI main application.
Architecture summary:
- REST API + a Bootstrap 5 UI served via Jinja2
- Background sync with APScheduler -> local DB (searches never hit platforms)
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .database import Base, engine, SessionLocal
from .models import User
from .core.security import (get_current_user, hash_password,
                            refresh_session_token, set_session_cookie)
from .core.scheduler import start_scheduler, stop_scheduler
from .api import (auth, dashboard, vms, hosts, networks, platforms, datastores, snapshots, backups,
                  reports, admin, clusters, topology)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
settings = get_settings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
# Cache buster: a version stamp that changes on every app start.
# Appended to static URLs as ?v= so the browser never uses stale
# CSS/JS after updates (no Ctrl+F5 needed).
import time as _time
templates.env.globals["asset_version"] = int(_time.time())
# App version shown in the UI (footer). version.py is bumped every phase.
from .core.version import APP_VERSION
templates.env.globals["app_version"] = APP_VERSION
# Timezone used to render dates/times in the UI (window.APP_TZ).
templates.env.globals["app_tz"] = settings.app_timezone


def _create_default_admin():
    """Create the default admin user on first install (admin / admin123)."""
    db = SessionLocal()
    try:
        if not db.query(User).count():
            db.add(User(username="admin", full_name="Sistem Yöneticisi",
                        role="admin", password_hash=hash_password("admin123")))
            db.commit()
            logging.warning("Default admin created: admin / admin123 "
                        "- CHANGE THE PASSWORD AFTER FIRST LOGIN!")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables, seed the admin, start the scheduler
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    from .database import ensure_schema
    ensure_schema(engine)   # add new columns to existing tables (light migration)
    # Purge old "mac_addresses" change rows (no longer tracked - dirty data)
    try:
        from .models import ChangeHistory
        _db = SessionLocal()
        n = _db.query(ChangeHistory).filter(ChangeHistory.field == "mac_addresses").delete()
        _db.commit(); _db.close()
        if n:
            logging.info("Temizlendi: %d adet mac_addresses degisiklik kaydi silindi", n)
    except Exception as exc:
        logging.warning("mac_addresses temizligi atlandi: %s", exc)
    _create_default_admin()
    start_scheduler()
    yield
    stop_scheduler()

    # Purge hw_model values that captured a component maker instead of the OEM
    # (early PCI-fallback bug wrote e.g. "Intel Corporation"); the fixed
    # collector refills them on the next sync.
    try:
        from .models import Host as _H
        _db = SessionLocal()
        _bad = ["Intel%", "Advanced Micro%", "AMD%", "Broadcom%", "Realtek%",
                "NVIDIA%", "Mellanox%", "Red Hat%"]
        n = 0
        for _p in _bad:
            n += _db.query(_H).filter(_H.hw_model.ilike(_p)) \
                    .update({_H.hw_model: None}, synchronize_session=False)
        _db.commit(); _db.close()
        if n:
            logging.info("Cleared %d component-vendor hw_model values", n)
    except Exception:
        pass


app = FastAPI(title=settings.app_name, lifespan=lifespan,
              docs_url="/api/docs" if settings.debug else None)


@app.middleware("http")
async def _slide_session(request: Request, call_next):
    """
        Sliding session: after every authenticated request the session cookie is
        rewritten with a fresh timestamp, so the timeout counts from the LAST
        activity, not from login.
        """
    response = await call_next(request)
    if getattr(request.state, "session_refresh", False):
        token = request.cookies.get("session")
        fresh = refresh_session_token(token) if token else None
        if fresh:
            set_session_cookie(response, fresh)
    return response

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")),
          name="static")

# API routes
for router in (auth.router, dashboard.router, vms.router, hosts.router,
               networks.router, platforms.router, reports.router, admin.router,
               clusters.router, datastores.router, snapshots.router, backups.router,
               topology.router):
    app.include_router(router)


# ---------- HTML pages ----------
PAGES = {
    "/": ("dashboard.html", "Dashboard"),
    "/vms": ("vms.html", "Sanal Makineler"),
    "/hosts": ("hosts.html", "Host'lar"),
    "/datastores": ("datastores.html", "Datastore'lar"),
    "/snapshots": ("snapshots.html", "Snapshot'lar"),
    "/backups": ("backups.html", "Yedekler"),
    "/networks": ("networks.html", "Ağlar"),
    "/platforms": ("platforms.html", "Platformlar"),
    "/reports": ("reports.html", "Raporlar"),
    "/history": ("history.html", "Değişiklik Geçmişi"),
    "/topology": ("topology.html", "Topoloji"),
    "/settings": ("settings.html", "Yönetim"),
}


def _render(request: Request, path: str):
    """Render the page with a session check; redirect to /login when absent."""
    from .database import SessionLocal
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    except Exception:
        return RedirectResponse("/login", status_code=303)
    finally:
        db.close()
    template, title = PAGES[path]
    return templates.TemplateResponse(template, {
        "request": request, "title": title, "active": path,
        "user": {"username": user.username, "role": user.role,
                 "full_name": user.full_name}})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: int = 0):
    return templates.TemplateResponse("login.html",
                                      {"request": request, "error": error})


# Create a route per page.
# Note: lambda won't do; FastAPI injects the Request object only when
# the parameter carries the "Request" type annotation.
def _make_page_handler(path: str):
    def page(request: Request):
        return _render(request, path)
    return page


for _path in PAGES:
    app.add_api_route(_path, _make_page_handler(_path), methods=["GET"],
                      response_class=HTMLResponse, include_in_schema=False)
