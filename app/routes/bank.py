from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.bank_balance import bank_balance_summary

router = APIRouter()


@router.get("/bank/balance-summary")
def bank_balance(session: Session = Depends(get_session)):
    """Active BANK accounts total balance."""
    return bank_balance_summary(session)
