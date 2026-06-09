"""Persist Pluggy snapshot data (account balance, bills, investments).

Everything here is best-effort — Pluggy connectors vary widely and some
endpoints (bills, investments, real-time balance) are simply unavailable
for many institutions. Each helper either succeeds or returns a structured
"skipped"/"failed" entry so the sync caller can log it without aborting
the whole sync.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx
from sqlmodel import Session, select

from app.models import (
    Account,
    CreditCardBill,
    Investment,
    InvestmentTransaction,
    Item,
)
from app.pluggy_client import pluggy

logger = logging.getLogger(__name__)


# ---------- type coercion helpers ----------


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_date(value: Any) -> Optional[datetime.date]:
    if not value:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _to_datetime(value: Any) -> Optional[datetime.datetime]:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# ---------- account snapshot ----------


def account_snapshot_values(raw_account: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Pluggy /accounts payload to ``Account`` snapshot fields.

    Returned dict is safe to ``setattr`` onto an Account row. Only keys with
    meaningful values are returned; missing or empty fields stay untouched
    so a connector that stops exposing a value doesn't wipe the prior one.
    """
    bank_data = raw_account.get("bankData") or {}
    credit_data = raw_account.get("creditData") or {}

    candidates: Dict[str, Any] = {
        "balance": _to_decimal(raw_account.get("balance")),
        "currency_code": raw_account.get("currencyCode"),
        "owner": raw_account.get("owner"),
        "tax_number": raw_account.get("taxNumber"),
        # bankData.*
        "bank_closing_balance": _to_decimal(bank_data.get("closingBalance")),
        "bank_automatically_invested_balance": _to_decimal(
            bank_data.get("automaticallyInvestedBalance")
        ),
        "bank_overdraft_contracted_limit": _to_decimal(bank_data.get("overdraftContractedLimit")),
        "bank_overdraft_used_limit": _to_decimal(bank_data.get("overdraftUsedLimit")),
        # creditData.*
        "credit_level": credit_data.get("level"),
        "credit_brand": credit_data.get("brand"),
        "credit_balance_close_date": _to_date(credit_data.get("balanceCloseDate")),
        "credit_balance_due_date": _to_date(credit_data.get("balanceDueDate")),
        "credit_available_limit": _to_decimal(credit_data.get("availableCreditLimit")),
        "credit_limit": _to_decimal(credit_data.get("creditLimit")),
        "credit_minimum_payment": _to_decimal(credit_data.get("minimumPayment")),
        "credit_status": credit_data.get("status"),
        "credit_holder_type": credit_data.get("holderType"),
        "balance_updated_at": _to_datetime(
            raw_account.get("updatedAt") or raw_account.get("lastUpdatedAt")
        ),
    }
    # Drop None so we don't overwrite a previously-good value with a blank.
    return {key: value for key, value in candidates.items() if value is not None}


# ---------- credit card bills ----------


@dataclass
class SnapshotOutcome:
    """Per-endpoint outcome the caller can log / surface to the response.

    ``skipped`` covers HTTPStatusError responses Pluggy returns when the
    connector simply doesn't support that endpoint (typical: 404/501 on
    bills/investments for institutions that don't expose them). Those are
    NOT failures — they're just "this connector can't give us that data".
    """

    upserted: int = 0
    skipped_reason: Optional[str] = None
    error: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)


def sync_credit_card_bills(
    session: Session,
    account_id: str,
) -> SnapshotOutcome:
    outcome = SnapshotOutcome()
    try:
        bills = pluggy.list_bills(account_id)
    except httpx.HTTPStatusError as exc:
        # 404/501 from the connector → not an error, just unavailable.
        if exc.response.status_code in (404, 405, 501):
            outcome.skipped_reason = f"bills unavailable (HTTP {exc.response.status_code})"
            return outcome
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome
    except Exception as exc:  # noqa: BLE001 — log any other failure but keep sync alive
        outcome.error = f"{type(exc).__name__}: {exc}"
        logger.exception("list_bills failed for account %s", account_id)
        return outcome

    bill_ids: list[str] = []
    for raw in bills:
        bill_id = raw.get("id")
        if not bill_id:
            continue
        values = {
            "account_id": account_id,
            "due_date": _to_date(raw.get("dueDate")),
            "total_amount": _to_decimal(raw.get("totalAmount")),
            "minimum_payment_amount": _to_decimal(raw.get("minimumPaymentAmount")),
            "allows_installments": raw.get("allowsInstallments"),
            "payments_total": _to_decimal(
                (raw.get("payments") or {}).get("totalAmount")
                if isinstance(raw.get("payments"), dict)
                else None
            ),
            "finance_charges_total": _to_decimal(
                (raw.get("financeCharges") or {}).get("totalAmount")
                if isinstance(raw.get("financeCharges"), dict)
                else None
            ),
            "currency_code": raw.get("currencyCode"),
            "updated_at": datetime.datetime.utcnow(),
        }
        existing = session.get(CreditCardBill, bill_id)
        if existing is None:
            session.add(CreditCardBill(id=bill_id, **values))
        else:
            for field_name, value in values.items():
                setattr(existing, field_name, value)
            session.add(existing)
        outcome.upserted += 1
        bill_ids.append(bill_id)
    outcome.extras["bill_ids"] = bill_ids
    return outcome


# ---------- investments ----------


def _investment_values(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": raw.get("name"),
        "type": raw.get("type"),
        "subtype": raw.get("subtype"),
        "amount": _to_decimal(raw.get("amount")),
        "balance": _to_decimal(raw.get("balance")),
        "amount_original": _to_decimal(raw.get("amountOriginal")),
        "amount_profit": _to_decimal(raw.get("amountProfit")),
        "amount_withdrawal": _to_decimal(raw.get("amountWithdrawal")),
        "rate": _to_decimal(raw.get("rate")),
        "rate_type": raw.get("rateType"),
        "fixed_annual_rate": _to_decimal(raw.get("fixedAnnualRate")),
        "issuer": raw.get("issuer"),
        "issue_date": _to_date(raw.get("issueDate")),
        "due_date": _to_date(raw.get("dueDate")),
        "status": raw.get("status"),
        "currency_code": raw.get("currencyCode"),
        "provider_id": raw.get("providerId"),
        "updated_at": datetime.datetime.utcnow(),
    }


def _investment_transaction_values(raw: Dict[str, Any], investment_id: str) -> Dict[str, Any]:
    return {
        "investment_id": investment_id,
        "date": _to_date(raw.get("date")),
        "trade_date": _to_date(raw.get("tradeDate")),
        "type": raw.get("type"),
        "description": raw.get("description"),
        "amount": _to_decimal(raw.get("amount")),
        "net_amount": _to_decimal(raw.get("netAmount")),
        "quantity": _to_decimal(raw.get("quantity")),
        "value": _to_decimal(raw.get("value")),
        "currency_code": raw.get("currencyCode"),
        "updated_at": datetime.datetime.utcnow(),
    }


def sync_investments(session: Session, item_id: str) -> SnapshotOutcome:
    outcome = SnapshotOutcome()
    try:
        investments = pluggy.list_investments(item_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 405, 501):
            outcome.skipped_reason = f"investments unavailable (HTTP {exc.response.status_code})"
            return outcome
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome
    except Exception as exc:  # noqa: BLE001
        outcome.error = f"{type(exc).__name__}: {exc}"
        logger.exception("list_investments failed for item %s", item_id)
        return outcome

    tx_total = 0
    tx_failures: List[Dict[str, str]] = []
    for raw in investments:
        investment_id = raw.get("id")
        if not investment_id:
            continue
        values = _investment_values(raw)
        existing = session.get(Investment, investment_id)
        if existing is None:
            session.add(Investment(id=investment_id, item_id=item_id, **values))
        else:
            existing.item_id = item_id
            for field_name, value in values.items():
                setattr(existing, field_name, value)
            session.add(existing)
        outcome.upserted += 1

        # Investment transactions are a separate endpoint per investment.
        # Failing one shouldn't kill the rest of the item's sync.
        try:
            tx_rows = pluggy.list_investment_transactions(investment_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404, 405, 501):
                continue
            tx_failures.append(
                {"investment_id": investment_id, "error": f"HTTP {exc.response.status_code}"}
            )
            continue
        except Exception as exc:  # noqa: BLE001
            tx_failures.append({"investment_id": investment_id, "error": str(exc)})
            logger.exception(
                "list_investment_transactions failed for investment %s",
                investment_id,
            )
            continue

        for raw_tx in tx_rows:
            tx_id = raw_tx.get("id")
            if not tx_id:
                continue
            tx_values = _investment_transaction_values(raw_tx, investment_id)
            tx_existing = session.get(InvestmentTransaction, tx_id)
            if tx_existing is None:
                session.add(InvestmentTransaction(id=tx_id, **tx_values))
            else:
                for field_name, value in tx_values.items():
                    setattr(tx_existing, field_name, value)
                session.add(tx_existing)
            tx_total += 1

    outcome.extras["transactions_upserted"] = tx_total
    if tx_failures:
        outcome.extras["transaction_failures"] = tx_failures
    return outcome


# ---------- account snapshot queries ----------


def _active_item_ids(session: Session) -> set:
    return {item.id for item in session.exec(select(Item)).all() if item.is_active}


def account_snapshot_summary(session: Session) -> Dict[str, Any]:
    """Aggregate Pluggy snapshot totals for active accounts.

    Every total here comes straight from Pluggy-persisted data — account
    balances, creditData limits and Investment.balance — NOT from
    re-deriving numbers out of raw transactions. Treat this as the source
    of truth for "how much money do I have / owe".
    """
    active_ids = _active_item_ids(session)
    all_accounts = list(session.exec(select(Account)).all())
    accounts = [a for a in all_accounts if a.is_active and a.item_id in active_ids]
    investments = [i for i in session.exec(select(Investment)).all() if i.item_id in active_ids]

    bank_accounts = [a for a in accounts if a.type == "BANK"]
    credit_accounts = [a for a in accounts if a.type == "CREDIT"]

    def _sum(values) -> Decimal:
        total = Decimal("0")
        for value in values:
            if value is not None:
                total += value
        return total

    bank_total = _sum(a.balance for a in bank_accounts)
    credit_used = _sum(a.balance for a in credit_accounts)
    credit_limit = _sum(a.credit_limit for a in credit_accounts)
    credit_available = _sum(a.credit_available_limit for a in credit_accounts)
    investments_total = _sum(i.balance for i in investments)

    # Whether the snapshot is actually populated. Lets the frontend decide
    # between "show the number" and "sync first / unavailable".
    bank_has_balance = any(a.balance is not None for a in bank_accounts)
    credit_has_balance = any(a.balance is not None for a in credit_accounts)

    return {
        "bank": {
            "total": float(bank_total),
            "account_count": len(bank_accounts),
            "has_balance": bank_has_balance,
            "accounts": [
                {
                    "id": a.id,
                    "item_id": a.item_id,
                    "is_active": a.is_active,
                    "name": a.marketing_name or a.name,
                    "balance": float(a.balance) if a.balance is not None else None,
                    "currency_code": a.currency_code,
                    "automatically_invested_balance": (
                        float(a.bank_automatically_invested_balance)
                        if a.bank_automatically_invested_balance is not None
                        else None
                    ),
                }
                for a in bank_accounts
            ],
        },
        "credit": {
            "used": float(credit_used),
            "limit": float(credit_limit),
            "available": float(credit_available),
            "account_count": len(credit_accounts),
            "has_balance": credit_has_balance,
            "accounts": [
                {
                    "id": a.id,
                    "item_id": a.item_id,
                    "is_active": a.is_active,
                    "name": a.marketing_name or a.name,
                    "brand": a.credit_brand,
                    "level": a.credit_level,
                    "used": float(a.balance) if a.balance is not None else None,
                    "limit": (float(a.credit_limit) if a.credit_limit is not None else None),
                    "available": (
                        float(a.credit_available_limit)
                        if a.credit_available_limit is not None
                        else None
                    ),
                    "minimum_payment": (
                        float(a.credit_minimum_payment)
                        if a.credit_minimum_payment is not None
                        else None
                    ),
                    "balance_close_date": (
                        a.credit_balance_close_date.isoformat()
                        if a.credit_balance_close_date
                        else None
                    ),
                    "balance_due_date": (
                        a.credit_balance_due_date.isoformat() if a.credit_balance_due_date else None
                    ),
                }
                for a in credit_accounts
            ],
        },
        "investments": {
            "total": float(investments_total),
            "investment_count": len(investments),
            "has_investments": len(investments) > 0,
        },
    }
