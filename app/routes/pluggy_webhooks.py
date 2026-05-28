import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlmodel import Session

from app.database import engine, get_session
from app.models import Item
from app.services.sync import SyncAlreadyRunning, sync_item as run_sync_item

logger = logging.getLogger("openfinance")

router = APIRouter()

SYNC_EVENTS = {
    "item/created",
    "item/updated",
    "transactions/created",
    "transactions/updated",
    "transactions/deleted",
}

ERROR_EVENTS = {
    "item/error",
    "item/waiting_user_input",
    "item/waiting_user_action",
    "item/login_error",
    "item/outdated",
}

_ERROR_MSG_MAX_LEN = 300


@router.post("/webhooks/pluggy", status_code=202)
async def pluggy_webhook(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    event = payload.get("event") or payload.get("eventType") or payload.get("type")
    item_id = payload.get("itemId") or payload.get("item_id")
    event_id = payload.get("eventId") or payload.get("id")

    event = str(event) if event is not None else "unknown"
    item_id = item_id.strip() if isinstance(item_id, str) and item_id.strip() else None

    logger.info(
        "pluggy webhook event=%s event_id=%s item_id=%s",
        event,
        event_id,
        item_id,
    )

    if event in SYNC_EVENTS:
        if not item_id:
            action = "missing_item_id"
        elif session.get(Item, item_id) is None:
            action = "item_not_found"
            logger.info(
                "pluggy webhook item_not_found event=%s item_id=%s", event, item_id
            )
        else:
            background_tasks.add_task(_do_sync_item, item_id)
            action = "sync_scheduled"
    elif event in ERROR_EVENTS:
        action = _record_item_status(event, item_id, payload, session)
    else:
        action = "ignored"

    logger.info("pluggy webhook action=%s event=%s item_id=%s", action, event, item_id)

    return {"ok": True, "event": event, "item_id": item_id, "action": action}


def _do_sync_item(item_id: str) -> None:
    try:
        with Session(engine) as session:
            result = run_sync_item(item_id, session)
        logger.info("webhook sync completed item_id=%s result=%s", item_id, result)
    except SyncAlreadyRunning:
        logger.info("webhook sync skipped, already running item_id=%s", item_id)
    except Exception:
        logger.exception("webhook sync failed item_id=%s", item_id)


def _record_item_status(
    event: str,
    item_id: Optional[str],
    payload: Dict[str, Any],
    session: Session,
) -> str:
    if not item_id:
        return "missing_item_id"

    item = session.get(Item, item_id)
    if item is None:
        return "item_not_found"

    error_parts = [event]
    for key in ("error", "message", "code"):
        val = payload.get(key)
        if val:
            error_parts.append(str(val))
    item.last_sync_error = " | ".join(error_parts)[:_ERROR_MSG_MAX_LEN]

    status = payload.get("status")
    if isinstance(status, str):
        item.status = status

    session.add(item)
    session.commit()
    return "status_recorded"
