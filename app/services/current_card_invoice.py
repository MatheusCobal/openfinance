from __future__ import annotations

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
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.transactions import (
    _non_duplicate_clause,
    credit_card_payment_transactions,
)


PAYMENT_MATCH_TOLERANCE = Decimal("1.00")
RECENT_DUE_WINDOW_DAYS = 5
REFUND_LOOKBACK_DAYS = 30

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


def _active_credit_accounts_with_balance(session: Session) -> list[Account]:
    active_item_ids = {item.id for item in session.exec(select(Item)).all() if item.is_active}
    return [
        account
        for account in session.exec(select(Account)).all()
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


def _serialize_payment(tx: Transaction) -> dict[str, Any]:
    return {
        "id": tx.id,
        "account_id": tx.account_id,
        "date": tx.date.isoformat(),
        "amount": float(abs(tx.amount)),
        "signed_amount": float(tx.amount),
        "description": tx.description,
        "category": tx.category,
    }


def _matching_invoice_payments(
    session: Session,
    bill: Optional[CreditCardBill],
) -> list[Transaction]:
    if bill is None or bill.due_date is None:
        return []
    bill_amount = _bill_amount(bill)
    if bill_amount <= 0:
        return []
    start = bill.due_date - datetime.timedelta(days=RECENT_DUE_WINDOW_DAYS)
    end = bill.due_date + datetime.timedelta(days=RECENT_DUE_WINDOW_DAYS)
    payments = credit_card_payment_transactions(session, start, end)
    return [
        tx
        for tx in payments
        if abs(abs(Decimal(tx.amount)) - bill_amount) <= PAYMENT_MATCH_TOLERANCE
    ]


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


def _serialize_refund(tx: Transaction) -> dict[str, Any]:
    return {
        "id": tx.id,
        "account_id": tx.account_id,
        "date": tx.date.isoformat(),
        "amount": float(tx.amount),
        "signed_amount": float(tx.amount),
        "description": tx.description,
        "category": tx.category,
    }


def _possible_refunds(
    session: Session,
    account: Account,
    latest_bill: Optional[CreditCardBill],
    today: datetime.date,
) -> list[Transaction]:
    from app.services.classification import TransactionClassifier

    start = today - datetime.timedelta(days=REFUND_LOOKBACK_DAYS)
    if latest_bill is not None and latest_bill.due_date is not None:
        start = max(start, latest_bill.due_date - datetime.timedelta(days=RECENT_DUE_WINDOW_DAYS))
    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id == account.id,
            Transaction.date >= start,
            Transaction.date <= today,
            _non_duplicate_clause(),
        )
        .order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()
    classifier = TransactionClassifier.from_session(session)
    return [tx for tx in rows if not classifier.is_invoice_payment(tx) and _looks_like_refund(tx)]


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
    user_rules: tuple = (),
) -> dict[str, Any]:
    classification = serialize_transaction_classification(
        tx,
        account_type="CREDIT",
        user_rules=user_rules,
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
) -> list[Transaction]:
    from app.services.classification import TransactionClassifier

    start = _category_window_start(account, latest_bill, today)
    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id == account.id,
            Transaction.date >= start,
            Transaction.date <= today,
            _non_duplicate_clause(),
        )
        .order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()

    classifier = TransactionClassifier.from_session(session)
    latest_bill_id = latest_bill.id if latest_bill is not None else None
    return [
        tx
        for tx in rows
        if not classifier.is_invoice_payment(tx)
        and not classifier.is_ignored(tx)
        and (latest_bill_id is None or tx.bill_id != latest_bill_id)
        and not _looks_like_refund(tx)
    ]


def current_card_invoice_summary(
    session: Session,
    today: Optional[datetime.date] = None,
) -> dict[str, Any]:
    """Return the Dashboard-only adjusted current card invoice summary.

    This intentionally does not reuse planning_invoice_for_month(): planning
    keeps future obligations and scheduled installments, while the Dashboard
    needs the currently visible card balance after removing a closed bill that
    Pluggy may still carry in Account.balance.
    """
    today = today if today is not None else datetime.date.today()

    from app.services.user_classification_rules import load_compiled_user_rules

    user_rules = load_compiled_user_rules(session)
    cards: list[dict[str, Any]] = []
    all_possible_refunds: list[dict[str, Any]] = []
    raw_purchase_transactions: list[dict[str, Any]] = []
    raw_total = Decimal("0")
    adjusted_total = Decimal("0")
    adjusted_any = False
    matched_payment_any = False

    for account in _active_credit_accounts_with_balance(session):
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

        matched_payments = _matching_invoice_payments(session, latest)
        if matched_payments and adjustments:
            matched_payment_any = True

        possible_refunds = _possible_refunds(session, account, latest, today)
        serialized_refunds = [_serialize_refund(tx) for tx in possible_refunds]
        all_possible_refunds.extend(serialized_refunds)
        category_transactions = _current_invoice_category_transactions(
            session,
            account,
            latest,
            today,
        )
        raw_purchase_transactions.extend(
            _serialize_current_invoice_transaction(tx, user_rules)
            for tx in category_transactions
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
                "matched_payment_transactions": [_serialize_payment(tx) for tx in matched_payments],
                "possible_refunds_total": float(
                    sum((Decimal(tx.amount) for tx in possible_refunds), Decimal("0"))
                ),
                "possible_refund_transactions": serialized_refunds,
            }
        )

    source = "adjusted_account_balance" if adjusted_any else "account_balance"
    confidence = "high" if matched_payment_any else ("medium" if cards else "none")
    possible_refunds_total = sum(
        (Decimal(str(tx["signed_amount"])) for tx in all_possible_refunds),
        Decimal("0"),
    )
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
        "legacy_category_breakdown_removed": False,
        "possible_refunds_total": float(possible_refunds_total),
        "possible_refund_transactions": all_possible_refunds,
        "source_detail": {
            "refunds_are_diagnostic_only": True,
            "reason": "Refunds may already be reflected in Account.balance, so they are not applied again.",
        },
        "reconciliation": {
            "amount": float(adjusted_total),
            "category_total": float(category_total),
            "refund_total": float(possible_refunds_total),
            "refund_abs_total": float(abs(possible_refunds_total)),
            "amount_minus_category_total": float(adjusted_total - category_total),
            "refunds_affect_amount": False,
            "refunds_are_diagnostic_only": True,
            "legacy_category_breakdown_removed": False,
            "source_label": source_label,
        },
    }
