from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import AppUser, Branch
from app.schemas import AppUserCreate, AppUserUpdate, AppUserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/app-users", tags=["AppUsers"])


@router.get("", response_model=List[AppUserResponse])
def get_users(db: Session = Depends(get_db)):
    """Список пользователей системы."""
    return db.query(AppUser).options(
        joinedload(AppUser.branch)
    ).order_by(AppUser.username.asc()).all()


@router.post("", response_model=AppUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: AppUserCreate, db: Session = Depends(get_db)):
    """Создать учетную запись пользователя."""
    username = payload.username.strip()
    existing = db.query(AppUser).filter(AppUser.username.ilike(username)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Пользователь '{username}' уже существует.")

    # Если локальный пользователь — пароль обязателен
    password_hash = None
    if payload.auth_type == "local":
        if not payload.password:
            raise HTTPException(status_code=400, detail="Для локального пользователя необходимо задать пароль.")
        password_hash = AuthService.hash_password(payload.password)

    if payload.branch_id:
        branch = db.query(Branch).filter(Branch.id == payload.branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Указанный филиал не существует.")

    user = AppUser(
        username=username,
        full_name=payload.full_name.strip(),
        password_hash=password_hash,
        auth_type=payload.auth_type,
        role=payload.role,
        is_active=payload.is_active,
        branch_id=payload.branch_id
    )
    db.add(user)
    db.commit()

    return db.query(AppUser).options(
        joinedload(AppUser.branch)
    ).filter(AppUser.id == user.id).first()


@router.put("/{user_id}", response_model=AppUserResponse)
def update_user(user_id: int, payload: AppUserUpdate, db: Session = Depends(get_db)):
    """Редактировать пользователя (ФИО, пароль, роль, блокировка, филиал)."""
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()

    if payload.password and payload.password.strip():
        user.password_hash = AuthService.hash_password(payload.password.strip())

    if payload.role is not None:
        user.role = payload.role

    if payload.is_active is not None:
        # Запрет блокировки главного администратора admin
        if user.username == "admin" and not payload.is_active:
            raise HTTPException(status_code=400, detail="Нельзя заблокировать главного администратора системы.")
        user.is_active = payload.is_active

    if payload.branch_id is not None:
        if payload.branch_id == 0 or payload.branch_id == -1:
            user.branch_id = None
        else:
            branch = db.query(Branch).filter(Branch.id == payload.branch_id).first()
            if not branch:
                raise HTTPException(status_code=404, detail="Указанный филиал не существует.")
            user.branch_id = payload.branch_id

    db.commit()

    return db.query(AppUser).options(
        joinedload(AppUser.branch)
    ).filter(AppUser.id == user.id).first()


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    """Удалить пользователя."""
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Нельзя удалить главного администратора admin.")

    db.delete(user)
    db.commit()
    return {"success": True, "message": f"Пользователь '{user.username}' удален."}
