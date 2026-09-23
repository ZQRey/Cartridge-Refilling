from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import AppUser
from app.schemas import LoginRequest, LoginResponse, AppUserResponse
from app.services.auth_service import AuthService, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Аутентификация пользователя (локально или через Active Directory)."""
    user = AuthService.authenticate_user(
        db=db,
        username=payload.username,
        password=payload.password,
        auth_type=payload.auth_type
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль."
        )

    # Генерация JWT токена
    token_data = {
        "sub": user.username,
        "role": user.role,
        "branch_id": user.branch_id
    }
    access_token = AuthService.create_access_token(token_data)

    # Загружаем связанные данные (филиал)
    user_with_branch = db.query(AppUser).options(
        joinedload(AppUser.branch)
    ).filter(AppUser.id == user.id).first()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_with_branch
    }


@router.get("/me", response_model=AppUserResponse)
def get_current_user_profile(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Получить профиль текущего авторизованного пользователя."""
    user_with_branch = db.query(AppUser).options(
        joinedload(AppUser.branch)
    ).filter(AppUser.id == user.id).first()
    return user_with_branch
