from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Batch, BatchItem, Cartridge, CartridgeStatus, HistoryLog, Branch, AppUser
from app.schemas import BatchResponse, BatchCreateRequest
from app.services.settings_service import SettingsService
from app.services.auth_service import require_operator

router = APIRouter(prefix="/api/batches", tags=["Batches"])


@router.get("", response_model=List[BatchResponse])
def get_batches(
    branch_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Список актов передачи картриджей поставщикам (только операторы и администраторы)."""
    query = db.query(Batch).options(
        joinedload(Batch.branch),
        joinedload(Batch.items).joinedload(BatchItem.cartridge).joinedload(Cartridge.current_user)
    )

    if current_user.role in ("admin", "operator") and current_user.branch_id:
        query = query.filter(Batch.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(Batch.branch_id == branch_id)

    return query.order_by(Batch.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{batch_id}", response_model=BatchResponse)
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """Получить подробную информацию об акте передачи."""
    batch = db.query(Batch).options(
        joinedload(Batch.branch),
        joinedload(Batch.items).joinedload(BatchItem.cartridge).joinedload(Cartridge.current_user)
    ).filter(Batch.id == batch_id).first()

    if not batch:
        raise HTTPException(status_code=404, detail="Акт не найден.")
    return batch


@router.post("", response_model=BatchResponse)
def create_batch(
    payload: BatchCreateRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """
    ЭТАП 2: ПЕРЕДАЧА ПОСТАВЩИКУ (ФОРМИРОВАНИЕ АКТА)
    Переводит выбранные картриджи в статус 'at_vendor' (На заправке),
    создает номер акта и связывает позиции.
    """
    if not payload.cartridge_ids:
        raise HTTPException(status_code=400, detail="Не выбраны картриджи для передачи.")

    settings = SettingsService.get_all(db)
    vendor = payload.vendor_name or settings.get("default_vendor", "Сервисный центр")
    prefix = settings.get("act_prefix", "АКТ-")

    now = datetime.utcnow()
    # Генерация номера акта: ПРЕФИКС-ГГГГММДД-КОЛ-ВО
    date_str = now.strftime("%Y%m%d")
    today_batches_count = db.query(Batch).filter(
        Batch.created_at >= datetime(now.year, now.month, now.day)
    ).count() + 1
    act_number = f"{prefix}{date_str}-{today_batches_count:03d}"

    # Создание акта
    batch = Batch(
        act_number=act_number,
        vendor_name=vendor,
        branch_id=payload.branch_id if payload.branch_id and payload.branch_id > 0 else None,
        created_at=now,
        status="open",
        notes=payload.notes
    )
    db.add(batch)
    db.flush()

    # Поиск и обновление картриджей
    cartridges = db.query(Cartridge).filter(Cartridge.id.in_(payload.cartridge_ids)).all()
    for cart in cartridges:
        cart.status = CartridgeStatus.AT_VENDOR
        cart.updated_at = now

        # Привязка к акту
        item = BatchItem(
            batch_id=batch.id,
            cartridge_id=cart.id,
            action_required=payload.action_required or "Заправка"
        )
        db.add(item)

        # Запись в историю
        log = HistoryLog(
            cartridge_id=cart.id,
            action="Передача поставщику",
            details=f"Передан поставщику '{vendor}' по акту № {act_number}. Требуется: {item.action_required}."
        )
        db.add(log)

    db.commit()

    # Загружаем со всеми связями
    full_batch = db.query(Batch).options(
        joinedload(Batch.branch),
        joinedload(Batch.items).joinedload(BatchItem.cartridge).joinedload(Cartridge.current_user)
    ).filter(Batch.id == batch.id).first()

    return full_batch
