"""User-defined classification rules (10D-D).

A thin CRUD + preview layer over ``UserClassificationRule`` plus a compiler
that turns persisted rows into DB-free ``CompiledUserRule`` objects the
classifier can match against.

Priority contract (see classify_input):

    manual override  >  user rule  >  Pluggy rule  >  system rule  >  fallback

User rules only ever change classification fields. Raw Pluggy data and
financial fields are never read-modified here.
"""

import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.categorization import normalize_description
from app.models import Account, Transaction, UserClassificationRule
from app.services.transaction_classifier import (
    ACCOUNT_TYPE_SCOPES,
    AMOUNT_SIGNS,
    CASHFLOW_TYPES,
    IGNORED_CASHFLOW_TYPES,
    INTERNAL_CATEGORIES,
    ClassificationInput,
    CompiledUserRule,
    _user_rule_matches,
    normalize_pluggy_value,
    serialize_transaction_classification,
)
from app.services.transactions import _non_duplicate_clause

# Content matchers; at least one must be set so a rule can never match the
# whole portfolio. account_type_scope / amount_sign are refinements, not
# standalone criteria.
_CONTENT_MATCH_FIELDS = (
    "match_pluggy_category",
    "match_pluggy_subcategory",
    "match_pluggy_type",
    "match_merchant",
    "match_description",
)

PREVIEW_EXAMPLE_LIMIT = 20


class UserRuleValidationError(ValueError):
    pass


class UserRuleNotFoundError(LookupError):
    pass


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def _resolved_ignored_from_totals(
    cashflow_type: str,
    ignored_from_totals: Optional[bool],
) -> bool:
    if ignored_from_totals is not None:
        return bool(ignored_from_totals)
    return cashflow_type in IGNORED_CASHFLOW_TYPES


def compile_rule(rule: UserClassificationRule) -> CompiledUserRule:
    """Turn a persisted rule into the matchable form the classifier consumes."""
    return CompiledUserRule(
        rule_id=rule.id,
        priority=rule.priority,
        account_type_scope=(rule.account_type_scope or "ALL").upper(),
        match_pluggy_category=normalize_pluggy_value(rule.match_pluggy_category),
        match_pluggy_subcategory=normalize_pluggy_value(rule.match_pluggy_subcategory),
        match_pluggy_type=normalize_pluggy_value(rule.match_pluggy_type),
        match_merchant=(normalize_description(rule.match_merchant) or None)
        if rule.match_merchant
        else None,
        match_description=(normalize_description(rule.match_description) or None)
        if rule.match_description
        else None,
        match_amount_sign=(rule.match_amount_sign or "any").lower(),
        target_internal_category=rule.target_internal_category,
        target_cashflow_type=rule.target_cashflow_type,
        ignored_from_totals=_resolved_ignored_from_totals(
            rule.target_cashflow_type,
            rule.ignored_from_totals,
        ),
    )


def load_compiled_user_rules(session: Session) -> tuple[CompiledUserRule, ...]:
    """Enabled rules, ordered by ascending priority (lowest value wins)."""
    rules = session.exec(
        select(UserClassificationRule)
        .where(UserClassificationRule.enabled.is_(True))
        .order_by(UserClassificationRule.priority.asc(), UserClassificationRule.id.asc())
    ).all()
    return tuple(compile_rule(rule) for rule in rules)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_and_normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    name = _clean(fields.get("name"))
    if not name:
        raise UserRuleValidationError("name must not be empty")

    account_type_scope = (fields.get("account_type_scope") or "ALL").upper()
    if account_type_scope not in ACCOUNT_TYPE_SCOPES:
        raise UserRuleValidationError("account_type_scope must be CREDIT, BANK or ALL")

    match_amount_sign = (fields.get("match_amount_sign") or "any").lower()
    if match_amount_sign not in AMOUNT_SIGNS:
        raise UserRuleValidationError("match_amount_sign must be positive, negative or any")

    target_internal_category = _clean(fields.get("target_internal_category"))
    if target_internal_category not in INTERNAL_CATEGORIES:
        raise UserRuleValidationError(
            "target_internal_category is not in the 10D-B taxonomy"
        )

    target_cashflow_type = _clean(fields.get("target_cashflow_type"))
    if target_cashflow_type not in CASHFLOW_TYPES:
        raise UserRuleValidationError("target_cashflow_type is not a supported cashflow type")

    cleaned = {
        "name": name,
        "enabled": bool(fields.get("enabled", True)),
        "priority": int(fields.get("priority", 100)),
        "account_type_scope": account_type_scope,
        "match_pluggy_category": _clean(fields.get("match_pluggy_category")),
        "match_pluggy_subcategory": _clean(fields.get("match_pluggy_subcategory")),
        "match_pluggy_type": _clean(fields.get("match_pluggy_type")),
        "match_merchant": _clean(fields.get("match_merchant")),
        "match_description": _clean(fields.get("match_description")),
        "match_amount_sign": match_amount_sign,
        "target_internal_category": target_internal_category,
        "target_cashflow_type": target_cashflow_type,
        "ignored_from_totals": fields.get("ignored_from_totals"),
    }

    if not any(cleaned[field] for field in _CONTENT_MATCH_FIELDS):
        raise UserRuleValidationError(
            "at least one match criterion is required "
            "(pluggy category/subcategory/type, merchant or description)"
        )

    return cleaned


# ---------------------------------------------------------------------------
# Matching helpers (shared by list affected_count and preview)
# ---------------------------------------------------------------------------


def _accounts_by_id(session: Session) -> dict[str, Account]:
    return {account.id: account for account in session.exec(select(Account)).all()}


def _classification_input_for(
    tx: Transaction,
    account_type: Optional[str],
) -> ClassificationInput:
    raw_category = tx.pluggy_raw_category if tx.pluggy_raw_category is not None else tx.category
    return ClassificationInput(
        pluggy_raw_category=raw_category,
        pluggy_raw_subcategory=tx.pluggy_raw_subcategory,
        pluggy_raw_type=tx.pluggy_raw_type,
        pluggy_merchant=tx.pluggy_merchant,
        description=tx.description,
        amount=tx.amount,
        account_type=account_type,
    )


def _matching_transactions(
    session: Session,
    compiled: CompiledUserRule,
) -> list[tuple[Transaction, Optional[str]]]:
    """Non-duplicate, non-overridden transactions the rule matches.

    Manual overrides are excluded because reclassification skips them — they
    can never be changed by a user rule.
    """
    accounts = _accounts_by_id(session)
    transactions = session.exec(
        select(Transaction).where(_non_duplicate_clause()).order_by(Transaction.date.desc())
    ).all()
    matched: list[tuple[Transaction, Optional[str]]] = []
    for tx in transactions:
        if tx.is_user_overridden:
            continue
        account = accounts.get(tx.account_id)
        account_type = account.type if account is not None else None
        if _user_rule_matches(_classification_input_for(tx, account_type), compiled):
            matched.append((tx, account_type))
    return matched


def count_rule_matches(session: Session, compiled: CompiledUserRule) -> int:
    return len(_matching_transactions(session, compiled))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_rule(session: Session, rule: UserClassificationRule) -> dict[str, Any]:
    return {
        **rule.model_dump(mode="json"),
        "affected_count": count_rule_matches(session, compile_rule(rule)),
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_user_classification_rules(session: Session) -> list[dict[str, Any]]:
    rules = session.exec(
        select(UserClassificationRule).order_by(
            UserClassificationRule.priority.asc(),
            UserClassificationRule.id.asc(),
        )
    ).all()
    return [serialize_rule(session, rule) for rule in rules]


def _get_rule(session: Session, rule_id: int) -> UserClassificationRule:
    rule = session.get(UserClassificationRule, rule_id)
    if rule is None:
        raise UserRuleNotFoundError(f"user classification rule {rule_id} not found")
    return rule


def _fields_from_rule(rule: UserClassificationRule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "account_type_scope": rule.account_type_scope,
        "match_pluggy_category": rule.match_pluggy_category,
        "match_pluggy_subcategory": rule.match_pluggy_subcategory,
        "match_pluggy_type": rule.match_pluggy_type,
        "match_merchant": rule.match_merchant,
        "match_description": rule.match_description,
        "match_amount_sign": rule.match_amount_sign,
        "target_internal_category": rule.target_internal_category,
        "target_cashflow_type": rule.target_cashflow_type,
        "ignored_from_totals": rule.ignored_from_totals,
    }


def create_user_classification_rule(
    session: Session,
    fields: dict[str, Any],
) -> dict[str, Any]:
    cleaned = _validate_and_normalize_fields(fields)
    now = datetime.datetime.utcnow()
    rule = UserClassificationRule(created_at=now, updated_at=now, **cleaned)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return serialize_rule(session, rule)


def update_user_classification_rule(
    session: Session,
    rule_id: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    rule = _get_rule(session, rule_id)
    # Merge incoming fields over the current row, then validate the whole thing
    # so partial updates can't bypass validation.
    merged = _fields_from_rule(rule)
    for key, value in fields.items():
        if key in merged:
            merged[key] = value
    cleaned = _validate_and_normalize_fields(merged)
    for key, value in cleaned.items():
        setattr(rule, key, value)
    rule.updated_at = datetime.datetime.utcnow()
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return serialize_rule(session, rule)


def delete_user_classification_rule(session: Session, rule_id: int) -> None:
    rule = _get_rule(session, rule_id)
    session.delete(rule)
    session.commit()


# ---------------------------------------------------------------------------
# Preview (read-only; never mutates the database)
# ---------------------------------------------------------------------------


def _preview_compiled_rule(
    session: Session,
    rule_id: Optional[int],
    fields: dict[str, Any],
) -> tuple[CompiledUserRule, tuple[CompiledUserRule, ...]]:
    """Compile the previewed rule plus the other enabled rules (for 'current').

    When previewing an existing rule, its current persisted form is excluded
    from the 'current' baseline so the comparison reflects this rule's effect.
    """
    effective_rule_id = rule_id or -1
    if rule_id is not None:
        persisted = _get_rule(session, rule_id)
        merged = _fields_from_rule(persisted)
        for key, value in fields.items():
            if key in merged:
                merged[key] = value
        fields = merged
    cleaned = _validate_and_normalize_fields(fields)
    preview_rule = UserClassificationRule(id=effective_rule_id, **cleaned)
    compiled = compile_rule(preview_rule)
    other_rules = tuple(
        r for r in load_compiled_user_rules(session) if r.rule_id != effective_rule_id
    )
    return compiled, other_rules


def preview_user_classification_rule(
    session: Session,
    fields: dict[str, Any],
    rule_id: Optional[int] = None,
) -> dict[str, Any]:
    compiled, other_rules = _preview_compiled_rule(session, rule_id, fields)
    matched = _matching_transactions(session, compiled)

    examples: list[dict[str, Any]] = []
    for tx, account_type in matched[:PREVIEW_EXAMPLE_LIMIT]:
        # 'current' = effective classification today, with the previewed rule
        # excluded so the diff isolates this rule's impact.
        current = serialize_transaction_classification(
            tx,
            account_type=account_type,
            user_rules=other_rules,
        )
        examples.append(
            {
                "id": tx.id,
                "date": tx.date.isoformat(),
                "description": tx.description,
                "amount": float(tx.amount),
                "account_type": account_type,
                "pluggy_raw_category": tx.pluggy_raw_category or tx.category,
                "pluggy_raw_subcategory": tx.pluggy_raw_subcategory,
                "pluggy_raw_type": tx.pluggy_raw_type,
                "pluggy_merchant": tx.pluggy_merchant,
                "current_internal_category": current["internal_category"],
                "current_cashflow_type": current["cashflow_type"],
                "new_internal_category": compiled.target_internal_category,
                "new_cashflow_type": compiled.target_cashflow_type,
            }
        )

    return {"matched_count": len(matched), "examples": examples}
