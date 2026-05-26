import logging
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import engine, get_session
from app.models import Account, AccountSync, Item
from app.pluggy_client import pluggy
from app.services.sync import (
    SyncAlreadyRunning,
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


@router.post("/webhooks/pluggy")
async def pluggy_webhook(request: Request, background_tasks: BackgroundTasks):
    payload: Dict[str, object] = await request.json()
    event = payload.get("event")
    item_id = payload.get("itemId")
    logger.info("pluggy webhook event=%s item=%s", event, item_id)

    if event in {"item/created", "item/updated"} and isinstance(item_id, str):
        background_tasks.add_task(_handle_item_event, item_id)

    return {"received": True}


def _handle_item_event(item_id: str) -> None:
    try:
        with Session(engine) as session:
            upsert_item(item_id, session)
            result = run_sync_item(item_id, session)
        logger.info("synced item=%s result=%s", item_id, result)
    except SyncAlreadyRunning:
        logger.info("skipping webhook sync, already running item=%s", item_id)
    except Exception:
        logger.exception("failed to process item event item=%s", item_id)


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


@router.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    return session.exec(select(Account)).all()
