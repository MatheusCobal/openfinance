from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import FixedCost, FixedCostCategory, FixedCostOverride
from app.services.expected_income import monthly_breakdown as expected_income_breakdown
from app.services.transaction_reports import stats_summary


class FixedCostValidationError(ValueError):
    pass


def _validate_month(year_month: str) -> None:
    try:
        year_str, month_str = year_month.split("-")
        year = int(year_str)
        month = int(month_str)
        if len(year_str) != 4 or len(month_str) != 2 or not (1 <= month <= 12):
            raise ValueError
        date(year, month, 1)
    except (ValueError, AttributeError):
        raise FixedCostValidationError("year_month must be in YYYY-MM format")


def _month_bounds(year_month: str) -> tuple[date, date]:
    _validate_month(year_month)
    year, month = (int(part) for part in year_month.split("-"))
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return date(year, month, 1), date.fromordinal(next_month.toordinal() - 1)


def _shift_year_month(year_month: str, months: int) -> str:
    _validate_month(year_month)
    year, month = (int(part) for part in year_month.split("-"))
    zero_based = year * 12 + (month - 1) + months
    return f"{zero_based // 12:04d}-{(zero_based % 12) + 1:02d}"


def _validate_amount(amount: Decimal, allow_zero: bool = False) -> None:
    if allow_zero:
        if amount < 0:
            raise FixedCostValidationError("amount must be non-negative")
    elif amount <= 0:
        raise FixedCostValidationError("amount must be positive")


def _validate_day(day: int) -> None:
    if not (1 <= day <= 31):
        raise FixedCostValidationError("due_day must be between 1 and 31")


def _validate_description(description: Optional[str]) -> str:
    if not description or not description.strip():
        raise FixedCostValidationError("description must not be empty")
    return description.strip()


def _serialize_category(category: FixedCostCategory) -> Dict[str, Any]:
    return {
        "id": category.id,
        "name": category.name,
        "color": category.color,
        "sort_order": category.sort_order,
    }


def _serialize_cost(cost: FixedCost, category: FixedCostCategory) -> Dict[str, Any]:
    return {
        "id": cost.id,
        "category_id": cost.category_id,
        "category_name": category.name,
        "category_color": category.color,
        "description": cost.description,
        "amount": float(cost.amount),
        "due_day": cost.due_day,
        "active": cost.active,
    }


def list_fixed_cost_categories(session: Session) -> List[Dict[str, Any]]:
    categories = session.exec(
        select(FixedCostCategory).order_by(
            FixedCostCategory.sort_order, FixedCostCategory.name
        )
    ).all()
    return [_serialize_category(category) for category in categories]


def create_fixed_cost_category(
    session: Session,
    name: str,
    color: str = "#64748b",
    sort_order: int = 0,
) -> Dict[str, Any]:
    name = _validate_description(name)
    category = FixedCostCategory(name=name, color=color, sort_order=sort_order)
    session.add(category)
    session.commit()
    session.refresh(category)
    return _serialize_category(category)


def update_fixed_cost_category(
    session: Session,
    category_id: int,
    name: Optional[str] = None,
    color: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    category = session.get(FixedCostCategory, category_id)
    if category is None:
        return None
    if name is not None:
        category.name = _validate_description(name)
    if color is not None:
        category.color = color
    if sort_order is not None:
        category.sort_order = sort_order
    session.add(category)
    session.commit()
    session.refresh(category)
    return _serialize_category(category)


def delete_fixed_cost_category(session: Session, category_id: int) -> bool:
    category = session.get(FixedCostCategory, category_id)
    if category is None:
        return False
    in_use = session.exec(
        select(FixedCost).where(FixedCost.category_id == category_id)
    ).first()
    if in_use is not None:
        raise FixedCostValidationError("category has fixed costs")
    session.delete(category)
    session.commit()
    return True


def list_fixed_costs(
    session: Session,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    categories = {
        category.id: category
        for category in session.exec(select(FixedCostCategory)).all()
    }
    query = select(FixedCost).order_by(FixedCost.due_day, FixedCost.description)
    if not include_inactive:
        query = query.where(FixedCost.active.is_(True))
    return [
        _serialize_cost(cost, categories[cost.category_id])
        for cost in session.exec(query).all()
        if cost.category_id in categories
    ]


def create_fixed_cost(
    session: Session,
    category_id: int,
    description: str,
    amount: Decimal,
    due_day: int,
) -> Optional[Dict[str, Any]]:
    description = _validate_description(description)
    _validate_amount(amount)
    _validate_day(due_day)
    category = session.get(FixedCostCategory, category_id)
    if category is None:
        return None
    cost = FixedCost(
        category_id=category_id,
        description=description,
        amount=amount,
        due_day=due_day,
    )
    session.add(cost)
    session.commit()
    session.refresh(cost)
    return _serialize_cost(cost, category)


def update_fixed_cost(
    session: Session,
    cost_id: int,
    category_id: Optional[int] = None,
    description: Optional[str] = None,
    amount: Optional[Decimal] = None,
    due_day: Optional[int] = None,
    active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    cost = session.get(FixedCost, cost_id)
    if cost is None:
        return None
    target_category_id = category_id if category_id is not None else cost.category_id
    category = session.get(FixedCostCategory, target_category_id)
    if category is None:
        return None
    if description is not None:
        cost.description = _validate_description(description)
    if amount is not None:
        _validate_amount(amount)
        cost.amount = amount
    if due_day is not None:
        _validate_day(due_day)
        cost.due_day = due_day
    if active is not None:
        cost.active = active
    cost.category_id = target_category_id
    session.add(cost)
    session.commit()
    session.refresh(cost)
    return _serialize_cost(cost, category)


def delete_fixed_cost(session: Session, cost_id: int) -> bool:
    cost = session.get(FixedCost, cost_id)
    if cost is None:
        return False
    overrides = session.exec(
        select(FixedCostOverride).where(FixedCostOverride.fixed_cost_id == cost_id)
    ).all()
    for override in overrides:
        session.delete(override)
    session.delete(cost)
    session.commit()
    return True


def monthly_breakdown(session: Session, year_month: str) -> Dict[str, Any]:
    _validate_month(year_month)
    costs = session.exec(
        select(FixedCost)
        .where(FixedCost.active.is_(True))
        .order_by(FixedCost.due_day, FixedCost.description)
    ).all()
    categories = {
        category.id: category
        for category in session.exec(select(FixedCostCategory)).all()
    }
    overrides = {
        override.fixed_cost_id: override
        for override in session.exec(
            select(FixedCostOverride).where(
                FixedCostOverride.year_month == year_month
            )
        ).all()
    }

    entries = []
    category_totals: dict[int, Decimal] = {}
    total = Decimal("0")
    for cost in costs:
        category = categories.get(cost.category_id)
        if category is None:
            continue
        override = overrides.get(cost.id)
        effective_amount = override.amount if override is not None else cost.amount
        total += effective_amount
        category_totals[cost.category_id] = (
            category_totals.get(cost.category_id, Decimal("0")) + effective_amount
        )
        entries.append(
            {
                "fixed_cost_id": cost.id,
                "category_id": category.id,
                "category_name": category.name,
                "category_color": category.color,
                "description": cost.description,
                "due_day": cost.due_day,
                "base_amount": float(cost.amount),
                "amount": float(effective_amount),
                "is_override": override is not None,
                "override_id": override.id if override is not None else None,
            }
        )

    category_rows = [
        {
            "category_id": category.id,
            "category_name": category.name,
            "category_color": category.color,
            "sort_order": category.sort_order,
            "total": float(category_totals.get(category.id, Decimal("0"))),
        }
        for category in sorted(
            categories.values(), key=lambda item: (item.sort_order, item.name)
        )
        if category.id in category_totals
    ]
    return {
        "year_month": year_month,
        "total": float(total),
        "categories": category_rows,
        "entries": entries,
    }


def upcoming_months(
    session: Session,
    start_year_month: str,
    months: int,
) -> List[Dict[str, Any]]:
    if not (1 <= months <= 24):
        raise FixedCostValidationError("months must be between 1 and 24")
    return [
        monthly_breakdown(session, _shift_year_month(start_year_month, offset))
        for offset in range(months)
    ]


def set_override(
    session: Session,
    cost_id: int,
    year_month: str,
    amount: Decimal,
) -> Optional[Dict[str, Any]]:
    _validate_month(year_month)
    _validate_amount(amount, allow_zero=True)
    cost = session.get(FixedCost, cost_id)
    if cost is None:
        return None
    existing = session.exec(
        select(FixedCostOverride).where(
            FixedCostOverride.fixed_cost_id == cost_id,
            FixedCostOverride.year_month == year_month,
        )
    ).first()
    if existing is None:
        existing = FixedCostOverride(
            fixed_cost_id=cost_id,
            year_month=year_month,
            amount=amount,
        )
    else:
        existing.amount = amount
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return {
        "id": existing.id,
        "fixed_cost_id": existing.fixed_cost_id,
        "year_month": existing.year_month,
        "amount": float(existing.amount),
    }


def delete_override(session: Session, cost_id: int, year_month: str) -> bool:
    _validate_month(year_month)
    existing = session.exec(
        select(FixedCostOverride).where(
            FixedCostOverride.fixed_cost_id == cost_id,
            FixedCostOverride.year_month == year_month,
        )
    ).first()
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def spending_capacity_summary(
    session: Session,
    year_month: str,
) -> Dict[str, Any]:
    first_day, last_day = _month_bounds(year_month)
    income = expected_income_breakdown(session, year_month)
    fixed = monthly_breakdown(session, year_month)
    invoice = stats_summary(session, first_day, last_day)

    expected_income_total = Decimal(str(income["total"]))
    fixed_cost_total = Decimal(str(fixed["total"]))
    card_invoice_total = Decimal(str(invoice["invoice_total"]))
    planned_after_fixed_costs = expected_income_total - fixed_cost_total
    remaining_after_invoice = planned_after_fixed_costs - card_invoice_total

    return {
        "year_month": year_month,
        "expected_income_total": float(expected_income_total),
        "fixed_cost_total": float(fixed_cost_total),
        "card_invoice_total": float(card_invoice_total),
        "invoice_mode": invoice["invoice_mode"],
        "planned_after_fixed_costs": float(planned_after_fixed_costs),
        "remaining_after_invoice": float(remaining_after_invoice),
        "fixed_costs": fixed,
        "expected_income": income,
    }
