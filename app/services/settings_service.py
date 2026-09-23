from typing import Dict, Optional
from sqlalchemy.orm import Session
from app.models import SystemSetting
from app.config import DEFAULT_SETTINGS


class SettingsService:
    @staticmethod
    def get_all(db: Session) -> Dict[str, str]:
        """Возвращает все настройки из БД в виде словаря key -> value с учетом дефолтов."""
        records = db.query(SystemSetting).all()
        settings = dict(DEFAULT_SETTINGS)
        for r in records:
            if r.value is not None:
                settings[r.key] = r.value
        return settings

    @staticmethod
    def get(db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
        """Получить значение одной настройки по ключу."""
        record = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if record and record.value is not None:
            return record.value
        return DEFAULT_SETTINGS.get(key, default)

    @staticmethod
    def update_bulk(db: Session, updates: Dict[str, Optional[str]]) -> Dict[str, str]:
        """Обновляет набор настроек в базе данных."""
        for key, val in updates.items():
            record = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if record:
                record.value = val
            else:
                db.add(SystemSetting(key=key, value=val))
        db.commit()
        return SettingsService.get_all(db)
