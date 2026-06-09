from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.routes.common import month_range
from app.services.budgets import budget_progress_summary

router = APIRouter()
LEGACY_BUDGET_REMOVED_MESSAGE = (
    "legacy category budgets were removed in 10D-A; "
    "TODO 10D-C: recreate variable targets on top of Pluggy-based classification"
)


class BudgetUpsert(BaseModel):
    monthly_target: Decimal


@router.get("/budgets")
def list_budgets(session: Session = Depends(get_session)):
    return {
        "items": [],
        "legacy_category_budget_removed": True,
        "todo": LEGACY_BUDGET_REMOVED_MESSAGE,
    }


@router.put("/budgets/{category_id}")
def upsert_budget(
    category_id: int,
    body: BudgetUpsert,
    session: Session = Depends(get_session),
):
    raise HTTPException(410, LEGACY_BUDGET_REMOVED_MESSAGE)


@router.delete("/budgets/{category_id}", status_code=204)
def delete_budget(category_id: int, session: Session = Depends(get_session)):
    raise HTTPException(410, LEGACY_BUDGET_REMOVED_MESSAGE)


@router.put("/budgets/{category_id}/months/{year_month}")
def upsert_budget_override(
    category_id: int,
    year_month: str,
    body: BudgetUpsert,
    session: Session = Depends(get_session),
):
    normalized_month, _, _ = month_range(year_month)
    raise HTTPException(410, f"{LEGACY_BUDGET_REMOVED_MESSAGE}; year_month={normalized_month}")


@router.delete("/budgets/{category_id}/months/{year_month}", status_code=204)
def delete_budget_override(
    category_id: int,
    year_month: str,
    session: Session = Depends(get_session),
):
    normalized_month, _, _ = month_range(year_month)
    raise HTTPException(410, f"{LEGACY_BUDGET_REMOVED_MESSAGE}; year_month={normalized_month}")


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
