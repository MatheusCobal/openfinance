from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import Budget, BudgetOverride, Category
from app.routes.common import month_range, validate_budget_target
from app.services.budgets import budget_progress_summary

router = APIRouter()


class BudgetUpsert(BaseModel):
    monthly_target: Decimal


@router.get("/budgets")
def list_budgets(session: Session = Depends(get_session)):
    return session.exec(select(Budget)).all()


@router.put("/budgets/{category_id}")
def upsert_budget(
    category_id: int,
    body: BudgetUpsert,
    session: Session = Depends(get_session),
):
    validate_budget_target(body.monthly_target)
    if not session.get(Category, category_id):
        raise HTTPException(404, "category not found")
    existing = session.exec(
        select(Budget).where(Budget.category_id == category_id)
    ).first()
    if existing:
        existing.monthly_target = body.monthly_target
        session.add(existing)
    else:
        existing = Budget(category_id=category_id, monthly_target=body.monthly_target)
        session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


@router.delete("/budgets/{category_id}", status_code=204)
def delete_budget(category_id: int, session: Session = Depends(get_session)):
    budget = session.exec(
        select(Budget).where(Budget.category_id == category_id)
    ).first()
    if budget:
        session.delete(budget)
        session.commit()
    return None


@router.put("/budgets/{category_id}/months/{year_month}")
def upsert_budget_override(
    category_id: int,
    year_month: str,
    body: BudgetUpsert,
    session: Session = Depends(get_session),
):
    validate_budget_target(body.monthly_target)
    normalized_month, _, _ = month_range(year_month)
    if not session.get(Category, category_id):
        raise HTTPException(404, "category not found")
    existing = session.exec(
        select(BudgetOverride).where(
            BudgetOverride.category_id == category_id,
            BudgetOverride.year_month == normalized_month,
        )
    ).first()
    if existing:
        existing.monthly_target = body.monthly_target
        session.add(existing)
    else:
        existing = BudgetOverride(
            category_id=category_id,
            year_month=normalized_month,
            monthly_target=body.monthly_target,
        )
        session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


@router.delete("/budgets/{category_id}/months/{year_month}", status_code=204)
def delete_budget_override(
    category_id: int,
    year_month: str,
    session: Session = Depends(get_session),
):
    normalized_month, _, _ = month_range(year_month)
    override = session.exec(
        select(BudgetOverride).where(
            BudgetOverride.category_id == category_id,
            BudgetOverride.year_month == normalized_month,
        )
    ).first()
    if override:
        session.delete(override)
        session.commit()
    return None


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


