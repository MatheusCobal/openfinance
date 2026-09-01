from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import Account, Transaction
from app.services.classification import TransactionClassifier, card_invoice_signed_amount
from app.services.credit_categories import (
    credit_category_payload,
    resolve_credit_internal_category,
)
from app.services.scoping import scope_query
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.transactions import _non_duplicate_clause, filter_ignored_transactions
from app.services.year_month import InvalidYearMonth, shift_year_month


CAIXA_CLOSING_DAY = 24
CAIXA_CREDIT_CATEGORY = "Créditos / Estornos"
CAIXA_STATEMENT_MARKERS = frozenset(
    {
        "aut pgto boleto registrado",
        "pgto boleto registrado",
        "total da fatura anterior",
    }
)


@dataclass(frozen=True)
class CaixaInvoiceEntry:
    transaction: Transaction
    invoice_month: str
    signed_amount: Decimal
    installment_number: Optional[int]
    total_installments: Optional[int]
    projected: bool = False


def is_caixa_account(account: Optional[Account]) -> bool:
    if account is None:
        return False
    identity = f"{account.marketing_name or ''} {account.name or ''}".casefold()
    return "caixa" in identity


def caixa_invoice_month(purchase_date: date) -> str:
    """Return the due month for a CAIXA purchase using its closing cycle."""
    # The CAIXA statement supplied by the user places purchases made on the
    # closing day itself in the next open cycle.
    month_offset = 1 if purchase_date.day < CAIXA_CLOSING_DAY else 2
    return shift_year_month(purchase_date.strftime("%Y-%m"), month_offset)


def shift_optional_year_month(year_month: Optional[str], offset: int) -> Optional[str]:
    if not year_month:
        return None
    try:
        return shift_year_month(year_month[:7], offset)
    except (InvalidYearMonth, TypeError):
        return None


def caixa_due_month_from_forecast(forecast_month: Optional[str]) -> Optional[str]:
    """Translate CAIXA's statement forecast month into its invoice due month."""
    # billForecastDate identifies the closing/statement month. The card due
    # date is in the following calendar month (forecast Aug -> due Sep).
    return shift_optional_year_month(forecast_month, 1)


def caixa_transaction_invoice_month(tx: Transaction) -> str:
    return caixa_due_month_from_forecast(tx.bill_forecast_month) or caixa_invoice_month(tx.date)


def is_caixa_statement_marker(tx: Transaction) -> bool:
    """Recognize exact CAIXA statement rows after harmless text normalization.

    Callers deliberately scope this helper to CAIXA accounts.  Exact matching
    prevents a legitimate purchase that merely contains the same words from
    being removed from invoice totals.
    """
    description = re.sub(r"[^a-z0-9]+", " ", normalize_description(tx.description)).strip()
    return description in CAIXA_STATEMENT_MARKERS


def _installment_plan_key(tx: Transaction) -> tuple:
    return (
        tx.account_id,
        tx.credit_card_last_four,
        tx.purchase_date or tx.date,
        normalize_description(tx.description),
        abs(tx.amount),
        tx.total_installments,
    )


def caixa_invoice_entries_by_month(
    session: Session,
    account_ids: set[str],
    minimum_invoice_month: str,
    classifier: TransactionClassifier,
    *,
    today: date,
    include_ignored: bool = False,
    user_id: Optional[int] = None,
) -> dict[str, list[CaixaInvoiceEntry]]:
    """Build the canonical CAIXA invoice schedule, including credits and projections."""
    if not account_ids:
        return {}

    rows = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.account_id.in_(account_ids),
                _non_duplicate_clause(),
            ),
            Transaction.user_id,
            user_id,
        ).order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()
    rows = filter_ignored_transactions(
        rows,
        session,
        include_ignored,
        user_id=user_id,
    )

    by_month: dict[str, list[CaixaInvoiceEntry]] = defaultdict(list)
    installment_anchors: dict[tuple, Transaction] = {}
    actual_installments: set[tuple[tuple, int]] = set()
    for tx in rows:
        if classifier.is_ignored(tx) or tx.ignored_from_totals or is_caixa_statement_marker(tx):
            continue
        classification = classifier.classify(tx)
        signed_amount = card_invoice_signed_amount(tx, classification)
        if signed_amount == 0:
            continue

        if (
            signed_amount > 0
            and tx.bill_forecast_month
            and tx.installment_number
            and tx.total_installments
            and tx.installment_number <= tx.total_installments
        ):
            plan_key = _installment_plan_key(tx)
            actual_installments.add((plan_key, tx.installment_number))
            current_anchor = installment_anchors.get(plan_key)
            if current_anchor is None or (current_anchor.installment_number or 0) < (
                tx.installment_number
            ):
                installment_anchors[plan_key] = tx

        # CAIXA may keep an older POSTED installment as the projection anchor,
        # but only open PENDING rows or actual future-dated rows belong to an
        # upcoming invoice.
        is_pending = str(tx.status or "").upper() == "PENDING"
        if not is_pending and tx.date <= today:
            continue

        invoice_month = caixa_transaction_invoice_month(tx)
        if invoice_month >= minimum_invoice_month:
            by_month[invoice_month].append(
                CaixaInvoiceEntry(
                    transaction=tx,
                    invoice_month=invoice_month,
                    signed_amount=signed_amount,
                    installment_number=tx.installment_number,
                    total_installments=tx.total_installments,
                )
            )

    for plan_key, tx in installment_anchors.items():
        current_installment = tx.installment_number or 0
        total_installments = tx.total_installments or 0
        for installment_number in range(current_installment + 1, total_installments + 1):
            if (plan_key, installment_number) in actual_installments:
                continue
            forecast_month = shift_optional_year_month(
                tx.bill_forecast_month,
                installment_number - current_installment,
            )
            invoice_month = caixa_due_month_from_forecast(forecast_month)
            if invoice_month is None or invoice_month < minimum_invoice_month:
                continue
            by_month[invoice_month].append(
                CaixaInvoiceEntry(
                    transaction=tx,
                    invoice_month=invoice_month,
                    signed_amount=abs(tx.amount),
                    installment_number=installment_number,
                    total_installments=total_installments,
                    projected=True,
                )
            )

    return dict(by_month)


def serialize_caixa_invoice_entry(entry: CaixaInvoiceEntry) -> dict:
    tx = entry.transaction
    classification = serialize_transaction_classification(tx, account_type="CREDIT")
    if entry.signed_amount < 0:
        classification = {
            **classification,
            "internal_category": "Estorno",
            "cashflow_type": "refund",
        }
        effective_category = CAIXA_CREDIT_CATEGORY
    else:
        effective_category = resolve_credit_internal_category(
            tx,
            account_type="CREDIT",
            current_internal_category=classification.get("internal_category"),
        )
    return {
        "id": f"{tx.id}:projected:{entry.installment_number}" if entry.projected else tx.id,
        "date": (tx.purchase_date or tx.date).isoformat(),
        "amount": float(abs(entry.signed_amount)),
        "signed_amount": float(entry.signed_amount),
        "description": tx.description,
        "pluggy_category": classification["pluggy_raw_category"],
        "status": tx.status,
        "bill_id": tx.bill_id,
        "installment_number": entry.installment_number,
        "total_installments": entry.total_installments,
        "is_projected": entry.projected,
        "invoice_assignment_source": (
            "installment_projection"
            if entry.projected
            else "pluggy_forecast"
            if tx.bill_forecast_month
            else "closing_cycle"
        ),
        **classification,
        **credit_category_payload(effective_category),
    }
