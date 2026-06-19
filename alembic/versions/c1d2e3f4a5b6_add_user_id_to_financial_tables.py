"""add user_id to financial tables

Revision ID: c1d2e3f4a5b6
Revises: b9d4e1f6a2c3
Create Date: 2026-06-19 00:00:00.000000

Adds a nullable ``user_id`` column (no FK constraint — avoids SQLite table
rebuilds) to every financial table, then backfills it to 1 so existing rows
are owned by the first (and currently only) user.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9d4e1f6a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = [
    "item",
    "account",
    "creditcardbill",
    "investment",
    "investmenttransaction",
    "accountsync",
    "pluggy_webhook_events",
    "transaction",
    "ignoreddescriptionrule",
    "user_classification_rules",
    "creditcardinvoicemonth",
    "bankincomemonth",
    "bankincomeexclusionrule",
    "bankcashflowexclusionrule",
    "monthlybalancemonth",
    "expectedincome",
    "expectedincomeoverride",
    "fixedcostcategory",
    "fixedcost",
    "fixedcostoverride",
    "fixedcosttransactionmatch",
    "variable_budgets",
]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"], unique=False)
        op.execute(f"UPDATE {table} SET user_id = 1")  # noqa: S608


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_column(table, "user_id")
