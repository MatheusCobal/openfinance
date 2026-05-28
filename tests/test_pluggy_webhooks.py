import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Item


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

    # --- 1. item/updated with itemId → sync_scheduled ---

    def test_item_updated_schedules_sync(self):
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
        mock_sync.assert_called_once_with("item-1")

    # --- 2. transactions/created with itemId → sync_scheduled ---

    def test_transactions_created_schedules_sync(self):
        with patch("app.routes.pluggy_webhooks._do_sync_item") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={"event": "transactions/created", "itemId": "item-2"},
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "sync_scheduled")
        mock_sync.assert_called_once_with("item-2")

    # --- 3. item/error with existing Item → status_recorded ---

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

    # --- 4. unknown event → ignored ---

    def test_unknown_event_is_ignored(self):
        resp = self.client.post(
            "/webhooks/pluggy",
            json={"event": "some/unknown_event", "itemId": "item-x"},
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "ignored")

    # --- 5. sync event without itemId → missing_item_id, no sync call ---

    def test_sync_event_without_item_id(self):
        with patch("app.routes.pluggy_webhooks._do_sync_item") as mock_sync:
            resp = self.client.post(
                "/webhooks/pluggy",
                json={"event": "item/updated"},
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["action"], "missing_item_id")
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
                mock_sync.assert_called_once_with("item-x")
