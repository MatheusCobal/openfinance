from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth.dependencies import current_scope_user_id
from app.config import database_settings
from app.database import get_session
from app.services.history import (
    bank_cashflow_monthly_summary,
    bank_income_history_summary,
    bank_income_monthly_summary,
    credit_card_invoice_purchases_monthly_summary,
    credit_card_payments_history_summary,
    credit_card_payments_monthly_summary,
    ignored_transactions_monthly_summary,
    monthly_balance_history_summary,
    monthly_balance_summary,
)
from app.services.database_backup import backup_sqlite_database
from app.services.snapshots import (
    DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
    DEFAULT_MONTHLY_BALANCE_MONTHS,
    refresh_monthly_balance_snapshots,
)

router = APIRouter()


def _validate_month_window(months: int) -> None:
    if months < 1 or months > 24:
        raise HTTPException(400, "months must be between 1 and 24")


@router.get("/ignored-transactions/monthly")
def ignored_transactions_monthly(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return ignored_transactions_monthly_summary(session, user_id=user_id)


@router.get("/credit-card-payments/monthly")
def credit_card_payments_monthly(
    months: int = DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    _validate_month_window(months)
    return credit_card_payments_monthly_summary(session, months, user_id=user_id)


@router.get("/credit-card-invoices/monthly")
def credit_card_invoices_monthly(
    months: int = DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    _validate_month_window(months)
    return credit_card_invoice_purchases_monthly_summary(session, months, user_id=user_id)


@router.get("/credit-card-payments/history")
def credit_card_payments_history(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return credit_card_payments_history_summary(session, user_id=user_id)


@router.get("/bank-income/monthly", deprecated=True)
def bank_income_monthly(
    months: int = 12,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    # Deprecated for the Historico UI in 11-B. Kept for compatibility and for
    # shared backend income diagnostics; Entradas e Saidas uses /bank-cashflow.
    _validate_month_window(months)
    return bank_income_monthly_summary(session, months, user_id=user_id)


@router.get("/bank-income/history", deprecated=True)
def bank_income_history(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    # Deprecated for the Historico UI in 11-B; retained as a read-only
    # snapshot compatibility endpoint.
    return bank_income_history_summary(session, user_id=user_id)


@router.get("/bank-cashflow/monthly")
def bank_cashflow_monthly(
    months: int = 12,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    _validate_month_window(months)
    return bank_cashflow_monthly_summary(session, months, user_id=user_id)


@router.get("/monthly-balance")
def monthly_balance(
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    _validate_month_window(months)
    return monthly_balance_summary(session, months, user_id=user_id)


@router.get("/monthly-balance/history")
def monthly_balance_history(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return monthly_balance_history_summary(session, user_id=user_id)


@router.post("/history/snapshots/refresh")
def refresh_history_snapshots(
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    _validate_month_window(months)
    backup_sqlite_database(database_settings.database_url, "snapshot-refresh")
    bank_income, credit_card_invoice, monthly_balance = refresh_monthly_balance_snapshots(
        session,
        months,
        user_id=user_id,
    )
    return {
        "status": "ok",
        "refreshed": {
            "bank_income": bank_income,
            "credit_card_invoice": credit_card_invoice,
            "monthly_balance": monthly_balance,
        },
    }
