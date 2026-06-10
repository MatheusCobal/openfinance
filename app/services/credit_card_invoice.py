"""Single source of truth for credit-card invoice planning.

All invoice-source decision logic lives here. Nothing in fixed_costs.py or
pluggy_snapshot.py should independently decide which invoice source to use.

Public API:
    planning_invoice_for_month(session, year_month, today=None) -> dict
    scheduled_installments_for_month(session, year_month, today=None) -> dict

Source priority:

  current_month:
    1. open_invoice  — bill_id-null transactions in the current billing cycle
                       (determined by Account.credit_balance_close_date), or the
                       current calendar month when no close_date is available.
    2. account_balance — sum of CREDIT Account.balance (snapshot) when no
                         cycle transactions exist.
    3. transaction_fallback — reconstructed via invoice_summary().
    4. none

  future_month:
    1. official_bill         — CreditCardBill.due_date in year_month.
    2. account_balance_due_month — Account.balance where credit_balance_due_date
                                   falls in year_month.
    3. scheduled_installments — future credit-card transactions in year_month.
    4. transaction_fallback
    5. none

  past_month:
    1. official_bill      — CreditCardBill.due_date in year_month.
    2. transaction_fallback
    3. none
"""

from __future__ import annotations

import calendar
import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import Account, CreditCardBill, Transaction
from app.services.transactions import _non_duplicate_clause


PAYMENT_MATCH_TOLERANCE = Decimal("1.00")


# ---------------------------------------------------------------------------
# Helpers shared with pluggy_snapshot (billing-cycle calculation)
# ---------------------------------------------------------------------------


def _billing_cycle_for_close_date(
    close_date: datetime.date,
) -> tuple[datetime.date, datetime.date]:
    """Return (cycle_start, cycle_end) for a credit-card close date.

    The cycle ends on ``close_date``. The start is the day after the same
    calendar day one month earlier.
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


def _next_close_date(close_date: datetime.date) -> datetime.date:
    """Return the next occurrence of the same close-date day, one month later.

    Handles month-length differences (e.g. close on the 31st → 28/29 in Feb).
    """
    if close_date.month == 12:
        next_year, next_month = close_date.year + 1, 1
    else:
        next_year, next_month = close_date.year, close_date.month + 1
    max_day = calendar.monthrange(next_year, next_month)[1]
    return datetime.date(next_year, next_month, min(close_date.day, max_day))


def _forming_billing_cycle(
    close_date: datetime.date,
    today: datetime.date,
) -> tuple[datetime.date, datetime.date]:
    """Return the billing cycle that is currently OPEN (forming) as of today.

    While today is on/before close_date the cycle ending on close_date is still
    forming.  Once today passes close_date that cycle has closed and the NEXT
    cycle (ending on the following close date) is the one accumulating new
    purchases.

    Example (close_date=2026-06-04):
      today=2026-06-01 → (2026-05-05, 2026-06-04)   [still forming]
      today=2026-06-08 → (2026-06-05, 2026-07-04)   [next cycle opened]
    """
    if today <= close_date:
        return _billing_cycle_for_close_date(close_date)
    return _billing_cycle_for_close_date(_next_close_date(close_date))


def _next_calendar_month(today: datetime.date) -> str:
    """The ``YYYY-MM`` of the month immediately after ``today``'s month.

    This is the "fatura vigente" month: the dashboard's default planning month
    (getDefaultPlanningMonth in planning_common.js) is always currentMonth + 1.
    """
    if today.month == 12:
        return f"{today.year + 1:04d}-01"
    return f"{today.year:04d}-{today.month + 1:02d}"


def _active_item_ids(session: Session) -> set:
    from app.models import Item

    return {item.id for item in session.exec(select(Item)).all() if item.is_active}


def _active_credit_accounts(session: Session) -> list[Account]:
    active_ids = _active_item_ids(session)
    return [
        a
        for a in session.exec(select(Account)).all()
        if a.type == "CREDIT" and a.is_active and a.item_id in active_ids
    ]


def _account_balance_total(credit_accounts: list[Account]) -> Decimal:
    return sum(
        (a.balance for a in credit_accounts if a.balance is not None),
        Decimal("0"),
    )


def _payment_status_from_amounts(
    invoice_amount: Decimal,
    paid_amount: Optional[Decimal],
    *,
    source: str,
    confidence: str,
) -> Dict[str, Any]:
    invoice_amount = max(invoice_amount, Decimal("0"))
    if invoice_amount <= 0:
        return {
            "payment_status": "unknown",
            "payment_confidence": "none",
            "payment_source": "none",
            "paid_amount": 0.0,
            "remaining_amount": 0.0,
            "matched_payment_transactions": [],
        }
    if paid_amount is None:
        return {
            "payment_status": "unknown",
            "payment_confidence": "none",
            "payment_source": "none",
            "paid_amount": 0.0,
            "remaining_amount": float(invoice_amount),
            "matched_payment_transactions": [],
        }

    paid_amount = max(paid_amount, Decimal("0"))
    remaining = max(invoice_amount - paid_amount, Decimal("0"))
    if paid_amount >= invoice_amount - PAYMENT_MATCH_TOLERANCE:
        status = "paid"
    elif paid_amount > 0:
        status = "partially_paid"
    else:
        status = "unpaid"
    return {
        "payment_status": status,
        "payment_confidence": confidence,
        "payment_source": source,
        "paid_amount": float(paid_amount),
        "remaining_amount": float(remaining),
        "matched_payment_transactions": [],
    }


def _serialize_payment_transaction(tx: Transaction) -> Dict[str, Any]:
    return {
        "id": tx.id,
        "date": tx.date.isoformat(),
        "amount": float(abs(tx.amount)),
        "description": tx.description,
        "account_id": tx.account_id,
        "category": tx.category,
    }


def _find_invoice_payment_transactions(
    session: Session,
    *,
    account_ids: set[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> list[Transaction]:
    from app.services.classification import TransactionClassifier
    from app.services.transactions import account_ids_by_type

    active_credit_ids = set(account_ids_by_type(session, {"CREDIT"}))
    if account_ids:
        active_credit_ids &= account_ids
    if not active_credit_ids:
        return []

    classifier = TransactionClassifier.from_session(session)
    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id.in_(active_credit_ids),
            Transaction.date >= start_date,
            Transaction.date <= end_date,
            _non_duplicate_clause(),
        )
        .order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()
    return [tx for tx in rows if classifier.is_invoice_payment(tx)]


def _payment_status_from_transactions(
    transactions: list[Transaction],
    invoice_amount: Decimal,
    *,
    source: str = "invoice_payment_transaction",
    confidence: str = "medium",
) -> Dict[str, Any]:
    paid_amount = sum((abs(tx.amount) for tx in transactions), Decimal("0"))
    result = _payment_status_from_amounts(
        invoice_amount,
        paid_amount,
        source=source,
        confidence=confidence,
    )
    result["matched_payment_transactions"] = [
        _serialize_payment_transaction(tx) for tx in transactions
    ]
    return result


def _default_payment_status(invoice_amount: Decimal, source: str) -> Dict[str, Any]:
    invoice_amount = max(invoice_amount, Decimal("0"))
    if source == "none" and invoice_amount <= 0:
        status = "not_applicable"
        confidence = "none"
        remaining = Decimal("0")
    elif invoice_amount <= 0:
        status = "unknown"
        confidence = "none"
        remaining = Decimal("0")
    else:
        status = "unknown"
        confidence = "none"
        remaining = invoice_amount
    return {
        "payment_status": status,
        "payment_confidence": confidence,
        "payment_source": "none",
        "paid_amount": 0.0,
        "remaining_amount": float(remaining),
        "matched_payment_transactions": [],
    }


def _bill_window(bill: CreditCardBill) -> tuple[datetime.date, datetime.date]:
    if bill.due_date is None:
        today = datetime.date.today()
        return today, today
    return (
        bill.due_date - datetime.timedelta(days=10),
        bill.due_date + datetime.timedelta(days=5),
    )


def _card_payment_status(bill: CreditCardBill) -> Dict[str, Any]:
    total = max(bill.total_amount or Decimal("0"), Decimal("0"))
    paid = max(bill.payments_total or Decimal("0"), Decimal("0"))
    if bill.total_amount is None or total <= 0 or bill.payments_total is None:
        status = "unknown"
        remaining = total
    elif paid >= total - PAYMENT_MATCH_TOLERANCE:
        status = "paid"
        remaining = Decimal("0")
    elif paid > 0:
        status = "partially_paid"
        remaining = total - paid
    else:
        status = "unpaid"
        remaining = total
    return {
        "paid_amount": float(paid),
        "remaining_amount": float(max(remaining, Decimal("0"))),
        "payment_status": status,
    }


def _payment_status_for_official_bills(
    session: Session,
    bills: list[CreditCardBill],
) -> Dict[str, Any]:
    invoice_amount = sum((b.total_amount or Decimal("0") for b in bills), Decimal("0"))
    if invoice_amount <= 0:
        return _default_payment_status(invoice_amount, "official_bill")

    if all(b.payments_total is not None for b in bills):
        paid_amount = sum((b.payments_total or Decimal("0") for b in bills), Decimal("0"))
        confidence = "high" if paid_amount > 0 else "medium"
        return _payment_status_from_amounts(
            invoice_amount,
            paid_amount,
            source="bill_payments_total",
            confidence=confidence,
        )

    payment_txs: list[Transaction] = []
    seen_ids: set[str] = set()
    for bill in bills:
        if bill.due_date is None:
            continue
        start_date, end_date = _bill_window(bill)
        for tx in _find_invoice_payment_transactions(
            session,
            account_ids={bill.account_id},
            start_date=start_date,
            end_date=end_date,
        ):
            if tx.id not in seen_ids:
                seen_ids.add(tx.id)
                payment_txs.append(tx)

    if payment_txs:
        return _payment_status_from_transactions(payment_txs, invoice_amount)

    return _default_payment_status(invoice_amount, "official_bill")


def _payment_status_for_non_official_invoice(
    session: Session,
    result: Dict[str, Any],
    today: datetime.date,
) -> Dict[str, Any]:
    invoice_amount = Decimal(str(result.get("amount") or 0))
    source = result.get("source") or "none"
    due_dates = [
        datetime.date.fromisoformat(value) for value in result.get("due_dates", []) if value
    ]
    account_ids = {
        card.get("account_id") for card in result.get("cards", []) if card.get("account_id")
    }

    if due_dates and invoice_amount > 0:
        payment_txs: list[Transaction] = []
        seen_ids: set[str] = set()
        for due_date in due_dates:
            start_date = due_date - datetime.timedelta(days=10)
            end_date = due_date + datetime.timedelta(days=5)
            for tx in _find_invoice_payment_transactions(
                session,
                account_ids=account_ids,
                start_date=start_date,
                end_date=end_date,
            ):
                if tx.id not in seen_ids:
                    seen_ids.add(tx.id)
                    payment_txs.append(tx)
        if payment_txs:
            return _payment_status_from_transactions(payment_txs, invoice_amount)
        if any(due_date <= today for due_date in due_dates):
            return _payment_status_from_amounts(
                invoice_amount,
                Decimal("0"),
                source="none",
                confidence="low",
            )

    return _default_payment_status(invoice_amount, source)


def _with_payment_status(
    result: Dict[str, Any],
    payment_status: Dict[str, Any],
) -> Dict[str, Any]:
    return {**result, **payment_status}


def _none_result(
    year_month: str,
    planning_mode: str,
    account_count: int,
    account_balance_total: float,
) -> Dict[str, Any]:
    return {
        "year_month": year_month,
        "planning_mode": planning_mode,
        "amount": 0.0,
        "source": "none",
        "source_label": "Sem dados de fatura",
        "is_estimated": True,
        "due_dates": [],
        "cards": [],
        "transaction_count": 0,
        "bill_count": 0,
        "account_count": account_count,
        "cycle_start": None,
        "cycle_end": None,
        "account_balance_total": account_balance_total,
    }


# ---------------------------------------------------------------------------
# Scheduled installments (public — used by upcoming_months in fixed_costs.py)
# ---------------------------------------------------------------------------


def scheduled_installments_for_month(
    session: Session,
    year_month: str,
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Future-dated credit-card purchases that will land in ``year_month``.

    Only transactions strictly AFTER ``today`` are counted so they don't
    double-count with spending already realised in the current month.
    Negative amounts (refunds, cancellations) are excluded.
    """
    from app.services.classification import SPENDING_ACCOUNT_TYPES, TransactionClassifier
    from app.services.transactions import account_ids_by_type

    today = today if today is not None else datetime.date.today()
    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    first_day = datetime.date(year_int, month_int, 1)
    _, last_day_n = calendar.monthrange(year_int, month_int)
    last_day = datetime.date(year_int, month_int, last_day_n)

    window_start = max(first_day, today + datetime.timedelta(days=1))
    if window_start > last_day:
        return {
            "year_month": year_month,
            "total": 0.0,
            "count": 0,
            "transactions": [],
        }

    credit_account_ids = account_ids_by_type(session, SPENDING_ACCOUNT_TYPES)
    if not credit_account_ids:
        return {
            "year_month": year_month,
            "total": 0.0,
            "count": 0,
            "transactions": [],
        }

    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.account_id.in_(credit_account_ids),
            Transaction.date >= window_start,
            Transaction.date <= last_day,
            _non_duplicate_clause(),
        )
        .order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()

    classifier = TransactionClassifier.from_session(session)
    total = Decimal("0")
    items: list[Dict[str, Any]] = []
    for tx in rows:
        if not classifier.is_card_purchase(tx):
            continue
        if tx.amount <= 0:
            continue
        total += tx.amount
        items.append(
            {
                "transaction_id": tx.id,
                "date": tx.date.isoformat(),
                "description": tx.description,
                "amount": float(tx.amount),
                "signed_amount": float(tx.amount),
                "category": tx.category,
            }
        )
    return {
        "year_month": year_month,
        "total": float(total),
        "count": len(items),
        "transactions": items,
    }


# ---------------------------------------------------------------------------
# Per-mode invoice logic
# ---------------------------------------------------------------------------


def _current_month_invoice(
    session: Session,
    year_month: str,
    today: datetime.date,
    credit_accounts: list[Account],
) -> Dict[str, Any]:
    """Open invoice estimate for the current billing month.

    Tier 1: bill_id-null transactions in the current billing cycle
            (cycle boundaries come from Account.credit_balance_close_date).
            No status filter — Pluggy marks settled purchases as status=null
            and very recent ones as PENDING; both must be counted.
    Tier 2: sum of Account.balance (snapshot) when no cycle transactions exist.
    Tier 3: invoice_summary() transaction reconstruction.
    Tier 4: none.
    """
    from app.services.transaction_reports import invoice_summary
    from app.services.classification import TransactionClassifier

    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    month_start = datetime.date(year_int, month_int, 1)
    _, month_last = calendar.monthrange(year_int, month_int)
    month_end = datetime.date(year_int, month_int, month_last)

    credit_account_ids = {a.id for a in credit_accounts}
    bal_total = _account_balance_total(credit_accounts)
    classifier = TransactionClassifier.from_session(session)

    if not credit_accounts:
        return _none_result(year_month, "current_month", 0, float(bal_total))

    # ---- Tier 1: billing-cycle transactions (bill_id = null) ----
    accounts_with_close = [a for a in credit_accounts if a.credit_balance_close_date]
    if accounts_with_close:
        all_starts, all_ends = [], []
        for a in accounts_with_close:
            cs, ce = _billing_cycle_for_close_date(a.credit_balance_close_date)
            all_starts.append(cs)
            all_ends.append(ce)
        cycle_start = min(all_starts)
        cycle_end = max(all_ends)

        open_cycle_txs = session.exec(
            select(Transaction).where(
                Transaction.account_id.in_(credit_account_ids),
                Transaction.date >= cycle_start,
                Transaction.date <= cycle_end,
                or_(Transaction.bill_id.is_(None), Transaction.bill_id == ""),
                _non_duplicate_clause(),
            )
        ).all()
        open_cycle_txs = [tx for tx in open_cycle_txs if classifier.is_card_purchase(tx)]

        if open_cycle_txs:
            total = sum((abs(tx.amount) for tx in open_cycle_txs), Decimal("0"))
            return {
                "year_month": year_month,
                "planning_mode": "current_month",
                "amount": float(total),
                "source": "open_invoice",
                "source_label": "Fatura aberta estimada",
                "is_estimated": True,
                "due_dates": [],
                "cards": [],
                "transaction_count": len(open_cycle_txs),
                "bill_count": 0,
                "account_count": len(accounts_with_close),
                "cycle_start": cycle_start.isoformat(),
                "cycle_end": cycle_end.isoformat(),
                "account_balance_total": float(bal_total),
            }

    # ---- Tier 2: calendar-month fallback (no close_date available) ----
    effective_end = min(month_end, today)
    open_month_txs = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(credit_account_ids),
            Transaction.date >= month_start,
            Transaction.date <= effective_end,
            or_(Transaction.bill_id.is_(None), Transaction.bill_id == ""),
            _non_duplicate_clause(),
        )
    ).all()
    open_month_txs = [tx for tx in open_month_txs if classifier.is_card_purchase(tx)]

    if open_month_txs:
        total = sum((abs(tx.amount) for tx in open_month_txs), Decimal("0"))
        return {
            "year_month": year_month,
            "planning_mode": "current_month",
            "amount": float(total),
            "source": "open_invoice",
            "source_label": "Fatura aberta estimada",
            "is_estimated": True,
            "due_dates": [],
            "cards": [],
            "transaction_count": len(open_month_txs),
            "bill_count": 0,
            "account_count": len(credit_accounts),
            "cycle_start": month_start.isoformat(),
            "cycle_end": effective_end.isoformat(),
            "account_balance_total": float(bal_total),
        }

    # ---- Tier 3: Account.balance snapshot ----
    # Accounts with no due date (unknown) are valid — we can still use their balance.
    # Accounts with a due date explicitly outside the selected month are stale —
    # their balance reflects a prior invoice cycle, so skip them.
    accounts_with_balance = [a for a in credit_accounts if a.balance is not None]
    _stale_ab_fields: Dict[str, Any] = {}

    if accounts_with_balance:
        stale_accounts = [
            a
            for a in accounts_with_balance
            if a.credit_balance_due_date is not None
            and a.credit_balance_due_date.strftime("%Y-%m") != year_month
        ]
        # Valid: no due date (unknown) or due date in the selected month
        valid_accounts = [a for a in accounts_with_balance if a not in stale_accounts]

        if valid_accounts:
            open_total = _account_balance_total(valid_accounts)
            due_dates = sorted(
                {
                    a.credit_balance_due_date.isoformat()
                    for a in valid_accounts
                    if a.credit_balance_due_date
                }
            )
            return {
                "year_month": year_month,
                "planning_mode": "current_month",
                "amount": float(open_total),
                "source": "account_balance",
                "source_label": "Saldo do cartão",
                "is_estimated": True,
                "due_dates": due_dates,
                "cards": [
                    {
                        "account_id": a.id,
                        "due_date": a.credit_balance_due_date.isoformat()
                        if a.credit_balance_due_date
                        else None,
                        "total_amount": float(a.balance or 0),
                        "minimum_payment_amount": float(a.credit_minimum_payment or 0),
                    }
                    for a in valid_accounts
                ],
                "transaction_count": 0,
                "bill_count": 0,
                "account_count": len(valid_accounts),
                "cycle_start": None,
                "cycle_end": None,
                "account_balance_total": float(bal_total),
            }
        else:
            # All accounts have stale due dates — retain visibility but skip as invoice amount.
            stale_dates = sorted(
                {
                    a.credit_balance_due_date.isoformat()
                    for a in stale_accounts
                    if a.credit_balance_due_date
                }
            )
            _stale_ab_fields = {
                "account_balance_due_date": stale_dates[0] if stale_dates else None,
                "account_balance_due_date_is_stale": True,
                "account_balance_ignored_reason": (
                    f"due date {stale_dates[0] if stale_dates else 'unknown'} "
                    f"is outside the selected month {year_month}"
                ),
            }

    # ---- Tier 4: transaction fallback ----
    inv = invoice_summary(session, from_date=month_start, to_date=month_end)
    inv_total = float(inv["invoice_gross_total"])
    if inv_total > 0:
        return {
            "year_month": year_month,
            "planning_mode": "current_month",
            "amount": inv_total,
            "source": "transaction_fallback",
            "source_label": "Reconstruída por transações",
            "is_estimated": True,
            "due_dates": [],
            "cards": [],
            "transaction_count": inv["invoice_gross_count"],
            "bill_count": 0,
            "account_count": len(credit_accounts),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
            **_stale_ab_fields,
        }

    none_r = _none_result(year_month, "current_month", len(credit_accounts), float(bal_total))
    return {**none_r, **_stale_ab_fields}


def _vigente_forming_invoice(
    session: Session,
    year_month: str,
    today: datetime.date,
    credit_accounts: list[Account],
) -> Optional[Dict[str, Any]]:
    """The "fatura vigente": invoice currently FORMING, due next month.

    This is the ONLY part of the future-month flow that is transaction-driven.
    It applies strictly to the vigente month (the calendar month immediately
    after ``today`` — the dashboard's default planning month) so that months
    further out keep using the official-bill / installments tiers unchanged.

    Why it's needed: when today is past the card's close_date, recent purchases
    land in the freshly-opened cycle that will be due next month. The old future
    tiers showed either a stale Account.balance snapshot (frozen between syncs)
    or a premature/empty official bill, so the value appeared "frozen". Here we
    sum the actual transactions of the forming cycle instead.

    Returns None (caller falls through to the official-bill tiers) when:
      * year_month is not the vigente month, or
      * no account exposes credit_balance_close_date, or
      * the forming cycle has no qualifying transactions yet.

    Sign conventions vary across synced rows, so purchases are summed by
    absolute value after non-purchase flows are excluded by the classifier.
    """
    if year_month != _next_calendar_month(today):
        return None

    accounts_with_close = [a for a in credit_accounts if a.credit_balance_close_date]
    if not accounts_with_close:
        return None

    all_starts, all_ends = [], []
    for a in accounts_with_close:
        cs, ce = _forming_billing_cycle(a.credit_balance_close_date, today)
        all_starts.append(cs)
        all_ends.append(ce)
    cycle_start = min(all_starts)
    cycle_end = max(all_ends)

    credit_account_ids = {a.id for a in credit_accounts}
    cycle_txs = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(credit_account_ids),
            Transaction.date >= cycle_start,
            Transaction.date <= cycle_end,
            _non_duplicate_clause(),
        )
    ).all()

    from app.services.classification import TransactionClassifier

    classifier = TransactionClassifier.from_session(session)
    qualifying_txs = [tx for tx in cycle_txs if classifier.is_card_purchase(tx)]
    if not qualifying_txs:
        return None

    raw_total = sum((abs(tx.amount) for tx in qualifying_txs), Decimal("0"))
    total = max(raw_total, Decimal("0"))

    return {
        "year_month": year_month,
        "planning_mode": "future_month",
        "amount": float(total),
        "source": "active_open_invoice_transactions",
        "source_label": "Fatura vigente em formação",
        "is_estimated": True,
        "due_dates": [],
        "cards": [],
        "transaction_count": len(qualifying_txs),
        "bill_count": 0,
        "account_count": len(accounts_with_close),
        "cycle_start": cycle_start.isoformat(),
        "cycle_end": cycle_end.isoformat(),
        "account_balance_total": float(_account_balance_total(credit_accounts)),
    }


def _future_month_invoice(
    session: Session,
    year_month: str,
    today: datetime.date,
    credit_accounts: list[Account],
) -> Dict[str, Any]:
    """Invoice estimate for a future month.

    Tier 0: fatura vigente — forming-cycle transactions, vigente month only
            (see _vigente_forming_invoice). Months beyond the vigente month
            skip this tier entirely.
    Tier 1: official CreditCardBill with due_date in year_month.
    Tier 2: Account.balance where credit_balance_due_date falls in year_month.
    Tier 3: scheduled future installments in year_month.
    Tier 4: transaction fallback.
    Tier 5: none.
    """
    from app.services.transaction_reports import invoice_summary

    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    _, month_last_n = calendar.monthrange(year_int, month_int)
    first_day = datetime.date(year_int, month_int, 1)
    last_day = datetime.date(year_int, month_int, month_last_n)

    credit_account_ids = {a.id for a in credit_accounts}
    bal_total = _account_balance_total(credit_accounts)

    if not credit_accounts:
        return _none_result(year_month, "future_month", 0, float(bal_total))

    # ---- Tier 0: fatura vigente (forming-cycle transactions, vigente month) ----
    forming = _vigente_forming_invoice(session, year_month, today, credit_accounts)
    if forming is not None:
        return forming

    # ---- Tier 1: official CreditCardBill ----
    bills = session.exec(select(CreditCardBill)).all()
    matched_bills = [
        b
        for b in bills
        if b.due_date is not None
        and b.due_date.strftime("%Y-%m") == year_month
        and b.total_amount is not None
        and b.account_id in credit_account_ids
    ]

    if matched_bills:
        official_total = sum((b.total_amount for b in matched_bills), Decimal("0"))
        due_dates = sorted({b.due_date.isoformat() for b in matched_bills})
        payment_status = _payment_status_for_official_bills(session, matched_bills)
        return _with_payment_status(
            {
                "year_month": year_month,
                "planning_mode": "future_month",
                "amount": float(official_total),
                "source": "official_bill",
                "source_label": "Fatura oficial (Pluggy)",
                "is_estimated": False,
                "due_dates": due_dates,
                "cards": [
                    {
                        "account_id": b.account_id,
                        "due_date": b.due_date.isoformat() if b.due_date else None,
                        "total_amount": float(b.total_amount or 0),
                        "minimum_payment_amount": float(b.minimum_payment_amount or 0),
                        **_card_payment_status(b),
                    }
                    for b in matched_bills
                ],
                "transaction_count": 0,
                "bill_count": len(matched_bills),
                "account_count": len(credit_accounts),
                "cycle_start": None,
                "cycle_end": None,
                "account_balance_total": float(bal_total),
            },
            payment_status,
        )

    # ---- Tier 2: Account.balance with due_date in this month ----
    credit_with_due_in_month = [
        a
        for a in credit_accounts
        if a.balance is not None
        and a.credit_balance_due_date is not None
        and a.credit_balance_due_date.strftime("%Y-%m") == year_month
    ]
    if credit_with_due_in_month:
        open_total = _account_balance_total(credit_with_due_in_month)
        due_dates = sorted(
            {a.credit_balance_due_date.isoformat() for a in credit_with_due_in_month}
        )
        return {
            "year_month": year_month,
            "planning_mode": "future_month",
            "amount": float(open_total),
            "source": "account_balance_due_month",
            "source_label": "Saldo do cartão (vencimento neste mês)",
            "is_estimated": True,
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
            "transaction_count": 0,
            "bill_count": 0,
            "account_count": len(credit_with_due_in_month),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
        }

    # ---- Tier 3: scheduled future installments ----
    installments = scheduled_installments_for_month(session, year_month, today=today)
    if installments["total"] > 0:
        return {
            "year_month": year_month,
            "planning_mode": "future_month",
            "amount": installments["total"],
            "source": "scheduled_installments",
            "source_label": "Parcelas programadas",
            "is_estimated": True,
            "due_dates": [],
            "cards": [],
            "transaction_count": installments["count"],
            "bill_count": 0,
            "account_count": len(credit_accounts),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
        }

    # ---- Tier 4: transaction fallback ----
    inv = invoice_summary(session, from_date=first_day, to_date=last_day)
    inv_total = float(inv["invoice_gross_total"])
    if inv_total > 0:
        return {
            "year_month": year_month,
            "planning_mode": "future_month",
            "amount": inv_total,
            "source": "transaction_fallback",
            "source_label": "Reconstruída por transações",
            "is_estimated": True,
            "due_dates": [],
            "cards": [],
            "transaction_count": inv["invoice_gross_count"],
            "bill_count": 0,
            "account_count": len(credit_accounts),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
        }

    return _none_result(year_month, "future_month", len(credit_accounts), float(bal_total))


def _past_month_invoice(
    session: Session,
    year_month: str,
    credit_accounts: list[Account],
) -> Dict[str, Any]:
    """Invoice summary for a past month.

    Tier 1: official CreditCardBill with due_date in year_month.
    Tier 2: transaction fallback.
    Tier 3: none.
    """
    from app.services.transaction_reports import invoice_summary

    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    _, month_last_n = calendar.monthrange(year_int, month_int)
    first_day = datetime.date(year_int, month_int, 1)
    last_day = datetime.date(year_int, month_int, month_last_n)

    credit_account_ids = {a.id for a in credit_accounts}
    bal_total = _account_balance_total(credit_accounts)

    if not credit_accounts:
        return _none_result(year_month, "past_month", 0, float(bal_total))

    # ---- Tier 1: official CreditCardBill ----
    bills = session.exec(select(CreditCardBill)).all()
    matched_bills = [
        b
        for b in bills
        if b.due_date is not None
        and b.due_date.strftime("%Y-%m") == year_month
        and b.total_amount is not None
        and b.account_id in credit_account_ids
    ]

    if matched_bills:
        official_total = sum((b.total_amount for b in matched_bills), Decimal("0"))
        due_dates = sorted({b.due_date.isoformat() for b in matched_bills})
        payment_status = _payment_status_for_official_bills(session, matched_bills)
        return _with_payment_status(
            {
                "year_month": year_month,
                "planning_mode": "past_month",
                "amount": float(official_total),
                "source": "official_bill",
                "source_label": "Fatura oficial (Pluggy)",
                "is_estimated": False,
                "due_dates": due_dates,
                "cards": [
                    {
                        "account_id": b.account_id,
                        "due_date": b.due_date.isoformat() if b.due_date else None,
                        "total_amount": float(b.total_amount or 0),
                        "minimum_payment_amount": float(b.minimum_payment_amount or 0),
                        **_card_payment_status(b),
                    }
                    for b in matched_bills
                ],
                "transaction_count": 0,
                "bill_count": len(matched_bills),
                "account_count": len(credit_accounts),
                "cycle_start": None,
                "cycle_end": None,
                "account_balance_total": float(bal_total),
            },
            payment_status,
        )

    # ---- Tier 2: transaction fallback ----
    inv = invoice_summary(session, from_date=first_day, to_date=last_day)
    inv_total = float(inv["invoice_gross_total"])
    if inv_total > 0:
        return {
            "year_month": year_month,
            "planning_mode": "past_month",
            "amount": inv_total,
            "source": "transaction_fallback",
            "source_label": "Reconstruída por transações",
            "is_estimated": True,
            "due_dates": [],
            "cards": [],
            "transaction_count": inv["invoice_gross_count"],
            "bill_count": 0,
            "account_count": len(credit_accounts),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
        }

    return _none_result(year_month, "past_month", len(credit_accounts), float(bal_total))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def planning_invoice_for_month(
    session: Session,
    year_month: str,
    today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Return the planning invoice for ``year_month`` as a single structured dict.

    This is the single source of truth for credit-card invoice decisions in
    the planning layer. ``spending_capacity_summary`` and
    ``GET /credit-card/invoice/{year_month}`` both delegate here.

    The ``today`` parameter is always threaded through so the function is
    deterministic in tests (no hidden ``datetime.date.today()`` calls).
    """
    today = today if today is not None else datetime.date.today()
    current_ym = today.strftime("%Y-%m")

    credit_accounts = _active_credit_accounts(session)

    if year_month == current_ym:
        result = _current_month_invoice(session, year_month, today, credit_accounts)
    elif year_month > current_ym:
        result = _future_month_invoice(session, year_month, today, credit_accounts)
    else:
        result = _past_month_invoice(session, year_month, credit_accounts)

    if "payment_status" in result:
        return result
    return _with_payment_status(
        result,
        _payment_status_for_non_official_invoice(session, result, today),
    )
