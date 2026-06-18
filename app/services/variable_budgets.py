"""Variable (discretionary) spending goals per category, per month.

This module is the 10D-C planning layer that replaces the removed legacy
category budgets. It is built entirely on top of the current Pluggy-based
classification:

* eligible categories are the credit-card category labels resolved by
  ``resolve_credit_internal_category`` — the same grouping the dashboard and
  the invoice summary already use;
* "spent" only ever counts **real CREDIT purchases** (``is_card_purchase``).
  Card refunds/cancellations net the category total down (never below zero),
  invoice payments / transfers / income / BANK movements are ignored. We never
  use ``abs(tx.amount)`` to turn a negative row into spending.

Goals are independent per month (no automatic carry-over). BANK/PIX spending is
intentionally out of scope here, mirroring the CREDIT-only "gastos por
categoria" report.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Set

from sqlmodel import Session, select

from app.models import Transaction, VariableBudget
from app.services.classification import (
    TransactionClassifier,
    card_invoice_signed_amount,
)
from app.services.credit_categories import (
    CREDIT_CATEGORY_LABELS,
    resolve_credit_internal_category,
)
from app.services.transactions import (
    SPENDING_ACCOUNT_TYPES,
    _non_duplicate_clause,
    account_ids_by_type,
)

_YEAR_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class VariableBudgetValidationError(ValueError):
    """Raised for invalid month / category / target inputs."""


def eligible_categories() -> list[str]:
    """Categories a user may set a variable goal for (Pluggy-based labels)."""
    return list(CREDIT_CATEGORY_LABELS)


def validate_year_month(year_month: str) -> str:
    value = (year_month or "").strip()
    if not _YEAR_MONTH_RE.match(value):
        raise VariableBudgetValidationError("year_month must be in YYYY-MM format")
    return value


def validate_category(category: str) -> str:
    name = (category or "").strip()
    if name not in CREDIT_CATEGORY_LABELS:
        raise VariableBudgetValidationError(f"unknown variable category: {category!r}")
    return name


def _normalize_target(target_amount: Any) -> Decimal:
    try:
        value = Decimal(str(target_amount))
    except Exception as exc:  # noqa: BLE001 - surfaced as a validation error
        raise VariableBudgetValidationError("target_amount must be a number") from exc
    if value < 0:
        raise VariableBudgetValidationError("target_amount must be greater than or equal to 0")
    return value


def list_goals(session: Session, year_month: str) -> Dict[str, VariableBudget]:
    year_month = validate_year_month(year_month)
    rows = session.exec(select(VariableBudget).where(VariableBudget.year_month == year_month)).all()
    return {row.category: row for row in rows}


def upsert_goal(
    session: Session,
    year_month: str,
    category: str,
    target_amount: Any,
) -> VariableBudget:
    year_month = validate_year_month(year_month)
    category = validate_category(category)
    target = _normalize_target(target_amount)

    existing = session.exec(
        select(VariableBudget).where(
            VariableBudget.year_month == year_month,
            VariableBudget.category == category,
        )
    ).first()
    if existing is not None:
        existing.target_amount = target
        from datetime import datetime

        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    goal = VariableBudget(
        year_month=year_month,
        category=category,
        target_amount=target,
    )
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def delete_goal(session: Session, year_month: str, category: str) -> bool:
    year_month = validate_year_month(year_month)
    category = validate_category(category)
    existing = session.exec(
        select(VariableBudget).where(
            VariableBudget.year_month == year_month,
            VariableBudget.category == category,
        )
    ).first()
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def _shift_month(year_month: str, delta: int) -> str:
    year, month = int(year_month[:4]), int(year_month[5:])
    month += delta
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def replicate_goals(
    session: Session,
    source_month: str,
    months_ahead: int = 11,
    overwrite: bool = False,
) -> dict:
    source_month = validate_year_month(source_month)
    if not (1 <= months_ahead <= 36):
        raise VariableBudgetValidationError("months_ahead must be between 1 and 36")

    source_goals = list_goals(session, source_month)
    if not source_goals:
        return {"replicated": 0, "skipped": 0, "months": []}

    replicated = 0
    skipped = 0
    updated_months = []

    for delta in range(1, months_ahead + 1):
        target_month = _shift_month(source_month, delta)
        existing = list_goals(session, target_month)
        if existing and not overwrite:
            skipped += 1
            continue
        for category, goal in source_goals.items():
            upsert_goal(session, target_month, category, goal.target_amount)
        replicated += 1
        updated_months.append(target_month)

    return {"replicated": replicated, "skipped": skipped, "months": updated_months}


def spend_by_category(
    session: Session,
    first_day: date,
    last_day: date,
    exclude_transaction_ids: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Real variable spending per category for the period.

    Only CREDIT purchases count. Refunds/cancellations net the category down
    (floored at zero). ``transaction_count`` counts purchases only. Anything
    already accounted for as a fixed cost (``exclude_transaction_ids``) is
    dropped to avoid double counting.
    """
    skip = exclude_transaction_ids or set()
    credit_account_ids = set(account_ids_by_type(session, SPENDING_ACCOUNT_TYPES))
    if not credit_account_ids:
        return {}
    classifier = TransactionClassifier.from_session(session)
    txs = session.exec(
        select(Transaction).where(
            Transaction.date >= first_day,
            Transaction.date <= last_day,
            _non_duplicate_clause(),
        )
    ).all()

    buckets: Dict[str, Dict[str, Any]] = {}
    for tx in txs:
        if tx.account_id not in credit_account_ids or tx.id in skip:
            continue
        classification = classifier.classify(tx)
        if not (classification.is_card_purchase or classification.is_card_refund):
            continue
        signed = card_invoice_signed_amount(tx, classification)
        if signed == 0:
            continue
        category = resolve_credit_internal_category(
            tx,
            account_type="CREDIT",
            current_internal_category=tx.internal_category,
        )
        bucket = buckets.setdefault(category, {"spent": Decimal("0"), "count": 0})
        bucket["spent"] += signed
        if classification.is_card_purchase:
            bucket["count"] += 1

    # Floor only the final category total — a net-negative category (more
    # refunds than purchases) is reported as zero spend, never as a credit.
    for bucket in buckets.values():
        if bucket["spent"] < 0:
            bucket["spent"] = Decimal("0")
    return buckets


def _status(progress_pct: Optional[float], has_target: bool) -> str:
    if not has_target:
        return "no_target"
    if progress_pct is None:
        return "ok"
    if progress_pct >= 100:
        return "over"
    if progress_pct >= 80:
        return "warning"
    return "ok"


def variable_budget_progress(
    session: Session,
    year_month: str,
    first_day: date,
    last_day: date,
    today: date,
    exclude_transaction_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Full variable-budget payload for a month.

    Returns the ``summary`` block consumed by ``spending_capacity_summary`` and
    the per-category ``items`` list consumed by the Planejamento "Metas
    variáveis" tab. A month with neither goals nor spending yields an honest
    empty state (``items == []`` and all-zero totals) — no misleading values.
    """
    exclude_ids = set(exclude_transaction_ids or set())
    goals = list_goals(session, year_month)
    spend = spend_by_category(session, first_day, last_day, exclude_ids)

    target_total = Decimal("0")
    budgeted_spent_total = Decimal("0")
    unbudgeted_spent_total = Decimal("0")
    unbudgeted_count = 0

    items = []
    for category in set(goals) | set(spend):
        goal = goals.get(category)
        has_target = goal is not None
        target = Decimal(goal.target_amount) if goal is not None else Decimal("0")
        bucket = spend.get(category, {})
        spent = bucket.get("spent", Decimal("0"))
        count = bucket.get("count", 0)
        remaining = target - spent

        if has_target:
            target_total += target
            budgeted_spent_total += spent
            progress = float(spent / target * 100) if target > 0 else None
        else:
            unbudgeted_spent_total += spent
            unbudgeted_count += 1
            progress = None

        items.append(
            {
                "category": category,
                "target": float(target),
                "spent": float(spent),
                "remaining": float(remaining),
                "progress_percent": progress,
                "status": _status(progress, has_target),
                "transaction_count": int(count),
                "has_target": has_target,
            }
        )

    # Goals first (sorted by how close to the limit they are), then categories
    # with spend but no goal (sorted by spend, as configuration suggestions).
    items.sort(
        key=lambda item: (
            not item["has_target"],
            -(item["progress_percent"] or 0) if item["has_target"] else 0,
            -item["spent"],
        )
    )

    target_consumed = min(budgeted_spent_total, target_total)
    target_overage = max(budgeted_spent_total - target_total, Decimal("0"))
    target_remaining = max(target_total - budgeted_spent_total, Decimal("0"))
    progress_pct = float(budgeted_spent_total / target_total * 100) if target_total > 0 else None

    summary = {
        "target": float(target_total),
        "actual_spent": float(budgeted_spent_total),
        "future_spent": 0.0,
        "projected_spent": float(budgeted_spent_total),
        "invoice_spent": float(budgeted_spent_total),
        "target_consumed": float(target_consumed),
        "target_remaining": float(target_remaining),
        "target_overage": float(target_overage),
        "free_impact": 0.0,
        "unbudgeted_actual_spent": float(unbudgeted_spent_total),
        "unbudgeted_future_spent": 0.0,
        "unbudgeted_projected_spent": float(unbudgeted_spent_total),
        "unbudgeted_count": unbudgeted_count,
        "fixed_cost_matched_transaction_count": len(exclude_ids),
        "actual_progress_pct": progress_pct,
        "progress_pct": progress_pct,
        "goal_count": len(goals),
    }

    return {
        "year_month": year_month,
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "today": today.isoformat(),
        "summary": summary,
        "items": items,
        "eligible_categories": eligible_categories(),
    }
