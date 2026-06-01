import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict

from sqlmodel import Session, select

from app.models import (
    Account,
    BankIncomeMonth,
    CreditCardInvoiceMonth,
    MonthlyBalanceMonth,
    Transaction,
)
from app.services.classification import TransactionClassifier
from app.services.snapshots import (
    refresh_bank_income_snapshots,
    refresh_credit_card_invoice_snapshots,
    refresh_monthly_balance_snapshots,
)
from app.services.transactions import (
    BANK_ACCOUNT_TYPES,
    account_ids_by_type,
    bank_cashflow_exclusion_rules,
    bank_income_transactions,
    credit_card_payment_transactions,
    ignored_description_patterns,
    is_ignored_transaction,
    last_month_keys,
    month_key,
)


_DEFAULT_DUE_DAY = 6  # fallback when account has no credit_balance_due_date


def invoice_month_from_payment(payment_date: date, due_day: int) -> str:
    """Return the YYYY-MM of the invoice that a payment belongs to.

    The invoice month is the month containing the nearest due date that
    falls ON OR AFTER the payment date.

    Example — payment 2026-04-29, due_day=4:
      candidate this month = 2026-04-04  (already past)
      → next month          = 2026-05   ✓

    Example — payment 2026-05-03, due_day=4:
      candidate this month = 2026-05-04  (still in the future)
      → same month          = 2026-05   ✓
    """
    max_day = calendar.monthrange(payment_date.year, payment_date.month)[1]
    candidate_day = min(due_day, max_day)
    candidate = payment_date.replace(day=candidate_day)
    if candidate >= payment_date:
        return candidate.strftime("%Y-%m")
    # Due date this month is already past — invoice belongs to next month.
    if payment_date.month == 12:
        return f"{payment_date.year + 1}-01"
    return f"{payment_date.year}-{payment_date.month + 1:02d}"


def ignored_transactions_monthly_summary(session: Session):
    today = date.today()
    ignored_patterns = ignored_description_patterns(session)
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.date <= today)
        .order_by(Transaction.date.desc())
    ).all()
    ignored_transactions = [
        tx
        for tx in transactions
        if ignored_patterns and is_ignored_transaction(tx, ignored_patterns)
    ]

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    for tx in ignored_transactions:
        by_month[tx.date.strftime("%Y-%m")].append(tx)

    months = []
    total = Decimal("0")
    for month in sorted(by_month.keys()):
        txs = by_month[month]
        month_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
        total += month_total
        months.append(
            {
                "month": month,
                "total": float(month_total),
                "count": len(txs),
                "transactions": [
                    {
                        "id": tx.id,
                        "date": tx.date.isoformat(),
                        "amount": float(tx.amount),
                        "amount_abs": float(abs(tx.amount)),
                        "description": tx.description,
                        "pluggy_category": tx.category,
                    }
                    for tx in txs
                ],
            }
        )

    return {
        "total": float(total),
        "total_count": len(ignored_transactions),
        "months": months,
    }


def credit_card_payments_monthly_summary(session: Session, months: int):
    """Return monthly credit-card invoice payments for the last ``months`` months.

    Payments are attributed to the invoice month (the month whose due date is
    the nearest future due date relative to the payment date), NOT to the
    calendar month of the payment transaction.  This correctly handles
    payments made before the due date — e.g. a payment on 2026-04-29 for an
    invoice due 2026-05-04 is attributed to 2026-05, not 2026-04.
    """
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    payment_transactions = credit_card_payment_transactions(
        session,
        start_date,
        today,
    )

    # Build a per-account due_day map from persisted Pluggy credit data.
    account_due_days: Dict[str, int] = {}
    for acct in session.exec(select(Account)).all():
        if acct.type == "CREDIT" and acct.credit_balance_due_date:
            account_due_days[acct.id] = acct.credit_balance_due_date.day

    # Bucket each payment by the invoice month it belongs to.
    by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    tx_invoice_month: Dict[str, str] = {}  # tx.id → invoice_month
    for tx in payment_transactions:
        due_day = account_due_days.get(tx.account_id, _DEFAULT_DUE_DAY)
        inv_month = invoice_month_from_payment(tx.date, due_day)
        tx_invoice_month[tx.id] = inv_month
        if inv_month in by_month:
            by_month[inv_month].append(tx)

    total = Decimal("0")
    total_count = 0
    output_months = []
    for month in month_keys:
        txs = by_month[month]
        month_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
        month_count = len(txs)
        total += month_total
        total_count += month_count
        output_months.append(
            {
                "month": month,
                "total": float(month_total),
                "count": month_count,
                "transactions": [
                    {
                        "id": tx.id,
                        "date": tx.date.isoformat(),
                        "amount": float(tx.amount),
                        "amount_abs": float(abs(tx.amount)),
                        "description": tx.description,
                        "pluggy_category": tx.category,
                        "invoice_month": tx_invoice_month[tx.id],
                    }
                    for tx in txs
                ],
            }
        )

    return {
        "total": float(total),
        "total_count": total_count,
        "months": output_months,
    }


def credit_card_payments_history_summary(session: Session):
    refresh_credit_card_invoice_snapshots(session)

    snapshots = session.exec(
        select(CreditCardInvoiceMonth).order_by(
            CreditCardInvoiceMonth.year_month.asc()
        )
    ).all()
    total = sum((snapshot.total for snapshot in snapshots), Decimal("0"))
    total_count = sum(snapshot.payment_count for snapshot in snapshots)
    return {
        "total": float(total),
        "total_count": total_count,
        "month_count": len(snapshots),
        "months": [
            {
                "month": snapshot.year_month,
                "total": float(snapshot.total),
                "count": snapshot.payment_count,
                "captured_at": snapshot.captured_at.isoformat(),
                "updated_at": snapshot.updated_at.isoformat(),
            }
            for snapshot in snapshots
        ],
    }


def bank_income_monthly_summary(session: Session, months: int):
    refresh_bank_income_snapshots(session, months)

    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    active_bank_ids = set(account_ids_by_type(session, BANK_ACCOUNT_TYPES, active_only=True))
    bank_accounts = {
        account.id: account
        for account in session.exec(select(Account)).all()
        if account.id in active_bank_ids
    }
    income_transactions = bank_income_transactions(session, start_date, today)
    snapshots = {
        snapshot.year_month: snapshot
        for snapshot in session.exec(select(BankIncomeMonth)).all()
        if snapshot.year_month in month_keys
    }

    by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    for tx in income_transactions:
        month = month_key(tx.date)
        if month in by_month:
            by_month[month].append(tx)

    total = Decimal("0")
    output_months = []
    for month in month_keys:
        snapshot = snapshots.get(month)
        txs = by_month[month]
        income = snapshot.total if snapshot is not None else Decimal("0")
        income_count = snapshot.income_count if snapshot is not None else 0
        total += income
        output_months.append(
            {
                "month": month,
                "income": float(income),
                "count": income_count,
                "transactions": [
                    {
                        "id": tx.id,
                        "account_id": tx.account_id,
                        "account_name": bank_accounts[tx.account_id].name,
                        "date": tx.date.isoformat(),
                        "amount": float(tx.amount),
                        "description": tx.description,
                        "pluggy_category": tx.category,
                    }
                    for tx in txs
                ],
            }
        )

    return {
        "total_income": float(total),
        "transaction_count": sum(month["count"] for month in output_months),
        "bank_account_count": len(bank_accounts),
        "months": output_months,
    }


def bank_income_history_summary(session: Session):
    refresh_bank_income_snapshots(session)

    snapshots = session.exec(
        select(BankIncomeMonth).order_by(BankIncomeMonth.year_month.asc())
    ).all()
    total = sum((snapshot.total for snapshot in snapshots), Decimal("0"))
    total_count = sum(snapshot.income_count for snapshot in snapshots)
    return {
        "total_income": float(total),
        "transaction_count": total_count,
        "month_count": len(snapshots),
        "months": [
            {
                "month": snapshot.year_month,
                "income": float(snapshot.total),
                "count": snapshot.income_count,
                "captured_at": snapshot.captured_at.isoformat(),
                "updated_at": snapshot.updated_at.isoformat(),
            }
            for snapshot in snapshots
        ],
    }


def bank_cashflow_monthly_summary(session: Session, months: int):
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    active_bank_ids = set(account_ids_by_type(session, BANK_ACCOUNT_TYPES, active_only=True))
    bank_accounts = {
        account.id: account
        for account in session.exec(select(Account)).all()
        if account.id in active_bank_ids
    }
    exclusion_rules = bank_cashflow_exclusion_rules(session)
    classifier = TransactionClassifier.from_session(session)
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.date >= start_date, Transaction.date <= today)
        .order_by(Transaction.date.desc())
    ).all()
    bank_transactions = [
        tx
        for tx in transactions
        if tx.account_id in bank_accounts
        and classifier.is_bank_cashflow(tx)
    ]

    by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    for tx in bank_transactions:
        month = month_key(tx.date)
        if month in by_month:
            by_month[month].append(tx)

    totals = {
        "income": Decimal("0"),
        "outflow": Decimal("0"),
        "net": Decimal("0"),
    }
    output_months = []
    for month in month_keys:
        txs = by_month[month]
        income = sum((tx.amount for tx in txs if tx.amount > 0), Decimal("0"))
        outflow = sum((abs(tx.amount) for tx in txs if tx.amount < 0), Decimal("0"))
        income_count = sum(1 for tx in txs if tx.amount > 0)
        outflow_count = sum(1 for tx in txs if tx.amount < 0)
        net = income - outflow
        totals["income"] += income
        totals["outflow"] += outflow
        totals["net"] += net
        output_months.append(
            {
                "month": month,
                "income": float(income),
                "outflow": float(outflow),
                "net": float(net),
                "income_count": income_count,
                "outflow_count": outflow_count,
                "transactions": [
                    {
                        "id": tx.id,
                        "account_id": tx.account_id,
                        "account_name": bank_accounts[tx.account_id].name,
                        "date": tx.date.isoformat(),
                        "amount": float(tx.amount),
                        "description": tx.description,
                        "pluggy_category": tx.category,
                    }
                    for tx in txs
                ],
            }
        )

    return {
        "months": output_months,
        "summary": {key: float(value) for key, value in totals.items()},
        "transaction_count": len(bank_transactions),
        "bank_account_count": len(bank_accounts),
        "excluded_rule_count": len(exclusion_rules),
    }


def monthly_balance_summary(session: Session, months: int):
    refresh_monthly_balance_snapshots(session, months)

    today = date.today()
    month_keys = last_month_keys(months, today)
    snapshots = {
        snapshot.year_month: snapshot
        for snapshot in session.exec(select(MonthlyBalanceMonth)).all()
        if snapshot.year_month in month_keys
    }

    output_months = []
    totals = {
        "income": Decimal("0"),
        "card_spend": Decimal("0"),
        "invoice_paid": Decimal("0"),
        "net_by_purchase_month": Decimal("0"),
        "net_cashflow": Decimal("0"),
    }
    for month in month_keys:
        snapshot = snapshots.get(month)
        income = snapshot.income if snapshot is not None else Decimal("0")
        card_spend = snapshot.card_spend if snapshot is not None else Decimal("0")
        invoice_paid = (
            snapshot.invoice_paid if snapshot is not None else Decimal("0")
        )
        net_by_purchase_month = income - card_spend
        net_cashflow = income - invoice_paid
        totals["income"] += income
        totals["card_spend"] += card_spend
        totals["invoice_paid"] += invoice_paid
        totals["net_by_purchase_month"] += net_by_purchase_month
        totals["net_cashflow"] += net_cashflow
        output_months.append(
            {
                "month": month,
                "income": float(income),
                "card_spend": float(card_spend),
                "invoice_paid": float(invoice_paid),
                "net_by_purchase_month": float(net_by_purchase_month),
                "net_cashflow": float(net_cashflow),
                "income_count": snapshot.income_count if snapshot else 0,
                "card_spend_count": snapshot.card_spend_count if snapshot else 0,
                "invoice_payment_count": (
                    snapshot.invoice_payment_count if snapshot else 0
                ),
            }
        )

    return {
        "months": output_months,
        "summary": {key: float(value) for key, value in totals.items()},
    }


def monthly_balance_history_summary(session: Session):
    refresh_monthly_balance_snapshots(session)

    snapshots = session.exec(
        select(MonthlyBalanceMonth).order_by(MonthlyBalanceMonth.year_month.asc())
    ).all()
    totals = {
        "income": sum((snapshot.income for snapshot in snapshots), Decimal("0")),
        "card_spend": sum(
            (snapshot.card_spend for snapshot in snapshots), Decimal("0")
        ),
        "invoice_paid": sum(
            (snapshot.invoice_paid for snapshot in snapshots), Decimal("0")
        ),
        "net_by_purchase_month": sum(
            (snapshot.net_by_purchase_month for snapshot in snapshots),
            Decimal("0"),
        ),
        "net_cashflow": sum(
            (snapshot.net_cashflow for snapshot in snapshots), Decimal("0")
        ),
    }
    return {
        "month_count": len(snapshots),
        "summary": {key: float(value) for key, value in totals.items()},
        "months": [
            {
                "month": snapshot.year_month,
                "income": float(snapshot.income),
                "card_spend": float(snapshot.card_spend),
                "invoice_paid": float(snapshot.invoice_paid),
                "net_by_purchase_month": float(snapshot.net_by_purchase_month),
                "net_cashflow": float(snapshot.net_cashflow),
                "income_count": snapshot.income_count,
                "card_spend_count": snapshot.card_spend_count,
                "invoice_payment_count": snapshot.invoice_payment_count,
                "captured_at": snapshot.captured_at.isoformat(),
                "updated_at": snapshot.updated_at.isoformat(),
            }
            for snapshot in snapshots
        ],
    }
