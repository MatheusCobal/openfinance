import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import Account, AccountSync, CreditCardBill, Item, Transaction
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
        self.assertEqual(status["accounts"]["total"], 0)
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

    def test_endpoint_returns_sync_status_json(self):
        response = self.client.get("/sync/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["last_sync_status"], "unknown")
        self.assertEqual(data["items"]["total"], 0)
        self.assertEqual(data["accounts"]["total"], 0)
        self.assertEqual(data["transactions"]["total"], 0)
        self.assertEqual(data["credit_card_bills"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
