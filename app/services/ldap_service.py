from datetime import datetime
from typing import Dict, Any, List, Tuple
from sqlalchemy.orm import Session
import ldap3
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException

from app.models import ADUser
from app.services.settings_service import SettingsService


class LDAPService:
    @staticmethod
    def _create_connection(
        host: str,
        bind_user: str,
        bind_password: str,
        connect_timeout: int = 5
    ) -> Connection:
        """Создает и возвращает объект Connection библиотеки ldap3."""
        use_ssl = host.startswith("ldaps://")
        
        # Очищаем хост от префикса если нужно для Server
        server_address = host
        if host.startswith("ldap://"):
            server_address = host.replace("ldap://", "")
        elif host.startswith("ldaps://"):
            server_address = host.replace("ldaps://", "")

        port = 636 if use_ssl else 389
        if ":" in server_address:
            parts = server_address.split(":")
            server_address = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                pass

        server = Server(
            host=server_address,
            port=port,
            use_ssl=use_ssl,
            get_info=ALL,
            connect_timeout=connect_timeout
        )

        conn = Connection(
            server,
            user=bind_user,
            password=bind_password,
            auto_bind=True,
            read_only=True
        )
        return conn

    @classmethod
    def test_connection(
        cls,
        db: Session,
        host: str = None,
        base_dn: str = None,
        bind_user: str = None,
        bind_password: str = None
    ) -> Dict[str, Any]:
        """Проверяет подключение к LDAP/AD серверу."""
        settings = SettingsService.get_all(db)
        h = host or settings.get("ad_host")
        u = bind_user or settings.get("ad_bind_user")
        p = bind_password if bind_password is not None else settings.get("ad_bind_password")
        b = base_dn or settings.get("ad_base_dn")

        if not h or not u:
            return {
                "success": False,
                "message": "Не указан адрес LDAP сервера или учетная запись Bind DN."
            }

        try:
            conn = cls._create_connection(h, u, p, connect_timeout=5)
            # Тестовый поиск
            search_ok = conn.search(
                search_base=b,
                search_filter="(objectClass=*)",
                search_scope=SUBTREE,
                size_limit=1
            )
            conn.unbind()
            return {
                "success": True,
                "message": f"Подключение к серверу {h} успешно установлено. Доступ к Base DN подтвержден."
            }
        except LDAPException as e:
            return {
                "success": False,
                "message": f"Ошибка LDAP: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Сетевая или системная ошибка: {str(e)}"
            }

    @classmethod
    def sync_users(cls, db: Session) -> Dict[str, Any]:
        """Синхронизирует пользователей из Active Directory в локальную таблицу ad_users."""
        settings = SettingsService.get_all(db)
        host = settings.get("ad_host")
        base_dn = settings.get("ad_base_dn")
        bind_user = settings.get("ad_bind_user")
        bind_password = settings.get("ad_bind_password")
        
        attr_name = settings.get("ad_attr_name", "displayName").strip()
        attr_cabinet = settings.get("ad_attr_cabinet", "physicalDeliveryOfficeName").strip()
        attr_dept = settings.get("ad_attr_department", "department").strip()
        attr_phones_str = settings.get("ad_attr_phone", "mobile,telephoneNumber")
        phone_attrs = [p.strip() for p in attr_phones_str.split(",") if p.strip()]
        
        search_filter = settings.get(
            "ad_filter",
            "(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
        )

        if not host or not base_dn or not bind_user:
            return {
                "success": False,
                "synced_count": 0,
                "message": "Настройки LDAP не заполнены (требуются Host, Base DN и Bind User)."
            }

        try:
            conn = cls._create_connection(host, bind_user, bind_password, connect_timeout=10)
        except Exception as e:
            return {
                "success": False,
                "synced_count": 0,
                "message": f"Не удалось подключиться к LDAP: {str(e)}"
            }

        # Все запрашиваемые атрибуты
        req_attributes = ["sAMAccountName", attr_name, attr_cabinet, attr_dept] + phone_attrs

        try:
            conn.search(
                search_base=base_dn,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=req_attributes
            )
            entries = conn.entries
        except Exception as e:
            conn.unbind()
            return {
                "success": False,
                "synced_count": 0,
                "message": f"Ошибка выполнения поиска в каталоге: {str(e)}"
            }

        synced_count = 0
        now = datetime.utcnow()

        try:
            for entry in entries:
                sam = getattr(entry, "sAMAccountName", None)
                if not sam or not str(sam.value).strip():
                    continue

                sam_account = str(sam.value).strip()

                # Имя
                disp_val = getattr(entry, attr_name, None)
                display_name = str(disp_val.value).strip() if disp_val and disp_val.value else sam_account

                # Кабинет
                cab_val = getattr(entry, attr_cabinet, None)
                cabinet = str(cab_val.value).strip() if cab_val and cab_val.value else None

                # Отдел
                dept_val = getattr(entry, attr_dept, None)
                department = str(dept_val.value).strip() if dept_val and dept_val.value else None

                # Телефон (проверяем по цепочке)
                phone = None
                for pattr in phone_attrs:
                    pval = getattr(entry, pattr, None)
                    if pval and pval.value:
                        # Если это список или строка
                        raw_p = pval.value
                        if isinstance(raw_p, list) and len(raw_p) > 0:
                            raw_p = raw_p[0]
                        phone_str = str(raw_p).strip()
                        if phone_str:
                            phone = phone_str
                            break

                # Upsert в базу
                user = db.query(ADUser).filter(ADUser.samaccountname == sam_account).first()
                if user:
                    user.display_name = display_name
                    user.department = department
                    user.cabinet = cabinet
                    user.phone = phone
                    user.updated_at = now
                else:
                    db.add(
                        ADUser(
                            samaccountname=sam_account,
                            display_name=display_name,
                            department=department,
                            cabinet=cabinet,
                            phone=phone,
                            updated_at=now
                        )
                    )
                synced_count += 1

            db.commit()
            conn.unbind()
            return {
                "success": True,
                "synced_count": synced_count,
                "message": f"Синхронизация завершена. Обработано пользователей: {synced_count}."
            }
        except Exception as e:
            db.rollback()
            conn.unbind()
            return {
                "success": False,
                "synced_count": synced_count,
                "message": f"Ошибка сохранения в базу данных: {str(e)}"
            }
