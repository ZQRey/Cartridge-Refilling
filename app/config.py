import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Database URL from env or local fallback
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "cartridges.db"
DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}")

# App configuration
SECRET_KEY = os.getenv("SECRET_KEY", "cartridge-management-super-secret-key-2026")
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

# Default values for settings table initialization
DEFAULT_SETTINGS = {
    # Active Directory / LDAP
    "ad_host": "ldap://192.168.1.10:389",
    "ad_base_dn": "DC=company,DC=local",
    "ad_bind_user": "CN=svc_ldap,OU=Service,DC=company,DC=local",
    "ad_bind_password": "",
    "ad_attr_name": "displayName",
    "ad_attr_cabinet": "physicalDeliveryOfficeName",
    "ad_attr_department": "department",
    "ad_attr_phone": "mobile,telephoneNumber",
    "ad_filter": "(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))",
    
    # WhatsApp (Evolution API)
    "wa_api_url": "http://whatsapp-gateway:8080",
    "wa_api_key": "cartridge_secret_key_2026",
    "wa_instance_name": "cartridge_bot",
    "wa_message_template": "Здравствуйте, {name}! Ваш картридж {marker} ({model}) для кабинета {cabinet} успешно заправлен и ожидает выдачи в {it_office}.",
    
    # General / Org details
    "org_name": "ООО «ТехноПром»",
    "it_office": "Кабинет IT № 108",
    "default_vendor": "ООО «СервисПринт»",
    "act_prefix": "АКТ-",
}

SETTING_DESCRIPTIONS = {
    "ad_host": "LDAP Сервер (IP или доменное имя с протоколом ldap:// или ldaps://)",
    "ad_base_dn": "Базовый DN каталога (Base DN)",
    "ad_bind_user": "Учетная запись для подключения (Bind DN или user@domain)",
    "ad_bind_password": "Пароль учетной записи для подключения к LDAP",
    "ad_attr_name": "Атрибут ФИО / имени пользователя в AD",
    "ad_attr_cabinet": "Атрибут номера кабинета в AD",
    "ad_attr_department": "Атрибут подразделения/отдела в AD",
    "ad_attr_phone": "Атрибуты телефона (через запятую, проверяются по очереди)",
    "ad_filter": "LDAP-фильтр выборки пользователей",
    
    "wa_api_url": "URL сервиса Evolution API (локальный шлюз)",
    "wa_api_key": "Глобальный API Key шлюза Evolution API",
    "wa_instance_name": "Имя инстанса WhatsApp в Evolution API",
    "wa_message_template": "Шаблон WhatsApp-сообщения при готовности к выдаче",
    
    "org_name": "Наименование организации (для шапки акта передачи)",
    "it_office": "Кабинет / Местоположение IT-отдела для получения картриджей",
    "default_vendor": "Поставщик услуг заправки по умолчанию (сервисный центр)",
    "act_prefix": "Префикс номеров актов передачи",
}
