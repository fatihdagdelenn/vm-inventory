"""
Veritabanı bağlantısı ve oturum yönetimi.
PostgreSQL (üretim) veya SQLite (küçük kurulumlar) destekler.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import get_settings

settings = get_settings()

# SQLite için thread kontrolünü kapat, PostgreSQL için bağlantı havuzu ayarla
engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # 500+ VM ortamı için bağlantı havuzu: eşzamanlı kullanıcı + arka plan senkronizasyonu
    engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: istek başına veritabanı oturumu."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema(engine):
    """
    Hafif otomatik migrasyon: modellerde tanımlı olup veritabanında
    bulunmayan kolonları ALTER TABLE ile ekler.

    Mevcut kurulumlar yeni sürüme geçtiğinde (örn. VM'lere eklenen
    cpu_usage_pct/ram_usage_mb kolonları) veri kaybı olmadan şema
    otomatik genişler. Yeni tablolar zaten create_all ile oluşur.
    """
    from sqlalchemy import inspect, text
    import logging
    logger = logging.getLogger("migration")
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all halleder
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            col_type = col.type.compile(engine.dialect)
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}'))
                logger.info("Şema genişletildi: %s.%s (%s)",
                            table.name, col.name, col_type)
            except Exception as exc:
                # Kolon başka bir süreç tarafından eklenmiş olabilir
                # (çoklu worker) — açılışı engelleme, logla ve devam et.
                logger.warning("Kolon eklenemedi %s.%s: %s",
                               table.name, col.name, exc)
