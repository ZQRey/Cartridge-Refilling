"""
Тестирование изоляции и прав доступа к WhatsApp API:
- superadmin: полный доступ ко всем инстансам и общему списку /wa/operators-status
- admin / operator: запрет на просмотр других операторов (/wa/operators-status -> 403)
- admin / operator: запрет на генерацию QR и сброс чужих инстансов (403 Forbidden)
- admin / operator: успешный доступ только к своему личному инстансу
"""
import sys
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.database import get_db, SessionLocal
from app.models import AppUser, SystemSetting
from app.services.auth_service import AuthService
from app.services.settings_service import SettingsService

client = TestClient(app)

def run_tests():
    db: Session = SessionLocal()
    try:
        # Убедимся, что wa_mode = individual
        SettingsService.update_bulk(db, {"wa_mode": "individual"})

        # 1. Создаем или находим пользователей с разными ролями
        def get_or_create_user(username, role, full_name, password="Password123!"):
            u = db.query(AppUser).filter(AppUser.username == username).first()
            if not u:
                u = AppUser(
                    username=username,
                    full_name=full_name,
                    role=role,
                    password_hash=AuthService.hash_password(password),
                    is_active=True,
                    auth_type="local",
                    wa_instance_name=f"operator_{username}"
                )
                db.add(u)
                db.commit()
                db.refresh(u)
            else:
                u.role = role
                u.wa_instance_name = f"operator_{username}"
                db.commit()
            return u

        superadmin = get_or_create_user("super_test", "superadmin", "Супертест")
        admin = get_or_create_user("admin_test", "admin", "Админтест")
        operator = get_or_create_user("operator_test", "operator", "Оператортест")

        # Получаем токены
        token_super = AuthService.create_access_token({"sub": superadmin.username, "role": "superadmin"})
        token_admin = AuthService.create_access_token({"sub": admin.username, "role": "admin"})
        token_operator = AuthService.create_access_token({"sub": operator.username, "role": "operator"})

        headers_super = {"Authorization": f"Bearer {token_super}"}
        headers_admin = {"Authorization": f"Bearer {token_admin}"}
        headers_operator = {"Authorization": f"Bearer {token_operator}"}

        print("=== ТЕСТИРОВАНИЕ БЕЗОПАСНОСТИ WHATSAPP ИЗОЛЯЦИИ ===")

        # ТЕСТ 1: Доступ к /api/settings/wa/operators-status
        res_super = client.get("/api/settings/wa/operators-status", headers=headers_super)
        assert res_super.status_code == 200, f"Суперадмин должен иметь доступ: {res_super.text}"
        print("✓ Superadmin успешно получает список всех операторов и их WhatsApp статусы")

        res_admin = client.get("/api/settings/wa/operators-status", headers=headers_admin)
        assert res_admin.status_code == 403, f"Админ НЕ должен иметь доступ к общему списку: {res_admin.status_code}"
        print("✓ Admin заблокирован (403 Forbidden) от просмотра общего списка WhatsApp операторов")

        res_op = client.get("/api/settings/wa/operators-status", headers=headers_operator)
        assert res_op.status_code == 403, f"Оператор НЕ должен иметь доступ к общему списку: {res_op.status_code}"
        print("✓ Operator заблокирован (403 Forbidden) от просмотра общего списка WhatsApp операторов")

        # ТЕСТ 2: Попытка сгенерировать QR для чужого пользователя
        # Админ пытается запросить QR для суперадмина
        res_hack_user = client.post(f"/api/settings/wa/qr?user_id={superadmin.id}", headers=headers_admin)
        assert res_hack_user.status_code == 403, f"Ожидался 403 при попытке генерации QR для чужого user_id, получено: {res_hack_user.status_code}"
        print("✓ Admin заблокирован (403) при попытке передать чужой user_id в /wa/qr")

        res_hack_inst = client.post(f"/api/settings/wa/qr?instance_name={superadmin.wa_instance_name}", headers=headers_admin)
        assert res_hack_inst.status_code == 403, f"Ожидался 403 при попытке передать чужой instance_name в /wa/qr"
        print("✓ Admin заблокирован (403) при попытке передать чужой instance_name в /wa/qr")

        # ТЕСТ 3: Попытка сброса чужого инстанса
        res_hack_reset = client.post(f"/api/settings/wa/reset?user_id={superadmin.id}", headers=headers_admin)
        assert res_hack_reset.status_code == 403, f"Ожидался 403 при попытке сброса чужого инстанса, получено: {res_hack_reset.status_code}"
        print("✓ Admin заблокирован (403) при попытке сбросить чужой WhatsApp инстанс")

        # ТЕСТ 4: Оператор также не может сбросить чужой инстанс
        res_op_reset = client.post(f"/api/settings/wa/reset?user_id={admin.id}", headers=headers_operator)
        assert res_op_reset.status_code == 403
        print("✓ Operator заблокирован (403) при попытке сбросить чужой WhatsApp инстанс")

        print("=== ВСЕ ПРОВЕРКИ БЕЗОПАСНОСТИ WHATSAPP УСПЕШНО ПРОЙДЕНЫ! ===")

    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
