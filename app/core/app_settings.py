"""Genel uygulama ayarları için yardımcılar (AppSetting key-value tablosu).

Çalışma zamanında arayüzden değiştirilebilen ayarları okur/yazar; kayıt yoksa
verilen varsayılana (genelde .env değeri) düşer.
"""
from ..models import AppSetting


def get_int_setting(db, key: str, default: int) -> int:
    row = db.query(AppSetting).filter_by(key=key).first()
    if row and row.value not in (None, ""):
        try:
            return int(row.value)
        except (TypeError, ValueError):
            pass
    return default


def get_bool_setting(db, key: str, default: bool) -> bool:
    row = db.query(AppSetting).filter_by(key=key).first()
    if row and row.value not in (None, ""):
        return str(row.value).strip().lower() in ("1", "true", "yes", "on", "evet")
    return default


def set_setting(db, key: str, value) -> None:
    row = db.query(AppSetting).filter_by(key=key).first()
    if row:
        row.value = str(value)
    else:
        db.add(AppSetting(key=key, value=str(value)))
