import os
import sys
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup test database
TEST_DB_FILE = "test_user_requirements.db"
if os.path.exists(TEST_DB_FILE):
    try:
        os.remove(TEST_DB_FILE)
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE}"

from app.main import app
from app.database import Base, get_db
from app.models import AppUser, Branch, Cartridge, CartridgeStatus, Batch, BatchItem
from app.services.auth_service import AuthService

engine = create_engine(f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

class TestUserRequirements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = TestingSessionLocal()
        # Create Branches
        b1 = Branch(name="Филиал Север", it_office="Кабинет 101", wa_message_template="Заберите из 101")
        b2 = Branch(name="Филиал Юг", it_office="Кабинет 202", wa_message_template="Заберите из 202")
        db.add_all([b1, b2])
        db.commit()
        db.refresh(b1)
        db.refresh(b2)
        cls.b1_id = b1.id
        cls.b2_id = b2.id

        # Create Users
        # 1. Superadmin
        superadmin = AppUser(
            username="superadmin_test",
            full_name="Главный Администратор",
            password_hash=AuthService.hash_password("admin123"),
            role="superadmin",
            is_active=True
        )
        # 2. Operator Branch 1
        op1 = AppUser(
            username="op_north",
            full_name="Оператор Север",
            password_hash=AuthService.hash_password("op123"),
            role="operator",
            branch_id=b1.id,
            is_active=True
        )
        # 3. Operator Branch 2
        op2 = AppUser(
            username="op_south",
            full_name="Оператор Юг",
            password_hash=AuthService.hash_password("op123"),
            role="operator",
            branch_id=b2.id,
            is_active=True
        )
        db.add_all([superadmin, op1, op2])
        db.commit()

        # Generate tokens
        cls.superadmin_token = AuthService.create_access_token({"sub": "superadmin_test", "role": "superadmin"})
        cls.op1_token = AuthService.create_access_token({"sub": "op_north", "role": "operator"})
        cls.op2_token = AuthService.create_access_token({"sub": "op_south", "role": "operator"})

        # Create Cartridges
        # Cartridge 1: in b1, status pending_vendor
        c1 = Cartridge(
            marker_label="CART-B1-01",
            model="HP LaserJet 1010",
            cabinet="105",
            branch_id=b1.id,
            status=CartridgeStatus.PENDING_VENDOR
        )
        # Cartridge 2: in b1, status pending_vendor
        c2 = Cartridge(
            marker_label="CART-B1-02",
            model="Canon 725",
            cabinet="106",
            branch_id=b1.id,
            status=CartridgeStatus.PENDING_VENDOR
        )
        # Cartridge 3: in b2, status pending_vendor
        c3 = Cartridge(
            marker_label="CART-B2-01",
            model="Xerox 3020",
            cabinet="205",
            branch_id=b2.id,
            status=CartridgeStatus.PENDING_VENDOR
        )
        db.add_all([c1, c2, c3])
        db.commit()
        db.refresh(c1)
        db.refresh(c2)
        db.refresh(c3)
        cls.c1_id = c1.id
        cls.c2_id = c2.id
        cls.c3_id = c3.id
        db.close()

    def test_01_status_filter_works_properly(self):
        """Проверка требования 2: фильтр по статусу в /api/cartridges строго фильтрует."""
        res_pending = client.get(
            "/api/cartridges?status=pending_vendor",
            headers={"Authorization": f"Bearer {self.superadmin_token}"}
        )
        self.assertEqual(res_pending.status_code, 200)
        items = res_pending.json()
        self.assertTrue(all(item["status"] == "pending_vendor" for item in items))
        self.assertEqual(len(items), 3)

        res_at_vendor = client.get(
            "/api/cartridges?status=at_vendor",
            headers={"Authorization": f"Bearer {self.superadmin_token}"}
        )
        self.assertEqual(res_at_vendor.status_code, 200)
        self.assertEqual(len(res_at_vendor.json()), 0)

    def test_02_batch_creation_branch_enforcement(self):
        """Проверка требования 1: Акт передачи формируется на основе филиала оператора."""
        # 1. Оператор Север пытается сформировать акт с картриджем Юга (c3) -> должен получить 403
        res_fail = client.post(
            "/api/batches",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={
                "cartridge_ids": [self.c1_id, self.c3_id],
                "vendor_name": "ООО Сервис"
            }
        )
        self.assertEqual(res_fail.status_code, 403)

        # 2. Оператор Север формирует акт для своих картриджей c1, c2 -> Успешно, филиал b1_id
        res_ok = client.post(
            "/api/batches",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={
                "cartridge_ids": [self.c1_id, self.c2_id],
                "vendor_name": "ООО Сервис"
            }
        )
        self.assertEqual(res_ok.status_code, 200)
        batch_data = res_ok.json()
        self.assertEqual(batch_data["branch_id"], self.b1_id)

        # Проверяем, что картриджи c1 и c2 перешли в at_vendor
        res_vendor = client.get(
            "/api/cartridges?status=at_vendor",
            headers={"Authorization": f"Bearer {self.op1_token}"}
        )
        self.assertEqual(res_vendor.status_code, 200)
        vendor_ids = [c["id"] for c in res_vendor.json()]
        self.assertIn(self.c1_id, vendor_ids)
        self.assertIn(self.c2_id, vendor_ids)

        # И они больше НЕ числятся в pending_vendor
        res_pending_b1 = client.get(
            "/api/cartridges?status=pending_vendor",
            headers={"Authorization": f"Bearer {self.op1_token}"}
        )
        self.assertEqual(len(res_pending_b1.json()), 0)

    def test_03_superadmin_can_choose_all_or_specific_branch(self):
        """Проверка требования 1: Супер-администратор может создавать акт для любого филиала или общий."""
        res_super = client.post(
            "/api/batches",
            headers={"Authorization": f"Bearer {self.superadmin_token}"},
            json={
                "cartridge_ids": [self.c3_id],
                "branch_id": self.b2_id,
                "vendor_name": "ООО МегаСервис"
            }
        )
        self.assertEqual(res_super.status_code, 200)
        self.assertEqual(res_super.json()["branch_id"], self.b2_id)

    def test_04_return_from_vendor_disappears_from_at_vendor(self):
        """Проверка требования 2: при возврате картридж уходит из 'На заправке' и появляется в 'Готов к выдаче'."""
        # Возвращаем c1 с заправки
        res_return = client.post(
            "/api/cartridges/return-vendor",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={"cartridge_ids": [self.c1_id]}
        )
        self.assertEqual(res_return.status_code, 200)

        # Проверяем список 'На заправке' для b1 -> c1 БОЛЬШЕ НЕ ДОЛЖЕН ТАМ БЫТЬ!
        res_vendor = client.get(
            "/api/cartridges?status=at_vendor",
            headers={"Authorization": f"Bearer {self.op1_token}"}
        )
        self.assertEqual(res_vendor.status_code, 200)
        vendor_ids = [c["id"] for c in res_vendor.json()]
        self.assertNotIn(self.c1_id, vendor_ids)
        self.assertIn(self.c2_id, vendor_ids)

        # Проверяем список 'Готов к выдаче' -> c1 ДОЛЖЕН ТАМ БЫТЬ!
        res_ready = client.get(
            "/api/cartridges?status=ready_for_pickup",
            headers={"Authorization": f"Bearer {self.op1_token}"}
        )
        self.assertEqual(res_ready.status_code, 200)
        ready_ids = [c["id"] for c in res_ready.json()]
        self.assertIn(self.c1_id, ready_ids)

    def test_05_whatsapp_report_modal_and_manual_issue(self):
        """Проверка требования 3: рассылка WhatsApp возвращает карточки всех картриджей, и ручная выдача работает."""
        # Рассылка WhatsApp для готового картриджа c1
        res_wa = client.post(
            "/api/notifications/whatsapp/ready",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={"cartridge_ids": [self.c1_id]}
        )
        self.assertEqual(res_wa.status_code, 200)
        wa_data = res_wa.json()
        self.assertEqual(wa_data["total"], 1)
        self.assertEqual(len(wa_data["results"]), 1)
        self.assertEqual(wa_data["results"][0]["cartridge_id"], self.c1_id)
        self.assertFalse(wa_data["results"][0]["success"])
        self.assertIsNotNone(wa_data["results"][0]["error"])

        # Ручная выдача картриджа c1 через POST /api/cartridges/{id}/issue с JSON телом
        res_issue = client.post(
            f"/api/cartridges/{self.c1_id}/issue",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={"notes": "Выдан вручную из теста"}
        )
        self.assertEqual(res_issue.status_code, 200)
        self.assertTrue(res_issue.json()["success"])

        # Проверяем, что статус c1 стал in_use
        res_c1 = client.get(
            f"/api/cartridges/{self.c1_id}",
            headers={"Authorization": f"Bearer {self.op1_token}"}
        )
        self.assertEqual(res_c1.status_code, 200)
        self.assertEqual(res_c1.json()["status"], "in_use")

    def test_06_bulk_issue_works(self):
        """Проверка массовой ручной выдачи /api/cartridges/bulk-issue."""
        # Возвращаем c2
        client.post(
            "/api/cartridges/return-vendor",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={"cartridge_ids": [self.c2_id]}
        )

        res_bulk = client.post(
            "/api/cartridges/bulk-issue",
            headers={"Authorization": f"Bearer {self.op1_token}"},
            json={"cartridge_ids": [self.c2_id], "notes": "Массовая выдача"}
        )
        self.assertEqual(res_bulk.status_code, 200)
        self.assertEqual(res_bulk.json()["issued_count"], 1)

        res_c2 = client.get(
            f"/api/cartridges/{self.c2_id}",
            headers={"Authorization": f"Bearer {self.op1_token}"}
        )
        self.assertEqual(res_c2.json()["status"], "in_use")

if __name__ == "__main__":
    unittest.main()
