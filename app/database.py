from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import DATABASE_URL, DEFAULT_SETTINGS, SETTING_DESCRIPTIONS

# Поддержка SQLite и PostgreSQL
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Инициализация базы данных и создание таблиц, а также первичная запись настроек, филиалов и администратора."""
    from app import models  # noqa: F401
    from app.services.auth_service import AuthService
    Base.metadata.create_all(bind=engine)

    # 0. Автоматическая миграция схемы для существующих баз данных SQLite
    try:
        with engine.connect() as conn:
            # cartridges.branch_id
            cols_cart = [
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(cartridges);").fetchall()
            ]
            if cols_cart and "branch_id" not in cols_cart:
                conn.exec_driver_sql("ALTER TABLE cartridges ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;")
                conn.commit()

            # batches.branch_id
            cols_batch = [
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(batches);").fetchall()
            ]
            if cols_batch and "branch_id" not in cols_batch:
                conn.exec_driver_sql("ALTER TABLE batches ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;")
                conn.commit()

            # app_users.wa_instance_name
            cols_users = [
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(app_users);").fetchall()
            ]
            if cols_users and "wa_instance_name" not in cols_users:
                conn.exec_driver_sql("ALTER TABLE app_users ADD COLUMN wa_instance_name VARCHAR(100);")
                conn.commit()
    except Exception as ex:
        print(f"[MIGRATION CHECK] Schema migration warning: {ex}")
    
    db = SessionLocal()
    try:
        # 1. Инициализация дефолтных настроек
        existing_keys = {
            s.key for s in db.query(models.SystemSetting.key).all()
        }
        for key, val in DEFAULT_SETTINGS.items():
            if key not in existing_keys:
                db.add(
                    models.SystemSetting(
                        key=key,
                        value=val,
                        description=SETTING_DESCRIPTIONS.get(key, "")
                    )
                )

        # 2. Инициализация филиала по умолчанию
        main_branch = db.query(models.Branch).first()
        if not main_branch:
            main_branch = models.Branch(
                name="Главный офис",
                code="HQ",
                address="Центральный офис",
                notes="Основной филиал компании"
            )
            db.add(main_branch)
            db.flush()

        # 3. Инициализация локального суперпользователя (admin / admin123)
        admin_user = db.query(models.AppUser).filter(models.AppUser.username == "admin").first()
        if not admin_user:
            admin_user = models.AppUser(
                username="admin",
                full_name="Главный Администратор",
                password_hash=AuthService.hash_password("admin123"),
                auth_type="local",
                role="superadmin",
                is_active=True,
                branch_id=None  # Доступ ко всем филиалам
            )
            db.add(admin_user)
        else:
            if admin_user.role == "admin":
                admin_user.role = "superadmin"

        # 4. Безопасность: сброс прав всех доменных пользователей (AD), которые ранее получили admin/superadmin, до 'user'
        db.query(models.AppUser).filter(
            models.AppUser.auth_type == "ad",
            models.AppUser.role.in_(["admin", "superadmin"])
        ).update({models.AppUser.role: "user"}, synchronize_session=False)

        # 5. Очистка логинов существующих AD-пользователей от доменных префиксов/суффиксов (@...)
        ad_users = db.query(models.AppUser).filter(models.AppUser.auth_type == "ad").all()
        for u in ad_users:
            if "@" in u.username or "\\" in u.username:
                clean_name = u.username.split("@")[0].split("\\")[-1].strip()
                existing = db.query(models.AppUser).filter(models.AppUser.username == clean_name, models.AppUser.id != u.id).first()
                if not existing:
                    u.username = clean_name

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[INIT DB ERROR] Error initializing database: {e}")
    finally:
        db.close()
