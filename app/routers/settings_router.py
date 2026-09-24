from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import SettingsDict, LdapTestRequest, WhatsAppTestRequest
from app.services.settings_service import SettingsService
from app.services.ldap_service import LDAPService
from app.services.whatsapp_service import WhatsAppService

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    """Получить текущие настройки системы."""
    return SettingsService.get_all(db)


@router.post("")
def update_settings(payload: SettingsDict, db: Session = Depends(get_db)):
    """Обновить настройки системы в БД без перезапуска контейнера."""
    updated = SettingsService.update_bulk(db, payload.settings)
    return {"success": True, "settings": updated}


@router.post("/ldap/test")
def test_ldap_connection(payload: LdapTestRequest, db: Session = Depends(get_db)):
    """Проверить подключение к Active Directory / LDAP."""
    result = LDAPService.test_connection(
        db=db,
        host=payload.host,
        base_dn=payload.base_dn,
        bind_user=payload.bind_user,
        bind_password=payload.bind_password
    )
    return result


@router.post("/ldap/sync")
def sync_ad_users(db: Session = Depends(get_db)):
    """Запустить принудительную синхронизацию пользователей из AD."""
    result = LDAPService.sync_users(db)
    return result


@router.get("/wa/status")
async def get_whatsapp_status(db: Session = Depends(get_db)):
    """Проверить статус подключения инстанса WhatsApp в Evolution API."""
    result = await WhatsAppService.get_connection_status(db)
    return result


@router.post("/wa/qr")
async def get_whatsapp_qr(db: Session = Depends(get_db)):
    """Получить или сгенерировать QR-код для авторизации корпоративного номера в WhatsApp."""
    result = await WhatsAppService.get_or_create_qr_code(db)
    return result


@router.post("/wa/reset")
async def reset_whatsapp_instance(db: Session = Depends(get_db)):
    """Сбросить текущий инстанс WhatsApp в Evolution API и принудительно сгенерировать новый QR-код."""
    result = await WhatsAppService.reset_instance(db)
    return result


@router.post("/wa/test")
async def send_whatsapp_test(payload: WhatsAppTestRequest, db: Session = Depends(get_db)):
    """Отправить тестовое сообщение в WhatsApp."""
    settings = SettingsService.get_all(db)
    text = payload.message or (
        f"Тестовое уведомление из системы Cartridge Tracker ({settings.get('org_name', '')}). "
        "Шлюз WhatsApp успешно настроен!"
    )
    result = await WhatsAppService.send_text_message(db, payload.phone, text)
    return result
