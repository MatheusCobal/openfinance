from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.auth.dependencies import current_scope_user_id
from app.database import get_session
from app.services.bank_balance import bank_balance_summary

router = APIRouter()


@router.get("/bank/balance-summary")
def bank_balance(
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    """Active BANK accounts total balance."""
    return bank_balance_summary(session, user_id=user_id)
