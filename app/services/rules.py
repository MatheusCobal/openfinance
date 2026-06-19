from typing import Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import (
    BankCashflowExclusionRule,
    BankIncomeExclusionRule,
    IgnoredDescriptionRule,
    Transaction,
)
from app.services.scoping import scope_query
from app.services.transactions import _non_duplicate_clause
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
    user_id: Optional[int] = None,
) -> int:
    return sum(
        1
        for tx in session.exec(
            scope_query(
                select(Transaction).where(_non_duplicate_clause()),
                Transaction.user_id,
                user_id,
            )
        ).all()
        if pattern_normalized in normalize_description(tx.description)
    )


def list_bank_income_exclusion_rules(session: Session, user_id: Optional[int] = None):
    rules = session.exec(
        scope_query(
            select(BankIncomeExclusionRule), BankIncomeExclusionRule.user_id, user_id
        ).order_by(
            BankIncomeExclusionRule.pluggy_category,
            BankIncomeExclusionRule.pattern,
        )
    ).all()
    return [
        {
            **rule.model_dump(mode="json"),
            "affected_count": count_bank_income_exclusion_matches(rule, session, user_id=user_id),
        }
        for rule in rules
    ]


def _normalize_cashflow_direction(direction: Optional[str]) -> str:
    normalized = (direction or "ALL").strip().upper()
    if normalized not in CASHFLOW_DIRECTIONS:
        raise RuleValidationError("direction must be IN, OUT or ALL")
    return normalized


def list_bank_cashflow_exclusion_rules(session: Session, user_id: Optional[int] = None):
    rules = session.exec(
        scope_query(
            select(BankCashflowExclusionRule), BankCashflowExclusionRule.user_id, user_id
        ).order_by(
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
                user_id=user_id,
            ),
        }
        for rule in rules
    ]


def upsert_bank_cashflow_exclusion_rule(
    session: Session,
    direction: Optional[str] = "ALL",
    pluggy_category: Optional[str] = None,
    pattern: Optional[str] = None,
    user_id: Optional[int] = None,
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
            scope_query(
                select(BankCashflowExclusionRule).where(
                    BankCashflowExclusionRule.direction == direction,
                    BankCashflowExclusionRule.pluggy_category == pluggy_category,
                ),
                BankCashflowExclusionRule.user_id,
                user_id,
            )
        ).first()
        if rule is None:
            rule = BankCashflowExclusionRule(
                direction=direction,
                pluggy_category=pluggy_category,
                user_id=user_id,
            )
    else:
        rule = session.exec(
            scope_query(
                select(BankCashflowExclusionRule).where(
                    BankCashflowExclusionRule.direction == direction,
                    BankCashflowExclusionRule.pattern_normalized == pattern_normalized,
                ),
                BankCashflowExclusionRule.user_id,
                user_id,
            )
        ).first()
        if rule is None:
            rule = BankCashflowExclusionRule(
                direction=direction,
                pattern=pattern,
                pattern_normalized=pattern_normalized,
                user_id=user_id,
            )
        else:
            rule.pattern = pattern

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return {
        **rule.model_dump(mode="json"),
        "affected_count": count_bank_cashflow_exclusion_matches(rule, session, user_id=user_id),
    }


def delete_bank_cashflow_exclusion_rule(
    session: Session,
    rule_id: int,
    user_id: Optional[int] = None,
) -> None:
    rule = session.get(BankCashflowExclusionRule, rule_id)
    if rule is not None and (user_id is None or rule.user_id == user_id):
        session.delete(rule)
        session.commit()


def upsert_bank_income_exclusion_rule(
    session: Session,
    pluggy_category: Optional[str] = None,
    pattern: Optional[str] = None,
    user_id: Optional[int] = None,
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
            scope_query(
                select(BankIncomeExclusionRule).where(
                    BankIncomeExclusionRule.pluggy_category == pluggy_category
                ),
                BankIncomeExclusionRule.user_id,
                user_id,
            )
        ).first()
        if rule is None:
            rule = BankIncomeExclusionRule(pluggy_category=pluggy_category, user_id=user_id)
    else:
        rule = session.exec(
            scope_query(
                select(BankIncomeExclusionRule).where(
                    BankIncomeExclusionRule.pattern_normalized == pattern_normalized
                ),
                BankIncomeExclusionRule.user_id,
                user_id,
            )
        ).first()
        if rule is None:
            rule = BankIncomeExclusionRule(
                pattern=pattern,
                pattern_normalized=pattern_normalized,
                user_id=user_id,
            )
        else:
            rule.pattern = pattern

    session.add(rule)
    session.commit()
    session.refresh(rule)
    return {
        **rule.model_dump(mode="json"),
        "affected_count": count_bank_income_exclusion_matches(rule, session, user_id=user_id),
    }


def delete_bank_income_exclusion_rule(
    session: Session,
    rule_id: int,
    user_id: Optional[int] = None,
) -> None:
    rule = session.get(BankIncomeExclusionRule, rule_id)
    if rule is not None and (user_id is None or rule.user_id == user_id):
        session.delete(rule)
        session.commit()


def list_ignored_description_rules(session: Session, user_id: Optional[int] = None):
    rules = session.exec(
        scope_query(
            select(IgnoredDescriptionRule), IgnoredDescriptionRule.user_id, user_id
        ).order_by(IgnoredDescriptionRule.pattern)
    ).all()
    return [
        {
            "id": rule.id,
            "pattern": rule.pattern,
            "pattern_normalized": rule.pattern_normalized,
            "affected_count": count_description_rule_matches(
                rule.pattern_normalized, session, user_id=user_id
            ),
        }
        for rule in rules
    ]


def delete_ignored_description_rule(
    session: Session,
    rule_id: int,
    user_id: Optional[int] = None,
) -> None:
    rule = session.get(IgnoredDescriptionRule, rule_id)
    if rule is not None and (user_id is None or rule.user_id == user_id):
        session.delete(rule)
        session.commit()


def upsert_ignored_description_rule(session: Session, pattern: str, user_id: Optional[int] = None):
    pattern = pattern.strip()
    pattern_normalized = normalize_description(pattern)
    if not pattern_normalized:
        raise RuleValidationError("pattern must not be empty")

    rule = session.exec(
        scope_query(
            select(IgnoredDescriptionRule).where(
                IgnoredDescriptionRule.pattern_normalized == pattern_normalized
            ),
            IgnoredDescriptionRule.user_id,
            user_id,
        )
    ).first()
    if rule is None:
        rule = IgnoredDescriptionRule(
            pattern=pattern,
            pattern_normalized=pattern_normalized,
            user_id=user_id,
        )
    else:
        rule.pattern = pattern
    session.add(rule)

    affected_count = count_description_rule_matches(pattern_normalized, session, user_id=user_id)
    session.commit()
    session.refresh(rule)
    return {
        "id": rule.id,
        "pattern": rule.pattern,
        "pattern_normalized": rule.pattern_normalized,
        "affected_count": affected_count,
    }
