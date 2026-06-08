"""transaction_dedup_fields

Add dedupe_key, is_duplicate, duplicate_of_id to the transaction table.

These fields are populated off-line by scripts/mark_duplicate_transactions.py
and are never written during normal sync — the migration is therefore safe to
apply to a live database with existing data.

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-06-08 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use individual ALTER TABLE ADD COLUMN for SQLite compatibility.
    # SQLite's batch_alter_table creates a temp-table copy which can fail if
    # the table is large; ADD COLUMN is an O(1) metadata-only operation.
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(
            sa.Column("dedupe_key", sa.String(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "is_duplicate",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("duplicate_of_id", sa.String(), nullable=True)
        )

    # Create indexes after the batch so they are not duplicated.
    op.create_index(
        "ix_transaction_dedupe_key",
        "transaction",
        ["dedupe_key"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_transaction_is_duplicate",
        "transaction",
        ["is_duplicate"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_transaction_is_duplicate", "transaction")
    op.drop_index("ix_transaction_dedupe_key", "transaction")
    with op.batch_alter_table("transaction") as batch:
        batch.drop_column("duplicate_of_id")
        batch.drop_column("is_duplicate")
        batch.drop_column("dedupe_key")
