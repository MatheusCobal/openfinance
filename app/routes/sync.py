import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, AccountSync, Item
from app.pluggy_client import pluggy
from app.services.sync import (
    SyncAlreadyRunning,
    reconcile_active_items,
    sync_item as run_sync_item,
    upsert_item,
)

logger = logging.getLogger("openfinance")

router = APIRouter()


class ConnectTokenRequest(BaseModel):
    clientUserId: Optional[str] = None
    itemId: Optional[str] = None


@router.post("/connect-token")
def connect_token(body: Optional[ConnectTokenRequest] = None):
    body = body or ConnectTokenRequest()
    try:
        token = pluggy.create_connect_token(
            client_user_id=body.clientUserId, item_id=body.itemId
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise HTTPException(
                401,
                "Pluggy rejected the credentials. Check PLUGGY_CLIENT_ID and "
                "PLUGGY_CLIENT_SECRET in your .env file.",
            )
        raise HTTPException(
            502, f"Pluggy returned {exc.response.status_code}: {exc.response.text}"
        )
    return {"accessToken": token}


@router.post("/items/{item_id}")
def register_item(item_id: str, session: Session = Depends(get_session)):
    return upsert_item(item_id, session)


@router.post("/items/{item_id}/sync")
def sync_item(item_id: str, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if item is None:
        item = upsert_item(item_id, session)
    try:
        return run_sync_item(item.id, session)
    except SyncAlreadyRunning:
        raise HTTPException(409, "sync already running for this item")



@router.get("/items")
def list_items(session: Session = Depends(get_session)):
    return session.exec(select(Item)).all()


@router.get("/sync/health")
def sync_health(session: Session = Depends(get_session)):
    items = session.exec(select(Item)).all()
    health = []
    for item in items:
        is_running = (
            item.sync_started_at is not None and item.sync_finished_at is None
        )
        failed = session.exec(
            select(Account.id, AccountSync.last_error, AccountSync.last_error_at)
            .join(AccountSync, AccountSync.account_id == Account.id)
            .where(Account.item_id == item.id)
            .where(AccountSync.last_error.is_not(None))
        ).all()
        health.append(
            {
                "item_id": item.id,
                "connector_name": item.connector_name,
                "status": item.status,
                "is_active": item.is_active,
                "deactivated_at": item.deactivated_at,
                "sync_started_at": item.sync_started_at,
                "sync_finished_at": item.sync_finished_at,
                "is_running": is_running,
                "last_sync_error": item.last_sync_error,
                "failed_accounts": [
                    {
                        "account_id": account_id,
                        "error": error,
                        "last_error_at": last_error_at,
                    }
                    for account_id, error, last_error_at in failed
                ],
            }
        )
    return health


@router.post("/sync/items/{item_id}/deactivate")
def deactivate_item(item_id: str, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, f"Item {item_id!r} not found")
    now = datetime.utcnow()
    item.is_active = False
    item.deactivated_at = now
    session.add(item)
    accounts = session.exec(select(Account).where(Account.item_id == item_id)).all()
    for account in accounts:
        account.is_active = False
        account.deactivated_at = now
        session.add(account)
    session.commit()
    return {
        "item_id": item_id,
        "deactivated_item": True,
        "deactivated_accounts": len(accounts),
    }


@router.post("/sync/reconcile-items")
def reconcile_items(session: Session = Depends(get_session)):
    return reconcile_active_items(session)


@router.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    return session.exec(select(Account)).all()
