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
    bind = op.get_bind()
    for table in _TABLES:
        inspector = sa.inspect(bind)
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "user_id" not in columns:
            op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))

        index_name = f"ix_{table}_user_id"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if index_name not in indexes:
            op.create_index(index_name, table, ["user_id"], unique=False)

        financial_table = sa.table(table, sa.column("user_id", sa.Integer()))
        op.execute(
            financial_table.update()
            .where(financial_table.c.user_id.is_(None))
            .values(user_id=1)
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_TABLES):
        index_name = f"ix_{table}_user_id"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)

        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "user_id" in columns:
            op.drop_column(table, "user_id")
