import sys
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, SessionLocal, init_db
from app.models import AppUser, Branch, Cartridge, CartridgeStatus, HistoryLog
from app.services.auth_service import AuthService

client = TestClient(app)

def run_tests():
    print("=== STARTING REPORTS VERIFICATION TESTS ===")
    init_db()
    db = SessionLocal()
    try:
        # Create test branches if needed
        b1 = db.query(Branch).filter(Branch.name == "Филиал Тест 1").first()
        if not b1:
            b1 = Branch(name="Филиал Тест 1", code="T1")
            db.add(b1)
            db.flush()

        b2 = db.query(Branch).filter(Branch.name == "Филиал Тест 2").first()
        if not b2:
            b2 = Branch(name="Филиал Тест 2", code="T2")
            db.add(b2)
            db.flush()

        # Create test users
        def get_or_create_user(username, role, branch_id=None):
            u = db.query(AppUser).filter(AppUser.username == username).first()
            if not u:
                u = AppUser(
                    username=username,
                    full_name=f"Test {username}",
                    password_hash=AuthService.hash_password("pass123"),
                    auth_type="local",
                    role=role,
                    is_active=True,
                    branch_id=branch_id
                )
                db.add(u)
                db.flush()
            else:
                u.role = role
                u.branch_id = branch_id
                db.flush()
            return u

        u_user = get_or_create_user("rep_user", "user")
        u_op = get_or_create_user("rep_op", "operator", b1.id)
        u_admin = get_or_create_user("rep_admin", "admin", b1.id)
        u_super = get_or_create_user("rep_super", "superadmin", None)

        # Create cartridges for b1 and b2
        c1 = db.query(Cartridge).filter(Cartridge.marker_label == "REP-C1").first()
        if not c1:
            c1 = Cartridge(marker_label="REP-C1", model="HP 85A", cabinet="101", branch_id=b1.id, status=CartridgeStatus.IN_USE)
            db.add(c1)
            db.flush()

        c2 = db.query(Cartridge).filter(Cartridge.marker_label == "REP-C2").first()
        if not c2:
            c2 = Cartridge(marker_label="REP-C2", model="Canon 728", cabinet="202", branch_id=b2.id, status=CartridgeStatus.PENDING_VENDOR)
            db.add(c2)
            db.flush()

        # Add history log
        log1 = HistoryLog(cartridge_id=c1.id, action="Приемка", user_name="rep_op", details="Принят на заправку")
        db.add(log1)
        db.commit()

        # Helper for headers
        def auth_header(u):
            token = AuthService.create_access_token({
                "sub": u.username,
                "role": u.role,
                "branch_id": u.branch_id
            })
            return {"Authorization": f"Bearer {token}"}

        # 1. Test role permissions
        print("\n--- 1. Testing Role Permissions ---")
        res = client.get("/api/reports/data?report_type=all", headers=auth_header(u_user))
        assert res.status_code == 403, f"Expected 403 for user role, got {res.status_code}"
        print("✓ Regular user correctly blocked (403 Forbidden)")

        res = client.get("/api/reports/data?report_type=all", headers=auth_header(u_op))
        assert res.status_code == 200, f"Expected 200 for operator, got {res.status_code}"
        print("✓ Operator can access reports")

        res = client.get("/api/reports/data?report_type=all", headers=auth_header(u_admin))
        assert res.status_code == 200, f"Expected 200 for admin, got {res.status_code}"
        print("✓ Admin can access reports")

        res = client.get("/api/reports/data?report_type=all", headers=auth_header(u_super))
        assert res.status_code == 200, f"Expected 200 for superadmin, got {res.status_code}"
        print("✓ Superadmin can access reports")

        # 2. Test branch filtering and locking
        print("\n--- 2. Testing Branch Filtering and Locking ---")
        # rep_op has branch_id = b1.id. Even if requested branch_id = b2.id, it must be locked to b1.id!
        res_op = client.get(f"/api/reports/data?report_type=all&branch_id={b2.id}", headers=auth_header(u_op)).json()
        report_op = res_op["report"]
        assert report_op["is_branch_locked"] is True, "Operator should be branch locked"
        assert report_op["branch_id"] == b1.id, f"Expected operator report branch {b1.id}, got {report_op['branch_id']}"
        markers_op = [x["marker_label"] for x in report_op["items"]]
        assert "REP-C1" in markers_op, "REP-C1 should be in operator's branch report"
        assert "REP-C2" not in markers_op, "REP-C2 should NOT be in operator's branch report"
        print("✓ Operator with assigned branch is strictly locked to their branch")

        # rep_super with no branch assigned can view b2 or all branches
        res_super_all = client.get("/api/reports/data?report_type=all", headers=auth_header(u_super)).json()["report"]
        markers_super = [x["marker_label"] for x in res_super_all["items"]]
        assert "REP-C1" in markers_super and "REP-C2" in markers_super, "Superadmin should see all cartridges"
        print("✓ Superadmin can view report for all branches")

        res_super_b2 = client.get(f"/api/reports/data?report_type=all&branch_id={b2.id}", headers=auth_header(u_super)).json()["report"]
        markers_b2 = [x["marker_label"] for x in res_super_b2["items"]]
        assert "REP-C2" in markers_b2 and "REP-C1" not in markers_b2, "Superadmin can filter by specific branch"
        print("✓ Superadmin can filter report by any specific branch")

        # 3. Test report types (all, year, month, custom)
        print("\n--- 3. Testing Report Types ---")
        # Year report
        res_year = client.get("/api/reports/data?report_type=year&year=2026", headers=auth_header(u_super)).json()["report"]
        assert res_year["report_type"] == "year"
        assert "2026" in res_year["period_title"]
        print("✓ Year report works properly")

        # Month report
        res_month = client.get("/api/reports/data?report_type=month&year=2026&month=9", headers=auth_header(u_super)).json()["report"]
        assert res_month["report_type"] == "month"
        assert "Сентябрь 2026" in res_month["period_title"]
        print("✓ Month report works properly")

        # Custom interval report
        res_custom = client.get("/api/reports/data?report_type=custom&date_from=2026-09-01&date_to=2026-09-30", headers=auth_header(u_super)).json()["report"]
        assert res_custom["report_type"] == "custom"
        assert "01.09.2026" in res_custom["period_title"]
        print("✓ Custom interval report works properly")

        # 4. Test Excel exports
        print("\n--- 4. Testing Excel Exports ---")
        res_xlsx_all = client.get("/api/reports/export/excel?report_type=all", headers=auth_header(u_super))
        assert res_xlsx_all.status_code == 200
        assert "application/vnd.openxmlformats" in res_xlsx_all.headers["content-type"]
        assert len(res_xlsx_all.content) > 1000
        print(f"✓ Excel export for 'all' generated successfully ({len(res_xlsx_all.content)} bytes)")

        res_xlsx_month = client.get("/api/reports/export/excel?report_type=month&year=2026&month=9", headers=auth_header(u_super))
        assert res_xlsx_month.status_code == 200
        assert len(res_xlsx_month.content) > 1000
        print(f"✓ Excel export for 'month' generated successfully ({len(res_xlsx_month.content)} bytes)")

        print("\n=== ALL REPORTS TESTS PASSED SUCCESSFULLY! ===")
    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
