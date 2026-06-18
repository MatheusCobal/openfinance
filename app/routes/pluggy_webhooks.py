import logging
import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlmodel import Session, desc, select

from app.database import engine, get_session
from app.models import Account, Item, PluggyWebhookEvent
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

REMOVAL_EVENTS = {
    "item/deleted",
    "item/removed",
    "item/disconnected",
}

_ERROR_MSG_MAX_LEN = 300
_PAYLOAD_JSON_MAX_LEN = 5000
_SYNC_ERROR_MAX_LEN = 500


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

    active_item_ids: list[str] = []
    if event in SYNC_EVENTS:
        if not item_id:
            active_item_ids = _active_item_ids(session)
            action = "sync_scheduled_all_active" if active_item_ids else "no_active_items"
        elif session.get(Item, item_id) is None:
            action = "item_not_found"
            logger.info("pluggy webhook item_not_found event=%s item_id=%s", event, item_id)
        else:
            action = "sync_scheduled"
    elif event in REMOVAL_EVENTS:
        action = _deactivate_item(item_id, session)
    elif event in ERROR_EVENTS:
        action = _record_item_status(event, item_id, payload, session)
    else:
        action = "ignored"

    logger.info("pluggy webhook action=%s event=%s item_id=%s", action, event, item_id)

    webhook_event = _record_webhook_event(
        session,
        event=event,
        event_id=event_id,
        item_id=item_id,
        action=action,
        payload=payload,
    )
    if action == "sync_scheduled" and item_id:
        background_tasks.add_task(_do_sync_item, item_id, webhook_event.id)
    elif action == "sync_scheduled_all_active":
        background_tasks.add_task(_do_sync_items, active_item_ids, webhook_event.id)

    return {"ok": True, "event": event, "item_id": item_id, "action": action}


@router.get("/sync/webhook-events")
def recent_webhook_events(limit: int = 25, session: Session = Depends(get_session)):
    limit = max(1, min(limit, 100))
    events = session.exec(
        select(PluggyWebhookEvent).order_by(desc(PluggyWebhookEvent.received_at)).limit(limit)
    ).all()
    return [
        {
            "id": event.id,
            "event": event.event,
            "event_id": event.event_id,
            "item_id": event.item_id,
            "action": event.action,
            "received_at": event.received_at,
            "sync_started_at": event.sync_started_at,
            "sync_finished_at": event.sync_finished_at,
            "sync_status": event.sync_status,
            "sync_error": event.sync_error,
        }
        for event in events
    ]


def _record_webhook_event(
    session: Session,
    event: str,
    event_id: Optional[Any],
    item_id: Optional[str],
    action: str,
    payload: Dict[str, Any],
) -> PluggyWebhookEvent:
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    row = PluggyWebhookEvent(
        event=event,
        event_id=str(event_id) if event_id is not None else None,
        item_id=item_id,
        action=action,
        payload_json=payload_json[:_PAYLOAD_JSON_MAX_LEN],
        sync_status="scheduled" if action.startswith("sync_scheduled") else None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _mark_webhook_sync_started(session: Session, event_id: Optional[int]) -> None:
    if event_id is None:
        return
    event = session.get(PluggyWebhookEvent, event_id)
    if event is None:
        return
    event.sync_started_at = datetime.utcnow()
    event.sync_status = "running"
    session.add(event)
    session.commit()


def _mark_webhook_sync_finished(
    session: Session,
    event_id: Optional[int],
    sync_status: str,
    sync_error: Optional[str] = None,
) -> None:
    if event_id is None:
        return
    event = session.get(PluggyWebhookEvent, event_id)
    if event is None:
        return
    event.sync_finished_at = datetime.utcnow()
    event.sync_status = sync_status
    event.sync_error = sync_error[:_SYNC_ERROR_MAX_LEN] if sync_error else None
    session.add(event)
    session.commit()


def _do_sync_item(item_id: str, webhook_event_id: Optional[int] = None) -> None:
    try:
        with Session(engine) as session:
            _mark_webhook_sync_started(session, webhook_event_id)
            result = run_sync_item(item_id, session)
            _mark_webhook_sync_finished(session, webhook_event_id, "completed")
        logger.info("webhook sync completed item_id=%s result=%s", item_id, result)
    except SyncAlreadyRunning:
        with Session(engine) as session:
            _mark_webhook_sync_finished(
                session,
                webhook_event_id,
                "skipped_already_running",
            )
        logger.info("webhook sync skipped, already running item_id=%s", item_id)
    except Exception as exc:
        with Session(engine) as session:
            _mark_webhook_sync_finished(session, webhook_event_id, "failed", str(exc))
        logger.exception("webhook sync failed item_id=%s", item_id)


def _do_sync_items(item_ids: list[str], webhook_event_id: Optional[int] = None) -> None:
    sync_errors = []
    with Session(engine) as session:
        _mark_webhook_sync_started(session, webhook_event_id)

    for item_id in item_ids:
        try:
            with Session(engine) as session:
                result = run_sync_item(item_id, session)
            logger.info("webhook sync completed item_id=%s result=%s", item_id, result)
        except SyncAlreadyRunning:
            logger.info("webhook sync skipped, already running item_id=%s", item_id)
        except Exception as exc:
            sync_errors.append(f"{item_id}: {exc}")
            logger.exception("webhook sync failed item_id=%s", item_id)

    with Session(engine) as session:
        if sync_errors:
            _mark_webhook_sync_finished(
                session,
                webhook_event_id,
                "failed",
                "; ".join(sync_errors),
            )
        else:
            _mark_webhook_sync_finished(session, webhook_event_id, "completed")


def _active_item_ids(session: Session) -> list[str]:
    items = session.exec(select(Item).where(Item.is_active)).all()
    return [item.id for item in items]


def _deactivate_item(item_id: Optional[str], session: Session) -> str:
    if not item_id:
        return "missing_item_id"
    item = session.get(Item, item_id)
    if item is None:
        return "item_not_found"
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
    return "item_deactivated"


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
