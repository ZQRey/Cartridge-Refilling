from typing import Optional
from urllib.parse import quote
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppUser
from app.services.auth_service import require_operator
from app.services.settings_service import SettingsService
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/data")
def get_report_data(
    report_type: str = Query("all", description="Тип отчета: all, year, month, custom"),
    branch_id: Optional[int] = Query(None, description="Филиал (для суперадмина или сотрудников без привязки)"),
    year: Optional[int] = Query(None, description="Год для годового/месячного отчета"),
    month: Optional[int] = Query(None, description="Месяц (1-12) для месячного отчета"),
    date_from: Optional[str] = Query(None, description="Дата начала YYYY-MM-DD для интервала"),
    date_to: Optional[str] = Query(None, description="Дата конца YYYY-MM-DD для интервала"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """
    Получить структурированные данные отчета в формате JSON для отображения в веб-интерфейсе.
    Доступно: Супер администратор, Администратор, Оператор.
    """
    try:
        data = ReportService.get_report_data(
            db=db,
            current_user=current_user,
            report_type=report_type,
            branch_id=branch_id,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to
        )
        return {"success": True, "report": data}
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ошибка формирования отчета: {str(e)}")


@router.get("/export/excel")
def export_report_excel(
    report_type: str = Query("all", description="Тип отчета: all, year, month, custom, models, history"),
    branch_id: Optional[int] = Query(None, description="Филиал"),
    year: Optional[int] = Query(None, description="Год"),
    month: Optional[int] = Query(None, description="Месяц"),
    date_from: Optional[str] = Query(None, description="Дата начала"),
    date_to: Optional[str] = Query(None, description="Дата конца"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """
    Сформировать и скачать отчет в виде красиво оформленного файла Excel (.xlsx).
    """
    try:
        report = ReportService.get_report_data(
            db=db,
            current_user=current_user,
            report_type=report_type,
            branch_id=branch_id,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to
        )
        settings = SettingsService.get_all(db)
        org_name = settings.get("org_name", "Cartridge Tracker")

        stream = ReportService.generate_excel(report, org_name=org_name)

        now_str = datetime.utcnow().strftime("%Y%m%d_%H%M")
        branch_part = report["branch_name"].replace(" ", "_")
        raw_filename = f"Отчет_{report['report_type']}_{branch_part}_{now_str}.xlsx"
        ascii_filename = f"report_{report['report_type']}_{now_str}.xlsx"
        encoded_filename = quote(raw_filename)

        headers = {
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
        }

        return StreamingResponse(
            stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ошибка выгрузки Excel: {str(e)}")


@router.get("/export/pdf")
def export_report_pdf(
    report_type: str = Query("all", description="Тип отчета: all, year, month, custom, models, history"),
    branch_id: Optional[int] = Query(None, description="Филиал"),
    year: Optional[int] = Query(None, description="Год"),
    month: Optional[int] = Query(None, description="Месяц"),
    date_from: Optional[str] = Query(None, description="Дата начала"),
    date_to: Optional[str] = Query(None, description="Дата конца"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_operator)
):
    """
    Сформировать и скачать отчет в виде красиво оформленного файла PDF (.pdf).
    """
    try:
        report = ReportService.get_report_data(
            db=db,
            current_user=current_user,
            report_type=report_type,
            branch_id=branch_id,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to
        )
        settings = SettingsService.get_all(db)
        org_name = settings.get("org_name", "Cartridge Tracker")

        stream = ReportService.generate_pdf(report, org_name=org_name)

        now_str = datetime.utcnow().strftime("%Y%m%d_%H%M")
        branch_part = report["branch_name"].replace(" ", "_")
        raw_filename = f"Отчет_{report['report_type']}_{branch_part}_{now_str}.pdf"
        ascii_filename = f"report_{report['report_type']}_{now_str}.pdf"
        encoded_filename = quote(raw_filename)

        headers = {
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
        }

        return StreamingResponse(
            stream,
            media_type="application/pdf",
            headers=headers
        )
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ошибка выгрузки PDF: {str(e)}")

