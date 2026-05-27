from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.reserve import emergency_reserve_monthly_summary

router = APIRouter()


@router.get("/emergency-reserve/monthly")
def monthly_emergency_reserve(
    months: int = 6,
    session: Session = Depends(get_session),
):
    try:
        return emergency_reserve_monthly_summary(
            session, months=months, today=date.today()
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
