from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict

from sqlmodel import Session, select

from app.models import (
    Account,
    BankIncomeMonth,
    CreditCardBill,
    CreditCardInvoiceMonth,
    MonthlyBalanceMonth,
    Transaction,
)
from app.services.invoice_month import (
    DEFAULT_CREDIT_CARD_DUE_DAY,
    invoice_month_from_payment,
)
from app.services.credit_categories import (
    credit_category_payload,
    resolve_credit_internal_category,
)
from app.services.transaction_classifier import (
    CompiledUserRule,
    serialize_transaction_classification,
)
from app.services.user_classification_rules import load_compiled_user_rules
from app.services.transactions import (
    BANK_ACCOUNT_TYPES,
    SPENDING_ACCOUNT_TYPES,
    _non_duplicate_clause,
    account_ids_by_type,
    bank_income_transactions,
    credit_card_payment_transactions,
    credit_card_spend_transactions,
    ignored_description_patterns,
    is_ignored_transaction,
    last_month_keys,
    month_key,
    shift_month,
)


def _classification_fields(
    tx: Transaction,
    accounts_by_id: Dict[str, Account],
    user_rules: tuple[CompiledUserRule, ...] = (),
) -> dict:
    account = accounts_by_id.get(tx.account_id)
    return serialize_transaction_classification(
        tx,
        account_type=account.type if account is not None else None,
        user_rules=user_rules,
    )


def _history_transaction_classification(
    tx: Transaction,
    accounts_by_id: Dict[str, Account],
    user_rules: tuple[CompiledUserRule, ...] = (),
) -> dict:
    classification = _classification_fields(tx, accounts_by_id, user_rules)
    return {
        "pluggy_category": classification["pluggy_raw_category"],
        **classification,
    }


def ignored_transactions_monthly_summary(session: Session):
    today = date.today()
    ignored_patterns = ignored_description_patterns(session)
    transactions = session.exec(
        select(Transaction)
        .where(Transaction.date <= today, _non_duplicate_clause())
        .order_by(Transaction.date.desc())
    ).all()
    ignored_transactions = [
        tx
        for tx in transactions
        if ignored_patterns and is_ignored_transaction(tx, ignored_patterns)
    ]
    accounts_by_id = {account.id: account for account in session.exec(select(Account)).all()}
    user_rules = load_compiled_user_rules(session)

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
                        **_history_transaction_classification(tx, accounts_by_id, user_rules),
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
    start_date = shift_month(date(int(first_year), int(first_month), 1), -1)
    payment_transactions = credit_card_payment_transactions(
        session,
        start_date,
        today,
    )
    accounts_by_id = {account.id: account for account in session.exec(select(Account)).all()}
    user_rules = load_compiled_user_rules(session)

    # Build a per-account due_day map from persisted Pluggy credit data.
    account_due_days: Dict[str, int] = {}
    for acct in accounts_by_id.values():
        if acct.type == "CREDIT" and acct.credit_balance_due_date:
            account_due_days[acct.id] = acct.credit_balance_due_date.day

    # Bucket each payment by the invoice month it belongs to.
    by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    tx_invoice_month: Dict[str, str] = {}  # tx.id → invoice_month
    for tx in payment_transactions:
        due_day = account_due_days.get(tx.account_id, DEFAULT_CREDIT_CARD_DUE_DAY)
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
                        **_history_transaction_classification(tx, accounts_by_id, user_rules),
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


def _month_start_from_key(year_month: str) -> date:
    year, month = year_month.split("-")
    return date(int(year), int(month), 1)


def _month_keys_between(start_month: date, end_month_exclusive: date) -> list[str]:
    keys: list[str] = []
    cursor = start_month
    while cursor < end_month_exclusive:
        keys.append(month_key(cursor))
        cursor = shift_month(cursor, 1)
    return keys


def _month_keys_ending_at(end_month: date, count: int) -> list[str]:
    return [
        month_key(shift_month(end_month, offset))
        for offset in range(-(count - 1), 1)
    ]


def _history_card_purchase_transaction(
    tx: Transaction,
    accounts_by_id: Dict[str, Account],
    user_rules: tuple[CompiledUserRule, ...],
) -> dict[str, Any]:
    classification = _history_transaction_classification(tx, accounts_by_id, user_rules)
    account = accounts_by_id.get(tx.account_id)
    effective_category = resolve_credit_internal_category(
        tx,
        account_type=account.type if account is not None else "CREDIT",
        current_internal_category=classification.get("internal_category"),
    )
    return {
        "id": tx.id,
        "account_id": tx.account_id,
        "account_name": account.name if account is not None else None,
        "date": tx.date.isoformat(),
        "amount": float(abs(tx.amount)),
        "amount_abs": float(abs(tx.amount)),
        "signed_amount": float(tx.amount),
        "description": tx.description,
        **classification,
        **credit_category_payload(effective_category),
        "status": tx.status,
        "bill_id": tx.bill_id,
        "installment_number": tx.installment_number,
        "total_installments": tx.total_installments,
    }


def _credit_card_official_bill_totals_by_month(
    session: Session,
    selected_months: set[str],
) -> dict[str, dict[str, Any]]:
    credit_account_ids = set(account_ids_by_type(session, SPENDING_ACCOUNT_TYPES))
    if not credit_account_ids:
        return {}

    bills = session.exec(select(CreditCardBill)).all()
    totals_by_month: dict[str, dict[str, Any]] = {}
    for bill in bills:
        if bill.account_id not in credit_account_ids:
            continue
        if bill.due_date is None or bill.total_amount is None:
            continue
        bill_month = month_key(bill.due_date)
        if bill_month not in selected_months:
            continue

        bucket = totals_by_month.setdefault(
            bill_month,
            {
                "total": Decimal("0"),
                "bill_count": 0,
                "due_dates": set(),
                "bills": [],
            },
        )
        bucket["total"] += Decimal(bill.total_amount)
        bucket["bill_count"] += 1
        bucket["due_dates"].add(bill.due_date.isoformat())
        bucket["bills"].append(
            {
                "id": bill.id,
                "account_id": bill.account_id,
                "due_date": bill.due_date.isoformat(),
                "total_amount": float(bill.total_amount),
                "minimum_payment_amount": float(bill.minimum_payment_amount or 0),
            }
        )

    return {
        month: {
            **bucket,
            "due_dates": sorted(bucket["due_dates"]),
        }
        for month, bucket in totals_by_month.items()
    }


def _credit_card_invoice_snapshot_totals_by_month(
    session: Session,
    selected_months: set[str],
) -> dict[str, dict[str, Any]]:
    snapshots = session.exec(
        select(CreditCardInvoiceMonth).where(
            CreditCardInvoiceMonth.year_month.in_(selected_months)
        )
    ).all()
    return {
        snapshot.year_month: {
            "total": Decimal(snapshot.total),
            "payment_count": snapshot.payment_count,
            "captured_at": snapshot.captured_at.isoformat(),
            "updated_at": snapshot.updated_at.isoformat(),
        }
        for snapshot in snapshots
    }


def credit_card_invoice_purchases_monthly_summary(session: Session, months: int):
    """Return invoice history with display totals separated from classifications.

    Historical months use Pluggy's official bill as the displayed invoice
    total. The vigente month uses the same current-invoice source as the
    Dashboard. Classified CREDIT purchases remain available for category
    breakdowns, averages and drilldowns.
    """
    today = date.today()
    from app.services.credit_card_invoice import _next_calendar_month
    from app.services.current_card_invoice import current_card_invoice_summary

    vigente_month = _next_calendar_month(today)
    selected_months = _month_keys_ending_at(_month_start_from_key(vigente_month), months)
    selected_month_set = set(selected_months)
    first_selected_month = _month_start_from_key(selected_months[0])
    average_window_start = shift_month(first_selected_month, -12)
    official_bills_by_month = _credit_card_official_bill_totals_by_month(
        session,
        selected_month_set,
    )
    invoice_snapshots_by_month = _credit_card_invoice_snapshot_totals_by_month(
        session,
        selected_month_set,
    )
    current_invoice = current_card_invoice_summary(session, today=today)
    current_invoice_total = Decimal(str(current_invoice.get("amount") or 0))

    purchases = credit_card_spend_transactions(
        session,
        average_window_start,
        today,
    )
    accounts_by_id = {account.id: account for account in session.exec(select(Account)).all()}
    user_rules = load_compiled_user_rules(session)

    selected_transactions_by_month: Dict[str, list[dict[str, Any]]] = {
        month: [] for month in selected_months
    }
    totals_by_month_category: Dict[str, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    counts_by_month_category: Dict[str, Dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    first_purchase_month: date | None = None

    for tx in purchases:
        serialized = _history_card_purchase_transaction(tx, accounts_by_id, user_rules)
        if serialized.get("ignored_from_totals") or serialized.get("cashflow_type") != "expense":
            continue

        category_name = serialized.get("effective_category") or "Outros"
        amount = Decimal(str(serialized["amount_abs"]))
        tx_month = month_key(tx.date)
        totals_by_month_category[tx_month][category_name] += amount
        counts_by_month_category[tx_month][category_name] += 1

        tx_month_start = _month_start_from_key(tx_month)
        if first_purchase_month is None or tx_month_start < first_purchase_month:
            first_purchase_month = tx_month_start

        if tx_month in selected_month_set:
            selected_transactions_by_month[tx_month].append(serialized)

    def average_month_keys_for(selected_month: str) -> list[str]:
        selected_start = _month_start_from_key(selected_month)
        window_start = shift_month(selected_start, -12)
        if first_purchase_month is None or first_purchase_month >= selected_start:
            return []
        effective_start = max(window_start, first_purchase_month)
        return _month_keys_between(effective_start, selected_start)

    output_months = []
    invoice_display_total = Decimal("0")
    classified_purchase_total = Decimal("0")
    total_count = 0
    for selected_month in selected_months:
        txs = selected_transactions_by_month[selected_month]
        month_classified_total = sum(
            (Decimal(str(tx["amount_abs"])) for tx in txs),
            Decimal("0"),
        )
        classified_purchase_total += month_classified_total
        total_count += len(txs)
        average_month_keys = average_month_keys_for(selected_month)
        average_months_used = len(average_month_keys)
        bill_bucket = official_bills_by_month.get(selected_month)
        official_bill_total = (
            Decimal(bill_bucket["total"])
            if bill_bucket is not None
            else None
        )
        snapshot_bucket = invoice_snapshots_by_month.get(selected_month)
        snapshot_invoice_total = (
            Decimal(snapshot_bucket["total"])
            if snapshot_bucket is not None
            else None
        )
        is_current_invoice = selected_month == vigente_month
        if is_current_invoice:
            month_invoice_display_total = current_invoice_total
            invoice_total_source = "dashboard_current_invoice"
        elif official_bill_total is not None:
            month_invoice_display_total = official_bill_total
            invoice_total_source = "pluggy_official_bill"
        elif snapshot_invoice_total is not None:
            month_invoice_display_total = snapshot_invoice_total
            invoice_total_source = "credit_card_invoice_snapshot"
        else:
            month_invoice_display_total = month_classified_total
            invoice_total_source = "missing_official_bill_fallback"
        invoice_display_total += month_invoice_display_total

        categories_by_name: Dict[str, dict[str, Any]] = {}
        for tx in txs:
            category_name = tx.get("effective_category") or "Outros"
            bucket = categories_by_name.setdefault(
                category_name,
                {
                    "id": category_name,
                    "name": category_name,
                    "effective_category": category_name,
                    "resolved_category": category_name,
                    "credit_category": category_name,
                    "total": Decimal("0"),
                    "count": 0,
                    "cashflow_type": "expense",
                    "source": "pluggy_based_classification",
                    "transactions": [],
                },
            )
            bucket["total"] += Decimal(str(tx["amount_abs"]))
            bucket["count"] += 1
            bucket["transactions"].append(tx)

        categories = []
        for category_name, bucket in categories_by_name.items():
            average_total = sum(
                (
                    totals_by_month_category[month].get(category_name, Decimal("0"))
                    for month in average_month_keys
                ),
                Decimal("0"),
            )
            average = (
                average_total / Decimal(average_months_used)
                if average_months_used > 0
                else Decimal("0")
            )
            difference = bucket["total"] - average
            difference_percent = (
                float((difference / average) * Decimal("100"))
                if average > 0
                else None
            )
            categories.append(
                {
                    **bucket,
                    "total": float(bucket["total"]),
                    "average_12m": float(average),
                    "average_months_used": average_months_used,
                    "average_window_months": 12,
                    "difference_from_average": float(difference),
                    "difference_percent": difference_percent,
                }
            )

        output_months.append(
            {
                "month": selected_month,
                "total": float(month_invoice_display_total),
                "invoice_display_total": float(month_invoice_display_total),
                "invoice_total_source": invoice_total_source,
                "official_bill_total": (
                    float(official_bill_total)
                    if official_bill_total is not None
                    else None
                ),
                "official_bill_count": bill_bucket["bill_count"] if bill_bucket else 0,
                "official_bill_due_dates": bill_bucket["due_dates"] if bill_bucket else [],
                "official_bills": bill_bucket["bills"] if bill_bucket else [],
                "snapshot_invoice_total": (
                    float(snapshot_invoice_total)
                    if snapshot_invoice_total is not None
                    else None
                ),
                "snapshot_payment_count": (
                    snapshot_bucket["payment_count"] if snapshot_bucket else 0
                ),
                "snapshot_captured_at": (
                    snapshot_bucket["captured_at"] if snapshot_bucket else None
                ),
                "snapshot_updated_at": (
                    snapshot_bucket["updated_at"] if snapshot_bucket else None
                ),
                "classified_purchase_total": float(month_classified_total),
                "classified_purchase_difference_from_invoice": float(
                    month_classified_total - month_invoice_display_total
                ),
                "is_current_invoice": is_current_invoice,
                "dashboard_current_invoice_source": (
                    current_invoice.get("source") if is_current_invoice else None
                ),
                "count": len(txs),
                "average_months_available": average_months_used,
                "categories": sorted(
                    categories,
                    key=lambda item: item["total"],
                    reverse=True,
                ),
                "transactions": sorted(
                    txs,
                    key=lambda tx: (tx["date"], tx["description"]),
                    reverse=True,
                ),
            }
        )

    return {
        "total": float(invoice_display_total),
        "invoice_display_total": float(invoice_display_total),
        "classified_purchase_total": float(classified_purchase_total),
        "total_count": total_count,
        "month_count": len(output_months),
        "months": output_months,
        "source": "credit_card_invoice_history",
        "classified_purchase_source": "credit_card_spend_transactions",
        "current_invoice_month": vigente_month,
        "average_window_months": 12,
        "purchase_boundary": {
            "account_type": "CREDIT",
            "cashflow_type": "expense",
            "ignored_from_totals": False,
            "duplicates": "excluded",
        },
    }


def credit_card_payments_history_summary(session: Session):
    snapshots = session.exec(
        select(CreditCardInvoiceMonth).order_by(CreditCardInvoiceMonth.year_month.asc())
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
    accounts_by_id = bank_accounts
    user_rules = load_compiled_user_rules(session)
    income_transactions = bank_income_transactions(session, start_date, today)
    by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    for tx in income_transactions:
        month = month_key(tx.date)
        if month in by_month:
            by_month[month].append(tx)

    total = Decimal("0")
    output_months = []
    for month in month_keys:
        txs = by_month[month]
        income = sum((tx.amount for tx in txs), Decimal("0"))
        income_count = len(txs)
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
                        **_history_transaction_classification(tx, accounts_by_id, user_rules),
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
    """Return raw monthly BANK inflows and outflows.

    This endpoint backs Historico's "Entradas e saidas" tab.  It is meant to
    behave like a bank-account cash movement view, so it includes every
    non-duplicate transaction from active BANK accounts: PIX, boleto, card
    payments, transfers and other Pluggy categories.  Classification remains
    serialized for display/editing, but it must not decide whether a BANK
    transaction appears in this view.
    """
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
    accounts_by_id = bank_accounts
    user_rules = load_compiled_user_rules(session)
    transactions = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id.in_(active_bank_ids),
            Transaction.date >= start_date,
            Transaction.date <= today,
            _non_duplicate_clause(),
        )
        .order_by(Transaction.date.desc())
    ).all()
    bank_transactions = [tx for tx in transactions if tx.account_id in bank_accounts]

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
                        **_history_transaction_classification(tx, accounts_by_id, user_rules),
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
        "excluded_rule_count": 0,
        "source": "raw_bank_transactions",
    }


def monthly_balance_summary(session: Session, months: int):
    today = date.today()
    month_keys = last_month_keys(months, today)
    first_year, first_month = month_keys[0].split("-")
    start_date = date(int(first_year), int(first_month), 1)
    payment_start_date = shift_month(start_date, -1)
    income_transactions = bank_income_transactions(session, start_date, today)
    card_transactions = credit_card_spend_transactions(session, start_date, today)
    payment_transactions = credit_card_payment_transactions(
        session,
        payment_start_date,
        today,
    )

    account_due_days: Dict[str, int] = {}
    for acct in session.exec(select(Account)).all():
        if acct.type == "CREDIT" and acct.credit_balance_due_date:
            account_due_days[acct.id] = acct.credit_balance_due_date.day

    income_by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    card_by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    payments_by_month: Dict[str, list[Transaction]] = {month: [] for month in month_keys}
    for tx in income_transactions:
        if (month := month_key(tx.date)) in income_by_month:
            income_by_month[month].append(tx)
    for tx in card_transactions:
        if (month := month_key(tx.date)) in card_by_month:
            card_by_month[month].append(tx)
    for tx in payment_transactions:
        due_day = account_due_days.get(tx.account_id, DEFAULT_CREDIT_CARD_DUE_DAY)
        invoice_month = invoice_month_from_payment(tx.date, due_day)
        if invoice_month in payments_by_month:
            payments_by_month[invoice_month].append(tx)

    output_months = []
    totals = {
        "income": Decimal("0"),
        "card_spend": Decimal("0"),
        "invoice_paid": Decimal("0"),
        "net_by_purchase_month": Decimal("0"),
        "net_cashflow": Decimal("0"),
    }
    for month in month_keys:
        income_txs = income_by_month[month]
        card_txs = card_by_month[month]
        payment_txs = payments_by_month[month]
        income = sum((tx.amount for tx in income_txs), Decimal("0"))
        card_spend = sum((abs(tx.amount) for tx in card_txs), Decimal("0"))
        invoice_paid = sum((abs(tx.amount) for tx in payment_txs), Decimal("0"))
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
                "income_count": len(income_txs),
                "card_spend_count": len(card_txs),
                "invoice_payment_count": len(payment_txs),
            }
        )

    return {
        "months": output_months,
        "summary": {key: float(value) for key, value in totals.items()},
    }


def monthly_balance_history_summary(session: Session):
    snapshots = session.exec(
        select(MonthlyBalanceMonth).order_by(MonthlyBalanceMonth.year_month.asc())
    ).all()
    totals = {
        "income": sum((snapshot.income for snapshot in snapshots), Decimal("0")),
        "card_spend": sum((snapshot.card_spend for snapshot in snapshots), Decimal("0")),
        "invoice_paid": sum((snapshot.invoice_paid for snapshot in snapshots), Decimal("0")),
        "net_by_purchase_month": sum(
            (snapshot.net_by_purchase_month for snapshot in snapshots),
            Decimal("0"),
        ),
        "net_cashflow": sum((snapshot.net_cashflow for snapshot in snapshots), Decimal("0")),
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
