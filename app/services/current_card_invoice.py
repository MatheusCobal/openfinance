from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import Account, CreditCardBill, Item, Transaction
from app.services.caixa_invoice import (
    CAIXA_CREDIT_CATEGORY,
    caixa_invoice_entries_by_month,
    caixa_transaction_invoice_month,
    is_caixa_account,
    is_caixa_statement_marker,
    serialize_caixa_invoice_entry,
)
from app.services.credit_categories import (
    credit_category_payload,
    resolve_credit_internal_category,
)
from app.services.scoping import scope_query
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.transactions import _non_duplicate_clause
from app.services.year_month import month_bounds, shift_year_month


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
    return shift_year_month(today.strftime("%Y-%m"), 1)


def _invoice_month_end(year_month: str) -> datetime.date:
    return month_bounds(year_month)[1]


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
        for account in session.exec(scope_query(select(Account), Account.user_id, user_id)).all()
        if account.type == "CREDIT" and account.is_active and account.item_id in active_item_ids
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


def _card_identity(account: Optional[Account], item: Optional[Item] = None) -> dict[str, Any]:
    if account is None:
        return {}
    number = "".join(character for character in str(account.number or "") if character.isdigit())
    return {
        "account_id": account.id,
        "account_name": account.marketing_name or account.name,
        "card_brand": account.credit_brand,
        "card_last_four": number[-4:] if number else None,
        "institution_name": item.connector_name if item is not None else None,
    }


def _serialize_current_invoice_transaction(
    tx: Transaction,
    account: Optional[Account] = None,
    item: Optional[Item] = None,
) -> dict[str, Any]:
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
        **_card_identity(account, item),
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
    accounts_by_id = {account.id: account for account in accounts}
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
    transactions = []
    for tx in rows:
        if not (
            str(tx.status or "").upper() == "PENDING"
            and tx.amount > 0
            and classifier.is_card_purchase(tx)
            and not classifier.is_invoice_payment(tx)
            and not classifier.is_ignored(tx)
            and not tx.ignored_from_totals
            and not _looks_like_refund(tx)
        ):
            continue
        account = accounts_by_id.get(tx.account_id)
        if is_caixa_account(account) and (
            is_caixa_statement_marker(tx) or caixa_transaction_invoice_month(tx) != invoice_month
        ):
            continue
        transactions.append(tx)
    return transactions


def current_card_invoice_summary(
    session: Session,
    today: Optional[datetime.date] = None,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Return the canonical current invoice shared by every application surface."""
    today = today if today is not None else datetime.date.today()
    invoice_month = current_invoice_month(today)
    cutoff = _invoice_month_end(invoice_month)
    accounts = _active_credit_accounts(session, user_id=user_id)
    accounts_by_id = {account.id: account for account in accounts}
    items_by_id = {
        item.id: item
        for item in session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
    }
    transactions = pending_current_invoice_transactions(
        session,
        today=today,
        user_id=user_id,
    )
    non_caixa_transactions = [
        tx for tx in transactions if not is_caixa_account(accounts_by_id.get(tx.account_id))
    ]
    serialized = [
        _serialize_current_invoice_transaction(
            tx,
            accounts_by_id.get(tx.account_id),
            items_by_id.get(accounts_by_id[tx.account_id].item_id)
            if tx.account_id in accounts_by_id
            else None,
        )
        for tx in non_caixa_transactions
    ]
    caixa_account_ids = {account.id for account in accounts if is_caixa_account(account)}
    if caixa_account_ids:
        from app.services.classification import TransactionClassifier

        classifier = TransactionClassifier.from_session(session, user_id=user_id)
        caixa_entries = caixa_invoice_entries_by_month(
            session,
            caixa_account_ids,
            invoice_month,
            classifier,
            today=today,
            user_id=user_id,
        ).get(invoice_month, [])
        for entry in caixa_entries:
            tx = entry.transaction
            identity = _card_identity(
                accounts_by_id.get(tx.account_id),
                items_by_id.get(accounts_by_id[tx.account_id].item_id)
                if tx.account_id in accounts_by_id
                else None,
            )
            if tx.credit_card_last_four:
                identity["card_last_four"] = tx.credit_card_last_four
            serialized.append(
                {
                    **serialize_caixa_invoice_entry(entry),
                    **identity,
                }
            )
    serialized.sort(key=lambda tx: (tx["date"], tx["description"]))
    categories_by_name: dict[str, dict[str, Any]] = {}
    for tx in serialized:
        signed_amount = Decimal(str(tx.get("signed_amount", tx["amount"])))
        is_credit = signed_amount < 0
        if tx.get("ignored_from_totals") or (
            not is_credit and tx.get("cashflow_type") != "expense"
        ):
            continue
        name = CAIXA_CREDIT_CATEGORY if is_credit else tx.get("effective_category") or "Outros"
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
            },
        )
        bucket["total"] += signed_amount
        bucket["count"] += 1
        bucket["transactions"].append(tx)

    categories = [
        {**bucket, "total": float(bucket["total"])}
        for bucket in sorted(
            categories_by_name.values(),
            key=lambda item: abs(item["total"]),
            reverse=True,
        )
    ]
    totals_by_account: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts_by_account: dict[str, int] = defaultdict(int)
    for tx in serialized:
        account_id = tx.get("account_id")
        if not account_id:
            continue
        signed_amount = Decimal(str(tx.get("signed_amount", tx["amount"])))
        totals_by_account[account_id] += signed_amount
        counts_by_account[account_id] += 1

    caixa_official_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    if caixa_account_ids:
        official_bills = session.exec(
            scope_query(
                select(CreditCardBill).where(CreditCardBill.account_id.in_(caixa_account_ids)),
                CreditCardBill.user_id,
                user_id,
            )
        ).all()
        for bill in official_bills:
            if (
                bill.due_date is not None
                and bill.due_date.strftime("%Y-%m") == invoice_month
                and bill.total_amount is not None
            ):
                caixa_official_totals[bill.account_id] += bill.total_amount

    selected_totals_by_account = {
        account.id: (
            caixa_official_totals[account.id]
            if account.id in caixa_official_totals
            else totals_by_account[account.id]
        )
        for account in accounts
    }
    total = sum(selected_totals_by_account.values(), Decimal("0"))
    cards = [
        {
            "account_id": account.id,
            **_card_identity(account, items_by_id.get(account.item_id)),
            "total_amount": float(selected_totals_by_account[account.id]),
            "transaction_count": counts_by_account[account.id],
        }
        for account in accounts
    ]

    recent_transactions = [
        tx
        for tx in serialized
        if not tx.get("is_projected") and datetime.date.fromisoformat(tx["date"]) <= today
    ]
    uses_caixa_schedule = bool(caixa_account_ids)
    source = "canonical_invoice_schedule" if uses_caixa_schedule else "pending_transactions"
    return {
        "amount": float(total),
        "source": source,
        "account_count": len(accounts),
        "invoice_month": invoice_month,
        "cutoff_date": cutoff.isoformat(),
        "cards": cards,
        "categories": categories,
        "transaction_count": len(serialized),
        "raw_purchase_transactions": serialized,
        "recent_purchase_transactions": recent_transactions,
    }
