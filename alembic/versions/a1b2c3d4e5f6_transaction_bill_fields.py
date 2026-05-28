"""transaction_bill_fields

Add Pluggy bill/installment metadata columns to the transaction table so
purchases can be linked to their official credit-card bill and installment
plan without recomputing that from transaction text.

Revision ID: a1b2c3d4e5f6
Revises: e1f5a8c92d10
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e1f5a8c92d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRANSACTION_COLUMNS: list[sa.Column] = [
    sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("bill_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("installment_number", sa.Integer(), nullable=True),
    sa.Column("total_installments", sa.Integer(), nullable=True),
    sa.Column("total_amount", sa.Numeric(), nullable=True),
]


def upgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        for column in TRANSACTION_COLUMNS:
            batch.add_column(column.copy())
    op.create_index("ix_transaction_bill_id", "transaction", ["bill_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transaction_bill_id", table_name="transaction")
    with op.batch_alter_table("transaction") as batch:
        for column in reversed(TRANSACTION_COLUMNS):
            batch.drop_column(column.name)
