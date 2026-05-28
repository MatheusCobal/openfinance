from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.pluggy_snapshot import account_snapshot_summary

router = APIRouter()


@router.get("/dashboard/snapshot")
def dashboard_snapshot(session: Session = Depends(get_session)):
    """Pluggy-native snapshot totals for the dashboard.

    Bank balances, credit-card usage/limits and investment/reserve totals,
    all sourced from persisted Pluggy data — not re-derived from raw
    transactions. Transaction-derived analytics stay on their own endpoints
    (/stats, /stats/monthly).
    """
    return account_snapshot_summary(session)
