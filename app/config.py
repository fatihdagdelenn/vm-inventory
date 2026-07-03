"""
Application configuration. All settings come from environment variables (.env).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Genel
    app_name: str = "VM Envanter Yönetim Sistemi"
    debug: bool = False
    secret_key: str = "degistir-bunu"          # Session signing key
    encryption_key: str = ""                   # Fernet key (credential encryption)

    # Database
    database_url: str = "sqlite:///./data/vminventory.db"

    # Oturum
    session_timeout_minutes: int = 30

    # Timezone (display + scheduled jobs).
    # Times are stored UTC in the DB; this TZ applies to the UI and cron.
    app_timezone: str = "Europe/Istanbul"

    # Senkronizasyon
    sync_interval_minutes: int = 15
    usage_sync_interval_minutes: int = 3   # instant-usage refresh interval (min)

    # Folder scheduled reports are written to (a volume in Docker)
    report_dir: str = "data/reports"

    # LDAP
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_base_dn: str = ""
    ldap_user_dn_template: str = "{username}"
    ldap_default_role: str = "viewer"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Load settings once and cache them."""
    return Settings()
