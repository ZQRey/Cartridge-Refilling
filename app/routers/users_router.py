from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db
from app.models import ADUser
from app.schemas import ADUserResponse

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("", response_model=List[ADUserResponse])
def search_users(
    q: Optional[str] = Query(None, description="Строка поиска по имени, логину, кабинету или отделу"),
    limit: int = Query(30, le=100),
    db: Session = Depends(get_db)
):
    """Поиск сотрудников из локальной синхронизированной базы Active Directory."""
    query = db.query(ADUser)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                ADUser.display_name.ilike(term),
                ADUser.samaccountname.ilike(term),
                ADUser.cabinet.ilike(term),
                ADUser.department.ilike(term)
            )
        )
    return query.order_by(ADUser.display_name.asc()).limit(limit).all()
