from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.history import (
    bank_income_history_summary,
    bank_income_monthly_summary,
    credit_card_payments_history_summary,
    credit_card_payments_monthly_summary,
    ignored_transactions_monthly_summary,
    monthly_balance_history_summary,
    monthly_balance_summary,
)
from app.services.snapshots import (
    DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
    DEFAULT_MONTHLY_BALANCE_MONTHS,
)

router = APIRouter()


def _validate_month_window(months: int) -> None:
    if months < 1 or months > 24:
        raise HTTPException(400, "months must be between 1 and 24")


@router.get("/ignored-transactions/monthly")
def ignored_transactions_monthly(session: Session = Depends(get_session)):
    return ignored_transactions_monthly_summary(session)


@router.get("/credit-card-payments/monthly")
def credit_card_payments_monthly(
    months: int = DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
    session: Session = Depends(get_session),
):
    _validate_month_window(months)
    return credit_card_payments_monthly_summary(session, months)


@router.get("/credit-card-payments/history")
def credit_card_payments_history(session: Session = Depends(get_session)):
    return credit_card_payments_history_summary(session)


@router.get("/bank-income/monthly")
def bank_income_monthly(
    months: int = 12,
    session: Session = Depends(get_session),
):
    _validate_month_window(months)
    return bank_income_monthly_summary(session, months)


@router.get("/bank-income/history")
def bank_income_history(session: Session = Depends(get_session)):
    return bank_income_history_summary(session)


@router.get("/monthly-balance")
def monthly_balance(
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
    session: Session = Depends(get_session),
):
    _validate_month_window(months)
    return monthly_balance_summary(session, months)


@router.get("/monthly-balance/history")
def monthly_balance_history(session: Session = Depends(get_session)):
    return monthly_balance_history_summary(session)
