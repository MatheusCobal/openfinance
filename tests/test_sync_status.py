import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, AccountSync, CreditCardBill, Item, Transaction
from app.services.sync import SyncAlreadyRunning
from app.services.sync_status import get_sync_status


class SyncStatusTest(unittest.TestCase):
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

    def test_empty_database_returns_unknown_status_and_zero_totals(self):
        with Session(self.engine) as session:
            status = get_sync_status(session)

        self.assertIsNone(status["last_sync_at"])
        self.assertEqual(status["last_sync_status"], "unknown")
        self.assertEqual(status["last_sync_status_source"], "not_tracked")
        self.assertIsNone(status["last_sync_error"])
        self.assertEqual(status["items"]["total"], 0)
        self.assertEqual(status["items"]["running"], 0)
        self.assertEqual(status["items"]["stale"], 0)
        self.assertEqual(status["accounts"]["total"], 0)
        self.assertEqual(status["failed_accounts"], [])
        self.assertEqual(status["sync_locks"], {"running": 0, "stale": 0})
        self.assertEqual(status["transactions"]["total"], 0)
        self.assertEqual(status["credit_card_bills"]["total"], 0)

    def test_status_summarizes_items_accounts_transactions_and_bills(self):
        started_at = datetime(2026, 6, 1, 18, 29, 30)
        finished_at = datetime(2026, 6, 1, 18, 30, 0)
        account_synced_at = datetime(2026, 6, 1, 18, 30, 5)

        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-active",
                    connector_id=200,
                    connector_name="MeuPluggy",
                    status="UPDATED",
                    sync_started_at=started_at,
                    sync_finished_at=finished_at,
                    is_active=True,
                )
            )
            session.add(
                Item(
                    id="item-inactive",
                    connector_id=201,
                    connector_name="Old Bank",
                    status="LOGIN_ERROR",
                    is_active=False,
                    deactivated_at=finished_at,
                )
            )
            session.add(
                Account(
                    id="credit-1",
                    item_id="item-active",
                    name="Credit",
                    type="CREDIT",
                    is_active=True,
                )
            )
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-active",
                    name="Bank",
                    type="BANK",
                    is_active=True,
                )
            )
            session.add(
                Account(
                    id="bank-old",
                    item_id="item-inactive",
                    name="Old Bank",
                    type="BANK",
                    is_active=False,
                )
            )
            session.add(
                AccountSync(
                    account_id="credit-1",
                    last_synced_at=account_synced_at,
                    last_transaction_date=date(2026, 6, 1),
                )
            )
            session.add(
                Transaction(
                    id="tx-old",
                    account_id="bank-1",
                    date=date(2024, 1, 1),
                    amount=Decimal("100"),
                    description="Old income",
                )
            )
            session.add(
                Transaction(
                    id="tx-new",
                    account_id="credit-1",
                    date=date(2026, 6, 1),
                    amount=Decimal("-50"),
                    description="New purchase",
                )
            )
            session.add(
                CreditCardBill(
                    id="bill-old",
                    account_id="credit-1",
                    due_date=date(2026, 5, 6),
                )
            )
            session.add(
                CreditCardBill(
                    id="bill-new",
                    account_id="credit-1",
                    due_date=date(2026, 7, 6),
                )
            )
            session.commit()

            status = get_sync_status(session)

        self.assertEqual(status["last_sync_at"], account_synced_at.isoformat())
        self.assertEqual(status["last_sync_status"], "success")
        self.assertEqual(
            status["last_sync_status_source"],
            "estimated_from_sync_timestamps",
        )
        self.assertEqual(status["last_sync_duration_seconds"], 30.0)
        self.assertEqual(status["items"]["total"], 2)
        self.assertEqual(status["items"]["active"], 1)
        self.assertEqual(status["items"]["inactive"], 1)
        self.assertEqual(status["items"]["updated"], 1)
        self.assertEqual(status["items"]["running"], 0)
        self.assertEqual(status["items"]["stale"], 0)
        self.assertEqual(status["sync_locks"], {"running": 0, "stale": 0})
        self.assertEqual(status["accounts"]["total"], 3)
        self.assertEqual(status["accounts"]["active"], 2)
        self.assertEqual(status["accounts"]["inactive"], 1)
        self.assertEqual(status["accounts"]["credit"], 1)
        self.assertEqual(status["accounts"]["bank"], 2)
        self.assertEqual(status["transactions"]["total"], 2)
        self.assertEqual(status["transactions"]["oldest_date"], "2024-01-01")
        self.assertEqual(status["transactions"]["latest_date"], "2026-06-01")
        self.assertEqual(status["credit_card_bills"]["total"], 2)
        self.assertEqual(status["credit_card_bills"]["latest_due_date"], "2026-07-06")

    def test_status_reports_persisted_errors(self):
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-error",
                    connector_id=200,
                    status="LOGIN_ERROR",
                    sync_started_at=datetime.utcnow() - timedelta(minutes=1),
                    sync_finished_at=datetime.utcnow(),
                    last_sync_error="item/login_error | Invalid credentials",
                )
            )
            session.commit()

            status = get_sync_status(session)

        self.assertEqual(status["last_sync_status"], "error")
        self.assertEqual(status["last_sync_status_source"], "persisted_error")
        self.assertIn("Invalid credentials", status["last_sync_error"])
        self.assertEqual(status["items"]["error"], 1)

    def test_status_reports_failed_accounts(self):
        failed_at = datetime(2026, 6, 1, 18, 30)
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-error",
                    connector_id=200,
                    connector_name="MeuPluggy",
                    status="UPDATED",
                )
            )
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-error",
                    name="Checking",
                    type="BANK",
                )
            )
            session.add(
                AccountSync(
                    account_id="bank-1",
                    last_error="RuntimeError: pluggy 500",
                    last_error_at=failed_at,
                )
            )
            session.commit()

            status = get_sync_status(session)

        self.assertEqual(status["last_sync_status"], "error")
        self.assertEqual(status["accounts"]["error"], 1)
        self.assertEqual(
            status["failed_accounts"],
            [
                {
                    "account_id": "bank-1",
                    "item_id": "item-error",
                    "account_name": "Checking",
                    "account_type": "BANK",
                    "error": "RuntimeError: pluggy 500",
                    "last_error_at": failed_at.isoformat(),
                }
            ],
        )

    def test_status_reports_stale_lock_without_running(self):
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-stale",
                    connector_id=200,
                    status="UPDATED",
                    sync_started_at=datetime.utcnow() - timedelta(minutes=30),
                    sync_finished_at=None,
                )
            )
            session.commit()

            status = get_sync_status(session)

        self.assertEqual(status["last_sync_status"], "error")
        self.assertEqual(status["last_sync_status_source"], "stale_sync_lock")
        self.assertEqual(status["items"]["running"], 0)
        self.assertEqual(status["items"]["stale"], 1)
        self.assertEqual(status["sync_locks"], {"running": 0, "stale": 1})

    def test_endpoint_returns_sync_status_json(self):
        response = self.client.get("/sync/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["last_sync_status"], "unknown")
        self.assertEqual(data["items"]["total"], 0)
        self.assertEqual(data["accounts"]["total"], 0)
        self.assertEqual(data["transactions"]["total"], 0)
        self.assertEqual(data["credit_card_bills"]["total"], 0)

    def test_sync_health_reports_failed_accounts_and_lock_status(self):
        failed_at = datetime(2026, 6, 1, 18, 30)
        started_at = datetime.utcnow() - timedelta(minutes=30)
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-1",
                    connector_id=200,
                    connector_name="MeuPluggy",
                    status="UPDATED",
                    sync_started_at=started_at,
                    sync_finished_at=None,
                )
            )
            session.add(
                Account(
                    id="bank-1",
                    item_id="item-1",
                    name="Checking",
                    type="BANK",
                )
            )
            session.add(
                AccountSync(
                    account_id="bank-1",
                    last_error="RuntimeError: pluggy 500",
                    last_error_at=failed_at,
                )
            )
            session.commit()

        response = self.client.get("/sync/health")

        self.assertEqual(response.status_code, 200)
        health = response.json()
        self.assertEqual(len(health), 1)
        self.assertFalse(health[0]["is_running"])
        self.assertEqual(health[0]["sync_lock_status"], "stale")
        self.assertEqual(
            health[0]["failed_accounts"],
            [
                {
                    "account_id": "bank-1",
                    "account_name": "Checking",
                    "account_type": "BANK",
                    "error": "RuntimeError: pluggy 500",
                    "last_error_at": failed_at.isoformat(),
                }
            ],
        )

    def test_manual_sync_backs_up_before_running_service(self):
        calls = []
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.commit()

        with (
            patch(
                "app.routes.sync.backup_sqlite_database",
                side_effect=lambda *args, **kwargs: calls.append("backup"),
            ) as backup,
            patch(
                "app.routes.sync.run_sync_item",
                side_effect=lambda *args, **kwargs: calls.append("sync") or {"ok": True},
            ) as run_sync,
        ):
            response = self.client.post("/items/item-1/sync")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(calls, ["backup", "sync"])
        self.assertEqual(backup.call_args.args[1], "pluggy-sync-item-1")
        run_sync.assert_called_once()

    def test_manual_sync_backup_failure_does_not_start_sync(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.commit()

        with (
            patch(
                "app.routes.sync.backup_sqlite_database",
                side_effect=RuntimeError("disk full"),
            ),
            patch("app.routes.sync.logger"),
            patch("app.routes.sync.run_sync_item") as run_sync,
        ):
            response = self.client.post("/items/item-1/sync")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "Could not create SQLite backup before starting Pluggy sync.",
        )
        run_sync.assert_not_called()

    def test_manual_sync_continues_when_backup_returns_none(self):
        with Session(self.engine) as session:
            session.add(Item(id="item-1", connector_id=200, status="UPDATED"))
            session.commit()

        with (
            patch("app.routes.sync.backup_sqlite_database", return_value=None) as backup,
            patch("app.routes.sync.run_sync_item", return_value={"ok": True}) as run_sync,
        ):
            response = self.client.post("/items/item-1/sync")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        backup.assert_called_once()
        run_sync.assert_called_once()

    def test_manual_sync_running_lock_returns_409(self):
        with Session(self.engine) as session:
            session.add(
                Item(
                    id="item-1",
                    connector_id=200,
                    status="UPDATED",
                    sync_started_at=datetime.utcnow(),
                    sync_finished_at=None,
                )
            )
            session.commit()

        with (
            patch("app.routes.sync.backup_sqlite_database", return_value=None),
            patch(
                "app.routes.sync.run_sync_item",
                side_effect=SyncAlreadyRunning("busy"),
            ) as run_sync,
        ):
            response = self.client.post("/items/item-1/sync")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "sync already running for this item")
        run_sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
