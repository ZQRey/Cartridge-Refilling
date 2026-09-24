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

    @staticmethod
    def _extract_qr(data: Any) -> tuple[Optional[str], Optional[str]]:
        """Извлекает base64 и текстовый code QR-кода из различных форматов ответов Evolution API v1/v2."""
        if not isinstance(data, dict):
            return None, None

        qr_b64 = None
        qr_code = data.get("code")

        # 1. Прямой ключ base64
        if data.get("base64") and isinstance(data.get("base64"), str):
            qr_b64 = data.get("base64")

        # 2. Вложенный объект qrcode: { "qrcode": { "base64": "...", "code": "..." } }
        elif isinstance(data.get("qrcode"), dict):
            qr_b64 = data["qrcode"].get("base64")
            qr_code = data["qrcode"].get("code") or qr_code

        # 3. Ключ qrcode как строка (data URI или чистый base64)
        elif isinstance(data.get("qrcode"), str) and data.get("qrcode"):
            qr_b64 = data.get("qrcode")

        # 4. Если в корне лежит qr
        elif data.get("qr") and isinstance(data.get("qr"), str):
            qr_b64 = data.get("qr")

        # Нормализация префикса Data URI для тега <img>
        if qr_b64 and isinstance(qr_b64, str):
            qr_b64 = qr_b64.strip().strip('"\'')
            if not qr_b64.startswith("data:image"):
                qr_b64 = f"data:image/png;base64,{qr_b64}"

        return qr_b64, qr_code

    @classmethod
    async def get_or_create_qr_code(cls, db: Session, force_recreate: bool = False) -> Dict[str, Any]:
        """
        Создает инстанс при необходимости и возвращает QR-код для авторизации.
        Опрашивает шлюз с задержкой (polling), ожидая генерации WebSocket-рукопожатия Baileys.
        Если инстанс уже подключен (state == 'open'), сообщает об этом.
        Если инстанс завис, безопасно сбрасывает и пересоздает его.
        """
        import asyncio

        settings = SettingsService.get_all(db)
        api_url = settings.get("wa_api_url", "http://whatsapp-gateway:8080").rstrip("/")
        api_key = settings.get("wa_api_key", "")
        instance = settings.get("wa_instance_name", "cartridge_bot")

        headers = {
            "apikey": api_key,
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Вспомогательная функция для опроса connect с ожиданием генерации QR
                async def poll_connect(max_retries: int = 5, delay: float = 1.2):
                    for attempt in range(max_retries):
                        try:
                            resp = await client.get(f"{api_url}/instance/connect/{instance}", headers=headers)
                            if resp.status_code == 200:
                                d = resp.json()
                                st = d.get("instance", {}).get("state") or d.get("instance", {}).get("status")
                                if st == "open":
                                    return {
                                        "success": True,
                                        "already_connected": True,
                                        "message": "Инстанс WhatsApp уже подключен и активен (сессия открыта)."
                                    }

                                q_b64, q_code = cls._extract_qr(d)
                                p_code = d.get("pairingCode") or (d.get("qrcode", {}).get("pairingCode") if isinstance(d.get("qrcode"), dict) else None)
                                if q_b64:
                                    return {
                                        "success": True,
                                        "qr_base64": q_b64,
                                        "code": q_code,
                                        "pairing_code": p_code,
                                        "message": "QR-код успешно получен. Отсканируйте его в приложении WhatsApp."
                                    }
                        except Exception:
                            pass
                        if attempt < max_retries - 1:
                            await asyncio.sleep(delay)
                    return None

                # 0. Если запрошен принудительный сброс
                if force_recreate:
                    try:
                        await client.delete(f"{api_url}/instance/delete/{instance}", headers=headers)
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass

                # 1. Проверяем текущее состояние инстанса (если не принудительный сброс)
                if not force_recreate:
                    try:
                        state_resp = await client.get(f"{api_url}/instance/connectionState/{instance}", headers=headers)
                        if state_resp.status_code == 200:
                            sdata = state_resp.json()
                            if sdata.get("instance", {}).get("state") == "open":
                                return {
                                    "success": True,
                                    "already_connected": True,
                                    "message": "Инстанс WhatsApp уже подключен и активен (сессия открыта)."
                                }
                    except Exception:
                        pass

                    # Пробуем получить QR для уже существующего инстанса (до 3 попыток с паузой)
                    existing_qr = await poll_connect(max_retries=3, delay=1.0)
                    if existing_qr:
                        return existing_qr

                # 2. Инстанс отсутствует либо завис — создаем или пересоздаем
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

                # Если инстанс уже существует в БД Evolution API (403 already in use)
                if create_resp.status_code == 403 or "already in use" in create_resp.text:
                    try:
                        # Удаляем зависший инстанс
                        await client.delete(f"{api_url}/instance/delete/{instance}", headers=headers)
                        await asyncio.sleep(0.8)
                    except Exception:
                        pass

                    # Создаем заново
                    create_resp = await client.post(
                        f"{api_url}/instance/create",
                        json=create_payload,
                        headers=headers
                    )

                if create_resp.status_code in (200, 201):
                    # Проверяем QR прямо в теле ответа создания
                    cdata = create_resp.json()
                    qr_b64, qr_code = cls._extract_qr(cdata)
                    p_code = cdata.get("pairingCode") or (cdata.get("qrcode", {}).get("pairingCode") if isinstance(cdata.get("qrcode"), dict) else None)
                    if qr_b64:
                        return {
                            "success": True,
                            "qr_base64": qr_b64,
                            "code": qr_code,
                            "pairing_code": p_code,
                            "message": "Инстанс создан. Отсканируйте полученный QR-код в WhatsApp."
                        }

                    # Ожидаем WebSocket-хэндшейка Baileys через connect (до 6 попыток)
                    polled_result = await poll_connect(max_retries=6, delay=1.2)
                    if polled_result:
                        return polled_result

                    return {
                        "success": False,
                        "message": "Шлюз создал инстанс, но еще генерирует QR-код. Подождите 2-3 секунды и нажмите «Обновить код»."
                    }

                return {
                    "success": False,
                    "message": f"Ошибка создания инстанса (HTTP {create_resp.status_code}): {create_resp.text[:200]}"
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
    async def reset_instance(cls, db: Session) -> Dict[str, Any]:
        """Удаляет инстанс из Evolution API и пересоздает его заново с новым QR-кодом."""
        return await cls.get_or_create_qr_code(db, force_recreate=True)

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
