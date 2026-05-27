from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services.savings import (
    SavingsTargetValidationError,
    clear_default,
    delete_override,
    get_default,
    monthly_breakdown,
    set_default,
    set_override,
)

router = APIRouter()


class SavingsTargetUpsert(BaseModel):
    monthly_target: Decimal


@router.get("/savings-target")
def get_default_route(session: Session = Depends(get_session)):
    return get_default(session)


@router.put("/savings-target")
def set_default_route(
    body: SavingsTargetUpsert,
    session: Session = Depends(get_session),
):
    try:
        return set_default(session, body.monthly_target)
    except SavingsTargetValidationError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/savings-target", status_code=204)
def clear_default_route(session: Session = Depends(get_session)):
    clear_default(session)
    return None


@router.get("/savings-target/months/{year_month}")
def get_month_route(
    year_month: str,
    session: Session = Depends(get_session),
):
    try:
        return monthly_breakdown(session, year_month)
    except SavingsTargetValidationError as exc:
        raise HTTPException(400, str(exc))


@router.put("/savings-target/months/{year_month}")
def set_override_route(
    year_month: str,
    body: SavingsTargetUpsert,
    session: Session = Depends(get_session),
):
    try:
        return set_override(session, year_month, body.monthly_target)
    except SavingsTargetValidationError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/savings-target/months/{year_month}", status_code=204)
def delete_override_route(
    year_month: str,
    session: Session = Depends(get_session),
):
    try:
        deleted = delete_override(session, year_month)
    except SavingsTargetValidationError as exc:
        raise HTTPException(400, str(exc))
    if not deleted:
        raise HTTPException(404, "override not found")
    return None
