import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.routes.pluggy_webhooks as webhook_routes
from app.database import get_session
from app.main import app
from app.models import Item, PluggyWebhookEvent
from app.services.sync import SyncAlreadyRunning


class PluggyWebhooksTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _seed_item(self, item_id: str = "item-1", status: str = "UPDATED") -> None:
        with Session(self.engine) as session:
            session.add(Item(id=item_id, connector_id=200, status=status))
            session.commit()

    # --- 1. item/updated with existing itemId → sync_scheduled ---

    def test_item_updated_schedules_sync(self):
        self._seed_item("item-1")
        with patch("app.routes.pluggy_webhooks._do_sync_item") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={
                    "event": "item/updated",
                    "eventId": "evt-1",
                    "itemId": "item-1",
                    "triggeredBy": "USER",
                },
            )
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "sync_scheduled")
        self.assertEqual(data["item_id"], "item-1")
        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.args[0], "item-1")

        with Session(self.engine) as session:
            events = session.exec(select(PluggyWebhookEvent)).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "item/updated")
        self.assertEqual(events[0].event_id, "evt-1")
        self.assertEqual(events[0].item_id, "item-1")
        self.assertEqual(events[0].action, "sync_scheduled")
        self.assertEqual(events[0].sync_status, "scheduled")
        self.assertIn('"triggeredBy": "USER"', events[0].payload_json)

    # --- 2. item/updated with unknown itemId → item_not_found ---

    def test_item_updated_unknown_item_id(self):
        with patch("app.routes.pluggy_webhooks._do_sync_item") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={"event": "item/updated", "itemId": "nonexistent-id"},
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "item_not_found")
        mock_sync.assert_not_called()

    # --- 3. transactions/created with existing itemId → sync_scheduled ---

    def test_transactions_created_schedules_sync(self):
        self._seed_item("item-2")
        with patch("app.routes.pluggy_webhooks._do_sync_item") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={"event": "transactions/created", "itemId": "item-2"},
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "sync_scheduled")
        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.args[0], "item-2")

    # --- 4. item/error with existing Item → status_recorded ---

    def test_item_error_records_status(self):
        self._seed_item("item-3")
        resp = self.client.post(
            "/webhooks/pluggy",
            json={
                "event": "item/error",
                "itemId": "item-3",
                "error": "credential_error",
                "message": "Invalid credentials",
            },
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["action"], "status_recorded")

        with Session(self.engine) as session:
            item = session.get(Item, "item-3")
        self.assertIsNotNone(item.last_sync_error)
        self.assertIn("item/error", item.last_sync_error)
        self.assertIn("credential_error", item.last_sync_error)

    # --- 5. unknown event → ignored ---

    def test_unknown_event_is_ignored(self):
        resp = self.client.post(
            "/webhooks/pluggy",
            json={"event": "some/unknown_event", "itemId": "item-x"},
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "ignored")

    # --- 6. sync event without itemId → sync all active items ---

    def test_sync_event_without_item_id_schedules_all_active_items(self):
        self._seed_item("item-active-1")
        self._seed_item("item-active-2")
        with patch("app.routes.pluggy_webhooks._do_sync_items") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={"event": "item/updated"},
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "sync_scheduled_all_active")
        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.args[0], ["item-active-1", "item-active-2"])

        with Session(self.engine) as session:
            event = session.exec(select(PluggyWebhookEvent)).one()
        self.assertEqual(event.action, "sync_scheduled_all_active")
        self.assertEqual(event.sync_status, "scheduled")

    def test_sync_event_without_item_id_and_no_active_items_does_not_schedule_sync(self):
        with patch("app.routes.pluggy_webhooks._do_sync_items") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={"event": "transactions/created"},
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "no_active_items")
        mock_sync.assert_not_called()

    # --- extra: item/error for non-existent item → item_not_found ---

    def test_item_error_for_unknown_item(self):
        resp = self.client.post(
            "/webhooks/pluggy",
            json={"event": "item/error", "itemId": "nonexistent"},
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "item_not_found")

    # --- extra: all SYNC_EVENTS are handled ---

    def test_all_sync_events_schedule_sync(self):
        self._seed_item("item-x")
        sync_events = [
            "item/created",
            "item/updated",
            "transactions/created",
            "transactions/updated",
            "transactions/deleted",
        ]
        for event in sync_events:
            with self.subTest(event=event):
                with patch("app.routes.pluggy_webhooks._do_sync_item") as mock_sync:
                    resp = self.client.post(
                        "/webhooks/pluggy",
                        json={"event": event, "itemId": "item-x"},
                    )
                self.assertEqual(resp.status_code, 202)
                self.assertEqual(resp.json()["action"], "sync_scheduled", msg=event)
                mock_sync.assert_called_once()
                self.assertEqual(mock_sync.call_args.args[0], "item-x")

    def test_recent_webhook_events_endpoint_lists_latest_events(self):
        self.client.post(
            "/webhooks/pluggy",
            json={"event": "some/unknown_event", "eventId": "evt-old", "itemId": "item-x"},
        )
        self.client.post(
            "/webhooks/pluggy",
            json={"event": "item/error", "eventId": "evt-new", "itemId": "missing"},
        )

        resp = self.client.get("/sync/webhook-events?limit=1")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["event_id"], "evt-new")
        self.assertEqual(payload[0]["action"], "item_not_found")
        self.assertNotIn("payload_json", payload[0])

    def test_background_sync_marks_webhook_event_completed(self):
        with Session(self.engine) as session:
            event = PluggyWebhookEvent(
                event="item/updated",
                event_id="evt-sync",
                item_id="item-sync",
                action="sync_scheduled",
                sync_status="scheduled",
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            event_id = event.id

        with (
            patch.object(webhook_routes, "engine", self.engine),
            patch.object(webhook_routes, "run_sync_item", return_value={"ok": True}),
        ):
            webhook_routes._do_sync_item("item-sync", event_id)

        with Session(self.engine) as session:
            event = session.get(PluggyWebhookEvent, event_id)
        self.assertEqual(event.sync_status, "completed")
        self.assertIsNotNone(event.sync_started_at)
        self.assertIsNotNone(event.sync_finished_at)
        self.assertIsNone(event.sync_error)

    def test_background_sync_marks_webhook_event_skipped_when_running(self):
        with Session(self.engine) as session:
            event = PluggyWebhookEvent(
                event="item/updated",
                item_id="item-sync",
                action="sync_scheduled",
                sync_status="scheduled",
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            event_id = event.id

        with (
            patch.object(webhook_routes, "engine", self.engine),
            patch.object(webhook_routes, "run_sync_item", side_effect=SyncAlreadyRunning()),
        ):
            webhook_routes._do_sync_item("item-sync", event_id)

        with Session(self.engine) as session:
            event = session.get(PluggyWebhookEvent, event_id)
        self.assertEqual(event.sync_status, "skipped_already_running")
        self.assertIsNotNone(event.sync_started_at)
        self.assertIsNotNone(event.sync_finished_at)

    def test_background_sync_marks_webhook_event_failed(self):
        with Session(self.engine) as session:
            event = PluggyWebhookEvent(
                event="item/updated",
                item_id="item-sync",
                action="sync_scheduled",
                sync_status="scheduled",
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            event_id = event.id

        with (
            patch.object(webhook_routes, "engine", self.engine),
            patch.object(webhook_routes, "run_sync_item", side_effect=RuntimeError("boom")),
        ):
            webhook_routes._do_sync_item("item-sync", event_id)

        with Session(self.engine) as session:
            event = session.get(PluggyWebhookEvent, event_id)
        self.assertEqual(event.sync_status, "failed")
        self.assertEqual(event.sync_error, "boom")

    def test_background_sync_all_active_marks_webhook_event_completed(self):
        with Session(self.engine) as session:
            event = PluggyWebhookEvent(
                event="transactions/created",
                action="sync_scheduled_all_active",
                sync_status="scheduled",
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            event_id = event.id

        with (
            patch.object(webhook_routes, "engine", self.engine),
            patch.object(webhook_routes, "run_sync_item", return_value={"ok": True}) as mock_sync,
        ):
            webhook_routes._do_sync_items(["item-a", "item-b"], event_id)

        self.assertEqual([call.args[0] for call in mock_sync.call_args_list], ["item-a", "item-b"])
        with Session(self.engine) as session:
            event = session.get(PluggyWebhookEvent, event_id)
        self.assertEqual(event.sync_status, "completed")
        self.assertIsNotNone(event.sync_started_at)
        self.assertIsNotNone(event.sync_finished_at)

    def test_background_sync_all_active_marks_webhook_event_failed_if_any_item_fails(self):
        with Session(self.engine) as session:
            event = PluggyWebhookEvent(
                event="transactions/created",
                action="sync_scheduled_all_active",
                sync_status="scheduled",
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            event_id = event.id

        def fake_sync(item_id, session):
            if item_id == "item-b":
                raise RuntimeError("boom")
            return {"ok": True}

        with (
            patch.object(webhook_routes, "engine", self.engine),
            patch.object(webhook_routes, "run_sync_item", side_effect=fake_sync),
        ):
            webhook_routes._do_sync_items(["item-a", "item-b"], event_id)

        with Session(self.engine) as session:
            event = session.get(PluggyWebhookEvent, event_id)
        self.assertEqual(event.sync_status, "failed")
        self.assertIn("item-b: boom", event.sync_error)
