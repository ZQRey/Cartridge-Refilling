import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import SECRET_KEY
from app.database import get_db
from app.models import AppUser
from app.services.ldap_service import LDAPService

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer(auto_error=False)


class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        """Хэширует пароль с использованием PBKDF2-HMAC-SHA256 и криптографической соли."""
        salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations=100000
        )
        return f"{salt}${key.hex()}"

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Сверяет пароль с сохраненным хэшем."""
        if not hashed or "$" not in hashed:
            return False
        try:
            salt, stored_key = hashed.split("$", 1)
            key = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("utf-8"),
                iterations=100000
            )
            return secrets.compare_digest(key.hex(), stored_key)
        except Exception:
            return False

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Создает подписанный JWT токен доступа."""
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
        """Декодирует и валидирует JWT токен."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.PyJWTError:
            return None

    @classmethod
    def authenticate_user(
        cls,
        db: Session,
        username: str,
        password: str,
        auth_type: str = "local"
    ) -> Optional[AppUser]:
        """
        Аутентифицирует пользователя локально или через Active Directory.
        """
        clean_user = username.strip()

        if auth_type == "ad":
            # Проверяем учетные данные напрямую через LDAP bind к AD
            ldap_res = LDAPService.test_connection(
                db=db,
                bind_user=clean_user,
                bind_password=password
            )
            if not ldap_res.get("success"):
                return None

            # Если вход через AD успешен — ищем или создаем профиль AppUser
            user = db.query(AppUser).filter(AppUser.username.ilike(clean_user)).first()
            if not user:
                # Первый вход доменного пользователя — создаем профиль оператора
                user = AppUser(
                    username=clean_user,
                    full_name=clean_user,
                    auth_type="ad",
                    role="operator",
                    is_active=True,
                    branch_id=None
                )
                db.add(user)
                db.commit()
                db.refresh(user)

            if not user.is_active:
                raise HTTPException(status_code=403, detail="Учетная запись заблокирована администратором.")

            return user

        # Локальный вход
        user = db.query(AppUser).filter(AppUser.username.ilike(clean_user)).first()
        if not user or not user.password_hash:
            return None

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Учетная запись заблокирована.")

        if not cls.verify_password(password, user.password_hash):
            return None

        return user


def get_current_user_optional(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[AppUser]:
    """Возвращает текущего пользователя из JWT токена, если токен передан."""
    if not auth:
        return None
    payload = AuthService.decode_access_token(auth.credentials)
    if not payload or "sub" not in payload:
        return None
    username = payload["sub"]
    user = db.query(AppUser).filter(AppUser.username == username).first()
    if not user or not user.is_active:
        return None
    return user


def get_current_user(
    user: Optional[AppUser] = Depends(get_current_user_optional)
) -> AppUser:
    """Обязательная проверка авторизации для защищенных эндпоинтов."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация в системе.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    """Проверка прав администратора."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуются права администратора."
        )
    return user
