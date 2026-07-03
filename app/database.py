"""
Database connection and session management.
Supports PostgreSQL (production) or SQLite (small setups).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import get_settings

settings = get_settings()

# Disable thread checks for SQLite, configure a connection pool for PostgreSQL
engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Pool for 500+ VM environments: concurrent users + background sync
    engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema(engine):
    """
        Light auto-migration: adds columns defined on the models but missing in
        the database via ALTER TABLE. Existing columns are never modified.
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
                logger.info("Schema extended: %s.%s (%s)",
                            table.name, col.name, col_type)
            except Exception as exc:
                # The column may have been added by another process
                # (multi-worker) - don't block startup, log and continue.
                logger.warning("Kolon eklenemedi %s.%s: %s",
                               table.name, col.name, exc)
