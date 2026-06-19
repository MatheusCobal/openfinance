from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth.dependencies import current_scope_user_id
from app.database import get_session
from app.services.credit_card_invoice import planning_invoice_for_month
from app.services.current_card_invoice import current_card_invoice_summary

router = APIRouter()


@router.get("/credit-card/current-invoice")
def current_card_invoice(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    """Dashboard-only current invoice based on adjusted Account.balance."""
    return current_card_invoice_summary(session, user_id=user_id)


@router.get("/credit-card/invoice/{year_month}")
def credit_card_invoice(
    year_month: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    """Single source of truth for the planning invoice of ``year_month``.

    Returns the structured ``planning_invoice`` object: amount, source,
    source_label, is_estimated, due_dates, cards, transaction_count,
    bill_count, account_count, cycle_start, cycle_end.
    """
    try:
        year, month = year_month.split("-")
        if len(year) != 4 or len(month) != 2 or not (1 <= int(month) <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(400, "year_month must be in YYYY-MM format")
    return planning_invoice_for_month(session, year_month, user_id=user_id)
