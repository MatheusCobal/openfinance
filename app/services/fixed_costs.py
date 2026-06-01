from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import (
    FixedCost,
    FixedCostCategory,
    FixedCostOverride,
    FixedCostTransactionMatch,
    Transaction,
)
from app.services.fixed_cost_defaults import (
    DEFAULT_FIXED_COST_CATEGORIES,
    FIXED_COST_TEMPLATES,
)


class FixedCostValidationError(ValueError):
    pass


MAX_CUSTOM_FIXED_COST_CATEGORIES = 5
AMOUNT_MATCH_TOLERANCE_PCT = Decimal("0.15")
AMOUNT_MATCH_TOLERANCE_MIN = Decimal("10")
DUE_SOON_DAYS = 3


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


def _date_for_month_day(year_month: str, day: int) -> date:
    first_day, last_day = _month_bounds(year_month)
    return date(first_day.year, first_day.month, min(day, last_day.day))


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


def _token_set(value: str) -> set[str]:
    stopwords = {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "com",
        "pagamento",
        "compra",
        "pix",
        "qr",
        "code",
    }
    return {
        token
        for token in normalize_description(value).split()
        if len(token) >= 3 and token not in stopwords
    }


def _serialize_category(category: FixedCostCategory) -> Dict[str, Any]:
    return {
        "id": category.id,
        "name": category.name,
        "color": category.color,
        "sort_order": category.sort_order,
        "is_default": category.is_default,
    }


def _serialize_cost(cost: FixedCost, category: FixedCostCategory) -> Dict[str, Any]:
    return {
        "id": cost.id,
        "category_id": cost.category_id,
        "category_name": category.name,
        "category_color": category.color,
        "category_is_default": category.is_default,
        "description": cost.description,
        "amount": float(cost.amount),
        "due_day": cost.due_day,
        "active": cost.active,
    }


def _serialize_transaction_match(tx: Transaction) -> Dict[str, Any]:
    return {
        "id": tx.id,
        "date": tx.date.isoformat(),
        "amount": float(tx.amount),
        "amount_abs": float(abs(tx.amount)),
        "description": tx.description,
        "pluggy_category": tx.category,
    }


def _serialize_fixed_cost_transaction_match(
    match: FixedCostTransactionMatch,
    cost: Optional[FixedCost] = None,
    tx: Optional[Transaction] = None,
) -> Dict[str, Any]:
    return {
        "id": match.id,
        "fixed_cost_id": match.fixed_cost_id,
        "fixed_cost_description": cost.description if cost is not None else None,
        "transaction_id": match.transaction_id,
        "year_month": match.year_month,
        "created_at": match.created_at.isoformat(),
        "transaction": _serialize_transaction_match(tx) if tx is not None else None,
    }


def _sync_default_categories(session: Session) -> None:
    existing_by_name = {
        category.name: category
        for category in session.exec(select(FixedCostCategory)).all()
    }
    default_names = {category["name"] for category in DEFAULT_FIXED_COST_CATEGORIES}
    changed = False
    for source in DEFAULT_FIXED_COST_CATEGORIES:
        existing = existing_by_name.get(source["name"])
        if existing is None:
            session.add(
                FixedCostCategory(
                    name=source["name"],
                    color=source["color"],
                    sort_order=source["sort_order"],
                    is_default=True,
                )
            )
            changed = True
            continue
        if (
            existing.color != source["color"]
            or existing.sort_order != source["sort_order"]
            or not existing.is_default
        ):
            existing.color = source["color"]
            existing.sort_order = source["sort_order"]
            existing.is_default = True
            session.add(existing)
            changed = True
    stale_defaults = [
        category
        for category in existing_by_name.values()
        if category.is_default and category.name not in default_names
    ]
    for category in stale_defaults:
        in_use = session.exec(
            select(FixedCost).where(FixedCost.category_id == category.id)
        ).first()
        if in_use is None:
            session.delete(category)
        else:
            category.is_default = False
            session.add(category)
        changed = True
    if changed:
        session.commit()


def _custom_category_count(session: Session) -> int:
    return len(
        session.exec(
            select(FixedCostCategory).where(
                FixedCostCategory.is_default.is_(False)
            )
        ).all()
    )


def _categories_by_name(session: Session) -> dict[str, FixedCostCategory]:
    _sync_default_categories(session)
    return {
        category.name: category
        for category in session.exec(select(FixedCostCategory)).all()
    }


def list_fixed_cost_templates(session: Session) -> List[Dict[str, Any]]:
    categories_by_name = _categories_by_name(session)
    return [
        {
            **template,
            "category_id": categories_by_name.get(template["category_name"]).id
            if template["category_name"] in categories_by_name
            else None,
        }
        for template in FIXED_COST_TEMPLATES
    ]


def list_fixed_cost_categories(session: Session) -> List[Dict[str, Any]]:
    _sync_default_categories(session)
    categories = session.exec(
        select(FixedCostCategory).order_by(
            FixedCostCategory.is_default.desc(),
            FixedCostCategory.sort_order,
            FixedCostCategory.name,
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
    _sync_default_categories(session)
    existing = session.exec(
        select(FixedCostCategory).where(FixedCostCategory.name == name)
    ).first()
    if existing is not None:
        raise FixedCostValidationError("category already exists")
    if _custom_category_count(session) >= MAX_CUSTOM_FIXED_COST_CATEGORIES:
        raise FixedCostValidationError("custom category limit reached")
    category = FixedCostCategory(
        name=name,
        color=color,
        sort_order=sort_order,
        is_default=False,
    )
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
        if category.is_default:
            raise FixedCostValidationError("default categories cannot be renamed")
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
    if category.is_default:
        raise FixedCostValidationError("default categories cannot be deleted")
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
    _sync_default_categories(session)
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
    _sync_default_categories(session)
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


def create_fixed_cost_from_transaction(
    session: Session,
    transaction_id: str,
    category_id: Optional[int] = None,
    description: Optional[str] = None,
    amount: Optional[Decimal] = None,
    due_day: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    tx = session.get(Transaction, transaction_id)
    if tx is None:
        return None
    _sync_default_categories(session)
    categories_by_name = _categories_by_name(session)
    fallback_category = _suggest_category_for_transaction(tx, categories_by_name)
    target_category_id = category_id or (fallback_category.id if fallback_category else None)
    if target_category_id is None:
        return None
    return create_fixed_cost(
        session,
        category_id=target_category_id,
        description=description or tx.description,
        amount=amount or abs(tx.amount),
        due_day=due_day or tx.date.day,
    )


def _suggest_category_for_transaction(
    tx: Transaction,
    categories_by_name: dict[str, FixedCostCategory],
) -> Optional[FixedCostCategory]:
    tx_tokens = _token_set(f"{tx.description} {tx.category or ''}")
    for template in FIXED_COST_TEMPLATES:
        template_tokens = _token_set(
            f"{template['label']} {template['description']} {template['category_name']}"
        )
        if tx_tokens & template_tokens:
            category = categories_by_name.get(template["category_name"])
            if category is not None:
                return category
    return next(iter(categories_by_name.values()), None)


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
    _sync_default_categories(session)
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
    matches = session.exec(
        select(FixedCostTransactionMatch).where(
            FixedCostTransactionMatch.fixed_cost_id == cost_id
        )
    ).all()
    overrides = session.exec(
        select(FixedCostOverride).where(FixedCostOverride.fixed_cost_id == cost_id)
    ).all()
    for match in matches:
        session.delete(match)
    for override in overrides:
        session.delete(override)
    session.delete(cost)
    session.commit()
    return True


def _transaction_month(tx: Transaction) -> str:
    return tx.date.strftime("%Y-%m")


def _matches_for_month(
    session: Session,
    year_month: str,
) -> list[FixedCostTransactionMatch]:
    _validate_month(year_month)
    return session.exec(
        select(FixedCostTransactionMatch).where(
            FixedCostTransactionMatch.year_month == year_month
        )
    ).all()


def _transactions_by_id(
    session: Session,
    transaction_ids: set[str],
) -> dict[str, Transaction]:
    if not transaction_ids:
        return {}
    return {
        tx.id: tx
        for tx in session.exec(
            select(Transaction).where(Transaction.id.in_(transaction_ids))
        ).all()
    }


def list_fixed_cost_transaction_matches(
    session: Session,
    year_month: str,
) -> List[Dict[str, Any]]:
    matches = _matches_for_month(session, year_month)
    transactions = _transactions_by_id(
        session, {match.transaction_id for match in matches}
    )
    costs = {
        cost.id: cost
        for cost in session.exec(
            select(FixedCost).where(
                FixedCost.id.in_({match.fixed_cost_id for match in matches})
            )
        ).all()
    } if matches else {}
    return [
        _serialize_fixed_cost_transaction_match(
            match,
            costs.get(match.fixed_cost_id),
            transactions.get(match.transaction_id),
        )
        for match in sorted(matches, key=lambda item: item.created_at)
    ]


def create_fixed_cost_transaction_match(
    session: Session,
    fixed_cost_id: int,
    transaction_id: str,
    year_month: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    cost = session.get(FixedCost, fixed_cost_id)
    tx = session.get(Transaction, transaction_id)
    if cost is None or tx is None:
        return None

    target_month = year_month or _transaction_month(tx)
    _validate_month(target_month)
    if _transaction_month(tx) != target_month:
        raise FixedCostValidationError("transaction date must be in year_month")

    existing_for_transaction = session.exec(
        select(FixedCostTransactionMatch).where(
            FixedCostTransactionMatch.transaction_id == transaction_id
        )
    ).first()
    if existing_for_transaction is not None:
        if (
            existing_for_transaction.fixed_cost_id == fixed_cost_id
            and existing_for_transaction.year_month == target_month
        ):
            return _serialize_fixed_cost_transaction_match(
                existing_for_transaction,
                cost,
                tx,
            )
        raise FixedCostValidationError("transaction already matched to fixed cost")

    existing_for_cost_month = session.exec(
        select(FixedCostTransactionMatch).where(
            FixedCostTransactionMatch.fixed_cost_id == fixed_cost_id,
            FixedCostTransactionMatch.year_month == target_month,
        )
    ).first()
    if existing_for_cost_month is not None:
        raise FixedCostValidationError("fixed cost already matched for this month")

    match = FixedCostTransactionMatch(
        fixed_cost_id=fixed_cost_id,
        transaction_id=transaction_id,
        year_month=target_month,
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return _serialize_fixed_cost_transaction_match(match, cost, tx)


def delete_fixed_cost_transaction_match(session: Session, match_id: int) -> bool:
    match = session.get(FixedCostTransactionMatch, match_id)
    if match is None:
        return False
    session.delete(match)
    session.commit()
    return True


def _find_matching_transaction(
    cost: FixedCost,
    amount: Decimal,
    transactions: list[Transaction],
) -> Optional[Transaction]:
    cost_tokens = _token_set(cost.description)
    tolerance = max(amount * AMOUNT_MATCH_TOLERANCE_PCT, AMOUNT_MATCH_TOLERANCE_MIN)
    candidates = []
    for tx in transactions:
        tx_amount = abs(tx.amount)
        amount_delta = abs(tx_amount - amount)
        if amount_delta > tolerance:
            continue
        tx_tokens = _token_set(tx.description)
        overlap = len(cost_tokens & tx_tokens)
        if cost_tokens and overlap == 0:
            continue
        candidates.append((overlap, amount_delta, tx.date, tx))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return candidates[0][3]


def _status_for_cost(
    due_date: date,
    matched_transaction: Optional[Transaction],
    today: date,
) -> str:
    if matched_transaction is not None:
        return "paid"
    if due_date < date(today.year, today.month, 1):
        return "unconfirmed"
    if due_date < today:
        return "overdue"
    if due_date <= today + timedelta(days=DUE_SOON_DAYS):
        return "due_soon"
    return "scheduled"


def monthly_breakdown(session: Session, year_month: str) -> Dict[str, Any]:
    _validate_month(year_month)
    today = date.today()
    first_day, last_day = _month_bounds(year_month)
    _sync_default_categories(session)
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
    month_transactions = session.exec(
        select(Transaction).where(
            Transaction.date >= first_day,
            Transaction.date <= last_day,
        )
    ).all()
    manual_matches = _matches_for_month(session, year_month)
    manual_transactions = _transactions_by_id(
        session, {match.transaction_id for match in manual_matches}
    )
    manual_by_cost: dict[int, tuple[FixedCostTransactionMatch, Transaction]] = {}
    for match in manual_matches:
        tx = manual_transactions.get(match.transaction_id)
        if tx is not None:
            manual_by_cost[match.fixed_cost_id] = (match, tx)
    manual_transaction_ids = set(manual_transactions.keys())
    auto_match_transactions = [
        tx for tx in month_transactions if tx.id not in manual_transaction_ids
    ]

    entries = []
    category_totals: dict[int, Decimal] = {}
    total = Decimal("0")
    actual_total = Decimal("0")
    pending_total = Decimal("0")
    variance_total = Decimal("0")
    positive_variance_total = Decimal("0")
    negative_variance_total = Decimal("0")
    reserved_or_actual_total = Decimal("0")
    paid_count = 0
    pending_count = 0
    for cost in costs:
        category = categories.get(cost.category_id)
        if category is None:
            continue
        override = overrides.get(cost.id)
        effective_amount = override.amount if override is not None else cost.amount
        due_date = _date_for_month_day(year_month, cost.due_day)
        manual_match = None
        manual_cost_match = manual_by_cost.get(cost.id)
        if manual_cost_match is not None:
            manual_match, matched_transaction = manual_cost_match
            match_source = "manual"
        else:
            matched_transaction = _find_matching_transaction(
                cost, effective_amount, auto_match_transactions
            )
            match_source = "auto" if matched_transaction is not None else None
        status = _status_for_cost(due_date, matched_transaction, today)

        # Plan-vs-actual fields. When a transaction is matched the bill is
        # considered "paid": the actual amount drives availability and any
        # difference vs the planned amount becomes a variance (positive =
        # overshoot reducing availability, negative = release back).
        # When unmatched the planned amount stays reserved as the pending
        # obligation.
        if matched_transaction is not None:
            actual_amount = abs(matched_transaction.amount)
            pending_amount = Decimal("0")
            variance = actual_amount - effective_amount
            reserved_or_actual_amount = actual_amount
            paid_count += 1
        else:
            actual_amount = Decimal("0")
            pending_amount = effective_amount
            variance = Decimal("0")
            reserved_or_actual_amount = effective_amount
            pending_count += 1

        total += effective_amount
        actual_total += actual_amount
        pending_total += pending_amount
        variance_total += variance
        if variance > 0:
            positive_variance_total += variance
        elif variance < 0:
            negative_variance_total += -variance
        reserved_or_actual_total += reserved_or_actual_amount

        category_totals[cost.category_id] = (
            category_totals.get(cost.category_id, Decimal("0")) + effective_amount
        )
        entries.append(
            {
                "fixed_cost_id": cost.id,
                "category_id": category.id,
                "category_name": category.name,
                "category_color": category.color,
                "category_is_default": category.is_default,
                "description": cost.description,
                "due_day": cost.due_day,
                "base_amount": float(cost.amount),
                "amount": float(effective_amount),
                "planned_amount": float(effective_amount),
                "actual_amount": float(actual_amount),
                "pending_amount": float(pending_amount),
                "variance": float(variance),
                "reserved_or_actual_amount": float(reserved_or_actual_amount),
                "is_override": override is not None,
                "override_id": override.id if override is not None else None,
                "due_date": due_date.isoformat(),
                "status": status,
                "match_source": match_source,
                "fixed_cost_transaction_match_id": (
                    manual_match.id if manual_match is not None else None
                ),
                "matched_transaction": _serialize_transaction_match(matched_transaction)
                if matched_transaction is not None
                else None,
            }
        )

    category_rows = [
        {
            "category_id": category.id,
            "category_name": category.name,
            "category_color": category.color,
            "category_is_default": category.is_default,
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
        "planned_total": float(total),
        "actual_total": float(actual_total),
        "pending_total": float(pending_total),
        "variance_total": float(variance_total),
        "positive_variance_total": float(positive_variance_total),
        "negative_variance_total": float(negative_variance_total),
        "reserved_or_actual_total": float(reserved_or_actual_total),
        "paid_count": paid_count,
        "pending_count": pending_count,
        "categories": category_rows,
        "entries": entries,
    }


def accounted_transaction_ids_for_month(
    session: Session,
    year_month: str,
    today: Optional[date] = None,
) -> set[str]:
    """Transactions already "spoken for" by a fixed cost in ``year_month``.

    Returns the UNION of:
      - Manual ``FixedCostTransactionMatch`` rows for the month (matches the
        user explicitly persisted).
      - Auto-detected matches that ``monthly_breakdown`` finds by description +
        amount similarity (``match_source == "auto"`` entries).

    Any caller that wants to avoid double-counting a fixed cost — variable
    budget consumption, discretionary invoice, unbudgeted spending — must
    consult this set, not ``FixedCostTransactionMatch`` alone. The auto-detected
    ones don't exist in the DB until the user confirms them, so a SELECT on
    that table would miss them and let the same transaction reduce the
    available-to-spend twice.
    """
    breakdown = monthly_breakdown(session, year_month)
    ids: set[str] = set()
    for entry in breakdown["entries"]:
        matched = entry.get("matched_transaction")
        if matched and matched.get("id"):
            ids.add(matched["id"])
    return ids


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
