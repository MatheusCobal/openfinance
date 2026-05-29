from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, CreditCardBill, Transaction
from app.services.pluggy_snapshot import (
    account_snapshot_summary,
    credit_card_obligation_summary,
    current_open_card_invoice_summary,
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


@router.get("/debug/credit-card-bills")
def debug_credit_card_bills(session: Session = Depends(get_session)):
    """Dev diagnostic: all CreditCardBill rows joined with their Account.

    Returns every stored bill ordered by due_date desc so the most recent
    invoice is always first. Includes the account fields most useful for
    debugging why the dashboard picks a particular invoice source.

    Read-only — does not change any data.
    """
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}
    bills = session.exec(
        select(CreditCardBill).order_by(CreditCardBill.due_date.desc())  # type: ignore[arg-type]
    ).all()

    return {
        "count": len(bills),
        "bills": [
            {
                # ── Bill fields ──
                "id": b.id,
                "account_id": b.account_id,
                "due_date": b.due_date.isoformat() if b.due_date else None,
                "total_amount": float(b.total_amount) if b.total_amount is not None else None,
                "minimum_payment_amount": float(b.minimum_payment_amount) if b.minimum_payment_amount is not None else None,
                "payments_total": float(b.payments_total) if b.payments_total is not None else None,
                "finance_charges_total": float(b.finance_charges_total) if b.finance_charges_total is not None else None,
                "updated_at": b.updated_at.isoformat() if b.updated_at else None,
                # ── Related account fields ──
                "account_name": accounts_by_id[b.account_id].name if b.account_id in accounts_by_id else None,
                "account_type": accounts_by_id[b.account_id].type if b.account_id in accounts_by_id else None,
                "account_item_id": accounts_by_id[b.account_id].item_id if b.account_id in accounts_by_id else None,
                "account_is_active": accounts_by_id[b.account_id].is_active if b.account_id in accounts_by_id else None,
                "account_balance": float(accounts_by_id[b.account_id].balance) if b.account_id in accounts_by_id and accounts_by_id[b.account_id].balance is not None else None,
                "account_credit_balance_due_date": accounts_by_id[b.account_id].credit_balance_due_date.isoformat() if b.account_id in accounts_by_id and accounts_by_id[b.account_id].credit_balance_due_date else None,
                "account_balance_updated_at": accounts_by_id[b.account_id].balance_updated_at.isoformat() if b.account_id in accounts_by_id and accounts_by_id[b.account_id].balance_updated_at else None,
            }
            for b in bills
        ],
    }


@router.get("/debug/current-card-invoice")
def debug_current_card_invoice(
    year_month: str = Query(..., description="YYYY-MM"),
    session: Session = Depends(get_session),
):
    """Dev diagnostic: open card invoice estimate for year_month.

    Shows which source tier was selected, the billing cycle window, and
    the first 20 PENDING transactions (for current-month only).

    Read-only — does not change any data.
    """
    import datetime, calendar as _cal
    from sqlalchemy import or_
    from app.services.classification import SPENDING_ACCOUNT_TYPES
    from app.services.transactions import account_ids_by_type

    summary = current_open_card_invoice_summary(session, year_month)

    # Fetch the raw transactions for context (current month only)
    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    _, month_last = _cal.monthrange(year_int, month_int)
    month_start = datetime.date(year_int, month_int, 1)
    month_end   = datetime.date(year_int, month_int, month_last)

    credit_ids = account_ids_by_type(session, SPENDING_ACCOUNT_TYPES)
    pending_txs = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(credit_ids),
            Transaction.date >= month_start,
            Transaction.date <= month_end,
            Transaction.status == "PENDING",
        )
    ).all()

    return {
        **summary,
        "sample_pending_transactions": [
            {
                "id": tx.id,
                "account_id": tx.account_id,
                "date": tx.date.isoformat(),
                "amount": float(abs(tx.amount)),
                "description": tx.description,
                "status": tx.status,
                "bill_id": tx.bill_id,
                "installment_number": tx.installment_number,
                "total_installments": tx.total_installments,
            }
            for tx in sorted(pending_txs, key=lambda t: t.date)[:20]
        ],
    }
