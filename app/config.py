"""
Uygulama yapılandırması.
Tüm ayarlar ortam değişkenlerinden (.env) okunur.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Genel
    app_name: str = "VM Envanter Yönetim Sistemi"
    debug: bool = False
    secret_key: str = "degistir-bunu"          # Oturum imzalama anahtarı
    encryption_key: str = ""                   # Fernet anahtarı (kimlik bilgisi şifreleme)

    # Veritabanı
    database_url: str = "sqlite:///./data/vminventory.db"

    # Oturum
    session_timeout_minutes: int = 30

    # Zaman dilimi (görüntüleme + zamanlanmış görevler).
    # DB'de zamanlar UTC saklanır; arayüze ve cron'a bu TZ uygulanır.
    app_timezone: str = "Europe/Istanbul"

    # Senkronizasyon
    sync_interval_minutes: int = 15
    usage_sync_interval_minutes: int = 3   # anlık kullanım tazeleme aralığı (dk)

    # Zamanlanmış raporların yazılacağı klasör (Docker'da volume'e bağlanır)
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
    """Ayarları tek sefer yükle ve önbellekte tut."""
    return Settings()
