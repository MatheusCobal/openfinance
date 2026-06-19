from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.dependencies import current_scope_user_id
from app.database import get_session
from app.services.fixed_costs import (
    FixedCostValidationError,
    create_fixed_cost,
    create_fixed_cost_category,
    create_fixed_cost_from_transaction,
    create_fixed_cost_transaction_match,
    delete_fixed_cost,
    delete_fixed_cost_category,
    delete_fixed_cost_transaction_match,
    delete_override,
    list_fixed_cost_categories,
    list_fixed_costs,
    list_fixed_cost_transaction_matches,
    list_fixed_cost_templates,
    monthly_breakdown,
    set_override,
    update_fixed_cost,
    update_fixed_cost_category,
)
from app.services.planning import upcoming_months
from app.services.spending_capacity import (
    spending_capacity_monthly_summary,
    spending_capacity_summary,
)

router = APIRouter()


class FixedCostCategoryCreate(BaseModel):
    name: str
    color: str = "#64748b"
    sort_order: int = 0


class FixedCostCategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class FixedCostCreate(BaseModel):
    category_id: int
    description: str
    amount: Decimal
    due_day: int


class FixedCostUpdate(BaseModel):
    category_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    due_day: Optional[int] = None
    active: Optional[bool] = None


class FixedCostOverrideUpsert(BaseModel):
    amount: Decimal


class FixedCostFromTransactionCreate(BaseModel):
    transaction_id: str
    category_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    due_day: Optional[int] = None


class FixedCostTransactionMatchCreate(BaseModel):
    transaction_id: str
    year_month: Optional[str] = None


@router.get("/fixed-cost-categories")
def list_categories_route(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return list_fixed_cost_categories(session, user_id=user_id)


@router.post("/fixed-cost-categories")
def create_category_route(
    body: FixedCostCategoryCreate,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return create_fixed_cost_category(
            session,
            name=body.name,
            color=body.color,
            sort_order=body.sort_order,
            user_id=user_id,
        )
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/fixed-cost-categories/{category_id}")
def update_category_route(
    category_id: int,
    body: FixedCostCategoryUpdate,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = update_fixed_cost_category(
            session,
            category_id=category_id,
            name=body.name,
            color=body.color,
            sort_order=body.sort_order,
            user_id=user_id,
        )
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "fixed cost category not found")
    return result


@router.delete("/fixed-cost-categories/{category_id}", status_code=204)
def delete_category_route(
    category_id: int,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        deleted = delete_fixed_cost_category(session, category_id, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if not deleted:
        raise HTTPException(404, "fixed cost category not found")
    return None


@router.get("/fixed-costs")
def list_fixed_costs_route(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return list_fixed_costs(session, include_inactive=include_inactive, user_id=user_id)


@router.get("/fixed-costs/templates")
def templates_route(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return list_fixed_cost_templates(session, user_id=user_id)


@router.post("/fixed-costs")
def create_fixed_cost_route(
    body: FixedCostCreate,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = create_fixed_cost(
            session,
            category_id=body.category_id,
            description=body.description,
            amount=body.amount,
            due_day=body.due_day,
            user_id=user_id,
        )
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "fixed cost category not found")
    return result


@router.post("/fixed-costs/from-transaction")
def create_from_transaction_route(
    body: FixedCostFromTransactionCreate,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = create_fixed_cost_from_transaction(
            session,
            transaction_id=body.transaction_id,
            category_id=body.category_id,
            description=body.description,
            amount=body.amount,
            due_day=body.due_day,
            user_id=user_id,
        )
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "transaction or fixed cost category not found")
    return result


@router.patch("/fixed-costs/{cost_id}")
def update_fixed_cost_route(
    cost_id: int,
    body: FixedCostUpdate,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = update_fixed_cost(
            session,
            cost_id=cost_id,
            category_id=body.category_id,
            description=body.description,
            amount=body.amount,
            due_day=body.due_day,
            active=body.active,
            user_id=user_id,
        )
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "fixed cost not found")
    return result


@router.delete("/fixed-costs/{cost_id}", status_code=204)
def delete_fixed_cost_route(
    cost_id: int,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    if not delete_fixed_cost(session, cost_id, user_id=user_id):
        raise HTTPException(404, "fixed cost not found")
    return None


@router.get("/fixed-costs/by-month")
def by_month_route(
    year_month: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return monthly_breakdown(session, year_month, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))


@router.get("/fixed-costs/matches")
def list_transaction_matches_route(
    year_month: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return list_fixed_cost_transaction_matches(session, year_month, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))


@router.post("/fixed-costs/{cost_id}/matches")
def create_transaction_match_route(
    cost_id: int,
    body: FixedCostTransactionMatchCreate,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = create_fixed_cost_transaction_match(
            session,
            fixed_cost_id=cost_id,
            transaction_id=body.transaction_id,
            year_month=body.year_month,
            user_id=user_id,
        )
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "fixed cost or transaction not found")
    return result


@router.delete("/fixed-costs/matches/{match_id}", status_code=204)
def delete_transaction_match_route(
    match_id: int,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    if not delete_fixed_cost_transaction_match(session, match_id, user_id=user_id):
        raise HTTPException(404, "fixed cost transaction match not found")
    return None


@router.get("/fixed-costs/upcoming")
def upcoming_route(
    start_year_month: str,
    months: int = 6,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return upcoming_months(session, start_year_month, months, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))


@router.put("/fixed-costs/{cost_id}/overrides/{year_month}")
def set_override_route(
    cost_id: int,
    year_month: str,
    body: FixedCostOverrideUpsert,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        result = set_override(session, cost_id, year_month, body.amount, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "fixed cost not found")
    return result


@router.delete("/fixed-costs/{cost_id}/overrides/{year_month}", status_code=204)
def delete_override_route(
    cost_id: int,
    year_month: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        deleted = delete_override(session, cost_id, year_month, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
    if not deleted:
        raise HTTPException(404, "override not found")
    return None


@router.get("/spending-capacity")
def spending_capacity_route(
    year_month: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return spending_capacity_summary(session, year_month, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))


@router.get("/spending-capacity/monthly")
def spending_capacity_monthly_route(
    months: int = 12,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return spending_capacity_monthly_summary(session, months, user_id=user_id)
    except FixedCostValidationError as exc:
        raise HTTPException(400, str(exc))
