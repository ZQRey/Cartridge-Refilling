"""
Тестирование формирования местоположения ИТ-отдела и шаблона WhatsApp на основе филиала:
1. Создание и редактирование филиалов с индивидуальным кабинетом IT (it_office) и персональным шаблоном (wa_message_template).
2. Формирование текста WhatsApp-оповещения для картриджей разных филиалов:
   - Филиал 1: Кабинет 120 + индивидуальный шаблон.
   - Филиал 2: Кабинет 430 + общий шаблон (подстановка it_office = 'Кабинет 430').
   - Картридж без филиала: fallback на общий кабинет IT из системных настроек.
3. Печать актов передачи: подстановка it_office филиала партии.
"""
import os
import sys
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

TEST_DB_PATH = "test_branch_settings.db"
if os.path.exists(TEST_DB_PATH):
    try:
        os.remove(TEST_DB_PATH)
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from app.database import Base, get_db, init_db
from app.main import app
from app.models import AppUser, Branch, Cartridge, CartridgeStatus, ADUser, Batch, BatchItem
from app.services.auth_service import AuthService
from app.services.settings_service import SettingsService

client = TestClient(app)

def run_tests():
    print("=== STARTING BRANCH IT-OFFICE & TEMPLATE TESTS ===")
    init_db()

    with next(get_db()) as db:
        # Устанавливаем общие реквизиты
        SettingsService.update_bulk(db, {
            "it_office": "Кабинет IT общий № 108",
            "wa_message_template": "Здравствуйте, {name}! Ваш картридж {marker} ({model}) для кабинета {cabinet} успешно заправлен и ожидает выдачи в {it_office}."
        })

        # Создаем суперпользователя для API запросов
        admin = AppUser(
            username="admin_test_branch",
            full_name="Админ Филиалов",
            role="superadmin",
            password_hash=AuthService.hash_password("admin123"),
            is_active=True,
            auth_type="local"
        )
        db.add(admin)
        db.commit()

    token = AuthService.create_access_token({"sub": "admin_test_branch", "role": "superadmin"})
    headers = {"Authorization": f"Bearer {token}"}

    # -------------------------------------------------------------
    # 1. Проверка API создания и редактирования филиалов
    # -------------------------------------------------------------
    print("\n--- 1. Тестирование создания филиалов с it_office и wa_message_template ---")
    res1 = client.post("/api/branches", json={
        "name": "Филиал №1 (Северный)",
        "code": "BR1",
        "address": "ул. Северная, 10",
        "it_office": "Кабинет 120",
        "wa_message_template": "Служба IT Филиала №1: {name}, заберите картридж {marker} в {it_office}."
    }, headers=headers)
    assert res1.status_code == 201, f"Failed to create branch 1: {res1.text}"
    b1_data = res1.json()
    assert b1_data["it_office"] == "Кабинет 120"
    assert "Филиала №1" in b1_data["wa_message_template"]
    b1_id = b1_data["id"]
    print("✓ Филиал №1 успешно создан с кабинетом 120 и персональным шаблоном")

    res2 = client.post("/api/branches", json={
        "name": "Филиал №2 (Южный)",
        "code": "BR2",
        "address": "пр. Южный, 45",
        "it_office": "Кабинет 430",
        "wa_message_template": None  # Без персонального шаблона — общий
    }, headers=headers)
    assert res2.status_code == 201
    b2_data = res2.json()
    assert b2_data["it_office"] == "Кабинет 430"
    assert b2_data["wa_message_template"] is None
    b2_id = b2_data["id"]
    print("✓ Филиал №2 успешно создан с кабинетом 430 и общим шаблоном")

    # Проверка PUT обновления
    res_up = client.put(f"/api/branches/{b1_id}", json={
        "it_office": "Кабинет 120-А (IT-отдел)"
    }, headers=headers)
    assert res_up.status_code == 200
    assert res_up.json()["it_office"] == "Кабинет 120-А (IT-отдел)"
    print("✓ Обновление кабинета филиала через PUT успешно выполнено")

    # -------------------------------------------------------------
    # 2. Тестирование рассылки WhatsApp-оповещений
    # -------------------------------------------------------------
    print("\n--- 2. Тестирование рассылки WhatsApp готовых картриджей по филиалам ---")
    with next(get_db()) as db:
        # Создаем владельцев
        u1 = ADUser(samaccountname="petrov", display_name="Петров П.П.", cabinet="15", phone="+77011111111")
        u2 = ADUser(samaccountname="sidorov", display_name="Сидоров С.С.", cabinet="22", phone="+77022222222")
        u3 = ADUser(samaccountname="ivanov", display_name="Иванов И.И.", cabinet="05", phone="+77033333333")
        db.add_all([u1, u2, u3])

        # Картридж филиала 1 (кабинет 120-А + персональный шаблон)
        c1 = Cartridge(
            marker_label="CART-B1-01",
            model="HP 85A",
            status=CartridgeStatus.READY_FOR_PICKUP,
            branch_id=b1_id,
            current_user_id="petrov",
            cabinet="15"
        )
        # Картридж филиала 2 (кабинет 430 + общий шаблон)
        c2 = Cartridge(
            marker_label="CART-B2-01",
            model="Canon 725",
            status=CartridgeStatus.READY_FOR_PICKUP,
            branch_id=b2_id,
            current_user_id="sidorov",
            cabinet="22"
        )
        # Картридж без филиала (fallback на общий кабинет IT № 108)
        c3 = Cartridge(
            marker_label="CART-HQ-01",
            model="HP 26A",
            status=CartridgeStatus.READY_FOR_PICKUP,
            branch_id=None,
            current_user_id="ivanov",
            cabinet="05"
        )
        db.add_all([c1, c2, c3])
        db.commit()
        c1_id, c2_id, c3_id = c1.id, c2.id, c3.id

    sent_messages = []

    async def mock_send_text(db, phone, message, instance_name=None):
        sent_messages.append({"phone": phone, "message": message, "instance": instance_name})
        return {"success": True, "message": "OK"}

    async def mock_status(db, instance_name=None):
        return {"connected": True, "state": "open"}

    with patch("app.services.whatsapp_service.WhatsAppService.get_connection_status", side_effect=mock_status):
        with patch("app.services.whatsapp_service.WhatsAppService.send_text_message", side_effect=mock_send_text):
            res_notify = client.post("/api/notifications/whatsapp/ready", json={
                "cartridge_ids": [c1_id, c2_id, c3_id]
            }, headers=headers)
            assert res_notify.status_code == 200, f"Notify failed: {res_notify.text}"
            data = res_notify.json()
            assert data["sent_count"] == 3

    assert len(sent_messages) == 3, f"Expected 3 messages sent, got {len(sent_messages)}"

    # Проверяем сообщение для c1 (Филиал 1): персональный шаблон + кабинет 120-А
    msg1 = next(m for m in sent_messages if m["phone"] == "+77011111111")
    print(f"Message 1 (Branch 1): {msg1['message']}")
    assert "Служба IT Филиала №1" in msg1["message"]
    assert "Кабинет 120-А (IT-отдел)" in msg1["message"]
    assert "CART-B1-01" in msg1["message"]
    print("✓ Картридж Филиала №1 успешно отправлен с текстом и кабинетом Филиала №1")

    # Проверяем сообщение для c2 (Филиал 2): общий шаблон + кабинет 430
    msg2 = next(m for m in sent_messages if m["phone"] == "+77022222222")
    print(f"Message 2 (Branch 2): {msg2['message']}")
    assert "успешно заправлен и ожидает выдачи в Кабинет 430" in msg2["message"]
    assert "CART-B2-01" in msg2["message"]
    print("✓ Картридж Филиала №2 успешно отправлен с общим шаблоном и кабинетом 430")

    # Проверяем сообщение для c3 (без филиала): общий кабинет IT № 108
    msg3 = next(m for m in sent_messages if m["phone"] == "+77033333333")
    print(f"Message 3 (No branch fallback): {msg3['message']}")
    assert "Кабинет IT общий № 108" in msg3["message"]
    print("✓ Картридж без филиала успешно использовал общий кабинет IT из настроек")

    # -------------------------------------------------------------
    # 3. Тестирование печати акта
    # -------------------------------------------------------------
    print("\n--- 3. Тестирование печати акта передачи партии филиала ---")
    with next(get_db()) as db:
        batch = Batch(
            act_number="АКТ-ТЕСТ-01",
            vendor_name="ООО Сервис",
            branch_id=b2_id
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        b_item = BatchItem(batch_id=batch.id, cartridge_id=c2_id)
        db.add(b_item)
        db.commit()
        batch_id = batch.id

    res_act = client.get(f"/print/act/{batch_id}")
    assert res_act.status_code == 200
    assert "Место составления: Кабинет 430" in res_act.text
    print("✓ В печатной форме акта успешно выведен кабинет филиала партии ('Кабинет 430')")

    print("\n=== ALL BRANCH IT-OFFICE & TEMPLATE TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
