from datetime import date
from typing import Optional, Set

from sqlmodel import Session


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
    fixed_cost_accounted_transaction_ids: Optional[Set[str]] = None,
):
    # 10D-A: variable budgets were coupled to the removed legacy financial
    # category system. Keep the response shape stable, but do not resolve or
    # group transactions until a 10D-C planning layer defines variable targets
    # on top of the Pluggy-based classification fields.
    if fixed_cost_accounted_transaction_ids is None:
        from app.services.fixed_costs import accounted_transaction_ids_for_month

        fixed_cost_accounted_transaction_ids = accounted_transaction_ids_for_month(
            session, year_month
        )
    fixed_cost_transaction_ids = set(fixed_cost_accounted_transaction_ids)

    return {
        "year_month": year_month,
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "today": today.isoformat(),
        "summary": {
            "target": 0.0,
            "actual_spent": 0.0,
            "future_spent": 0.0,
            "projected_spent": 0.0,
            "invoice_spent": 0.0,
            "target_consumed": 0.0,
            "target_remaining": 0.0,
            "target_overage": 0.0,
            "free_impact": 0.0,
            "unbudgeted_actual_spent": 0.0,
            "unbudgeted_future_spent": 0.0,
            "unbudgeted_projected_spent": 0.0,
            "unbudgeted_count": 0,
            "fixed_cost_matched_transaction_count": len(fixed_cost_transaction_ids),
            "actual_progress_pct": None,
            "progress_pct": None,
        },
        "items": [],
        "legacy_category_budget_removed": True,
        "todo": "TODO 10D-C: recreate variable budget targets on top of Pluggy-based classification.",
    }
