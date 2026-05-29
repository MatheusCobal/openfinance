"""Persist Pluggy snapshot data (account balance, bills, investments).

Everything here is best-effort — Pluggy connectors vary widely and some
endpoints (bills, investments, real-time balance) are simply unavailable
for many institutions. Each helper either succeeds or returns a structured
"skipped"/"failed" entry so the sync caller can log it without aborting
the whole sync.
"""
from __future__ import annotations

import calendar
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
        "bank_overdraft_contracted_limit": _to_decimal(
            bank_data.get("overdraftContractedLimit")
        ),
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
            outcome.skipped_reason = (
                f"bills unavailable (HTTP {exc.response.status_code})"
            )
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


def _investment_transaction_values(
    raw: Dict[str, Any], investment_id: str
) -> Dict[str, Any]:
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
            outcome.skipped_reason = (
                f"investments unavailable (HTTP {exc.response.status_code})"
            )
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


# ---------- reserve / dashboard queries ----------


# Pluggy investment ``type`` values that we treat as "reserva de emergência".
# Anything liquid + low risk: fixed income, savings accounts, money-market
# funds. Equities and ETFs are deliberately excluded — they're investment,
# not reserve.
RESERVE_INVESTMENT_TYPES = {"FIXED_INCOME", "SAVINGS", "MUTUAL_FUND", "TREASURY"}


def _active_item_ids(session: Session) -> set:
    return {item.id for item in session.exec(select(Item)).all() if item.is_active}


def reserve_investments(session: Session) -> List[Investment]:
    active_ids = _active_item_ids(session)
    return [
        inv
        for inv in session.exec(select(Investment)).all()
        if (inv.type or "").upper() in RESERVE_INVESTMENT_TYPES
        and inv.item_id in active_ids
    ]


def reserve_total_from_investments(session: Session) -> Decimal:
    """Sum of Investment.balance for reserve-eligible positions.

    Returns 0 when no investments are persisted yet — callers should use
    that as a signal to fall back to the transaction-derived reserve.
    """
    total = Decimal("0")
    for inv in reserve_investments(session):
        if inv.balance is not None:
            total += inv.balance
    return total


def has_any_investments(session: Session) -> bool:
    return session.exec(select(Investment.id).limit(1)).first() is not None


def account_snapshot_summary(session: Session) -> Dict[str, Any]:
    """Aggregate Pluggy snapshot totals for the dashboard.

    Every total here comes straight from Pluggy-persisted data — account
    balances, creditData limits and Investment.balance — NOT from
    re-deriving numbers out of raw transactions. The dashboard should treat
    this as the source of truth for "how much money do I have / owe".
    """
    active_ids = _active_item_ids(session)
    all_accounts = list(session.exec(select(Account)).all())
    accounts = [a for a in all_accounts if a.is_active and a.item_id in active_ids]
    investments = [
        i for i in session.exec(select(Investment)).all() if i.item_id in active_ids
    ]

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
    reserve_total = reserve_total_from_investments(session)

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
                    "limit": (
                        float(a.credit_limit) if a.credit_limit is not None else None
                    ),
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
                        a.credit_balance_due_date.isoformat()
                        if a.credit_balance_due_date
                        else None
                    ),
                }
                for a in credit_accounts
            ],
        },
        "investments": {
            "total": float(investments_total),
            "reserve_total": float(reserve_total),
            "investment_count": len(investments),
            "reserve_investment_count": len(reserve_investments(session)),
            "has_investments": len(investments) > 0,
        },
    }


def latest_bill_for_account(
    session: Session,
    account_id: str,
) -> Optional[CreditCardBill]:
    """Most recent bill (by due_date) for the account, or None.

    Bills without a due_date go to the back so a connector that returns
    half-populated rows can't shadow a real one. Done in Python because
    SQLite's NULLS LAST is patchy.
    """
    bills = list(
        session.exec(
            select(CreditCardBill).where(CreditCardBill.account_id == account_id)
        ).all()
    )
    bills.sort(
        key=lambda bill: (
            bill.due_date is None,
            -(bill.due_date.toordinal() if bill.due_date else 0),
        )
    )
    return bills[0] if bills else None


def official_bills_total_for_month(
    session: Session,
    year_month: str,
) -> Optional[Dict[str, Any]]:
    """Sum of Pluggy CreditCardBill.total_amount due in ``year_month``.

    Returns None when there is no bill due that month — the caller should
    then fall back to the transaction-reconstructed invoice. A bill is
    matched by its ``due_date`` falling inside the month, which is how the
    cash obligation is bucketed in the planning view.
    """
    active_ids = _active_item_ids(session)
    active_credit_account_ids = {
        a.id for a in session.exec(select(Account)).all()
        if a.type == "CREDIT" and a.is_active and a.item_id in active_ids
    }
    bills = list(session.exec(select(CreditCardBill)).all())
    matched = [
        bill
        for bill in bills
        if bill.due_date is not None
        and bill.due_date.strftime("%Y-%m") == year_month
        and bill.total_amount is not None
        and bill.account_id in active_credit_account_ids
    ]
    if not matched:
        return None
    total = sum((bill.total_amount for bill in matched), Decimal("0"))
    minimum = sum(
        (
            bill.minimum_payment_amount
            for bill in matched
            if bill.minimum_payment_amount is not None
        ),
        Decimal("0"),
    )
    return {
        "total_amount": float(total),
        "minimum_payment_amount": float(minimum),
        "bill_count": len(matched),
        "account_ids": sorted({bill.account_id for bill in matched}),
    }


def _billing_cycle_for_close_date(
    close_date: datetime.date,
) -> tuple[datetime.date, datetime.date]:
    """Return (cycle_start, cycle_end) for a credit-card's close date.

    The cycle ends on ``close_date``. The start is the day after the same
    calendar day in the previous month.
    Example: close=2026-06-04 → start=2026-05-05, end=2026-06-04.
    """
    cycle_end = close_date
    prev_year = close_date.year if close_date.month > 1 else close_date.year - 1
    prev_month = close_date.month - 1 if close_date.month > 1 else 12
    max_day = calendar.monthrange(prev_year, prev_month)[1]
    prev_day = min(close_date.day, max_day)
    prev_close = datetime.date(prev_year, prev_month, prev_day)
    cycle_start = prev_close + datetime.timedelta(days=1)
    return cycle_start, cycle_end


def current_open_card_invoice_summary(
    session: Session,
    year_month: str,
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Estimate the current open card invoice from PENDING transactions.

    Priority:
    1. PENDING transactions with no bill_id within the current billing
       cycle (determined by Account.credit_balance_close_date).
       source = "pending_cycle_transactions"
    2. PENDING transactions with no bill_id within the current calendar
       month (fallback when no close_date is set on any account).
       source = "pending_month_transactions"
    3. Sum of Account.balance across active CREDIT accounts.
       source = "account_balance_fallback"

    CreditCardBill is intentionally NOT used here. Bills represent closed
    billing cycles and must not be used for the live open invoice.
    """
    from sqlalchemy import or_  # SQLAlchemy or_ for NULL checks
    from app.models import Transaction as Tx  # local alias avoids shadowing
    from app.services.transactions import account_ids_by_type
    from app.services.classification import SPENDING_ACCOUNT_TYPES

    today = today if today is not None else datetime.date.today()
    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    month_start = datetime.date(year_int, month_int, 1)
    _, month_last = calendar.monthrange(year_int, month_int)
    month_end = datetime.date(year_int, month_int, month_last)

    active_ids = _active_item_ids(session)
    credit_accounts = [
        a for a in session.exec(select(Account)).all()
        if a.type == "CREDIT" and a.is_active and a.item_id in active_ids
    ]
    if not credit_accounts:
        return {
            "total": 0.0,
            "source": "none",
            "label": "Sem contas de crédito",
            "cycle_start": None,
            "cycle_end": None,
            "transaction_count": 0,
            "account_count": 0,
        }

    credit_account_ids = {a.id for a in credit_accounts}

    # ---- Tier 1: PENDING in billing cycle ----
    accounts_with_close = [a for a in credit_accounts if a.credit_balance_close_date]
    if accounts_with_close:
        all_starts, all_ends = [], []
        for a in accounts_with_close:
            cs, ce = _billing_cycle_for_close_date(a.credit_balance_close_date)
            all_starts.append(cs)
            all_ends.append(ce)
        cycle_start = min(all_starts)
        cycle_end = max(all_ends)

        pending_txs = session.exec(
            select(Tx).where(
                Tx.account_id.in_(credit_account_ids),
                Tx.date >= cycle_start,
                Tx.date <= cycle_end,
                Tx.status == "PENDING",
                or_(Tx.bill_id.is_(None), Tx.bill_id == ""),
            )
        ).all()

        if pending_txs:
            total = sum((abs(tx.amount) for tx in pending_txs), Decimal("0"))
            return {
                "total": float(total),
                "source": "pending_cycle_transactions",
                "label": "Fatura aberta estimada",
                "cycle_start": cycle_start.isoformat(),
                "cycle_end": cycle_end.isoformat(),
                "transaction_count": len(pending_txs),
                "account_count": len(accounts_with_close),
            }

    # ---- Tier 2: PENDING in current calendar month ----
    effective_end = min(month_end, today)
    month_pending = session.exec(
        select(Tx).where(
            Tx.account_id.in_(credit_account_ids),
            Tx.date >= month_start,
            Tx.date <= effective_end,
            Tx.status == "PENDING",
            or_(Tx.bill_id.is_(None), Tx.bill_id == ""),
        )
    ).all()

    if month_pending:
        total = sum((abs(tx.amount) for tx in month_pending), Decimal("0"))
        return {
            "total": float(total),
            "source": "pending_month_transactions",
            "label": "Fatura aberta estimada",
            "cycle_start": month_start.isoformat(),
            "cycle_end": effective_end.isoformat(),
            "transaction_count": len(month_pending),
            "account_count": len(credit_accounts),
        }

    # ---- Tier 3: Account.balance ----
    accounts_with_balance = [a for a in credit_accounts if a.balance is not None]
    if accounts_with_balance:
        balance_total = sum((a.balance for a in accounts_with_balance), Decimal("0"))
        due_dates = sorted({
            a.credit_balance_due_date.isoformat()
            for a in accounts_with_balance
            if a.credit_balance_due_date
        })
        return {
            "total": float(balance_total),
            "source": "account_balance_fallback",
            "label": "Saldo do cartão",
            "cycle_start": None,
            "cycle_end": None,
            "transaction_count": 0,
            "account_count": len(accounts_with_balance),
            "due_dates": due_dates,
        }

    return {
        "total": 0.0,
        "source": "none",
        "label": "Sem dados de fatura",
        "cycle_start": None,
        "cycle_end": None,
        "transaction_count": 0,
        "account_count": len(credit_accounts),
    }


def credit_card_obligation_summary(
    session: Session,
    year_month: str,
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """3-tier credit-card obligation summary for a given month.

    Priority:
    1. ``bill``             — official CreditCardBill rows due this month (any month).
    2. ``account_balance``  — sum of CREDIT Account.balance (CURRENT MONTH ONLY).
                              Account.balance reflects the current open invoice, so
                              it is meaningless as a proxy for a past or future month.
    3. ``transaction_fallback`` — reconstructed via invoice_summary() for any month.
    """
    from app.services.transaction_reports import invoice_summary  # avoid circular at import time

    today = today if today is not None else datetime.date.today()
    current_year_month = today.strftime("%Y-%m")

    active_ids = _active_item_ids(session)
    all_credit = [
        a for a in session.exec(select(Account)).all()
        if a.type == "CREDIT"
    ]
    credit_accounts = [
        a for a in all_credit if a.is_active and a.item_id in active_ids
    ]
    active_credit_account_ids = {a.id for a in credit_accounts}

    # ---- Tier 1: Pluggy CreditCardBill due in year_month ----
    bills = list(session.exec(select(CreditCardBill)).all())
    matched_bills = [
        b for b in bills
        if b.due_date is not None
        and b.due_date.strftime("%Y-%m") == year_month
        and b.total_amount is not None
        and b.account_id in active_credit_account_ids
    ]

    if matched_bills:
        official_total = sum((b.total_amount for b in matched_bills), Decimal("0"))
        minimum_total = sum(
            (b.minimum_payment_amount for b in matched_bills if b.minimum_payment_amount is not None),
            Decimal("0"),
        )
        payments = sum(
            (b.payments_total for b in matched_bills if b.payments_total is not None),
            Decimal("0"),
        )
        charges = sum(
            (b.finance_charges_total for b in matched_bills if b.finance_charges_total is not None),
            Decimal("0"),
        )
        due_dates = sorted({b.due_date.isoformat() for b in matched_bills})
        open_total = sum(
            (a.balance for a in credit_accounts if a.balance is not None),
            Decimal("0"),
        )
        return {
            "year_month": year_month,
            "source": "bill",
            "official_bill_total": float(official_total),
            "current_open_total": float(open_total),
            "minimum_payment_total": float(minimum_total),
            "payments_total": float(payments),
            "finance_charges_total": float(charges),
            "due_dates": due_dates,
            "cards": [
                {
                    "account_id": b.account_id,
                    "due_date": b.due_date.isoformat() if b.due_date else None,
                    "total_amount": float(b.total_amount or 0),
                    "minimum_payment_amount": float(b.minimum_payment_amount or 0),
                }
                for b in matched_bills
            ],
        }

    # ---- Tier 2: CREDIT Account.balance — current month only ----
    # Account.balance is the current open invoice snapshot. It is only a valid
    # proxy for the current month's obligation. For past or future months it
    # would inject today's balance into the wrong month, distorting the plan.
    if year_month == current_year_month:
        credit_with_balance = [a for a in credit_accounts if a.balance is not None]
        if credit_with_balance:
            open_total = sum((a.balance for a in credit_with_balance), Decimal("0"))
            min_total = sum(
                (a.credit_minimum_payment for a in credit_with_balance if a.credit_minimum_payment is not None),
                Decimal("0"),
            )
            due_dates = sorted({
                a.credit_balance_due_date.isoformat()
                for a in credit_with_balance
                if a.credit_balance_due_date is not None
            })
            return {
                "year_month": year_month,
                "source": "account_balance",
                "official_bill_total": None,
                "current_open_total": float(open_total),
                "minimum_payment_total": float(min_total),
                "payments_total": None,
                "finance_charges_total": None,
                "due_dates": due_dates,
                "cards": [
                    {
                        "account_id": a.id,
                        "due_date": a.credit_balance_due_date.isoformat() if a.credit_balance_due_date else None,
                        "total_amount": float(a.balance or 0),
                        "minimum_payment_amount": float(a.credit_minimum_payment or 0),
                    }
                    for a in credit_with_balance
                ],
            }

    # ---- Tier 2b: CREDIT Account.balance with credit_balance_due_date in year_month (future month) ----
    # For a future month we can use Account.balance only when the account's
    # credit_balance_due_date falls exactly in that month. This represents the
    # current open invoice that will become due in this specific future month.
    # Accounts without a due_date, or with a due_date in a different month, are excluded.
    if year_month > current_year_month:
        credit_with_due_in_month = [
            a for a in credit_accounts
            if a.balance is not None
            and a.credit_balance_due_date is not None
            and a.credit_balance_due_date.strftime("%Y-%m") == year_month
        ]
        if credit_with_due_in_month:
            open_total = sum((a.balance for a in credit_with_due_in_month), Decimal("0"))
            min_total = sum(
                (a.credit_minimum_payment for a in credit_with_due_in_month if a.credit_minimum_payment is not None),
                Decimal("0"),
            )
            due_dates = sorted({
                a.credit_balance_due_date.isoformat()
                for a in credit_with_due_in_month
            })
            return {
                "year_month": year_month,
                "source": "account_balance_due_month",
                "official_bill_total": None,
                "current_open_total": float(open_total),
                "minimum_payment_total": float(min_total),
                "payments_total": None,
                "finance_charges_total": None,
                "due_dates": due_dates,
                "cards": [
                    {
                        "account_id": a.id,
                        "due_date": a.credit_balance_due_date.isoformat(),
                        "total_amount": float(a.balance or 0),
                        "minimum_payment_amount": float(a.credit_minimum_payment or 0),
                    }
                    for a in credit_with_due_in_month
                ],
            }

    # ---- Tier 3: transaction fallback ----
    year, month = int(year_month[:4]), int(year_month[5:])
    _, last_day = calendar.monthrange(year, month)
    from_date = datetime.date(year, month, 1)
    to_date = datetime.date(year, month, last_day)
    inv = invoice_summary(session, from_date=from_date, to_date=to_date)
    return {
        "year_month": year_month,
        "source": "transaction_fallback",
        "official_bill_total": None,
        "current_open_total": float(inv["invoice_gross_total"]),
        "minimum_payment_total": None,
        "payments_total": None,
        "finance_charges_total": None,
        "due_dates": [],
        "cards": [],
    }
