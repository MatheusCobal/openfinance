from typing import Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import (
    BankCashflowExclusionRule,
    BankIncomeExclusionRule,
    Category,
    DescriptionCategoryRule,
    IgnoredDescriptionRule,
    Transaction,
)
from app.services.transactions import count_bank_income_exclusion_matches
from app.services.transactions import count_bank_cashflow_exclusion_matches


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
        for tx in session.exec(select(Transaction)).all()
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
                BankCashflowExclusionRule.pattern_normalized
                == pattern_normalized,
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
    categories = {
        category.id: category
        for category in session.exec(select(Category)).all()
    }
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
            "affected_count": count_description_rule_matches(
                rule.pattern_normalized, session
            ),
        }
        for rule in rules
    ]


def delete_description_category_rule(session: Session, rule_id: int) -> None:
    rule = session.get(DescriptionCategoryRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()


def list_ignored_description_rules(session: Session):
    rules = session.exec(
        select(IgnoredDescriptionRule).order_by(IgnoredDescriptionRule.pattern)
    ).all()
    return [
        {
            "id": rule.id,
            "pattern": rule.pattern,
            "pattern_normalized": rule.pattern_normalized,
            "affected_count": count_description_rule_matches(
                rule.pattern_normalized, session
            ),
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
