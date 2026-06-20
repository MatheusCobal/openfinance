from __future__ import annotations

import calendar
import datetime
from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import Account, Item, Transaction
from app.services.credit_categories import (
    credit_category_payload,
    resolve_credit_internal_category,
)
from app.services.scoping import scope_query
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.transactions import _non_duplicate_clause


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


def current_invoice_month(today: datetime.date) -> str:
    if today.month == 12:
        return f"{today.year + 1}-01"
    return f"{today.year}-{today.month + 1:02d}"


def _invoice_month_end(year_month: str) -> datetime.date:
    year, month = int(year_month[:4]), int(year_month[5:])
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


def _active_credit_accounts(
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
    ]


def _looks_like_refund(tx: Transaction) -> bool:
    if tx.amount < 0:
        return True
    normalized_description = normalize_description(tx.description)
    normalized_category = normalize_description(tx.category or "")
    return any(
        pattern in normalized_description or pattern in normalized_category
        for pattern in REFUND_DESCRIPTION_PATTERNS
    )


def _serialize_current_invoice_transaction(tx: Transaction) -> dict[str, Any]:
    classification = serialize_transaction_classification(tx, account_type="CREDIT")
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


def pending_current_invoice_transactions(
    session: Session,
    today: Optional[datetime.date] = None,
    user_id: Optional[int] = None,
) -> list[Transaction]:
    """Return the only transaction set allowed to compose the current invoice.

    The current invoice is the next calendar month's invoice. Every eligible
    CREDIT purchase still reported as PENDING up to the end of that invoice
    month belongs to it. Later months are never included.
    """
    from app.services.classification import TransactionClassifier

    today = today if today is not None else datetime.date.today()
    invoice_month = current_invoice_month(today)
    cutoff = _invoice_month_end(invoice_month)
    accounts = _active_credit_accounts(session, user_id=user_id)
    account_ids = {account.id for account in accounts}
    if not account_ids:
        return []

    rows = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.account_id.in_(account_ids),
                Transaction.date <= cutoff,
                _non_duplicate_clause(),
            ),
            Transaction.user_id,
            user_id,
        ).order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()
    classifier = TransactionClassifier.from_session(session, user_id=user_id)
    return [
        tx
        for tx in rows
        if str(tx.status or "").upper() == "PENDING"
        and tx.amount > 0
        and classifier.is_card_purchase(tx)
        and not classifier.is_invoice_payment(tx)
        and not classifier.is_ignored(tx)
        and not tx.ignored_from_totals
        and not _looks_like_refund(tx)
    ]


def current_card_invoice_summary(
    session: Session,
    today: Optional[datetime.date] = None,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Return the current invoice built exclusively from eligible PENDING purchases."""
    today = today if today is not None else datetime.date.today()
    invoice_month = current_invoice_month(today)
    cutoff = _invoice_month_end(invoice_month)
    accounts = _active_credit_accounts(session, user_id=user_id)
    transactions = pending_current_invoice_transactions(
        session,
        today=today,
        user_id=user_id,
    )
    serialized = [_serialize_current_invoice_transaction(tx) for tx in transactions]
    total = sum((Decimal(str(tx["amount"])) for tx in serialized), Decimal("0"))

    categories_by_name: dict[str, dict[str, Any]] = {}
    for tx in serialized:
        if tx.get("ignored_from_totals") or tx.get("cashflow_type") != "expense":
            continue
        name = tx.get("effective_category") or "Outros"
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
                "source": "pending_transaction_classification",
            },
        )
        bucket["total"] += Decimal(str(tx["amount"]))
        bucket["count"] += 1
        bucket["transactions"].append(tx)

    categories = [
        {**bucket, "total": float(bucket["total"])}
        for bucket in sorted(
            categories_by_name.values(),
            key=lambda item: item["total"],
            reverse=True,
        )
    ]
    category_total = sum(
        (Decimal(str(category["total"])) for category in categories),
        Decimal("0"),
    )

    totals_by_account: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts_by_account: dict[str, int] = defaultdict(int)
    for tx in transactions:
        totals_by_account[tx.account_id] += abs(tx.amount)
        counts_by_account[tx.account_id] += 1
    cards = [
        {
            "account_id": account.id,
            "name": account.name,
            "pending_total": float(totals_by_account[account.id]),
            "transaction_count": counts_by_account[account.id],
            "invoice_month": invoice_month,
            "cutoff_date": cutoff.isoformat(),
        }
        for account in accounts
    ]

    recent_transactions = [
        tx for tx in serialized if datetime.date.fromisoformat(tx["date"]) <= today
    ]
    return {
        "amount": float(total),
        "source": "pending_transactions",
        "source_label": "Compras PENDING da fatura vigente",
        "confidence": "high" if accounts else "none",
        "account_count": len(accounts),
        "invoice_month": invoice_month,
        "cutoff_date": cutoff.isoformat(),
        "status_filter": "PENDING",
        "cards": cards,
        "categories": categories,
        "category_total": float(category_total),
        "category_count": len(serialized),
        "raw_purchase_transactions": serialized,
        "recent_purchase_transactions": recent_transactions,
        "source_detail": {
            "rule": "pending_credit_purchases_through_current_invoice_month",
            "account_type": "CREDIT",
            "status": "PENDING",
            "cutoff_date": cutoff.isoformat(),
            "future_months_excluded": True,
        },
        "reconciliation": {
            "amount": float(total),
            "category_total": float(category_total),
            "identified_category_total": float(category_total),
            "unreconciled_amount": 0.0,
            "amount_minus_category_total": float(total - category_total),
            "source_label": "Soma das compras PENDING",
        },
        "legacy_category_breakdown_removed": False,
    }
