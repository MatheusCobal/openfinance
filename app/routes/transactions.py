import datetime
from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.dependencies import current_scope_user_id
from app.database import get_session
from app.models import Account
from app.pluggy_client import pluggy
from app.services.classification_override import (
    apply_manual_classification,
    classification_options,
    reset_manual_classification,
)
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.transaction_reports import (
    enriched_transactions,
    monthly_stats_summary,
    stats_summary,
    upcoming_summary,
)

router = APIRouter()


@router.get("/transactions")
def list_transactions(
    account_id: Optional[str] = None,
    account_type: Optional[str] = "CREDIT",
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        return enriched_transactions(
            session,
            account_id=account_id,
            account_type=account_type,
            from_date=from_date,
            to_date=to_date,
            include_future=include_future,
            include_ignored=include_ignored,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class ClassificationOverridePayload(BaseModel):
    internal_category: str
    cashflow_type: str
    # None lets the backend derive the flag from the cashflow type.
    ignored_from_totals: Optional[bool] = None


def _classification_response(tx, session: Session) -> dict:
    account = session.get(Account, tx.account_id)
    return {
        "id": tx.id,
        **serialize_transaction_classification(
            tx,
            account_type=account.type if account is not None else None,
        ),
    }


@router.get("/transactions/classification-options")
def transaction_classification_options():
    return classification_options()


@router.patch("/transactions/{transaction_id}/classification")
def override_transaction_classification(
    transaction_id: str,
    payload: ClassificationOverridePayload,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        tx = apply_manual_classification(
            session,
            transaction_id,
            internal_category=payload.internal_category,
            cashflow_type=payload.cashflow_type,
            ignored_from_totals=payload.ignored_from_totals,
            user_id=user_id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _classification_response(tx, session)


@router.delete("/transactions/{transaction_id}/classification-override")
def reset_transaction_classification(
    transaction_id: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    try:
        tx = reset_manual_classification(session, transaction_id, user_id=user_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    return _classification_response(tx, session)


@router.get("/upcoming")
def upcoming(
    include_ignored: bool = False,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return upcoming_summary(session, include_ignored=include_ignored, user_id=user_id)


@router.get("/stats/monthly")
def stats_monthly(
    include_ignored: bool = False,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return monthly_stats_summary(session, include_ignored=include_ignored, user_id=user_id)


@router.get("/stats")
def stats(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_ignored: bool = False,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    return stats_summary(
        session,
        from_date=from_date,
        to_date=to_date,
        include_ignored=include_ignored,
        user_id=user_id,
    )


@router.post("/accounts/{account_id}/refresh-balance")
def refresh_balance(
    account_id: str,
    session: Session = Depends(get_session),
    user_id: Optional[int] = Depends(current_scope_user_id),
):
    account = session.get(Account, account_id)
    if account is None or (user_id is not None and account.user_id != user_id):
        raise HTTPException(404, f"account {account_id} not found")
    try:
        data = pluggy.get_account_balance(account_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 405, 501):
            raise HTTPException(
                503,
                f"real-time balance not supported for account {account_id}",
            ) from exc
        if exc.response.status_code == 429:
            raise HTTPException(429, "rate limited by Pluggy") from exc
        raise HTTPException(502, f"Pluggy error: {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"network error reaching Pluggy: {exc}") from exc

    from decimal import Decimal, InvalidOperation

    raw_balance = data.get("balance")
    if raw_balance is not None:
        try:
            account.balance = Decimal(str(raw_balance))
        except (InvalidOperation, ValueError):
            pass
    raw_updated = data.get("updatedAt") or data.get("date")
    if raw_updated:
        try:
            account.balance_updated_at = datetime.datetime.fromisoformat(
                str(raw_updated).replace("Z", "+00:00")
            )
        except ValueError:
            pass
    session.add(account)
    session.commit()
    session.refresh(account)
    return {
        "account_id": account_id,
        "balance": float(account.balance) if account.balance is not None else None,
        "balance_updated_at": (
            account.balance_updated_at.isoformat() if account.balance_updated_at else None
        ),
    }
