"""Per-user data isolation (Fase 6).

Proves that, when authentication is enabled, a request scoped to user B never
sees user A's financial data and cannot mutate it. The middleware session gate
(``session_is_valid``) is patched so the test exercises the per-user filtering
performed by the ``current_scope_user_id`` dependency + the service layer, not
the coarse gate (already covered by test_auth/test_security).
"""

import datetime
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.security as security
from app.auth import sessions as auth_sessions
from app.auth.passwords import hash_password
from app.auth.sessions import SESSION_COOKIE_NAME, create_session
from app.database import get_session
from app.main import app
from app.models import Account, ExpectedIncome, Item, Transaction, User


def _settings():
    return security.SecuritySettings(
        _env_file=None,
        openfinance_env="local",
        openfinance_require_auth=True,
        openfinance_public_health=True,
        openfinance_webhook_secret="",
    )


def _seed_user(db: Session, email: str) -> int:
    user = User(email=email, password_hash=hash_password("pw"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _seed_financials(db: Session, user_id: int, suffix: str) -> None:
    """One active CREDIT item + account + a single purchase transaction."""
    db.add(
        Item(id=f"item-{suffix}", user_id=user_id, connector_id=1, status="UPDATED")
    )
    db.add(
        Account(
            id=f"acc-{suffix}",
            user_id=user_id,
            item_id=f"item-{suffix}",
            name=f"Card {suffix}",
            type="CREDIT",
            is_active=True,
        )
    )
    db.add(
        Transaction(
            id=f"tx-{suffix}",
            user_id=user_id,
            account_id=f"acc-{suffix}",
            date=datetime.date.today(),
            amount=Decimal("100.00"),
            description=f"Purchase {suffix}",
        )
    )
    db.add(
        ExpectedIncome(
            user_id=user_id,
            description=f"Salary {suffix}",
            amount=Decimal("5000"),
            expected_day=5,
        )
    )
    db.commit()


class IsolationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            self.user_a = _seed_user(db, "a@example.com")
            self.user_b = _seed_user(db, "b@example.com")
            _seed_financials(db, self.user_a, "a")
            _seed_financials(db, self.user_b, "b")
            self.token_a = create_session(db, self.user_a).token
            self.token_b = create_session(db, self.user_b).token

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self._settings_patch = patch.object(security, "get_security_settings", _settings)
        self._settings_patch.start()
        # Gate passes; per-user filtering is what we're testing.
        self._gate_patch = patch.object(auth_sessions, "session_is_valid", lambda token: True)
        self._gate_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self._gate_patch.stop()
        self._settings_patch.stop()
        app.dependency_overrides.clear()

    def _as(self, token: str):
        self.client.cookies.set(SESSION_COOKIE_NAME, token)

    def test_transactions_are_isolated_per_user(self):
        self._as(self.token_a)
        rows_a = self.client.get("/transactions?account_type=ALL").json()
        ids_a = {row["id"] for row in rows_a}
        self.assertEqual(ids_a, {"tx-a"})

        self._as(self.token_b)
        rows_b = self.client.get("/transactions?account_type=ALL").json()
        ids_b = {row["id"] for row in rows_b}
        self.assertEqual(ids_b, {"tx-b"})

    def test_accounts_are_isolated_per_user(self):
        self._as(self.token_a)
        accounts_a = self.client.get("/accounts").json()
        self.assertEqual({a["id"] for a in accounts_a}, {"acc-a"})

        self._as(self.token_b)
        accounts_b = self.client.get("/accounts").json()
        self.assertEqual({a["id"] for a in accounts_b}, {"acc-b"})

    def test_expected_income_is_isolated_per_user(self):
        self._as(self.token_a)
        income_a = self.client.get("/expected-income").json()
        self.assertEqual([e["description"] for e in income_a], ["Salary a"])

        self._as(self.token_b)
        income_b = self.client.get("/expected-income").json()
        self.assertEqual([e["description"] for e in income_b], ["Salary b"])

    def test_user_cannot_delete_other_users_expected_income(self):
        # Resolve user A's expected-income id.
        self._as(self.token_a)
        a_entry_id = self.client.get("/expected-income").json()[0]["id"]

        # User B attempts to delete A's entry → 404, and A's entry survives.
        self._as(self.token_b)
        resp = self.client.delete(f"/expected-income/{a_entry_id}")
        self.assertEqual(resp.status_code, 404)

        self._as(self.token_a)
        still_there = self.client.get("/expected-income").json()
        self.assertEqual(len(still_there), 1)


if __name__ == "__main__":
    unittest.main()
