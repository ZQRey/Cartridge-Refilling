from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import CartridgeModel, Cartridge, AppUser
from app.schemas import CartridgeModelCreate, CartridgeModelUpdate, CartridgeModelResponse
from app.services.auth_service import require_operator, require_admin

router = APIRouter(prefix="/api/cartridge-models", tags=["CartridgeModels"])


@router.get("", response_model=List[CartridgeModelResponse])
def get_cartridge_models(
    q: Optional[str] = Query(None, description="Поиск по названию или совместимым принтерам"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Получить список всех моделей картриджей со счетчиком их использования."""
    query = db.query(CartridgeModel)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            (CartridgeModel.name.ilike(term)) |
            (CartridgeModel.vendor.ilike(term)) |
            (CartridgeModel.compatible_printers.ilike(term))
        )
    
    models = query.order_by(CartridgeModel.name.asc()).all()

    # Подсчет количества картриджей в системе по каждой модели
    counts = dict(
        db.query(Cartridge.model, func.count(Cartridge.id))
        .group_by(Cartridge.model)
        .all()
    )

    results = []
    for m in models:
        resp = CartridgeModelResponse.model_validate(m)
        resp.cartridges_count = counts.get(m.name, 0)
        results.append(resp)

    return results


@router.post("", response_model=CartridgeModelResponse, status_code=status.HTTP_201_CREATED)
def create_cartridge_model(
    payload: CartridgeModelCreate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Добавить новую модель картриджа в справочник (Администратор и Супер администратор)."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название модели не может быть пустым.")

    existing = db.query(CartridgeModel).filter(CartridgeModel.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Модель '{name}' уже есть в справочнике.")

    model = CartridgeModel(
        name=name,
        vendor=payload.vendor.strip() if payload.vendor else None,
        resource_pages=payload.resource_pages,
        compatible_printers=payload.compatible_printers.strip() if payload.compatible_printers else None,
        notes=payload.notes.strip() if payload.notes else None
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    resp = CartridgeModelResponse.model_validate(model)
    resp.cartridges_count = 0
    return resp


@router.put("/{model_id}", response_model=CartridgeModelResponse)
def update_cartridge_model(
    model_id: int,
    payload: CartridgeModelUpdate,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Редактировать модель картриджа."""
    model = db.query(CartridgeModel).filter(CartridgeModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Модель не найдена.")

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Название модели не может быть пустым.")
        existing = db.query(CartridgeModel).filter(
            CartridgeModel.name.ilike(new_name),
            CartridgeModel.id != model_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Модель '{new_name}' уже зарегистрирована.")
        model.name = new_name

    if payload.vendor is not None:
        model.vendor = payload.vendor.strip() if payload.vendor else None

    if payload.resource_pages is not None:
        model.resource_pages = payload.resource_pages

    if payload.compatible_printers is not None:
        model.compatible_printers = payload.compatible_printers.strip() if payload.compatible_printers else None

    if payload.notes is not None:
        model.notes = payload.notes.strip() if payload.notes else None

    db.commit()
    db.refresh(model)

    count = db.query(Cartridge).filter(Cartridge.model == model.name).count()
    resp = CartridgeModelResponse.model_validate(model)
    resp.cartridges_count = count
    return resp


@router.delete("/{model_id}")
def delete_cartridge_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_admin)
):
    """Удалить модель картриджа из справочника."""
    model = db.query(CartridgeModel).filter(CartridgeModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Модель не найдена.")

    # Проверка, есть ли картриджи данной модели в базе
    count = db.query(Cartridge).filter(Cartridge.model == model.name).count()
    if count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя удалить модель '{model.name}', так как в системе зарегистрировано {count} картридж(ей) этой модели."
        )

    db.delete(model)
    db.commit()
    return {"success": True, "message": f"Модель '{model.name}' удалена из справочника."}
