from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Type

from sqlmodel import Session, select

from app.models import (
    Account,
    BankIncomeMonth,
    CreditCardInvoiceMonth,
    MonthlyBalanceMonth,
    Transaction,
)
from app.services.invoice_month import (
    DEFAULT_CREDIT_CARD_DUE_DAY,
    invoice_month_from_payment,
)
from app.services.scoping import scope_query
from app.services.transactions import (
    bank_income_transactions,
    credit_card_payment_transactions,
    credit_card_spend_transactions,
    last_month_keys,
    month_key,
    shift_month,
)

DEFAULT_CREDIT_CARD_PAYMENT_MONTHS = 12
DEFAULT_MONTHLY_BALANCE_MONTHS = 12


def _snapshot_for_month(
    session: Session,
    model: Type,
    year_month: str,
    user_id: Optional[int],
):
    query = select(model).where(model.year_month == year_month)
    if user_id is not None:
        return session.exec(query.where(model.user_id == user_id)).first()

    rows = session.exec(query).all()
    unowned = next((row for row in rows if row.user_id is None), None)
    if unowned is not None:
        return unowned
    if len(rows) <= 1:
        return rows[0] if rows else None
    raise RuntimeError(
        "snapshot refresh with authentication disabled found multiple user-owned rows"
    )


def _upsert_snapshot(
    session: Session,
    model: Type,
    year_month: str,
    user_id: Optional[int],
    now: datetime,
    values: Dict[str, Any],
) -> None:
    snapshot = _snapshot_for_month(session, model, year_month, user_id)
    if snapshot is None:
        snapshot = model(
            year_month=year_month,
            user_id=user_id,
            captured_at=now,
            updated_at=now,
            **values,
        )
    else:
        for field, value in values.items():
            setattr(snapshot, field, value)
        snapshot.updated_at = now
    session.add(snapshot)


def refresh_credit_card_invoice_snapshots(
    session: Session,
    months: int = DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
    user_id: Optional[int] = None,
) -> int:
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = shift_month(date(int(first_year), int(first_month), 1), -1)
    payment_transactions = credit_card_payment_transactions(
        session,
        start_date,
        today,
        user_id=user_id,
    )

    account_due_days: Dict[str, int] = {}
    for acct in session.exec(scope_query(select(Account), Account.user_id, user_id)).all():
        if acct.type == "CREDIT" and acct.credit_balance_due_date:
            account_due_days[acct.id] = acct.credit_balance_due_date.day

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in payment_transactions:
        due_day = account_due_days.get(tx.account_id, DEFAULT_CREDIT_CARD_DUE_DAY)
        invoice_month = invoice_month_from_payment(tx.date, due_day)
        by_month[invoice_month].append(tx)

    refreshed_count = 0
    now = datetime.utcnow()
    existing_months = {
        snapshot.year_month
        for snapshot in session.exec(
            scope_query(select(CreditCardInvoiceMonth), CreditCardInvoiceMonth.user_id, user_id)
        ).all()
        if snapshot.year_month in month_keys
    }
    for month in month_keys:
        txs = by_month.get(month, [])
        if not txs and month not in existing_months:
            continue
        month_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
        _upsert_snapshot(
            session,
            CreditCardInvoiceMonth,
            month,
            user_id,
            now,
            {
                "total": month_total,
                "payment_count": len(txs),
            },
        )
        refreshed_count += 1

    session.commit()
    return refreshed_count


def refresh_bank_income_snapshots(
    session: Session,
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
    user_id: Optional[int] = None,
) -> int:
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    income_transactions = bank_income_transactions(session, start_date, today, user_id=user_id)

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in income_transactions:
        by_month[month_key(tx.date)].append(tx)

    refreshed_count = 0
    now = datetime.utcnow()
    existing_months = {
        snapshot.year_month
        for snapshot in session.exec(
            scope_query(select(BankIncomeMonth), BankIncomeMonth.user_id, user_id)
        ).all()
        if snapshot.year_month in month_keys
    }
    for month in month_keys:
        txs = by_month.get(month, [])
        if not txs and month not in existing_months:
            continue
        month_total = sum((tx.amount for tx in txs), Decimal("0"))
        _upsert_snapshot(
            session,
            BankIncomeMonth,
            month,
            user_id,
            now,
            {
                "total": month_total,
                "income_count": len(txs),
            },
        )
        refreshed_count += 1

    session.commit()
    return refreshed_count


def refresh_monthly_balance_snapshots(
    session: Session,
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
    user_id: Optional[int] = None,
) -> tuple[int, int, int]:
    """Refresh all three snapshot tables and return (income_count, invoice_count, balance_count)."""
    refreshed_income_count = refresh_bank_income_snapshots(session, months, user_id=user_id)
    refreshed_invoice_count = refresh_credit_card_invoice_snapshots(session, months, user_id=user_id)

    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    card_spend_transactions = credit_card_spend_transactions(
        session,
        start_date,
        today,
        user_id=user_id,
    )

    card_spend_by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in card_spend_transactions:
        card_spend_by_month[month_key(tx.date)].append(tx)

    income_snapshots = {
        snapshot.year_month: snapshot
        for snapshot in session.exec(
            scope_query(select(BankIncomeMonth), BankIncomeMonth.user_id, user_id)
        ).all()
        if snapshot.year_month in month_keys
    }
    invoice_snapshots = {
        snapshot.year_month: snapshot
        for snapshot in session.exec(
            scope_query(select(CreditCardInvoiceMonth), CreditCardInvoiceMonth.user_id, user_id)
        ).all()
        if snapshot.year_month in month_keys
    }
    existing_months = {
        snapshot.year_month
        for snapshot in session.exec(
            scope_query(select(MonthlyBalanceMonth), MonthlyBalanceMonth.user_id, user_id)
        ).all()
        if snapshot.year_month in month_keys
    }

    refreshed_count = 0
    now = datetime.utcnow()
    for month in month_keys:
        income_snapshot = income_snapshots.get(month)
        invoice_snapshot = invoice_snapshots.get(month)
        spend_txs = card_spend_by_month.get(month, [])
        income = income_snapshot.total if income_snapshot is not None else Decimal("0")
        income_transaction_count = income_snapshot.income_count if income_snapshot else 0
        invoice_paid = invoice_snapshot.total if invoice_snapshot is not None else Decimal("0")
        invoice_payment_count = invoice_snapshot.payment_count if invoice_snapshot else 0
        card_spend = sum((abs(tx.amount) for tx in spend_txs), Decimal("0"))
        card_spend_count = len(spend_txs)

        if month not in existing_months and income == 0 and card_spend == 0 and invoice_paid == 0:
            continue

        net_by_purchase_month = income - card_spend
        net_cashflow = income - invoice_paid
        _upsert_snapshot(
            session,
            MonthlyBalanceMonth,
            month,
            user_id,
            now,
            {
                "income": income,
                "card_spend": card_spend,
                "invoice_paid": invoice_paid,
                "net_by_purchase_month": net_by_purchase_month,
                "net_cashflow": net_cashflow,
                "income_count": income_transaction_count,
                "card_spend_count": card_spend_count,
                "invoice_payment_count": invoice_payment_count,
            },
        )
        refreshed_count += 1

    session.commit()
    return refreshed_income_count, refreshed_invoice_count, refreshed_count
