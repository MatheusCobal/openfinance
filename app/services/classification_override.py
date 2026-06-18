"""Manual per-transaction classification overrides (10D-C).

Lets the user pin a specific transaction to an internal category and cashflow
type, and undo that override back to the automatic 10D-B classification. Only
classification fields may change here — raw Pluggy fields and financial data
(amount/date/description/account) are never touched.
"""

from typing import Optional

from sqlmodel import Session

from app.models import Account, Transaction
from app.services.transaction_classifier import (
    CASHFLOW_TYPES,
    IGNORED_CASHFLOW_TYPES,
    INTERNAL_CATEGORIES,
    classify_transaction,
    is_supported_internal_category,
    normalize_internal_category,
)

MANUAL_OVERRIDE_SOURCE = "manual_override"
MANUAL_OVERRIDE_CONFIDENCE = "high"
MANUAL_OVERRIDE_RULE_KEY = "manual_override"


def default_ignored_from_totals(cashflow_type: str) -> bool:
    return cashflow_type in IGNORED_CASHFLOW_TYPES


def classification_options() -> dict:
    """Options for the manual-override UI, sourced from the 10D-B classifier."""
    return {
        "internal_categories": list(INTERNAL_CATEGORIES),
        "cashflow_types": sorted(CASHFLOW_TYPES),
        "suggested_ignored_from_totals": {
            cashflow_type: default_ignored_from_totals(cashflow_type)
            for cashflow_type in sorted(CASHFLOW_TYPES)
        },
    }


def validate_override_values(internal_category: str, cashflow_type: str) -> None:
    if not is_supported_internal_category(internal_category):
        raise ValueError(f"internal_category {internal_category!r} is not in the 10D-B taxonomy")
    if cashflow_type not in CASHFLOW_TYPES:
        raise ValueError(f"cashflow_type {cashflow_type!r} is not a supported cashflow type")


def _get_transaction(session: Session, transaction_id: str) -> Transaction:
    tx = session.get(Transaction, transaction_id)
    if tx is None:
        raise LookupError(f"transaction {transaction_id} not found")
    return tx


def apply_manual_classification(
    session: Session,
    transaction_id: str,
    internal_category: str,
    cashflow_type: str,
    ignored_from_totals: Optional[bool] = None,
) -> Transaction:
    """Pin the transaction's classification to user-chosen values.

    ``ignored_from_totals`` left as None derives from the cashflow type using
    the same rule the automatic classifier applies.
    """
    validate_override_values(internal_category, cashflow_type)
    internal_category = normalize_internal_category(internal_category)
    tx = _get_transaction(session, transaction_id)

    tx.internal_category = internal_category
    tx.cashflow_type = cashflow_type
    tx.classification_source = MANUAL_OVERRIDE_SOURCE
    tx.classification_confidence = MANUAL_OVERRIDE_CONFIDENCE
    tx.classification_rule_key = MANUAL_OVERRIDE_RULE_KEY
    tx.ignored_from_totals = (
        ignored_from_totals
        if ignored_from_totals is not None
        else default_ignored_from_totals(cashflow_type)
    )
    tx.is_user_overridden = True

    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def reset_manual_classification(session: Session, transaction_id: str) -> Transaction:
    """Drop the manual override and re-apply the automatic classification.

    The automatic path includes 10D-D user rules, so after a reset the
    transaction follows: user rule > Pluggy rule > system rule > fallback.
    """
    from app.services.user_classification_rules import load_compiled_user_rules

    tx = _get_transaction(session, transaction_id)
    account = session.get(Account, tx.account_id)

    # Clear the flag first so classify_transaction takes the automatic path
    # instead of the reserved manual_override branch.
    tx.is_user_overridden = False
    result = classify_transaction(
        tx,
        account_type=account.type if account is not None else None,
        user_rules=load_compiled_user_rules(session),
    )
    for field, value in result.transaction_values().items():
        setattr(tx, field, value)

    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx
