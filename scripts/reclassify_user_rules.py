#!/usr/bin/env python
"""Reclassify transactions applying 10D-D user-defined rules.

Runs the full deterministic classifier (user rules > Pluggy rules > system
rules > fallback) over every non-duplicate transaction and reports — or, with
--apply, persists — the resulting classification fields.

Safety guarantees:
  * --dry-run is the default; --apply additionally requires --yes-i-backed-up.
  * Manual per-transaction overrides (is_user_overridden) are always skipped.
  * Raw Pluggy fields and all financial fields are never written.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import database_settings  # noqa: E402
from app.models import Account, Transaction  # noqa: E402
from app.services.transaction_classifier import classify_transaction  # noqa: E402
from app.services.transactions import _non_duplicate_clause  # noqa: E402
from app.services.user_classification_rules import (  # noqa: E402
    load_compiled_user_rules,
)

# Only these classification fields are ever written. Raw Pluggy and financial
# columns are deliberately absent from this list.
CLASSIFICATION_FIELDS = (
    "internal_category",
    "cashflow_type",
    "classification_source",
    "classification_confidence",
    "classification_rule_key",
    "ignored_from_totals",
)


def _connect_args(database_url: str) -> dict:
    if make_url(database_url).get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    return {}


def reclassify_user_rules(database_url: str, apply: bool) -> dict:
    engine = create_engine(
        database_url,
        echo=False,
        connect_args=_connect_args(database_url),
    )
    with engine.connect() as connection:
        tables = set(sqlalchemy_inspect(connection).get_table_names())
    if "user_classification_rules" not in tables:
        if apply:
            raise RuntimeError(
                "user_classification_rules table is missing; run the 10D-D Alembic "
                "migration before --apply"
            )
        return {
            "mode": "dry-run",
            "analyzed": 0,
            "skipped_overrides": 0,
            "would_change": 0,
            "changed": 0,
            "still_outros": 0,
            "matched_by_rule": Counter(),
            "transitions": Counter(),
            "user_rule_count": 0,
            "table_missing": True,
        }

    analyzed = 0
    skipped_overrides = 0
    would_change = 0
    changed = 0
    still_outros = 0
    matched_by_rule: Counter = Counter()
    transitions: Counter = Counter()

    with Session(engine) as session:
        accounts = {account.id: account for account in session.exec(select(Account)).all()}
        user_rules = load_compiled_user_rules(session)
        transactions = session.exec(
            select(Transaction).where(_non_duplicate_clause()).order_by(Transaction.date.asc())
        ).all()

        for tx in transactions:
            if tx.is_user_overridden:
                skipped_overrides += 1
                continue
            analyzed += 1
            account = accounts.get(tx.account_id)
            account_type = account.type if account is not None else None
            result = classify_transaction(
                tx,
                account_type=account_type,
                user_rules=user_rules,
            )
            values = result.transaction_values()

            if result.source == "user_rule":
                matched_by_rule[result.matched_rule] += 1
            if values["internal_category"] == "Outros":
                still_outros += 1

            row_changed = any(getattr(tx, field) != value for field, value in values.items())
            if row_changed:
                would_change += 1
                old_category = tx.internal_category or "<unset>"
                old_cashflow = tx.cashflow_type or "<unset>"
                transitions[
                    (
                        old_category,
                        old_cashflow,
                        values["internal_category"],
                        values["cashflow_type"],
                    )
                ] += 1
                if apply:
                    for field in CLASSIFICATION_FIELDS:
                        setattr(tx, field, values[field])
                    session.add(tx)
                    changed += 1

        if apply:
            session.commit()

    return {
        "mode": "apply" if apply else "dry-run",
        "analyzed": analyzed,
        "skipped_overrides": skipped_overrides,
        "would_change": would_change,
        "changed": changed,
        "still_outros": still_outros,
        "matched_by_rule": matched_by_rule,
        "transitions": transitions,
        "user_rule_count": len(user_rules),
        "table_missing": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply user-defined (10D-D) classification rules. "
            "Run a database backup before --apply."
        )
    )
    parser.add_argument("--db-url", default=database_settings.database_url)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    mode.add_argument("--apply", action="store_true", help="Write classification fields")
    parser.add_argument(
        "--yes-i-backed-up",
        action="store_true",
        help="Required with --apply to confirm a backup/recovery path exists",
    )
    args = parser.parse_args()

    if args.apply and not args.yes_i_backed_up:
        parser.error("--apply requires --yes-i-backed-up")
    apply = bool(args.apply)
    result = reclassify_user_rules(args.db_url, apply=apply)

    print(f"mode: {result['mode']}")
    if result.get("table_missing"):
        print("warning: user_classification_rules table is missing; run Alembic migration")
    print(f"user_rules_loaded: {result['user_rule_count']}")
    print(f"analyzed: {result['analyzed']}")
    print(f"skipped_overrides: {result['skipped_overrides']}")
    print(f"would_change: {result['would_change']}")
    print(f"changed: {result['changed']}")
    print(f"still_outros: {result['still_outros']}")
    print("matched_by_user_rule | count")
    for rule_key, count in result["matched_by_rule"].most_common():
        print(f"{rule_key} | {count}")
    print("transition (old_internal/old_cashflow -> new_internal/new_cashflow) | count")
    for (old_category, old_cashflow, new_category, new_cashflow), count in result[
        "transitions"
    ].most_common():
        print(f"{old_category}/{old_cashflow} -> {new_category}/{new_cashflow} | {count}")


if __name__ == "__main__":
    main()
