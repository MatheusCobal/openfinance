from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.routes.common import month_range
from app.services.budgets import budget_progress_summary

router = APIRouter()
LEGACY_BUDGET_REMOVED_MESSAGE = (
    "legacy category budgets were removed in 10D-A; "
    "TODO 10D-C: recreate variable targets on top of Pluggy-based classification"
)


@router.get("/budgets")
def list_budgets(session: Session = Depends(get_session)):
    return {
        "items": [],
        "legacy_category_budget_removed": True,
        "todo": LEGACY_BUDGET_REMOVED_MESSAGE,
    }


@router.get("/budgets/progress")
def budgets_progress(
    year_month: Optional[str] = None,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
):
    today = date.today()
    year_month, first_day, last_day = month_range(year_month)
    return budget_progress_summary(
        session,
        year_month=year_month,
        first_day=first_day,
        last_day=last_day,
        today=today,
        include_ignored=include_ignored,
    )
