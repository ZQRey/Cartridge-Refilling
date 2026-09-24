from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Branch, Cartridge, AppUser
from app.schemas import BranchCreate, BranchUpdate, BranchResponse
from app.services.auth_service import require_admin

router = APIRouter(prefix="/api/branches", tags=["Branches"])


@router.get("", response_model=List[BranchResponse])
def get_branches(db: Session = Depends(get_db)):
    """Список всех филиалов организации."""
    return db.query(Branch).order_by(Branch.name.asc()).all()


@router.post("", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
def create_branch(
    payload: BranchCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Создать новый филиал (Администратор или Супер администратор)."""
    name = payload.name.strip()
    existing = db.query(Branch).filter(Branch.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Филиал с наименованием '{name}' уже существует.")

    branch = Branch(
        name=name,
        code=payload.code.strip() if payload.code else None,
        address=payload.address.strip() if payload.address else None,
        notes=payload.notes.strip() if payload.notes else None
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


@router.put("/{branch_id}", response_model=BranchResponse)
def update_branch(
    branch_id: int,
    payload: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Обновить параметры филиала."""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Филиал не найден.")

    if payload.name:
        name = payload.name.strip()
        existing = db.query(Branch).filter(Branch.name.ilike(name), Branch.id != branch_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Филиал '{name}' уже существует.")
        branch.name = name

    if payload.code is not None:
        branch.code = payload.code.strip() if payload.code else None
    if payload.address is not None:
        branch.address = payload.address.strip() if payload.address else None
    if payload.notes is not None:
        branch.notes = payload.notes.strip() if payload.notes else None

    db.commit()
    db.refresh(branch)
    return branch


@router.delete("/{branch_id}")
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Удалить филиал."""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Филиал не найден.")

    # Проверка, есть ли привязанные картриджи
    cart_count = db.query(Cartridge).filter(Cartridge.branch_id == branch_id).count()
    if cart_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Невозможно удалить филиал: к нему привязано {cart_count} картридж(ей). Сначала отвяжите их."
        )

    # Отвязываем пользователей
    db.query(AppUser).filter(AppUser.branch_id == branch_id).update({"branch_id": None})

    db.delete(branch)
    db.commit()
    return {"success": True, "message": f"Филиал '{branch.name}' успешно удален."}
