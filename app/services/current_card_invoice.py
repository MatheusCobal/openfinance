from __future__ import annotations

import calendar
import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import Account, CreditCardBill, Item, Transaction
from app.services.credit_categories import (
    credit_category_payload,
    resolve_credit_internal_category,
)
from app.services.scoping import scope_query
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.transactions import _non_duplicate_clause


RECENT_DUE_WINDOW_DAYS = 5

REFUND_DESCRIPTION_PATTERNS = tuple(
    normalize_description(pattern)
    for pattern in (
        "refund",
        "reembolso",
        "estorno",
        "cancelamento",
        "cancelada",
        "canc parcela",
        "ajuste",
    )
)


def _active_credit_accounts_with_balance(
    session: Session,
    user_id: Optional[int] = None,
) -> list[Account]:
    active_item_ids = {
        item.id
        for item in session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
        if item.is_active
    }
    return [
        account
        for account in session.exec(
            scope_query(select(Account), Account.user_id, user_id)
        ).all()
        if account.type == "CREDIT"
        and account.is_active
        and account.item_id in active_item_ids
        and account.balance is not None
    ]


def _latest_bill(session: Session, account_id: str, today: datetime.date):
    return session.exec(
        select(CreditCardBill)
        .where(
            CreditCardBill.account_id == account_id,
            CreditCardBill.due_date.is_not(None),
            CreditCardBill.due_date <= today,
        )
        .order_by(CreditCardBill.due_date.desc())
    ).first()


def _next_bill(session: Session, account_id: str, today: datetime.date):
    return session.exec(
        select(CreditCardBill)
        .where(
            CreditCardBill.account_id == account_id,
            CreditCardBill.due_date.is_not(None),
            CreditCardBill.due_date > today,
        )
        .order_by(CreditCardBill.due_date.asc())
    ).first()


def _bill_amount(bill: Optional[CreditCardBill]) -> Decimal:
    if bill is None or bill.total_amount is None:
        return Decimal("0")
    return Decimal(bill.total_amount)


def _is_recent_due_window(due_date: datetime.date, today: datetime.date) -> bool:
    return abs((due_date - today).days) <= RECENT_DUE_WINDOW_DAYS


def _future_bill_is_reliable(
    account: Account,
    next_bill: Optional[CreditCardBill],
    today: datetime.date,
) -> bool:
    if next_bill is None or next_bill.due_date is None:
        return False
    if _bill_amount(next_bill) <= 0:
        return False
    if account.credit_balance_due_date == next_bill.due_date:
        return True
    return account.credit_balance_due_date is not None and account.credit_balance_due_date > today


def _should_subtract_latest_bill(
    account: Account,
    latest_bill: Optional[CreditCardBill],
    next_bill: Optional[CreditCardBill],
    raw_balance: Decimal,
    today: datetime.date,
) -> bool:
    if latest_bill is None or latest_bill.due_date is None:
        return False
    latest_amount = _bill_amount(latest_bill)
    if latest_amount <= 0:
        return False
    if account.credit_balance_due_date is None:
        return False
    account_due_is_latest = account.credit_balance_due_date == latest_bill.due_date
    due_is_settling = account.credit_balance_due_date <= today or _is_recent_due_window(
        account.credit_balance_due_date, today
    )
    if not due_is_settling and not account_due_is_latest:
        return False
    if raw_balance < latest_amount:
        return False
    if _future_bill_is_reliable(account, next_bill, today) and not account_due_is_latest:
        return False
    return True


def _looks_like_refund(tx: Transaction) -> bool:
    if tx.amount < 0:
        return True
    return _looks_like_refund_text(tx)


def _looks_like_refund_text(tx: Transaction) -> bool:
    normalized_description = normalize_description(tx.description)
    if any(pattern in normalized_description for pattern in REFUND_DESCRIPTION_PATTERNS):
        return True
    normalized_category = normalize_description(tx.category or "")
    return any(pattern in normalized_category for pattern in REFUND_DESCRIPTION_PATTERNS)


def _category_window_start(
    account: Account,
    latest_bill: Optional[CreditCardBill],
    today: datetime.date,
) -> datetime.date:
    if account.credit_balance_close_date is not None:
        from app.services.credit_card_invoice import _forming_billing_cycle

        cycle_start, _ = _forming_billing_cycle(
            account.credit_balance_close_date,
            today,
        )
        return cycle_start
    if latest_bill is not None and latest_bill.due_date is not None:
        month_start = today.replace(day=1)
        return min(month_start, latest_bill.due_date)
    return today.replace(day=1)


def _serialize_current_invoice_transaction(
    tx: Transaction,
) -> dict[str, Any]:
    classification = serialize_transaction_classification(
        tx,
        account_type="CREDIT",
    )
    effective_category = resolve_credit_internal_category(
        tx,
        account_type="CREDIT",
        current_internal_category=classification.get("internal_category"),
    )
    return {
        "id": tx.id,
        "date": tx.date.isoformat(),
        "description": tx.description,
        "amount": float(abs(tx.amount)),
        "signed_amount": float(tx.amount),
        "pluggy_category": classification["pluggy_raw_category"],
        **classification,
        **credit_category_payload(effective_category),
        "status": tx.status,
        "bill_id": tx.bill_id,
        "installment_number": tx.installment_number,
        "total_installments": tx.total_installments,
    }


def _current_invoice_category_transactions(
    session: Session,
    account: Account,
    latest_bill: Optional[CreditCardBill],
    today: datetime.date,
    user_id: Optional[int] = None,
) -> list[Transaction]:
    from app.services.classification import TransactionClassifier

    start = _category_window_start(account, latest_bill, today)
    rows = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.date >= start,
                Transaction.date <= today,
                _non_duplicate_clause(),
            ),
            Transaction.user_id,
            user_id,
        ).order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()

    classifier = TransactionClassifier.from_session(session, user_id=user_id)
    latest_bill_id = latest_bill.id if latest_bill is not None else None
    return [
        tx
        for tx in rows
        if not classifier.is_invoice_payment(tx)
        and not classifier.is_ignored(tx)
        and (latest_bill_id is None or tx.bill_id != latest_bill_id)
        and not _looks_like_refund(tx)
    ]


def _next_invoice_scheduled_transactions(
    session: Session,
    account: Account,
    today: datetime.date,
    user_id: Optional[int] = None,
) -> list[Transaction]:
    """Return the future installments that compose the next due invoice.

    Pluggy stores scheduled installments with a future transaction date. The
    adjusted card balance can already include those commitments, so omitting
    them from the category breakdown creates a large unexplained gap.
    """
    from app.services.classification import TransactionClassifier

    if today.month == 12:
        year, month = today.year + 1, 1
    else:
        year, month = today.year, today.month + 1
    first_day = datetime.date(year, month, 1)
    last_day = datetime.date(year, month, calendar.monthrange(year, month)[1])
    rows = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.date >= first_day,
                Transaction.date <= last_day,
                _non_duplicate_clause(),
            ),
            Transaction.user_id,
            user_id,
        ).order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()
    classifier = TransactionClassifier.from_session(session, user_id=user_id)
    return [tx for tx in rows if tx.amount > 0 and classifier.is_card_purchase(tx)]


def current_card_invoice_summary(
    session: Session,
    today: Optional[datetime.date] = None,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Return the Dashboard-only adjusted current card invoice summary.

    This intentionally does not reuse planning_invoice_for_month(): planning
    keeps future obligations and scheduled installments, while the Dashboard
    needs the currently visible card balance after removing a closed bill that
    Pluggy may still carry in Account.balance.
    """
    today = today if today is not None else datetime.date.today()

    cards: list[dict[str, Any]] = []
    raw_purchase_transactions: list[dict[str, Any]] = []
    recent_purchase_transactions: list[dict[str, Any]] = []
    raw_total = Decimal("0")
    adjusted_total = Decimal("0")
    adjusted_any = False

    for account in _active_credit_accounts_with_balance(session, user_id=user_id):
        raw_balance = Decimal(account.balance or 0)
        raw_total += raw_balance

        latest = _latest_bill(session, account.id, today)
        next_bill = _next_bill(session, account.id, today)
        latest_amount = _bill_amount(latest)

        adjustments: list[dict[str, Any]] = []
        adjusted_balance = raw_balance
        if _should_subtract_latest_bill(
            account,
            latest,
            next_bill,
            raw_balance,
            today,
        ):
            adjusted_balance = raw_balance - latest_amount
            adjusted_any = True
            adjustments.append(
                {
                    "type": "subtract_closed_bill",
                    "amount": float(latest_amount),
                    "bill_id": latest.id,
                    "bill_due_date": latest.due_date.isoformat() if latest.due_date else None,
                    "reason": "Account.balance still appears to include the latest closed bill",
                }
            )

        current_transactions = _current_invoice_category_transactions(
            session,
            account,
            latest,
            today,
            user_id=user_id,
        )
        recent_purchase_transactions.extend(
            _serialize_current_invoice_transaction(tx) for tx in current_transactions
        )
        category_transactions = list(current_transactions)
        category_transactions.extend(
            _next_invoice_scheduled_transactions(session, account, today, user_id=user_id)
        )
        raw_purchase_transactions.extend(
            _serialize_current_invoice_transaction(tx) for tx in category_transactions
        )

        adjusted_total += adjusted_balance
        cards.append(
            {
                "account_id": account.id,
                "name": account.name,
                "raw_balance": float(raw_balance),
                "adjusted_balance": float(adjusted_balance),
                "due_date": (
                    account.credit_balance_due_date.isoformat()
                    if account.credit_balance_due_date
                    else None
                ),
                "balance_updated_at": (
                    account.balance_updated_at.isoformat() if account.balance_updated_at else None
                ),
                "latest_bill_id": latest.id if latest else None,
                "latest_bill_amount": float(latest_amount),
                "latest_bill_due_date": (
                    latest.due_date.isoformat() if latest is not None and latest.due_date else None
                ),
                "next_bill_id": next_bill.id if next_bill else None,
                "next_bill_due_date": (
                    next_bill.due_date.isoformat()
                    if next_bill is not None and next_bill.due_date
                    else None
                ),
                "adjustments": adjustments,
            }
        )

    source = "adjusted_account_balance" if adjusted_any else "account_balance"
    confidence = "medium" if cards else "none"
    category_total = Decimal("0")
    category_count = 0
    categories_by_name: dict[str, dict[str, Any]] = {}
    for tx in raw_purchase_transactions:
        if tx.get("ignored_from_totals") or tx.get("cashflow_type") != "expense":
            continue
        name = tx.get("effective_category") or "Outros"
        amount = Decimal(str(tx.get("amount") or 0))
        bucket = categories_by_name.setdefault(
            name,
            {
                "id": name,
                "name": name,
                "effective_category": name,
                "resolved_category": name,
                "credit_category": name,
                "color": "#64748b",
                "total": Decimal("0"),
                "count": 0,
                "transactions": [],
                "source": "pluggy_based_classification",
            },
        )
        bucket["total"] += amount
        bucket["count"] += 1
        bucket["transactions"].append(tx)
        category_total += amount
        category_count += 1

    identified_category_total = category_total
    unreconciled_amount = adjusted_total - identified_category_total
    if unreconciled_amount > Decimal("0.005"):
        categories_by_name["Não conciliado"] = {
            "id": "unreconciled",
            "name": "Não conciliado",
            "effective_category": "Não conciliado",
            "resolved_category": "Não conciliado",
            "credit_category": "Não conciliado",
            "color": "#64748b",
            "total": unreconciled_amount,
            "count": 0,
            "transactions": [],
            "source": "account_balance_reconciliation",
            "description": "Saldo informado pela instituição sem transações detalhadas",
        }
        category_total += unreconciled_amount
    categories = [
        {
            **bucket,
            "total": float(bucket["total"]),
        }
        for bucket in sorted(
            categories_by_name.values(),
            key=lambda item: item["total"],
            reverse=True,
        )
    ]

    source_label = (
        "Fatura vigente ajustada"
        if source == "adjusted_account_balance"
        else "Saldo atual ajustado"
    )
    return {
        "amount": float(adjusted_total),
        "raw_account_balance_total": float(raw_total),
        "adjusted_total": float(adjusted_total),
        "source": source,
        "source_label": source_label,
        "confidence": confidence,
        "account_count": len(cards),
        "cards": cards,
        "categories": categories,
        "category_total": float(category_total),
        "category_count": category_count,
        "raw_purchase_transactions": raw_purchase_transactions,
        "recent_purchase_transactions": recent_purchase_transactions,
        "legacy_category_breakdown_removed": False,
        "source_detail": {
            "category_basis": "current_purchases_plus_next_invoice_installments",
            "unreconciled_balance_is_explicit": True,
        },
        "reconciliation": {
            "amount": float(adjusted_total),
            "category_total": float(category_total),
            "identified_category_total": float(identified_category_total),
            "unreconciled_amount": float(max(unreconciled_amount, Decimal("0"))),
            "amount_minus_category_total": float(adjusted_total - category_total),
            "legacy_category_breakdown_removed": False,
            "source_label": source_label,
        },
    }
