from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.dependencies import current_scope_user_id
from app.database import get_session
from app.routes.common import month_range
from app.services.budgets import budget_progress_summary
from app.services.variable_budgets import (
    VariableBudgetValidationError,
    delete_goal,
    eligible_categories,
    replicate_goals,
    upsert_goal,
)

router = APIRouter()


class VariableBudgetUpsert(BaseModel):
    year_month: str
    category: str
    target_amount: float


@router.get("/budgets")
def list_budgets():
    # Legacy per-category budget storage was removed in 10D-A. The variable
    # goals live under /budgets/variable + /budgets/progress now.
    return {"items": []}


@router.get("/budgets/variable/categories")
def variable_budget_categories():
    return {"categories": eligible_categories()}


@router.get("/budgets/progress")
def budgets_progress(
    year_month: Optional[str] = None,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
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
        user_id=user_id,
    )


@router.put("/budgets/variable")
def upsert_variable_budget(
    body: VariableBudgetUpsert,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        goal = upsert_goal(
            session,
            year_month=body.year_month,
            category=body.category,
            target_amount=body.target_amount,
            user_id=user_id,
        )
    except VariableBudgetValidationError as exc:
        raise HTTPException(400, str(exc))
    return {
        "id": goal.id,
        "year_month": goal.year_month,
        "category": goal.category,
        "target_amount": float(goal.target_amount),
    }


class ReplicateBody(BaseModel):
    source_month: str
    months_ahead: int = 11
    overwrite: bool = False


@router.post("/budgets/variable/replicate")
def replicate_variable_budgets(
    body: ReplicateBody,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = replicate_goals(
            session,
            source_month=body.source_month,
            months_ahead=body.months_ahead,
            overwrite=body.overwrite,
            user_id=user_id,
        )
    except VariableBudgetValidationError as exc:
        raise HTTPException(400, str(exc))
    return result


@router.delete("/budgets/variable")
def remove_variable_budget(
    year_month: str,
    category: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        removed = delete_goal(session, year_month=year_month, category=category, user_id=user_id)
    except VariableBudgetValidationError as exc:
        raise HTTPException(400, str(exc))
    if not removed:
        raise HTTPException(404, "variable budget goal not found")
    return {"deleted": True, "year_month": year_month, "category": category}
