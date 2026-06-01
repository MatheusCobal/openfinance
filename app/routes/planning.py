from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.fixed_costs import FixedCostValidationError
from app.services.planning import planning_month_summary

router = APIRouter()


@router.get("/planning/month/{year_month}")
def planning_month_route(
    year_month: str,
    session: Session = Depends(get_session),
):
    try:
        return planning_month_summary(session, year_month)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
