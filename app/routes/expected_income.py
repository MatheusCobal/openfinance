from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services.expected_income import (
    ExpectedIncomeValidationError,
    create_expected_income,
    delete_expected_income,
    expected_income_forecast,
    list_expected_income,
    update_expected_income,
)

router = APIRouter()


class ExpectedIncomeCreate(BaseModel):
    description: str
    amount: Decimal
    expected_day: int


class ExpectedIncomeUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    expected_day: Optional[int] = None
    active: Optional[bool] = None


@router.get("/expected-income")
def list_route(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
):
    return list_expected_income(session, include_inactive=include_inactive)


@router.post("/expected-income")
def create_route(
    body: ExpectedIncomeCreate,
    session: Session = Depends(get_session),
):
    try:
        return create_expected_income(
            session,
            description=body.description,
            amount=body.amount,
            expected_day=body.expected_day,
        )
    except ExpectedIncomeValidationError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/expected-income/{entry_id}")
def update_route(
    entry_id: int,
    body: ExpectedIncomeUpdate,
    session: Session = Depends(get_session),
):
    try:
        result = update_expected_income(
            session,
            entry_id=entry_id,
            description=body.description,
            amount=body.amount,
            expected_day=body.expected_day,
            active=body.active,
        )
    except ExpectedIncomeValidationError as exc:
        raise HTTPException(400, str(exc))
    if result is None:
        raise HTTPException(404, "expected income not found")
    return result


@router.delete("/expected-income/{entry_id}", status_code=204)
def delete_route(
    entry_id: int,
    session: Session = Depends(get_session),
):
    if not delete_expected_income(session, entry_id):
        raise HTTPException(404, "expected income not found")
    return None


@router.get("/expected-income/forecast")
def forecast_route(
    year_month: str,
    session: Session = Depends(get_session),
):
    try:
        return expected_income_forecast(session, year_month)
    except ExpectedIncomeValidationError as exc:
        raise HTTPException(400, str(exc))
