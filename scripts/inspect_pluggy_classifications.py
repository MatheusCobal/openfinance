#!/usr/bin/env python
"""Read-only diagnosis of persisted Pluggy transaction classifications."""

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
def _connect_args(database_url: str) -> dict:
    if make_url(database_url).get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    return {}


def _sanitize_description(description: str | None) -> str:
    words = (description or "").replace("\n", " ").split()
    if not words:
        return ""
    return " ".join(words[:3]) + (" ..." if len(words) > 3 else "")


def inspect(database_url: str, limit: int) -> list[dict]:
    engine = create_engine(
        database_url,
        echo=False,
        connect_args=_connect_args(database_url),
    )
    buckets: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "total_abs_amount": Decimal("0"),
            "example_sanitized_description": "",
        }
    )
    with engine.connect() as connection:
        columns = {
            column["name"]
            for column in sqlalchemy_inspect(connection).get_columns("transaction")
        }
        raw_category_sql = (
            "COALESCE(pluggy_raw_category, category)"
            if "pluggy_raw_category" in columns
            else "category"
        )
        rows = connection.execute(
            text(
                f"""
                SELECT {raw_category_sql} AS raw_category, amount, description
                FROM "transaction"
                """
            )
        ).mappings()
        for row in rows:
            key = row["raw_category"] or "<empty>"
            bucket = buckets[key]
            bucket["count"] += 1
            bucket["total_abs_amount"] += abs(Decimal(str(row["amount"])))
            if not bucket["example_sanitized_description"]:
                bucket["example_sanitized_description"] = _sanitize_description(
                    row["description"]
                )
    rows = [
        {
            "pluggy_raw_category": key,
            **value,
        }
        for key, value in buckets.items()
    ]
    return sorted(
        rows,
        key=lambda row: (-row["count"], row["pluggy_raw_category"]),
    )[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Group persisted Pluggy raw transaction categories without mutating data."
    )
    parser.add_argument("--db-url", default=database_settings.database_url)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    print("pluggy_raw_category | count | total_abs_amount | example_sanitized_description")
    for row in inspect(args.db_url, args.limit):
        print(
            f"{row['pluggy_raw_category']} | "
            f"{row['count']} | "
            f"{row['total_abs_amount']:.2f} | "
            f"{row['example_sanitized_description']}"
        )


if __name__ == "__main__":
    main()
