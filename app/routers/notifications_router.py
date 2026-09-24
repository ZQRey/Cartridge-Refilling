from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Cartridge, CartridgeStatus, HistoryLog, AppUser
from app.schemas import NotifyWhatsAppRequest
from app.services.settings_service import SettingsService
from app.services.whatsapp_service import WhatsAppService
from app.services.auth_service import require_operator

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.post("/whatsapp/ready")
async def notify_ready_cartridges(
    payload: NotifyWhatsAppRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
) -> Dict[str, Any]:
    """
    ЭТАП 3: ОПОВЕЩЕНИЕ В WHATSAPP
    Рассылка персональных сообщений владельцам/кабинетам по готовым к выдаче картриджам.
    Поддерживает отправку как через единый корпоративный шлюз, так и через личный WhatsApp авторизованного оператора.
    """
    settings = SettingsService.get_all(db)
    template = settings.get(
        "wa_message_template",
        "Здравствуйте, {name}! Ваш картридж {marker} ({model}) для кабинета {cabinet} успешно заправлен и ожидает выдачи в {it_office}."
    )
    it_office = settings.get("it_office", "Кабинет IT")

    # Определяем шлюз/инстанс отправки
    instance_name, sender_desc = WhatsAppService.get_instance_for_user(db, current_user)

    query = db.query(Cartridge).options(joinedload(Cartridge.current_user))
    if payload.cartridge_ids:
        query = query.filter(Cartridge.id.in_(payload.cartridge_ids))
    else:
        query = query.filter(Cartridge.status == CartridgeStatus.READY_FOR_PICKUP)

    cartridges = query.all()

    if not cartridges:
        return {
            "success": True,
            "total": 0,
            "sent_count": 0,
            "failed_count": 0,
            "message": "Нет картриджей со статусом 'Готов к выдаче' для отправки.",
            "sender": sender_desc,
            "instance_name": instance_name,
            "results": []
        }

    # Быстрая проверка подключения шлюза перед отправкой
    wa_status = await WhatsAppService.get_connection_status(db, instance_name=instance_name)
    if not wa_status.get("connected", False):
        return {
            "success": False,
            "total": len(cartridges),
            "sent_count": 0,
            "failed_count": len(cartridges),
            "message": f"WhatsApp ({sender_desc}) не подключен: {wa_status.get('message', 'Требуется сканирование QR-кода')}.",
            "sender": sender_desc,
            "instance_name": instance_name,
            "results": []
        }

    results = []
    sent_count = 0
    failed_count = 0

    for cart in cartridges:
        user = cart.current_user
        user_name = user.display_name if user else "Коллега"
        phone = user.phone if user else None

        if not phone:
            failed_count += 1
            results.append({
                "cartridge_id": cart.id,
                "marker": cart.marker_label,
                "user": user_name,
                "phone": None,
                "success": False,
                "error": "У сотрудника не указан номер телефона в профиле AD."
            })
            continue

        # Формируем текст по шаблону
        text = WhatsAppService.format_message(
            template=template,
            name=user_name,
            marker=cart.marker_label,
            model=cart.model,
            cabinet=cart.cabinet,
            it_office=it_office
        )

        send_res = await WhatsAppService.send_text_message(db, phone=phone, message=text, instance_name=instance_name)
        is_ok = send_res.get("success", False)

        if is_ok:
            sent_count += 1
            # Запись в историю картриджа
            db.add(
                HistoryLog(
                    cartridge_id=cart.id,
                    action="Оповещение WhatsApp",
                    user_name=user_name,
                    details=f"Отправлено уведомление ({sender_desc}) на номер {phone}."
                )
            )
        else:
            failed_count += 1

        results.append({
            "cartridge_id": cart.id,
            "marker": cart.marker_label,
            "user": user_name,
            "phone": phone,
            "success": is_ok,
            "error": None if is_ok else send_res.get("message")
        })

    db.commit()

    return {
        "success": True,
        "total": len(cartridges),
        "sent_count": sent_count,
        "failed_count": failed_count,
        "sender": sender_desc,
        "instance_name": instance_name,
        "message": f"Рассылка завершена через {sender_desc}: успешно отправлено {sent_count} из {len(cartridges)}.",
        "results": results
    }
