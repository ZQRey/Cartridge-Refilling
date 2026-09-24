import os
import sys
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB_PATH = "test_rbac.db"
if os.path.exists(TEST_DB_PATH):
    try:
        os.remove(TEST_DB_PATH)
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from app.database import Base, get_db, init_db
from app.main import app
from app.models import AppUser, Branch, Cartridge, ADUser
from app.services.auth_service import AuthService

# Use test client
client = TestClient(app)

def run_tests():
    print("=== STARTING RBAC VERIFICATION TESTS ===")
    
    # 1. Test Database Init and Superadmin Creation
    init_db()
    
    # Create test users for each of the 4 roles
    with next(get_db()) as db:
        # Branch 1 and Branch 2
        b1 = Branch(name="Филиал Север", code="NORTH")
        b2 = Branch(name="Филиал Юг", code="SOUTH")
        db.add_all([b1, b2])
        db.commit()
        db.refresh(b1)
        db.refresh(b2)
        b1_id, b2_id = b1.id, b2.id
        
        # Superadmin (already created as 'admin' in init_db, verify role)
        admin_user = db.query(AppUser).filter(AppUser.username == "admin").first()
        assert admin_user is not None, "Admin user should exist"
        assert admin_user.role == "superadmin", f"Admin user should have role superadmin, got {admin_user.role}"
        print("✓ init_db correctly set admin to superadmin")
        
        # Admin for Branch 1
        admin_b1 = AppUser(
            username="admin_b1",
            full_name="Админ Севера",
            password_hash=AuthService.hash_password("pass123"),
            auth_type="local",
            role="admin",
            branch_id=b1_id,
            is_active=True
        )
        # Operator for Branch 1
        operator_b1 = AppUser(
            username="op_b1",
            full_name="Оператор Севера",
            password_hash=AuthService.hash_password("pass123"),
            auth_type="local",
            role="operator",
            branch_id=b1_id,
            is_active=True
        )
        # AD User 1
        ad_user1 = AppUser(
            username="ivanov",
            full_name="Иванов Иван",
            password_hash=None,
            auth_type="ad",
            role="user",
            branch_id=b1_id,
            is_active=True
        )
        # AD User 2
        ad_user2 = AppUser(
            username="petrov",
            full_name="Петров Петр",
            password_hash=None,
            auth_type="ad",
            role="user",
            branch_id=b2_id,
            is_active=True
        )
        db.add_all([admin_b1, operator_b1, ad_user1, ad_user2])
        db.commit()

        # Add Cartridges:
        # Cartridge 1: in Branch 1, assigned to ivanov
        # Cartridge 2: in Branch 1, assigned to someone else
        # Cartridge 3: in Branch 2, assigned to petrov
        c1 = Cartridge(
            marker_label="CART-1",
            model="HP 12A",
            cabinet="101",
            branch_id=b1_id,
            current_user_id="ivanov",
            status="in_use"
        )
        c2 = Cartridge(
            marker_label="CART-2",
            model="Canon 728",
            cabinet="102",
            branch_id=b1_id,
            current_user_id="sidorov",
            status="in_use"
        )
        c3 = Cartridge(
            marker_label="CART-3",
            model="HP 85A",
            cabinet="201",
            branch_id=b2_id,
            current_user_id="petrov",
            status="in_use"
        )
        db.add_all([c1, c2, c3])
        db.commit()
        c1_id = c1.id
        c2_id = c2.id
        c3_id = c3.id

    # Helper for creating tokens
    def get_token(username):
        with next(get_db()) as db:
            user = db.query(AppUser).filter(AppUser.username == username).first()
            return AuthService.create_access_token({
                "sub": user.username,
                "role": user.role,
                "branch_id": user.branch_id
            })

    token_superadmin = get_token("admin")
    token_admin_b1 = get_token("admin_b1")
    token_op_b1 = get_token("op_b1")
    token_user_ivanov = get_token("ivanov")
    token_user_petrov = get_token("petrov")

    # ==========================================
    # TEST 1: User (ivanov) - Strictly Limited
    # ==========================================
    print("\n--- Testing 'user' role (ivanov) ---")
    
    # 1.1 Registry: Only see their own cartridges
    res = client.get("/api/cartridges", headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    items = res.json()
    assert len(items) == 1, f"User ivanov should only see 1 cartridge, got {len(items)}"
    assert items[0]["marker_label"] == "CART-1", f"Expected CART-1, got {items[0]['marker_label']}"
    print("✓ User only sees cartridges assigned to them")

    # 1.2 Access specific cartridge detail: allowed for own, 403 for someone else's
    res_own = client.get(f"/api/cartridges/{c1_id}", headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res_own.status_code == 200, f"Expected 200 for own cartridge, got {res_own.status_code}"
    res_other = client.get(f"/api/cartridges/{c2_id}", headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res_other.status_code == 403, f"Expected 403 for other's cartridge, got {res_other.status_code}"
    print("✓ User blocked from viewing other cartridges by direct ID")

    # 1.3 Blocked from operator actions (accept, batches, return, issue)
    res_accept = client.post("/api/cartridges/accept", json={"cartridge_id": c1_id}, headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res_accept.status_code == 403, f"Expected 403 on accept, got {res_accept.status_code}"
    res_batch = client.get("/api/batches", headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res_batch.status_code == 403, f"Expected 403 on batches, got {res_batch.status_code}"
    res_settings = client.post("/api/settings", json={"settings": {}}, headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res_settings.status_code == 403, f"Expected 403 on settings, got {res_settings.status_code}"
    res_users = client.get("/api/app-users", headers={"Authorization": f"Bearer {token_user_ivanov}"})
    assert res_users.status_code == 403, f"Expected 403 on app-users, got {res_users.status_code}"
    print("✓ User blocked from all operator, admin, and settings endpoints")

    # ==========================================
    # TEST 2: Operator (op_b1)
    # ==========================================
    print("\n--- Testing 'operator' role (op_b1) ---")
    
    # 2.1 Registry: Sees cartridges of Branch 1 (CART-1, CART-2), NOT Branch 2 (CART-3)
    res = client.get("/api/cartridges", headers={"Authorization": f"Bearer {token_op_b1}"})
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2, f"Operator should see 2 cartridges of their branch, got {len(items)}"
    labels = {c["marker_label"] for c in items}
    assert labels == {"CART-1", "CART-2"}, f"Expected CART-1 and CART-2, got {labels}"
    print("✓ Operator sees cartridges of their own branch")

    # 2.2 Operator can accept cartridge
    res_accept = client.post("/api/cartridges/accept", json={
        "marker_label": "NEW-1",
        "model": "HP 12A",
        "cabinet": "105",
        "notes": "Принят на заправку"
    }, headers={"Authorization": f"Bearer {token_op_b1}"})
    assert res_accept.status_code == 200, f"Expected 200 on accept, got {res_accept.status_code}: {res_accept.text}"
    print("✓ Operator can accept cartridges")

    # 2.3 Operator CANNOT delete cartridge
    res_del = client.delete(f"/api/cartridges/{c1_id}", headers={"Authorization": f"Bearer {token_op_b1}"})
    assert res_del.status_code == 403, f"Expected 403 for operator deleting cartridge, got {res_del.status_code}"
    print("✓ Operator blocked from deleting cartridges")

    # 2.4 Operator CANNOT access Settings, Branches CRUD, or App-Users
    res_branch = client.post("/api/branches", json={"name": "Новый филиал"}, headers={"Authorization": f"Bearer {token_op_b1}"})
    assert res_branch.status_code == 403, f"Expected 403 for operator on branch create, got {res_branch.status_code}"
    res_users = client.get("/api/app-users", headers={"Authorization": f"Bearer {token_op_b1}"})
    assert res_users.status_code == 403, f"Expected 403 for operator on app-users, got {res_users.status_code}"
    res_settings = client.post("/api/settings", json={"settings": {}}, headers={"Authorization": f"Bearer {token_op_b1}"})
    assert res_settings.status_code == 403, f"Expected 403 for operator on settings, got {res_settings.status_code}"
    print("✓ Operator blocked from branches, users management, and settings save")

    # ==========================================
    # TEST 3: Administrator (admin_b1)
    # ==========================================
    print("\n--- Testing 'admin' role (admin_b1) ---")
    
    # 3.1 Admin can create branch
    res_branch = client.post("/api/branches", json={"name": "Филиал Восток", "code": "EAST"}, headers={"Authorization": f"Bearer {token_admin_b1}"})
    assert res_branch.status_code == 201, f"Expected 201 for admin creating branch, got {res_branch.status_code}"
    print("✓ Admin can manage branches")

    # 3.2 Admin can delete cartridges of their branch
    res_del = client.delete(f"/api/cartridges/{c2_id}", headers={"Authorization": f"Bearer {token_admin_b1}"})
    assert res_del.status_code == 200, f"Expected 200 for admin deleting cartridge, got {res_del.status_code}"
    print("✓ Admin can delete cartridges")

    # 3.3 Admin CANNOT access Users management or Save System Settings
    res_users = client.get("/api/app-users", headers={"Authorization": f"Bearer {token_admin_b1}"})
    assert res_users.status_code == 403, f"Expected 403 for admin on app-users, got {res_users.status_code}"
    res_settings = client.post("/api/settings", json={"settings": {}}, headers={"Authorization": f"Bearer {token_admin_b1}"})
    assert res_settings.status_code == 403, f"Expected 403 for admin on save settings, got {res_settings.status_code}"
    print("✓ Admin blocked from user management and system settings")

    # ==========================================
    # TEST 4: Superadmin (admin)
    # ==========================================
    print("\n--- Testing 'superadmin' role (admin) ---")
    
    # 4.1 Superadmin can manage AppUsers
    res_users = client.get("/api/app-users", headers={"Authorization": f"Bearer {token_superadmin}"})
    assert res_users.status_code == 200, f"Expected 200, got {res_users.status_code}"
    assert len(res_users.json()) >= 4
    print("✓ Superadmin can access users management")

    # 4.2 Superadmin can save settings
    res_settings = client.post("/api/settings", json={"settings": {"org_name": "ООО Ромашка"}}, headers={"Authorization": f"Bearer {token_superadmin}"})
    assert res_settings.status_code == 200, f"Expected 200, got {res_settings.status_code}"
    print("✓ Superadmin can save system settings")

    # 4.3 Superadmin sees all cartridges across all branches
    res = client.get("/api/cartridges", headers={"Authorization": f"Bearer {token_superadmin}"})
    assert res.status_code == 200
    # ==========================================
    # TEST 5: AD Login without domain prefix/suffix
    # ==========================================
    print("\n--- Testing AD login normalization (ivanov vs ivanov@gp1.loc) ---")
    from unittest.mock import patch

    # 5.1 Simple login 'sidorov'
    with patch("app.services.ldap_service.LDAPService.authenticate_ad_user") as mock_auth:
        mock_auth.return_value = (True, "sidorov", {"samaccountname": "sidorov", "display_name": "Сидоров С.", "department": "Бухгалтерия", "cabinet": "205", "phone": "+79991112233"})
        with next(get_db()) as db:
            user = AuthService.authenticate_user(db, "sidorov", "ad_pass", auth_type="ad")
            assert user is not None
            assert user.username == "sidorov", f"Expected sidorov, got {user.username}"
            assert user.role == "user", f"Expected default role 'user', got {user.role}"
            assert user.full_name == "Сидоров С."
            print("✓ AD user logging in with simple 'sidorov' gets authenticated with clean username and 'user' role")

    # 5.2 Login with suffix 'kuznetsov@gp1.loc' -> gets normalized to 'kuznetsov'
    with patch("app.services.ldap_service.LDAPService.authenticate_ad_user") as mock_auth:
        mock_auth.return_value = (True, "kuznetsov", {"samaccountname": "kuznetsov", "display_name": "Кузнецов К.", "department": "IT", "cabinet": "108", "phone": None})
        with next(get_db()) as db:
            user = AuthService.authenticate_user(db, "kuznetsov@gp1.loc", "ad_pass", auth_type="ad")
            assert user is not None
            assert user.username == "kuznetsov", f"Expected kuznetsov, got {user.username}"
            assert user.role == "user"
            print("✓ AD user logging in with 'kuznetsov@gp1.loc' is automatically normalized to 'kuznetsov'")

    # 5.3 Verify DB cleanup of old @domain usernames in init_db()
    with next(get_db()) as db:
        old_ad_user = AppUser(
            username="olduser@gp1.loc",
            full_name="Старый Пользователь",
            auth_type="ad",
            role="user"
        )
        db.add(old_ad_user)
        db.commit()

    init_db()

    with next(get_db()) as db:
        cleaned_user = db.query(AppUser).filter(AppUser.full_name == "Старый Пользователь").first()
        assert cleaned_user.username == "olduser", f"Expected cleaned username 'olduser', got {cleaned_user.username}"
        print("✓ init_db correctly stripped @gp1.loc from existing AD user in database")

    # 5.4 Verify role persistence across init_db() calls
    with next(get_db()) as db:
        ad_admin = AppUser(
            username="ad_admin_user",
            full_name="Доменный Администратор",
            auth_type="ad",
            role="admin"
        )
        ad_superadmin = AppUser(
            username="ad_superadmin_user",
            full_name="Доменный Супер Администратор",
            auth_type="ad",
            role="superadmin"
        )
        ad_operator = AppUser(
            username="ad_operator_user",
            full_name="Доменный Оператор",
            auth_type="ad",
            role="operator"
        )
        db.add_all([ad_admin, ad_superadmin, ad_operator])
        db.commit()

    # Simulate container restart
    init_db()

    with next(get_db()) as db:
        u_adm = db.query(AppUser).filter(AppUser.username == "ad_admin_user").first()
        u_sup = db.query(AppUser).filter(AppUser.username == "ad_superadmin_user").first()
        u_op = db.query(AppUser).filter(AppUser.username == "ad_operator_user").first()
        assert u_adm.role == "admin", f"Role was reset! Expected 'admin', got '{u_adm.role}'"
        assert u_sup.role == "superadmin", f"Role was reset! Expected 'superadmin', got '{u_sup.role}'"
        assert u_op.role == "operator", f"Role was reset! Expected 'operator', got '{u_op.role}'"
        print("✓ Roles for AD users (admin, superadmin, operator) persist across init_db() restarts")

    print("\n=== ALL RBAC & AD LOGIN TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
