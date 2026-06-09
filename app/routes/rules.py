from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services.rules import (
    RuleCategoryNotFoundError,
    RuleValidationError,
    delete_bank_cashflow_exclusion_rule as delete_bank_cashflow_exclusion_rule_service,
    delete_bank_income_exclusion_rule as delete_bank_income_exclusion_rule_service,
    delete_ignored_description_rule as delete_ignored_description_rule_service,
    list_bank_cashflow_exclusion_rules as list_bank_cashflow_exclusion_rules_service,
    list_bank_income_exclusion_rules as list_bank_income_exclusion_rules_service,
    list_ignored_description_rules as list_ignored_description_rules_service,
    upsert_bank_cashflow_exclusion_rule as upsert_bank_cashflow_exclusion_rule_service,
    upsert_bank_income_exclusion_rule as upsert_bank_income_exclusion_rule_service,
    upsert_ignored_description_rule as upsert_ignored_description_rule_service,
)

router = APIRouter()
LEGACY_CATEGORY_RULES_REMOVED_MESSAGE = (
    "legacy category description rules were removed in 10D-A; "
    "TODO 10D-D: add user-owned rules for the Pluggy-based classification layer"
)


class BankIncomeExclusionRuleUpsert(BaseModel):
    pluggy_category: Optional[str] = None
    pattern: Optional[str] = None


class BankCashflowExclusionRuleUpsert(BaseModel):
    direction: str = "ALL"
    pluggy_category: Optional[str] = None
    pattern: Optional[str] = None


class IgnoredDescriptionRuleUpsert(BaseModel):
    pattern: str


def _handle_rule_error(exc: Exception):
    if isinstance(exc, RuleValidationError):
        raise HTTPException(400, str(exc))
    if isinstance(exc, RuleCategoryNotFoundError):
        raise HTTPException(404, str(exc))
    raise exc


@router.get("/bank-income/exclusion-rules")
def list_bank_income_exclusion_rules(session: Session = Depends(get_session)):
    return list_bank_income_exclusion_rules_service(session)


@router.post("/bank-income/exclusion-rules")
def upsert_bank_income_exclusion_rule(
    body: BankIncomeExclusionRuleUpsert,
    session: Session = Depends(get_session),
):
    try:
        return upsert_bank_income_exclusion_rule_service(
            session,
            pluggy_category=body.pluggy_category,
            pattern=body.pattern,
        )
    except (RuleValidationError, RuleCategoryNotFoundError) as exc:
        _handle_rule_error(exc)


@router.delete("/bank-income/exclusion-rules/{rule_id}", status_code=204)
def delete_bank_income_exclusion_rule(
    rule_id: int,
    session: Session = Depends(get_session),
):
    delete_bank_income_exclusion_rule_service(session, rule_id)
    return None


@router.get("/bank-cashflow/exclusion-rules")
def list_bank_cashflow_exclusion_rules(session: Session = Depends(get_session)):
    return list_bank_cashflow_exclusion_rules_service(session)


@router.post("/bank-cashflow/exclusion-rules")
def upsert_bank_cashflow_exclusion_rule(
    body: BankCashflowExclusionRuleUpsert,
    session: Session = Depends(get_session),
):
    try:
        return upsert_bank_cashflow_exclusion_rule_service(
            session,
            direction=body.direction,
            pluggy_category=body.pluggy_category,
            pattern=body.pattern,
        )
    except (RuleValidationError, RuleCategoryNotFoundError) as exc:
        _handle_rule_error(exc)


@router.delete("/bank-cashflow/exclusion-rules/{rule_id}", status_code=204)
def delete_bank_cashflow_exclusion_rule(
    rule_id: int,
    session: Session = Depends(get_session),
):
    delete_bank_cashflow_exclusion_rule_service(session, rule_id)
    return None


@router.get("/category-rules/description")
def list_description_category_rules(session: Session = Depends(get_session)):
    raise HTTPException(410, LEGACY_CATEGORY_RULES_REMOVED_MESSAGE)


@router.get("/category-rules/description/suggestions")
def description_category_rule_suggestions(
    months: int = 12,
    min_count: int = 2,
    limit: int = 10,
    session: Session = Depends(get_session),
):
    raise HTTPException(410, LEGACY_CATEGORY_RULES_REMOVED_MESSAGE)


@router.post("/category-rules/description")
def upsert_description_category_rule(
    body: dict,
    session: Session = Depends(get_session),
):
    raise HTTPException(410, LEGACY_CATEGORY_RULES_REMOVED_MESSAGE)


@router.delete("/category-rules/description/{rule_id}", status_code=204)
def delete_description_category_rule(
    rule_id: int,
    session: Session = Depends(get_session),
):
    raise HTTPException(410, LEGACY_CATEGORY_RULES_REMOVED_MESSAGE)


@router.get("/transaction-ignore-rules/description")
def list_ignored_description_rules(session: Session = Depends(get_session)):
    return list_ignored_description_rules_service(session)


@router.post("/transaction-ignore-rules/description")
def upsert_ignored_description_rule(
    body: IgnoredDescriptionRuleUpsert,
    session: Session = Depends(get_session),
):
    try:
        return upsert_ignored_description_rule_service(session, body.pattern)
    except (RuleValidationError, RuleCategoryNotFoundError) as exc:
        _handle_rule_error(exc)


@router.delete("/transaction-ignore-rules/description/{rule_id}", status_code=204)
def delete_ignored_description_rule(
    rule_id: int,
    session: Session = Depends(get_session),
):
    delete_ignored_description_rule_service(session, rule_id)
    return None
