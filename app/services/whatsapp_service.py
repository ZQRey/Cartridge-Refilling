import re
from typing import Dict, Any, Optional
import httpx
from sqlalchemy.orm import Session
from app.services.settings_service import SettingsService


class WhatsAppService:
    @staticmethod
    def clean_phone(phone: str) -> str:
        """Очищает телефон от скобок, пробелов, тире и нормализует формат (например 8999... -> 7999...)."""
        if not phone:
            return ""
        digits = re.sub(r"\D", "", phone)
        # Если номер начинается с 8 и длина 11 цифр (РФ) -> заменяем на 7
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        return digits

    @staticmethod
    def format_message(
        template: str,
        name: str,
        marker: str,
        model: str,
        cabinet: str,
        it_office: str
    ) -> str:
        """Подставляет переменные в шаблон сообщения WhatsApp."""
        return template.format(
            name=name or "Сотрудник",
            marker=marker or "",
            model=model or "",
            cabinet=cabinet or "",
            it_office=it_office or "IT-отдел"
        )

    @classmethod
    async def get_connection_status(cls, db: Session) -> Dict[str, Any]:
        """Проверяет состояние подключения инстанса в Evolution API."""
        settings = SettingsService.get_all(db)
        api_url = settings.get("wa_api_url", "http://whatsapp-gateway:8080").rstrip("/")
        api_key = settings.get("wa_api_key", "")
        instance = settings.get("wa_instance_name", "cartridge_bot")

        headers = {
            "apikey": api_key,
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(
                    f"{api_url}/instance/connectionState/{instance}",
                    headers=headers
                )

                if resp.status_code == 200:
                    data = resp.json()
                    # State can be 'open', 'close', 'connecting'
                    state = data.get("instance", {}).get("state", "unknown")
                    return {
                        "connected": state == "open",
                        "state": state,
                        "raw": data,
                        "message": f"Статус сессии: {state}"
                    }
                elif resp.status_code == 404:
                    return {
                        "connected": False,
                        "state": "not_found",
                        "message": f"Инстанс '{instance}' еще не создан в Evolution API."
                    }
                else:
                    return {
                        "connected": False,
                        "state": "error",
                        "message": f"Ответ шлюза: HTTP {resp.status_code} ({resp.text[:100]})"
                    }
        except httpx.ConnectError:
            return {
                "connected": False,
                "state": "unreachable",
                "message": f"Шлюз WhatsApp недоступен по адресу {api_url}"
            }
        except Exception as e:
            return {
                "connected": False,
                "state": "error",
                "message": f"Ошибка проверки подключения: {str(e)}"
            }

    @classmethod
    async def get_or_create_qr_code(cls, db: Session) -> Dict[str, Any]:
        """Создает инстанс при необходимости и возвращает QR-код для авторизации."""
        settings = SettingsService.get_all(db)
        api_url = settings.get("wa_api_url", "http://whatsapp-gateway:8080").rstrip("/")
        api_key = settings.get("wa_api_key", "")
        instance = settings.get("wa_instance_name", "cartridge_bot")

        headers = {
            "apikey": api_key,
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Сначала пробуем получить QR для существующего инстанса
                connect_resp = await client.get(
                    f"{api_url}/instance/connect/{instance}",
                    headers=headers
                )

                if connect_resp.status_code == 200:
                    cdata = connect_resp.json()
                    qr_base64 = cdata.get("base64")
                    qr_code = cdata.get("code")
                    if qr_base64:
                        return {
                            "success": True,
                            "qr_base64": qr_base64,
                            "code": qr_code,
                            "message": "QR-код успешно получен. Отсканируйте его в приложении WhatsApp."
                        }

                # 2. Если инстанса нет (404), создаем его
                create_payload = {
                    "instanceName": instance,
                    "token": f"{instance}_token",
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS"
                }

                create_resp = await client.post(
                    f"{api_url}/instance/create",
                    json=create_payload,
                    headers=headers
                )

                if create_resp.status_code in (200, 201):
                    cdata = create_resp.json()
                    # Проверяем qr в ответе создания
                    qr_base64 = cdata.get("qrcode", {}).get("base64")
                    qr_code = cdata.get("qrcode", {}).get("code")
                    
                    if not qr_base64:
                        # Запрашиваем connect еще раз
                        connect_resp2 = await client.get(
                            f"{api_url}/instance/connect/{instance}",
                            headers=headers
                        )
                        if connect_resp2.status_code == 200:
                            cdata2 = connect_resp2.json()
                            qr_base64 = cdata2.get("base64")
                            qr_code = cdata2.get("code")

                    return {
                        "success": True,
                        "qr_base64": qr_base64,
                        "code": qr_code,
                        "message": "Инстанс создан. Отсканируйте полученный QR-код в WhatsApp."
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Ошибка создания инстанса: {create_resp.text}"
                    }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": f"Не удалось соединиться со шлюзом Evolution API ({api_url}). Убедитесь, что контейнер запущен."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Ошибка получения QR-кода: {str(e)}"
            }

    @classmethod
    async def send_text_message(
        cls,
        db: Session,
        phone: str,
        message: str
    ) -> Dict[str, Any]:
        """Отправляет текстовое сообщение через Evolution API."""
        clean_p = cls.clean_phone(phone)
        if not clean_p:
            return {"success": False, "message": "Некорректный номер телефона."}

        settings = SettingsService.get_all(db)
        api_url = settings.get("wa_api_url", "http://whatsapp-gateway:8080").rstrip("/")
        api_key = settings.get("wa_api_key", "")
        instance = settings.get("wa_instance_name", "cartridge_bot")

        headers = {
            "apikey": api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "number": clean_p,
            "text": message
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{api_url}/message/sendText/{instance}",
                    json=payload,
                    headers=headers
                )

                if resp.status_code in (200, 201):
                    return {
                        "success": True,
                        "message": "Сообщение успешно отправлено в WhatsApp.",
                        "data": resp.json()
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Ошибка отправки (HTTP {resp.status_code}): {resp.text}"
                    }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": f"Не удалось подключиться к шлюзу Evolution API ({api_url})."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Исключение при отправке сообщения: {str(e)}"
            }
