"""
Автоматизированный верификационный тест для системы Cartridge Tracker.
Проверяет базу данных, все 4 этапа жизненного цикла картриджа, генерацию акта передачи и печатной формы.
"""
import os
import sys

# Настройка тестовой БД в памяти или временном файле
os.environ["DATABASE_URL"] = "sqlite:///./data/test_cartridges.db"

from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.models import Cartridge, CartridgeStatus, SystemSetting, ADUser, Batch
from app.services.whatsapp_service import WhatsAppService


def run_tests():
    print("[1/7] Инициализация базы данных...")
    init_db()
    db = SessionLocal()

    # Проверка дефолтных настроек
    settings_count = db.query(SystemSetting).count()
    assert settings_count > 0, "Настройки не были проинициализированы!"
    print(f" -> Успешно. Количество настроек по умолчанию: {settings_count}")

    # Создание тестового пользователя AD
    test_user = ADUser(
        samaccountname="i.ivanov",
        display_name="Иванов Иван Иванович",
        department="Бухгалтерия",
        cabinet="204",
        phone="+7 (999) 111-22-33"
    )
    db.merge(test_user)
    db.commit()
    print(" -> Тестовый пользователь Active Directory сохранен.")

    client = TestClient(app)

    # 1. Проверка API настроек
    print("\n[2/7] Тестирование API настроек...")
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "ad_host" in data
    assert "wa_api_url" in data
    print(" -> GET /api/settings: OK")

    res = client.post("/api/settings", json={"settings": {"org_name": "ООО «ТестПром»"}})
    assert res.status_code == 200
    assert res.json()["settings"]["org_name"] == "ООО «ТестПром»"
    print(" -> POST /api/settings (обновление без перезапуска): OK")

    # 2. Этап 1: Приемка картриджа
    print("\n[3/7] Тестирование ЭТАПА 1: Приемка картриджа...")
    accept_payload = {
        "marker_label": "Каб. 204 #1",
        "qr_code": "QR-CAB204-1",
        "model": "HP CF218A",
        "cabinet": "204",
        "current_user_id": "i.ivanov",
        "notes": "Полосит при печати",
        "action_required": "Заправка"
    }
    res = client.post("/api/cartridges/accept", json=accept_payload)
    assert res.status_code == 200, res.text
    cart_data = res.json()
    cart_id = cart_data["id"]
    assert cart_data["status"] == "pending_vendor"
    assert cart_data["marker_label"] == "Каб. 204 #1"
    print(f" -> Картридж успешно принят. ID={cart_id}, Статус={cart_data['status']}")

    # Проверка быстрого поиска по маркеру
    res = client.get("/api/cartridges/search/quick", params={"marker": "Каб. 204 #1"})
    assert res.status_code == 200, res.text
    assert res.json()["found"] is True
    print(" -> Быстрый поиск по надписи маркером: OK")

    # 3. Этап 2: Формирование акта передачи поставщику
    print("\n[4/7] Тестирование ЭТАПА 2: Формирование акта передачи...")
    batch_payload = {
        "cartridge_ids": [cart_id],
        "vendor_name": "ООО «СервисПринт»",
        "action_required": "Заправка",
        "notes": "Срочный заказ"
    }
    res = client.post("/api/batches", json=batch_payload)
    assert res.status_code == 200, res.text
    batch_data = res.json()
    batch_id = batch_data["id"]
    assert "АКТ-" in batch_data["act_number"]
    assert len(batch_data["items"]) == 1
    print(f" -> Акт сформирован: № {batch_data['act_number']}, ID={batch_id}")

    # Проверяем, что картридж сменил статус на 'at_vendor'
    res = client.get(f"/api/cartridges/{cart_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["status"] == "at_vendor"
    assert len(detail["history"]) >= 2
    print(f" -> Статус картриджа обновлен: {detail['status']}, записей в истории: {len(detail['history'])}")

    # Проверяем HTML печатной формы А4
    res = client.get(f"/print/act/{batch_id}")
    assert res.status_code == 200
    assert "АКТ ПРИЕМА-ПЕРЕДАЧИ КАРТРИДЖЕЙ" in res.text
    assert "Каб. 204 #1" in res.text
    assert "ООО «ТестПром»" in res.text
    print(" -> HTML печатной формы А4 сгенерирован корректно: OK")

    # 4. Этап 3: Возврат с заправки и шаблон WhatsApp
    print("\n[5/7] Тестирование ЭТАПА 3: Возврат с заправки и шаблон WhatsApp...")
    res = client.post("/api/cartridges/return-vendor", json={"cartridge_ids": [cart_id]})
    assert res.status_code == 200
    assert res.json()["returned_count"] == 1

    # Проверяем статус 'ready_for_pickup'
    res = client.get(f"/api/cartridges/{cart_id}")
    detail = res.json()
    assert detail["status"] == "ready_for_pickup"
    print(f" -> Картридж переведен в статус: {detail['status']}")

    # Тестирование шаблонизатора WhatsApp
    template = "Здравствуйте, {name}! Ваш картридж {marker} ({model}) для кабинета {cabinet} готов в {it_office}."
    formatted_msg = WhatsAppService.format_message(
        template=template,
        name="Иван Иванович",
        marker="Каб. 204 #1",
        model="HP CF218A",
        cabinet="204",
        it_office="Кабинет IT № 108"
    )
    assert "Иван Иванович" in formatted_msg
    assert "Каб. 204 #1" in formatted_msg
    assert "Кабинет IT № 108" in formatted_msg
    print(f" -> Шаблонизатор WhatsApp сформировал: \"{formatted_msg}\"")

    clean_ph = WhatsAppService.clean_phone("+7 (999) 111-22-33")
    assert clean_ph == "79991112233"
    print(f" -> Нормализация телефона: '+7 (999) 111-22-33' -> '{clean_ph}' OK")

    # 5. Этап 4: Выдача картриджа сотруднику
    print("\n[6/7] Тестирование ЭТАПА 4: Выдача картриджа...")
    res = client.post(f"/api/cartridges/{cart_id}/issue", json={"notes": "Выдан лично"})
    assert res.status_code == 200
    res = client.get(f"/api/cartridges/{cart_id}")
    detail = res.json()
    assert detail["status"] == "in_use"
    print(f" -> Картридж успешно выдан! Статус: {detail['status']}")

    # 6. Реестр и статические файлы
    print("\n[7/7] Тестирование реестра и доступности веб-интерфейса...")
    res = client.get("/api/cartridges")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    res = client.get("/")
    assert res.status_code == 200
    assert "Cartridge Tracker" in res.text
    print(" -> Веб-интерфейс отдается успешно: HTTP 200 OK")

    print("\n" + "="*50)
    print("ВСЕ 7 ТЕСТОВ УСПЕШНО ПРОЙДЕНЫ! СИСТЕМА ПОЛНОСТЬЮ ГОТОВА.")
    print("="*50)

    db.close()


if __name__ == "__main__":
    run_tests()
