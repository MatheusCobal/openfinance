from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, CreditCardBill
from app.services.pluggy_snapshot import (
    account_snapshot_summary,
    credit_card_obligation_summary,
)

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


@router.get("/dashboard/credit-card-diagnostics")
def credit_card_diagnostics(
    year_month: str = Query(..., description="YYYY-MM"),
    session: Session = Depends(get_session),
):
    """Diagnostic endpoint: explains why a given month uses a particular invoice source.

    Read-only — does not change any data.
    """
    credit_accounts = [a for a in session.exec(select(Account)).all() if a.type == "CREDIT"]
    all_bills = list(session.exec(select(CreditCardBill)).all())
    bills_for_month = [
        b for b in all_bills
        if b.due_date is not None and b.due_date.strftime("%Y-%m") == year_month
    ]
    credit_accounts_with_balance = [a for a in credit_accounts if a.balance is not None]

    bills_for_month_count = len(bills_for_month)
    credit_account_count = len(credit_accounts)
    credit_accounts_with_balance_count = len(credit_accounts_with_balance)

    if bills_for_month_count > 0:
        fallback_reason = "bill_available"
    elif credit_accounts_with_balance_count > 0:
        fallback_reason = "account_balance_available"
    elif credit_account_count == 0:
        fallback_reason = "no_credit_accounts"
    elif credit_account_count > 0 and credit_accounts_with_balance_count == 0:
        fallback_reason = "credit_accounts_without_balance"
    else:
        fallback_reason = "unknown"

    obligation = credit_card_obligation_summary(session, year_month)

    return {
        "year_month": year_month,
        "source": obligation.get("source"),
        "credit_accounts": [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "balance": float(a.balance) if a.balance is not None else None,
                "has_balance": a.balance is not None,
                "credit_balance_due_date": a.credit_balance_due_date.isoformat() if a.credit_balance_due_date else None,
                "credit_limit": float(a.credit_limit) if a.credit_limit is not None else None,
                "credit_available_limit": float(a.credit_available_limit) if a.credit_available_limit is not None else None,
            }
            for a in credit_accounts
        ],
        "credit_account_count": credit_account_count,
        "credit_accounts_with_balance_count": credit_accounts_with_balance_count,
        "bills_for_month": [
            {
                "id": b.id,
                "account_id": b.account_id,
                "due_date": b.due_date.isoformat() if b.due_date else None,
                "total_amount": float(b.total_amount) if b.total_amount is not None else None,
            }
            for b in bills_for_month
        ],
        "bills_for_month_count": bills_for_month_count,
        "all_bills_count": len(all_bills),
        "fallback_reason": fallback_reason,
    }
