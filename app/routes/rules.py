from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.categorization import normalize_description
from app.database import get_session
from app.models import (
    BankIncomeExclusionRule,
    Category,
    DescriptionCategoryRule,
    IgnoredDescriptionRule,
)
from app.routes.common import count_description_rule_matches
from app.services.transactions import count_bank_income_exclusion_matches

router = APIRouter()


class BankIncomeExclusionRuleUpsert(BaseModel):
    pluggy_category: Optional[str] = None
    pattern: Optional[str] = None


class DescriptionCategoryRuleUpsert(BaseModel):
    pattern: str
    category_id: int


class IgnoredDescriptionRuleUpsert(BaseModel):
    pattern: str


@router.get("/bank-income/exclusion-rules")
def list_bank_income_exclusion_rules(session: Session = Depends(get_session)):
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


@router.post("/bank-income/exclusion-rules")
def upsert_bank_income_exclusion_rule(
    body: BankIncomeExclusionRuleUpsert,
    session: Session = Depends(get_session),
):
    pluggy_category = (
        body.pluggy_category.strip() if body.pluggy_category else None
    )
    pattern = body.pattern.strip() if body.pattern else None
    if bool(pluggy_category) == bool(pattern):
        raise HTTPException(
            400,
            "Provide exactly one of pluggy_category or pattern",
        )

    pattern_normalized = normalize_description(pattern) if pattern else None
    if pattern is not None and not pattern_normalized:
        raise HTTPException(400, "pattern must not be empty")

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


@router.delete("/bank-income/exclusion-rules/{rule_id}", status_code=204)
def delete_bank_income_exclusion_rule(
    rule_id: int,
    session: Session = Depends(get_session),
):
    rule = session.get(BankIncomeExclusionRule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()
    return None


@router.post("/category-rules/description")
def upsert_description_category_rule(
    body: DescriptionCategoryRuleUpsert,
    session: Session = Depends(get_session),
):
    pattern = body.pattern.strip()
    pattern_normalized = normalize_description(pattern)
    if not pattern_normalized:
        raise HTTPException(400, "pattern must not be empty")

    category = session.get(Category, body.category_id)
    if category is None:
        raise HTTPException(404, "category not found")

    rule = session.exec(
        select(DescriptionCategoryRule).where(
            DescriptionCategoryRule.pattern_normalized == pattern_normalized
        )
    ).first()
    if rule is None:
        rule = DescriptionCategoryRule(
            pattern=pattern,
            pattern_normalized=pattern_normalized,
            category_id=body.category_id,
        )
    else:
        rule.pattern = pattern
        rule.category_id = body.category_id
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


@router.get("/transaction-ignore-rules/description")
def list_ignored_description_rules(session: Session = Depends(get_session)):
    return session.exec(
        select(IgnoredDescriptionRule).order_by(IgnoredDescriptionRule.pattern)
    ).all()


@router.post("/transaction-ignore-rules/description")
def upsert_ignored_description_rule(
    body: IgnoredDescriptionRuleUpsert,
    session: Session = Depends(get_session),
):
    pattern = body.pattern.strip()
    pattern_normalized = normalize_description(pattern)
    if not pattern_normalized:
        raise HTTPException(400, "pattern must not be empty")

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
