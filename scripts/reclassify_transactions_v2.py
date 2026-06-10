#!/usr/bin/env python
"""Reclassify transactions with the 10D-B Pluggy-based classifier."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import inspect as sqlalchemy_inspect, text
from sqlalchemy.engine import make_url
from sqlmodel import create_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import database_settings  # noqa: E402
from app.services.transaction_classifier import ClassificationInput, classify_input  # noqa: E402


CLASSIFICATION_COLUMNS = (
    "pluggy_raw_category",
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


def _classification_values(row: dict, account_type: str | None) -> dict:
    raw_category = row.get("pluggy_raw_category") or row.get("category")
    amount = row.get("amount")
    result = classify_input(
        ClassificationInput(
            pluggy_raw_category=raw_category,
            pluggy_raw_subcategory=row.get("pluggy_raw_subcategory"),
            pluggy_raw_type=row.get("pluggy_raw_type"),
            pluggy_merchant=row.get("pluggy_merchant"),
            description=row.get("description"),
            amount=Decimal(str(amount)) if amount is not None else None,
            account_type=account_type,
            is_user_overridden=bool(row.get("is_user_overridden") or False),
        )
    )
    values = result.transaction_values()
    values["pluggy_raw_category"] = raw_category
    return values


def _needs_update(row: dict, values: dict) -> bool:
    return any(row.get(field) != value for field, value in values.items())


def reclassify(database_url: str, apply: bool) -> dict:
    engine = create_engine(
        database_url,
        echo=False,
        connect_args=_connect_args(database_url),
    )
    changed = 0
    skipped_overrides = 0
    no_longer_outros = 0
    still_outros = 0
    totals = Counter()
    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in sqlalchemy_inspect(connection).get_columns("transaction")
        }
        missing_columns = set(CLASSIFICATION_COLUMNS) - columns
        if apply and missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise RuntimeError(
                "classification columns are missing; run the additive Alembic "
                f"migration before --apply ({missing})"
            )
        account_rows = connection.execute(text('SELECT id, type FROM "account"')).mappings()
        account_types = {row["id"]: row["type"] for row in account_rows}
        select_columns = [
            "id",
            "account_id",
            "date",
            "amount",
            "description",
            "category",
        ]
        for optional in (
            "pluggy_raw_category",
            "pluggy_raw_subcategory",
            "pluggy_raw_type",
            "pluggy_merchant",
            "internal_category",
            "cashflow_type",
            "classification_source",
            "classification_confidence",
            "classification_rule_key",
            "is_user_overridden",
            "ignored_from_totals",
        ):
            if optional in columns:
                select_columns.append(optional)
        rows = connection.execute(
            text(
                "SELECT "
                + ", ".join(select_columns)
                + ' FROM "transaction" ORDER BY date ASC'
            )
        ).mappings()
        for row in rows:
            row_dict = dict(row)
            account_type = account_types.get(row_dict["account_id"])
            if row_dict.get("is_user_overridden"):
                skipped_overrides += 1
                continue
            values = _classification_values(row_dict, account_type)
            totals[(values["internal_category"], values["cashflow_type"])] += 1
            if values["internal_category"] == "Outros":
                still_outros += 1
            elif row_dict.get("internal_category") == "Outros":
                no_longer_outros += 1
            if not _needs_update(row_dict, values):
                continue
            changed += 1
            if apply:
                connection.execute(
                    text(
                        """
                        UPDATE "transaction"
                        SET pluggy_raw_category = :pluggy_raw_category,
                            internal_category = :internal_category,
                            cashflow_type = :cashflow_type,
                            classification_source = :classification_source,
                            classification_confidence = :classification_confidence,
                            classification_rule_key = :classification_rule_key,
                            ignored_from_totals = :ignored_from_totals
                        WHERE id = :id
                        """
                    ),
                    {
                        **values,
                        "ignored_from_totals": bool(values["ignored_from_totals"]),
                        "id": row_dict["id"],
                    },
                )
    return {
        "mode": "apply" if apply else "dry-run",
        "would_change": changed,
        "changed": changed if apply else 0,
        "skipped_overrides": skipped_overrides,
        "no_longer_outros": no_longer_outros,
        "still_outros": still_outros,
        "buckets": totals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply deterministic 10D-B classification fields. "
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
    result = reclassify(args.db_url, apply=apply)
    print(f"mode: {result['mode']}")
    print(f"would_change: {result['would_change']}")
    print(f"changed: {result['changed']}")
    print(f"skipped_overrides: {result['skipped_overrides']}")
    print(f"no_longer_outros: {result['no_longer_outros']}")
    print(f"still_outros: {result['still_outros']}")
    print("internal_category | cashflow_type | count")
    for (category, cashflow_type), count in result["buckets"].most_common():
        print(f"{category} | {cashflow_type} | {count}")


if __name__ == "__main__":
    main()
