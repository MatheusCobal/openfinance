#!/usr/bin/env python
"""Read-only diagnosis of Pluggy transaction classifications.

Groups transactions by their raw Pluggy fields plus the *effective* internal
classification (persisted 10D-B fields when present, otherwise computed with
the current classifier). Never mutates data.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
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
from app.services.transaction_classifier import (  # noqa: E402
    ClassificationInput,
    classify_input,
)

SCOPES = {
    "credit": {"CREDIT"},
    "bank": {"BANK"},
    "all": None,
}


def _connect_args(database_url: str) -> dict:
    if make_url(database_url).get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    return {}


def _sanitize_description(description: str | None) -> str:
    words = (description or "").replace("\n", " ").split()
    if not words:
        return ""
    return " ".join(words[:3]) + (" ..." if len(words) > 3 else "")


def _effective_classification(row: dict, account_type: str | None) -> tuple[str, str]:
    """Persisted internal classification when complete, else computed live."""
    if (
        row.get("internal_category")
        and row.get("cashflow_type")
        and row.get("classification_source")
        and row.get("classification_confidence")
    ):
        return row["internal_category"], row["cashflow_type"]
    amount = row.get("amount")
    result = classify_input(
        ClassificationInput(
            pluggy_raw_category=row.get("pluggy_raw_category") or row.get("category"),
            pluggy_raw_subcategory=row.get("pluggy_raw_subcategory"),
            pluggy_raw_type=row.get("pluggy_raw_type"),
            pluggy_merchant=row.get("pluggy_merchant"),
            description=row.get("description"),
            amount=Decimal(str(amount)) if amount is not None else None,
            account_type=account_type,
            is_user_overridden=bool(row.get("is_user_overridden") or False),
        )
    )
    return result.internal_category, result.cashflow_type


def inspect(
    database_url: str,
    limit: int,
    scope: str = "all",
    only_outros: bool = False,
    sort_by: str = "count",
) -> tuple[list[dict], dict]:
    engine = create_engine(
        database_url,
        echo=False,
        connect_args=_connect_args(database_url),
    )
    scope_types = SCOPES[scope]
    buckets: dict[tuple, dict] = defaultdict(
        lambda: {
            "count": 0,
            "total_abs_amount": Decimal("0"),
            "example_sanitized_description": "",
        }
    )
    summary = {"transactions": 0, "outros": 0, "unknown_cashflow": 0}
    with engine.connect() as connection:
        columns = {
            column["name"] for column in sqlalchemy_inspect(connection).get_columns("transaction")
        }
        account_rows = connection.execute(text('SELECT id, type FROM "account"')).mappings()
        account_types = {row["id"]: row["type"] for row in account_rows}

        select_columns = ["id", "account_id", "amount", "description", "category"]
        for optional in (
            "pluggy_raw_category",
            "pluggy_raw_subcategory",
            "pluggy_raw_type",
            "pluggy_merchant",
            "internal_category",
            "cashflow_type",
            "classification_source",
            "classification_confidence",
            "is_user_overridden",
        ):
            if optional in columns:
                select_columns.append(optional)
        rows = connection.execute(
            text("SELECT " + ", ".join(select_columns) + ' FROM "transaction"')
        ).mappings()
        for row in rows:
            row_dict = dict(row)
            account_type = account_types.get(row_dict["account_id"])
            if scope_types is not None and account_type not in scope_types:
                continue
            internal_category, cashflow_type = _effective_classification(row_dict, account_type)
            summary["transactions"] += 1
            if internal_category == "Outros":
                summary["outros"] += 1
            if cashflow_type == "unknown":
                summary["unknown_cashflow"] += 1
            if only_outros and internal_category != "Outros":
                continue
            key = (
                row_dict.get("pluggy_raw_category") or row_dict.get("category") or "<empty>",
                row_dict.get("pluggy_raw_subcategory") or "<empty>",
                row_dict.get("pluggy_raw_type") or "<empty>",
                internal_category,
                cashflow_type,
            )
            bucket = buckets[key]
            bucket["count"] += 1
            bucket["total_abs_amount"] += abs(Decimal(str(row_dict["amount"])))
            if not bucket["example_sanitized_description"]:
                bucket["example_sanitized_description"] = _sanitize_description(
                    row_dict["description"]
                )

    output_rows = [
        {
            "pluggy_raw_category": key[0],
            "pluggy_raw_subcategory": key[1],
            "pluggy_raw_type": key[2],
            "internal_category": key[3],
            "cashflow_type": key[4],
            **value,
        }
        for key, value in buckets.items()
    ]
    sort_key = (
        (lambda row: (-row["total_abs_amount"], -row["count"]))
        if sort_by == "amount"
        else (lambda row: (-row["count"], -row["total_abs_amount"]))
    )
    return sorted(output_rows, key=sort_key)[:limit], summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Group Pluggy raw classifications without mutating data."
    )
    parser.add_argument("--db-url", default=database_settings.database_url)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--scope", choices=sorted(SCOPES), default="all")
    parser.add_argument(
        "--only-outros",
        action="store_true",
        help="Show only buckets whose effective internal_category is Outros",
    )
    parser.add_argument("--sort-by", choices=("count", "amount"), default="count")
    args = parser.parse_args()

    rows, summary = inspect(
        args.db_url,
        args.limit,
        scope=args.scope,
        only_outros=args.only_outros,
        sort_by=args.sort_by,
    )
    print(
        f"scope: {args.scope} | transactions: {summary['transactions']} | "
        f"outros: {summary['outros']} | unknown_cashflow: {summary['unknown_cashflow']}"
    )
    print(
        "pluggy_raw_category | pluggy_raw_subcategory | pluggy_raw_type | "
        "internal_category | cashflow_type | count | total_abs_amount | example"
    )
    for row in rows:
        print(
            f"{row['pluggy_raw_category']} | "
            f"{row['pluggy_raw_subcategory']} | "
            f"{row['pluggy_raw_type']} | "
            f"{row['internal_category']} | "
            f"{row['cashflow_type']} | "
            f"{row['count']} | "
            f"{row['total_abs_amount']:.2f} | "
            f"{row['example_sanitized_description']}"
        )


if __name__ == "__main__":
    main()
