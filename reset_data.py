"""
Скрипт для очистки тестовых данных в Cartridge Tracker.

Использование:
  python reset_data.py             # Очистка только тестового оборота (картриджи, акты, история), сохраняя настройки и пользователей
  python reset_data.py --full      # Полный сброс всей базы данных до заводского состояния (чистый admin/admin123)
"""
import os
import sys
import argparse
from app.config import DEFAULT_SQLITE_PATH
from app.database import SessionLocal, init_db, engine
from app import models

def reset_test_cartridges(clear_ad_users=False):
    """
    Очищает только тестовые картриджи, акты и историю движения.
    Сохраняет:
    - Настройки организации и WhatsApp
    - Филиалы
    - Учетные записи пользователей и их роли
    - Справочник моделей картриджей
    """
    db = SessionLocal()
    try:
        count_logs = db.query(models.HistoryLog).delete()
        count_items = db.query(models.BatchItem).delete()
        count_batches = db.query(models.Batch).delete()
        count_carts = db.query(models.Cartridge).delete()
        
        count_ad = 0
        if clear_ad_users:
            count_ad = db.query(models.ADUser).delete()

        db.commit()
        print("=== Очистка тестовых данных успешно завершена ===")
        print(f"✓ Удалено картриджей: {count_carts}")
        print(f"✓ Удалено актов передачи/партий: {count_batches} (позиций: {count_items})")
        print(f"✓ Удалено записей в журнале истории: {count_logs}")
        if clear_ad_users:
            print(f"✓ Очищен кэш сотрудников AD: {count_ad}")
        print("\nСохранены:")
        print(f"- Учетные записи системы: {db.query(models.AppUser).count()}")
        print(f"- Филиалы: {db.query(models.Branch).count()}")
        print(f"- Модели картриджей: {db.query(models.CartridgeModel).count()}")
        print(f"- Системные настройки: {db.query(models.SystemSetting).count()}")
    except Exception as e:
        db.rollback()
        print(f"Ошибка при очистке: {e}")
    finally:
        db.close()

def reset_full_database():
    """
    Полное удаление файла SQLite и повторная инициализация 'с чистого листа'.
    """
    db_path = DEFAULT_SQLITE_PATH
    print(f"Полный сброс базы данных: {db_path}")
    
    # Закрываем соединения
    engine.dispose()
    
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print("✓ Старый файл базы данных удален.")
        except Exception as e:
            print(f"Не удалось удалить файл (возможно, сервер запущен): {e}")
            print("Остановите сервер uvicorn/контейнер перед полным удалением файла.")
            return

    init_db()
    print("✓ База данных заново создана и проинициализирована по умолчанию.")
    print("  Суперпользователь: admin / admin123")
    print("  Филиал по умолчанию: Главный офис")
    print("  Справочник моделей: базовый набор HP, Canon, Pantum, Kyocera, Samsung")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Очистка тестовых данных Cartridge Tracker")
    parser.add_argument("--full", action="store_true", help="Полное удаление базы и возврат к заводским настройкам")
    parser.add_argument("--clear-ad-users", action="store_true", help="Также очистить кэш синхронизированных пользователей Active Directory")
    args = parser.parse_args()

    if args.full:
        reset_full_database()
    else:
        reset_test_cartridges(clear_ad_users=args.clear_ad_users)
