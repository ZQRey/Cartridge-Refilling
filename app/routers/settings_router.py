from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AppUser
from app.schemas import SettingsDict, LdapTestRequest, WhatsAppTestRequest
from app.services.settings_service import SettingsService
from app.services.ldap_service import LDAPService
from app.services.whatsapp_service import WhatsAppService
from app.services.auth_service import (
    get_current_user_optional,
    require_superadmin,
    require_admin,
    require_operator
)

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("")
def get_settings(
    db: Session = Depends(get_db),
    current_user: Optional[AppUser] = Depends(get_current_user_optional)
):
    """Получить текущие настройки системы (пароль AD скрыт для не-суперадминов)."""
    settings = SettingsService.get_all(db)
    if not current_user or current_user.role != "superadmin":
        if "ad_bind_password" in settings and settings["ad_bind_password"]:
            settings["ad_bind_password"] = "******"
    return settings


@router.post("")
def update_settings(
    payload: SettingsDict,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_superadmin)
):
    """Обновить настройки системы в БД (доступно только Супер администратору)."""
    cleaned = dict(payload.settings)
    if cleaned.get("ad_bind_password") == "******":
        cleaned.pop("ad_bind_password", None)

    updated = SettingsService.update_bulk(db, cleaned)
    return {"success": True, "settings": updated}


@router.post("/ldap/test")
def test_ldap_connection(
    payload: LdapTestRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_superadmin)
):
    """Проверить подключение к Active Directory / LDAP (только Супер администратор)."""
    result = LDAPService.test_connection(
        db=db,
        host=payload.host,
        base_dn=payload.base_dn,
        bind_user=payload.bind_user,
        bind_password=payload.bind_password
    )
    return result


@router.post("/ldap/sync")
def sync_ad_users(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_superadmin)
):
    """Запустить синхронизацию пользователей из AD (только Супер администратор)."""
    result = LDAPService.sync_users(db)
    return result


@router.get("/wa/status")
async def get_whatsapp_status(
    instance_name: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Проверить статус подключения инстанса WhatsApp в Evolution API."""
    if user_id:
        target_user = db.query(AppUser).filter(AppUser.id == user_id).first()
        if target_user:
            instance_name = target_user.wa_instance_name or f"operator_{target_user.id}"
    elif not instance_name and current_user:
        settings = SettingsService.get_all(db)
        if settings.get("wa_mode") == "individual":
            instance_name = current_user.wa_instance_name or f"operator_{current_user.id}"

    result = await WhatsAppService.get_connection_status(db, instance_name=instance_name)
    return result


@router.get("/wa/operators-status")
async def get_operators_wa_status(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Получить статус подключения WhatsApp для всех активных операторов."""
    return await WhatsAppService.get_all_operators_status(db)


@router.post("/wa/qr")
async def get_whatsapp_qr(
    instance_name: Optional[str] = None,
    user_id: Optional[int] = None,
    force_recreate: bool = False,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Получить или сгенерировать QR-код для авторизации номера в WhatsApp."""
    if user_id:
        target_user = db.query(AppUser).filter(AppUser.id == user_id).first()
        if target_user:
            instance_name = target_user.wa_instance_name or f"operator_{target_user.id}"
    elif not instance_name and current_user:
        settings = SettingsService.get_all(db)
        if settings.get("wa_mode") == "individual":
            instance_name = current_user.wa_instance_name or f"operator_{current_user.id}"

    result = await WhatsAppService.get_or_create_qr_code(db, instance_name=instance_name, force_recreate=force_recreate)
    return result


@router.post("/wa/reset")
async def reset_whatsapp_instance(
    instance_name: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Сбросить инстанс WhatsApp в Evolution API и принудительно сгенерировать новый QR-код."""
    if user_id:
        target_user = db.query(AppUser).filter(AppUser.id == user_id).first()
        if target_user:
            instance_name = target_user.wa_instance_name or f"operator_{target_user.id}"
    elif not instance_name and current_user:
        settings = SettingsService.get_all(db)
        if settings.get("wa_mode") == "individual":
            instance_name = current_user.wa_instance_name or f"operator_{current_user.id}"

    result = await WhatsAppService.reset_instance(db, instance_name=instance_name)
    return result


@router.post("/wa/test")
async def send_whatsapp_test(
    payload: WhatsAppTestRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Отправить тестовое сообщение в WhatsApp."""
    settings = SettingsService.get_all(db)
    inst, desc = WhatsAppService.get_instance_for_user(db, current_user)
    if payload.instance_name:
        inst = payload.instance_name

    text = payload.message or (
        f"Тестовое уведомление из системы Cartridge Tracker ({settings.get('org_name', '')}). "
        f"Шлюз WhatsApp ({desc}) успешно настроен!"
    )
    result = await WhatsAppService.send_text_message(db, payload.phone, text, instance_name=inst)
    return result
