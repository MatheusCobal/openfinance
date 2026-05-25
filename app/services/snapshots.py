from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Dict

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.models import (
    BankIncomeMonth,
    CreditCardInvoiceMonth,
    MonthlyBalanceMonth,
    Transaction,
)
from app.services.transactions import (
    bank_income_transactions,
    credit_card_payment_transactions,
    credit_card_spend_transactions,
    last_month_keys,
    month_key,
)

DEFAULT_CREDIT_CARD_PAYMENT_MONTHS = 12
DEFAULT_MONTHLY_BALANCE_MONTHS = 12


def refresh_credit_card_invoice_snapshots(
    session: Session,
    months: int = DEFAULT_CREDIT_CARD_PAYMENT_MONTHS,
) -> int:
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    payment_transactions = credit_card_payment_transactions(
        session,
        start_date,
        today,
    )

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in payment_transactions:
        by_month[month_key(tx.date)].append(tx)

    refreshed_count = 0
    now = datetime.utcnow()
    existing_months = {
        snapshot.year_month
        for snapshot in session.exec(select(CreditCardInvoiceMonth)).all()
        if snapshot.year_month in month_keys
    }
    for month in month_keys:
        txs = by_month.get(month, [])
        if not txs and month not in existing_months:
            continue
        month_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
        statement = sqlite_insert(CreditCardInvoiceMonth).values(
            year_month=month,
            total=month_total,
            payment_count=len(txs),
            captured_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["year_month"],
            set_={
                "total": month_total,
                "payment_count": len(txs),
                "updated_at": now,
            },
        )
        session.execute(statement)
        refreshed_count += 1

    session.commit()
    return refreshed_count


def refresh_bank_income_snapshots(
    session: Session,
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
) -> int:
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    income_transactions = bank_income_transactions(session, start_date, today)

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in income_transactions:
        by_month[month_key(tx.date)].append(tx)

    refreshed_count = 0
    now = datetime.utcnow()
    existing_months = {
        snapshot.year_month
        for snapshot in session.exec(select(BankIncomeMonth)).all()
        if snapshot.year_month in month_keys
    }
    for month in month_keys:
        txs = by_month.get(month, [])
        if not txs and month not in existing_months:
            continue
        month_total = sum((tx.amount for tx in txs), Decimal("0"))
        statement = sqlite_insert(BankIncomeMonth).values(
            year_month=month,
            total=month_total,
            income_count=len(txs),
            captured_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["year_month"],
            set_={
                "total": month_total,
                "income_count": len(txs),
                "updated_at": now,
            },
        )
        session.execute(statement)
        refreshed_count += 1

    session.commit()
    return refreshed_count


def refresh_monthly_balance_snapshots(
    session: Session,
    months: int = DEFAULT_MONTHLY_BALANCE_MONTHS,
) -> tuple[int, int, int]:
    """Refresh all three snapshot tables and return (income_count, invoice_count, balance_count)."""
    income_count = refresh_bank_income_snapshots(session, months)
    invoice_count = refresh_credit_card_invoice_snapshots(session, months)

    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    card_spend_transactions = credit_card_spend_transactions(
        session,
        start_date,
        today,
    )

    card_spend_by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in card_spend_transactions:
        card_spend_by_month[month_key(tx.date)].append(tx)

    income_snapshots = {
        snapshot.year_month: snapshot
        for snapshot in session.exec(select(BankIncomeMonth)).all()
        if snapshot.year_month in month_keys
    }
    invoice_snapshots = {
        snapshot.year_month: snapshot
        for snapshot in session.exec(select(CreditCardInvoiceMonth)).all()
        if snapshot.year_month in month_keys
    }
    existing_months = {
        snapshot.year_month
        for snapshot in session.exec(select(MonthlyBalanceMonth)).all()
        if snapshot.year_month in month_keys
    }

    refreshed_count = 0
    now = datetime.utcnow()
    for month in month_keys:
        income_snapshot = income_snapshots.get(month)
        invoice_snapshot = invoice_snapshots.get(month)
        spend_txs = card_spend_by_month.get(month, [])
        income = income_snapshot.total if income_snapshot is not None else Decimal("0")
        income_count = income_snapshot.income_count if income_snapshot else 0
        invoice_paid = (
            invoice_snapshot.total if invoice_snapshot is not None else Decimal("0")
        )
        invoice_count = invoice_snapshot.payment_count if invoice_snapshot else 0
        card_spend = sum((abs(tx.amount) for tx in spend_txs), Decimal("0"))
        card_spend_count = len(spend_txs)

        if (
            month not in existing_months
            and income == 0
            and card_spend == 0
            and invoice_paid == 0
        ):
            continue

        net_by_purchase_month = income - card_spend
        net_cashflow = income - invoice_paid
        statement = sqlite_insert(MonthlyBalanceMonth).values(
            year_month=month,
            income=income,
            card_spend=card_spend,
            invoice_paid=invoice_paid,
            net_by_purchase_month=net_by_purchase_month,
            net_cashflow=net_cashflow,
            income_count=income_count,
            card_spend_count=card_spend_count,
            invoice_payment_count=invoice_count,
            captured_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["year_month"],
            set_={
                "income": income,
                "card_spend": card_spend,
                "invoice_paid": invoice_paid,
                "net_by_purchase_month": net_by_purchase_month,
                "net_cashflow": net_cashflow,
                "income_count": income_count,
                "card_spend_count": card_spend_count,
                "invoice_payment_count": invoice_count,
                "updated_at": now,
            },
        )
        session.execute(statement)
        refreshed_count += 1

    session.commit()
    return income_count, invoice_count, refreshed_count
