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
                role="admin",
                is_active=True,
                branch_id=None  # Доступ ко всем филиалам
            )
            db.add(admin_user)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[INIT DB ERROR] Error initializing database: {e}")
    finally:
        db.close()
