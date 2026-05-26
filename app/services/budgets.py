from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, Optional

from sqlmodel import Session, select

from app.categorization import CategoryResolver
from app.models import Budget, BudgetOverride, Transaction
from app.services.transactions import (
    SPENDING_ACCOUNT_TYPES,
    filter_ignored_transactions,
    filter_transactions_by_account_type,
)


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
    transactions = session.exec(
        select(Transaction).where(
            Transaction.date >= first_day,
            Transaction.date <= last_day,
        )
    ).all()
    transactions = filter_transactions_by_account_type(
        transactions,
        session,
        SPENDING_ACCOUNT_TYPES,
    )
    transactions = filter_ignored_transactions(
        transactions,
        session,
        include_ignored,
    )

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
        if target is not None and target > 0:
            total_target += target
            total_actual_spent += actual_spent
            total_future_spent += future_spent
            actual_progress_pct = (float(actual_spent) / float(target)) * 100
            progress_pct = (float(projected_spent) / float(target)) * 100
        else:
            unbudgeted_actual_spent += actual_spent
            unbudgeted_future_spent += future_spent
            unbudgeted_count += actual_count + future_count
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
            "unbudgeted_actual_spent": float(unbudgeted_actual_spent),
            "unbudgeted_future_spent": float(unbudgeted_future_spent),
            "unbudgeted_projected_spent": float(
                unbudgeted_actual_spent + unbudgeted_future_spent
            ),
            "unbudgeted_count": unbudgeted_count,
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
