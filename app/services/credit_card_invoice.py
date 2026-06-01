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
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import Account, CreditCardBill, Transaction


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


def _active_item_ids(session: Session) -> set:
    from app.models import Item
    return {item.id for item in session.exec(select(Item)).all() if item.is_active}


def _active_credit_accounts(session: Session) -> list[Account]:
    active_ids = _active_item_ids(session)
    return [
        a for a in session.exec(select(Account)).all()
        if a.type == "CREDIT" and a.is_active and a.item_id in active_ids
    ]


def _account_balance_total(credit_accounts: list[Account]) -> Decimal:
    return sum(
        (a.balance for a in credit_accounts if a.balance is not None),
        Decimal("0"),
    )


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
    from app.services.classification import SPENDING_ACCOUNT_TYPES
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
        )
        .order_by(Transaction.date.asc(), Transaction.description.asc())
    ).all()

    total = Decimal("0")
    items: list[Dict[str, Any]] = []
    for tx in rows:
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

    year_int, month_int = int(year_month[:4]), int(year_month[5:])
    month_start = datetime.date(year_int, month_int, 1)
    _, month_last = calendar.monthrange(year_int, month_int)
    month_end = datetime.date(year_int, month_int, month_last)

    credit_account_ids = {a.id for a in credit_accounts}
    bal_total = _account_balance_total(credit_accounts)

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
            )
        ).all()

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
        )
    ).all()

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
    accounts_with_balance = [a for a in credit_accounts if a.balance is not None]
    if accounts_with_balance:
        open_total = _account_balance_total(accounts_with_balance)
        due_dates = sorted({
            a.credit_balance_due_date.isoformat()
            for a in accounts_with_balance
            if a.credit_balance_due_date
        })
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
                    "due_date": a.credit_balance_due_date.isoformat() if a.credit_balance_due_date else None,
                    "total_amount": float(a.balance or 0),
                    "minimum_payment_amount": float(a.credit_minimum_payment or 0),
                }
                for a in accounts_with_balance
            ],
            "transaction_count": 0,
            "bill_count": 0,
            "account_count": len(accounts_with_balance),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(open_total),
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
        }

    return _none_result(year_month, "current_month", len(credit_accounts), float(bal_total))


def _future_month_invoice(
    session: Session,
    year_month: str,
    today: datetime.date,
    credit_accounts: list[Account],
) -> Dict[str, Any]:
    """Invoice estimate for a future month.

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

    # ---- Tier 1: official CreditCardBill ----
    bills = session.exec(select(CreditCardBill)).all()
    matched_bills = [
        b for b in bills
        if b.due_date is not None
        and b.due_date.strftime("%Y-%m") == year_month
        and b.total_amount is not None
        and b.account_id in credit_account_ids
    ]

    if matched_bills:
        official_total = sum((b.total_amount for b in matched_bills), Decimal("0"))
        due_dates = sorted({b.due_date.isoformat() for b in matched_bills})
        return {
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
                }
                for b in matched_bills
            ],
            "transaction_count": 0,
            "bill_count": len(matched_bills),
            "account_count": len(credit_accounts),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
        }

    # ---- Tier 2: Account.balance with due_date in this month ----
    credit_with_due_in_month = [
        a for a in credit_accounts
        if a.balance is not None
        and a.credit_balance_due_date is not None
        and a.credit_balance_due_date.strftime("%Y-%m") == year_month
    ]
    if credit_with_due_in_month:
        open_total = _account_balance_total(credit_with_due_in_month)
        due_dates = sorted({
            a.credit_balance_due_date.isoformat()
            for a in credit_with_due_in_month
        })
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
        b for b in bills
        if b.due_date is not None
        and b.due_date.strftime("%Y-%m") == year_month
        and b.total_amount is not None
        and b.account_id in credit_account_ids
    ]

    if matched_bills:
        official_total = sum((b.total_amount for b in matched_bills), Decimal("0"))
        due_dates = sorted({b.due_date.isoformat() for b in matched_bills})
        return {
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
                }
                for b in matched_bills
            ],
            "transaction_count": 0,
            "bill_count": len(matched_bills),
            "account_count": len(credit_accounts),
            "cycle_start": None,
            "cycle_end": None,
            "account_balance_total": float(bal_total),
        }

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
        return _current_month_invoice(session, year_month, today, credit_accounts)
    elif year_month > current_ym:
        return _future_month_invoice(session, year_month, today, credit_accounts)
    else:
        return _past_month_invoice(session, year_month, credit_accounts)
