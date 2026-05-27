from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, Optional

from sqlmodel import Session, select

from app.categorization import CategoryResolver
from app.models import (
    Budget,
    BudgetOverride,
    FixedCost,
    FixedCostTransactionMatch,
)
from app.services.transactions import discretionary_spend_transactions


def budget_status(progress_pct: Optional[float]) -> Optional[str]:
    if progress_pct is None:
        return None
    if progress_pct >= 100:
        return "over"
    if progress_pct >= 80:
        return "warning"
    return "ok"


def budget_progress_summary(
    session: Session,
    year_month: str,
    first_day: date,
    last_day: date,
    today: date,
    include_ignored: bool = False,
):
    resolver = CategoryResolver(session)
    # NOTE: now includes BANK outflows (PIX/débito) — previously only
    # CREDIT purchases were tracked, which made debit/PIX spending
    # invisible to the budget cards.
    transactions = discretionary_spend_transactions(
        session,
        start_date=first_day,
        end_date=last_day,
        include_ignored=include_ignored,
    )
    active_fixed_cost_ids = set(
        session.exec(
            select(FixedCost.id).where(FixedCost.active.is_(True))
        ).all()
    )
    fixed_cost_transaction_ids = set()
    if active_fixed_cost_ids:
        fixed_cost_transaction_ids = set(
            session.exec(
                select(FixedCostTransactionMatch.transaction_id).where(
                    FixedCostTransactionMatch.year_month == year_month,
                    FixedCostTransactionMatch.fixed_cost_id.in_(
                        active_fixed_cost_ids
                    ),
                )
            ).all()
        )
    if fixed_cost_transaction_ids:
        transactions = [
            tx for tx in transactions if tx.id not in fixed_cost_transaction_ids
        ]

    actual_spent_by_category: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    future_spent_by_category: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    actual_counts_by_category: Dict[int, int] = defaultdict(int)
    future_counts_by_category: Dict[int, int] = defaultdict(int)
    for tx in transactions:
        cat = resolver.display_category(resolver.resolve(tx.category, tx.description))
        amount = abs(tx.amount)
        if tx.date <= today:
            actual_spent_by_category[cat.id] += amount
            actual_counts_by_category[cat.id] += 1
        else:
            future_spent_by_category[cat.id] += amount
            future_counts_by_category[cat.id] += 1

    budgets = {budget.category_id: budget for budget in session.exec(select(Budget)).all()}
    overrides = {
        budget.category_id: budget
        for budget in session.exec(
            select(BudgetOverride).where(BudgetOverride.year_month == year_month)
        ).all()
    }

    items = []
    total_target = Decimal("0")
    total_actual_spent = Decimal("0")
    total_future_spent = Decimal("0")
    total_target_consumed = Decimal("0")
    total_target_remaining = Decimal("0")
    total_target_overage = Decimal("0")
    total_free_impact = Decimal("0")
    unbudgeted_actual_spent = Decimal("0")
    unbudgeted_future_spent = Decimal("0")
    unbudgeted_count = 0
    for cat in resolver.all_top_level_categories():
        default_target = (
            budgets[cat.id].monthly_target if cat.id in budgets else None
        )
        month_target = (
            overrides[cat.id].monthly_target if cat.id in overrides else None
        )
        target = month_target if month_target is not None else default_target
        target_scope = (
            "month"
            if month_target is not None
            else "default"
            if default_target is not None
            else None
        )
        if target is not None and target <= 0:
            target = None
            target_scope = None

        actual_spent = actual_spent_by_category[cat.id]
        future_spent = future_spent_by_category[cat.id]
        projected_spent = actual_spent + future_spent
        actual_count = actual_counts_by_category[cat.id]
        future_count = future_counts_by_category[cat.id]

        actual_progress_pct = None
        progress_pct = None
        target_consumed = Decimal("0")
        target_remaining = None
        target_overage = Decimal("0")
        free_impact = projected_spent
        if target is not None and target > 0:
            total_target += target
            total_actual_spent += actual_spent
            total_future_spent += future_spent
            target_consumed = min(projected_spent, target)
            target_remaining = max(target - projected_spent, Decimal("0"))
            target_overage = max(projected_spent - target, Decimal("0"))
            free_impact = target_overage
            total_target_consumed += target_consumed
            total_target_remaining += target_remaining
            total_target_overage += target_overage
            actual_progress_pct = (float(actual_spent) / float(target)) * 100
            progress_pct = (float(projected_spent) / float(target)) * 100
        else:
            unbudgeted_actual_spent += actual_spent
            unbudgeted_future_spent += future_spent
            unbudgeted_count += actual_count + future_count
        total_free_impact += free_impact
        items.append(
            {
                "category_id": cat.id,
                "category_name": cat.name,
                "category_color": cat.color,
                "category_sort_order": cat.sort_order,
                "default_target": (
                    float(default_target)
                    if default_target is not None and default_target > 0
                    else None
                ),
                "target": float(target) if target is not None else None,
                "target_scope": target_scope,
                "actual_spent": float(actual_spent),
                "future_spent": float(future_spent),
                "projected_spent": float(projected_spent),
                "spent": float(projected_spent),
                "invoice_spent": float(projected_spent),
                "target_consumed": float(target_consumed),
                "remaining_target": (
                    float(target_remaining) if target_remaining is not None else None
                ),
                "overage": float(target_overage),
                "free_impact": float(free_impact),
                "actual_count": actual_count,
                "future_count": future_count,
                "count": actual_count + future_count,
                "actual_progress_pct": actual_progress_pct,
                "progress_pct": progress_pct,
                "actual_status": budget_status(actual_progress_pct),
                "status": budget_status(progress_pct),
            }
        )

    items.sort(
        key=lambda item: (
            item["target"] is None,
            item["category_sort_order"],
        )
    )

    return {
        "year_month": year_month,
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "today": today.isoformat(),
        "summary": {
            "target": float(total_target),
            "actual_spent": float(total_actual_spent),
            "future_spent": float(total_future_spent),
            "projected_spent": float(total_actual_spent + total_future_spent),
            "invoice_spent": float(total_actual_spent + total_future_spent),
            "target_consumed": float(total_target_consumed),
            "target_remaining": float(total_target_remaining),
            "target_overage": float(total_target_overage),
            "free_impact": float(total_free_impact),
            "unbudgeted_actual_spent": float(unbudgeted_actual_spent),
            "unbudgeted_future_spent": float(unbudgeted_future_spent),
            "unbudgeted_projected_spent": float(
                unbudgeted_actual_spent + unbudgeted_future_spent
            ),
            "unbudgeted_count": unbudgeted_count,
            "fixed_cost_matched_transaction_count": len(fixed_cost_transaction_ids),
            "actual_progress_pct": (
                (float(total_actual_spent) / float(total_target)) * 100
                if total_target > 0
                else None
            ),
            "progress_pct": (
                (float(total_actual_spent + total_future_spent) / float(total_target))
                * 100
                if total_target > 0
                else None
            ),
        },
        "items": items,
    }


