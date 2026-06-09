"""transaction_classification_fields

Add explicit Pluggy raw classification fields and deterministic internal
classification fields to transactions. The migration is additive only: it does
not drop or rewrite legacy category storage.

Revision ID: b7e4d2c9a10f
Revises: a9b8c7d6e5f4
Create Date: 2026-06-09 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e4d2c9a10f"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STRING_COLUMNS = (
    "pluggy_raw_category",
    "pluggy_raw_subcategory",
    "pluggy_raw_type",
    "pluggy_merchant",
    "internal_category",
    "cashflow_type",
    "classification_source",
    "classification_confidence",
    "classification_rule_key",
)
BOOLEAN_COLUMNS = (
    "is_user_overridden",
    "ignored_from_totals",
)


def upgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        for column_name in STRING_COLUMNS:
            batch.add_column(sa.Column(column_name, sa.String(), nullable=True))
        for column_name in BOOLEAN_COLUMNS:
            batch.add_column(
                sa.Column(
                    column_name,
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    for column_name in STRING_COLUMNS + BOOLEAN_COLUMNS:
        op.create_index(
            f"ix_transaction_{column_name}",
            "transaction",
            [column_name],
            if_not_exists=True,
        )


def downgrade() -> None:
    for column_name in reversed(STRING_COLUMNS + BOOLEAN_COLUMNS):
        op.drop_index(f"ix_transaction_{column_name}", table_name="transaction")
    with op.batch_alter_table("transaction") as batch:
        for column_name in reversed(BOOLEAN_COLUMNS):
            batch.drop_column(column_name)
        for column_name in reversed(STRING_COLUMNS):
            batch.drop_column(column_name)
