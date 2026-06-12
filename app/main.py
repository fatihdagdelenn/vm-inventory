"""
VM Envanter Yönetim Sistemi - FastAPI ana uygulaması.

Mimari özet:
- REST API + Jinja2 ile sunulan Bootstrap 5 arayüzü
- Zamanlanmış arka plan senkronizasyonu (APScheduler)
- Kullanıcı istekleri her zaman lokal veritabanından yanıtlanır
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
from .core.security import get_current_user, hash_password
from .core.scheduler import start_scheduler, stop_scheduler
from .api import (auth, dashboard, vms, hosts, networks, platforms,
                  reports, admin, clusters)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
settings = get_settings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
# Önbellek kırıcı: her uygulama başlangıcında değişen sürüm damgası.
# Statik dosya URL'lerine ?v= olarak eklenir; böylece güncellemelerden
# sonra tarayıcı asla eski CSS/JS kullanmaz (Ctrl+F5 gerekmez).
import time as _time
templates.env.globals["asset_version"] = int(_time.time())


def _create_default_admin():
    """İlk kurulumda varsayılan admin kullanıcısı oluştur (admin / admin123)."""
    db = SessionLocal()
    try:
        if not db.query(User).count():
            db.add(User(username="admin", full_name="Sistem Yöneticisi",
                        role="admin", password_hash=hash_password("admin123")))
            db.commit()
            logging.warning("Varsayılan admin oluşturuldu: admin / admin123 "
                            "- İLK GİRİŞTEN SONRA PAROLAYI DEĞİŞTİRİN!")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Açılış: tabloları oluştur, admin'i kur, zamanlayıcıyı başlat
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    from .database import ensure_schema
    ensure_schema(engine)   # mevcut tablolara yeni kolonları ekle (hafif migrasyon)
    _create_default_admin()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, lifespan=lifespan,
              docs_url="/api/docs" if settings.debug else None)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")),
          name="static")

# API rotaları
for router in (auth.router, dashboard.router, vms.router, hosts.router,
               networks.router, platforms.router, reports.router, admin.router,
               clusters.router):
    app.include_router(router)


# ---------- HTML sayfaları ----------
PAGES = {
    "/": ("dashboard.html", "Dashboard"),
    "/vms": ("vms.html", "Sanal Makineler"),
    "/hosts": ("hosts.html", "Host'lar"),
    "/networks": ("networks.html", "Ağlar"),
    "/platforms": ("platforms.html", "Platformlar"),
    "/reports": ("reports.html", "Raporlar"),
    "/history": ("history.html", "Değişiklik Geçmişi"),
    "/settings": ("settings.html", "Yönetim"),
}


def _render(request: Request, path: str):
    """Oturum kontrolü yaparak sayfayı render et; oturum yoksa /login'e yönlendir."""
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


# Her sayfa için rota oluştur.
# Not: lambda kullanılamaz; FastAPI'nin Request nesnesini enjekte etmesi için
# parametrenin "Request" tip açıklamasına sahip olması gerekir.
def _make_page_handler(path: str):
    def page(request: Request):
        return _render(request, path)
    return page


for _path in PAGES:
    app.add_api_route(_path, _make_page_handler(_path), methods=["GET"],
                      response_class=HTMLResponse, include_in_schema=False)
