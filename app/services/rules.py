from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from app.categorization import CategoryResolver
from app.categorization import normalize_description
from app.models import (
    BankCashflowExclusionRule,
    BankIncomeExclusionRule,
    Category,
    DescriptionCategoryRule,
    IgnoredDescriptionRule,
    Transaction,
)
from app.services.transactions import _non_duplicate_clause
from app.services.transactions import count_bank_income_exclusion_matches
from app.services.transactions import count_bank_cashflow_exclusion_matches
from app.services.transactions import discretionary_spend_transactions
from app.services.transactions import shift_month


class RuleValidationError(ValueError):
    pass


class RuleCategoryNotFoundError(LookupError):
    pass


CASHFLOW_DIRECTIONS = {"IN", "OUT", "ALL"}


def count_description_rule_matches(
    pattern_normalized: str,
    session: Session,
) -> int:
    return sum(
        1
        for tx in session.exec(select(Transaction).where(_non_duplicate_clause())).all()
        if pattern_normalized in normalize_description(tx.description)
    )


def list_bank_income_exclusion_rules(session: Session):
    rules = session.exec(
        select(BankIncomeExclusionRule).order_by(
            BankIncomeExclusionRule.pluggy_category,
            BankIncomeExclusionRule.pattern,
        )
    ).all()
    return [
        {
            **rule.model_dump(mode="json"),
            "affected_count": count_bank_income_exclusion_matches(rule, session),
        }
        for rule in rules
    ]


def _normalize_cashflow_direction(direction: Optional[str]) -> str:
    normalized = (direction or "ALL").strip().upper()
    if normalized not in CASHFLOW_DIRECTIONS:
        raise RuleValidationError("direction must be IN, OUT or ALL")
    return normalized


def list_bank_cashflow_exclusion_rules(session: Session):
    rules = session.exec(
        select(BankCashflowExclusionRule).order_by(
            BankCashflowExclusionRule.direction,
            BankCashflowExclusionRule.pluggy_category,
            BankCashflowExclusionRule.pattern,
        )
    ).all()
    return [
        {
            **rule.model_dump(mode="json"),
            "affected_count": count_bank_cashflow_exclusion_matches(
                rule,
                session,
            ),
        }
        for rule in rules
    ]


def upsert_bank_cashflow_exclusion_rule(
    session: Session,
    direction: Optional[str] = "ALL",
    pluggy_category: Optional[str] = None,
    pattern: Optional[str] = None,
):
    direction = _normalize_cashflow_direction(direction)
    pluggy_category = pluggy_category.strip() if pluggy_category else None
    pattern = pattern.strip() if pattern else None
    if bool(pluggy_category) == bool(pattern):
        raise RuleValidationError("Provide exactly one of pluggy_category or pattern")

    pattern_normalized = normalize_description(pattern) if pattern else None
    if pattern is not None and not pattern_normalized:
        raise RuleValidationError("pattern must not be empty")

    if pluggy_category is not None:
        rule = session.exec(
            select(BankCashflowExclusionRule).where(
                BankCashflowExclusionRule.direction == direction,
                BankCashflowExclusionRule.pluggy_category == pluggy_category,
            )
        ).first()
        if rule is None:
            rule = BankCashflowExclusionRule(
                direction=direction,
                pluggy_category=pluggy_category,
            )
    else:
        rule = session.exec(
            select(BankCashflowExclusionRule).where(
                BankCashflowExclusionRule.direction == direction,
                BankCashflowExclusionRule.pattern_normalized == pattern_normalized,
            )
        ).first()
        if rule is None:
            rule = BankCashflowExclusionRule(
                direction=direction,
                pattern=pattern,
                pattern_normalized=pattern_normalized,
            )
        else:
            rule.pattern = pattern

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return {
        **rule.model_dump(mode="json"),
        "affected_count": count_bank_cashflow_exclusion_matches(rule, session),
    }


def delete_bank_cashflow_exclusion_rule(session: Session, rule_id: int) -> None:
    rule = session.get(BankCashflowExclusionRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()


def upsert_bank_income_exclusion_rule(
    session: Session,
    pluggy_category: Optional[str] = None,
    pattern: Optional[str] = None,
):
    pluggy_category = pluggy_category.strip() if pluggy_category else None
    pattern = pattern.strip() if pattern else None
    if bool(pluggy_category) == bool(pattern):
        raise RuleValidationError("Provide exactly one of pluggy_category or pattern")

    pattern_normalized = normalize_description(pattern) if pattern else None
    if pattern is not None and not pattern_normalized:
        raise RuleValidationError("pattern must not be empty")

    if pluggy_category is not None:
        rule = session.exec(
            select(BankIncomeExclusionRule).where(
                BankIncomeExclusionRule.pluggy_category == pluggy_category
            )
        ).first()
        if rule is None:
            rule = BankIncomeExclusionRule(pluggy_category=pluggy_category)
    else:
        rule = session.exec(
            select(BankIncomeExclusionRule).where(
                BankIncomeExclusionRule.pattern_normalized == pattern_normalized
            )
        ).first()
        if rule is None:
            rule = BankIncomeExclusionRule(
                pattern=pattern,
                pattern_normalized=pattern_normalized,
            )
        else:
            rule.pattern = pattern

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return {
        **rule.model_dump(mode="json"),
        "affected_count": count_bank_income_exclusion_matches(rule, session),
    }


def delete_bank_income_exclusion_rule(session: Session, rule_id: int) -> None:
    rule = session.get(BankIncomeExclusionRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()


def upsert_description_category_rule(
    session: Session,
    pattern: str,
    category_id: int,
):
    pattern = pattern.strip()
    pattern_normalized = normalize_description(pattern)
    if not pattern_normalized:
        raise RuleValidationError("pattern must not be empty")

    category = session.get(Category, category_id)
    if category is None:
        raise RuleCategoryNotFoundError("category not found")

    rule = session.exec(
        select(DescriptionCategoryRule).where(
            DescriptionCategoryRule.pattern_normalized == pattern_normalized
        )
    ).first()
    if rule is None:
        rule = DescriptionCategoryRule(
            pattern=pattern,
            pattern_normalized=pattern_normalized,
            category_id=category_id,
        )
    else:
        rule.pattern = pattern
        rule.category_id = category_id
    session.add(rule)

    affected_count = count_description_rule_matches(pattern_normalized, session)
    session.commit()
    session.refresh(rule)
    return {
        "id": rule.id,
        "pattern": rule.pattern,
        "pattern_normalized": rule.pattern_normalized,
        "category_id": category.id,
        "category_name": category.name,
        "category_color": category.color,
        "affected_count": affected_count,
    }


def list_description_category_rules(session: Session):
    rules = session.exec(
        select(DescriptionCategoryRule).order_by(DescriptionCategoryRule.pattern)
    ).all()
    categories = {category.id: category for category in session.exec(select(Category)).all()}
    return [
        {
            "id": rule.id,
            "pattern": rule.pattern,
            "pattern_normalized": rule.pattern_normalized,
            "category_id": rule.category_id,
            "category_name": categories.get(rule.category_id).name
            if categories.get(rule.category_id)
            else None,
            "category_color": categories.get(rule.category_id).color
            if categories.get(rule.category_id)
            else None,
            "affected_count": count_description_rule_matches(rule.pattern_normalized, session),
        }
        for rule in rules
    ]


def delete_description_category_rule(session: Session, rule_id: int) -> None:
    rule = session.get(DescriptionCategoryRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()


def description_category_rule_suggestions(
    session: Session,
    months: int = 12,
    min_count: int = 2,
    limit: int = 10,
    today: Optional[date] = None,
):
    if not (1 <= months <= 24):
        raise RuleValidationError("months must be between 1 and 24")
    if not (2 <= min_count <= 50):
        raise RuleValidationError("min_count must be between 2 and 50")
    if not (1 <= limit <= 50):
        raise RuleValidationError("limit must be between 1 and 50")

    today = today if today is not None else date.today()
    current_month = date(today.year, today.month, 1)
    start_date = shift_month(current_month, -(months - 1))
    end_date = today
    resolver = CategoryResolver(session)
    existing_patterns = [
        rule.pattern_normalized
        for rule in session.exec(select(DescriptionCategoryRule)).all()
        if rule.pattern_normalized
    ]

    groups = defaultdict(
        lambda: {
            "sample_description": "",
            "transaction_count": 0,
            "total": Decimal("0"),
            "first_seen": None,
            "last_seen": None,
            "pluggy_categories": set(),
            "categories": defaultdict(int),
            "category_refs": {},
        }
    )

    for tx in discretionary_spend_transactions(
        session,
        start_date=start_date,
        end_date=end_date,
        include_ignored=False,
    ):
        normalized = normalize_description(tx.description)
        if len(normalized) < 3:
            continue
        if any(pattern in normalized for pattern in existing_patterns):
            continue

        group = groups[normalized]
        category = resolver.display_category(resolver.resolve(tx.category, tx.description))
        if not group["sample_description"]:
            group["sample_description"] = tx.description
        group["transaction_count"] += 1
        group["total"] += abs(tx.amount)
        group["first_seen"] = (
            tx.date if group["first_seen"] is None else min(group["first_seen"], tx.date)
        )
        group["last_seen"] = (
            tx.date if group["last_seen"] is None else max(group["last_seen"], tx.date)
        )
        if tx.category:
            group["pluggy_categories"].add(tx.category)
        group["categories"][category.id] += 1
        group["category_refs"][category.id] = category

    suggestions = []
    for pattern_normalized, group in groups.items():
        if group["transaction_count"] < min_count:
            continue
        category_id = max(
            group["categories"],
            key=lambda key: group["categories"][key],
        )
        category = group["category_refs"][category_id]
        suggestions.append(
            {
                "pattern": group["sample_description"],
                "pattern_normalized": pattern_normalized,
                "sample_description": group["sample_description"],
                "transaction_count": group["transaction_count"],
                "total": float(group["total"]),
                "first_seen": group["first_seen"].isoformat(),
                "last_seen": group["last_seen"].isoformat(),
                "current_category_id": category.id,
                "current_category_name": category.name,
                "current_category_color": category.color,
                "pluggy_categories": sorted(group["pluggy_categories"]),
            }
        )

    suggestions.sort(
        key=lambda item: (
            -item["transaction_count"],
            -item["total"],
            item["pattern_normalized"],
        )
    )
    return {
        "months": months,
        "min_count": min_count,
        "limit": limit,
        "suggestions": suggestions[:limit],
    }


def list_ignored_description_rules(session: Session):
    rules = session.exec(
        select(IgnoredDescriptionRule).order_by(IgnoredDescriptionRule.pattern)
    ).all()
    return [
        {
            "id": rule.id,
            "pattern": rule.pattern,
            "pattern_normalized": rule.pattern_normalized,
            "affected_count": count_description_rule_matches(rule.pattern_normalized, session),
        }
        for rule in rules
    ]


def delete_ignored_description_rule(session: Session, rule_id: int) -> None:
    rule = session.get(IgnoredDescriptionRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()


def upsert_ignored_description_rule(session: Session, pattern: str):
    pattern = pattern.strip()
    pattern_normalized = normalize_description(pattern)
    if not pattern_normalized:
        raise RuleValidationError("pattern must not be empty")

    rule = session.exec(
        select(IgnoredDescriptionRule).where(
            IgnoredDescriptionRule.pattern_normalized == pattern_normalized
        )
    ).first()
    if rule is None:
        rule = IgnoredDescriptionRule(
            pattern=pattern,
            pattern_normalized=pattern_normalized,
        )
    else:
        rule.pattern = pattern
    session.add(rule)

    affected_count = count_description_rule_matches(pattern_normalized, session)
    session.commit()
    session.refresh(rule)
    return {
        "id": rule.id,
        "pattern": rule.pattern,
        "pattern_normalized": rule.pattern_normalized,
        "affected_count": affected_count,
    }
