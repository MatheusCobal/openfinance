"""persist nested Pluggy credit-card transaction metadata

Revision ID: 2b6f4a8c1d90
Revises: 0f1e2d3c4b5a
Create Date: 2026-08-04 18:30:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "2b6f4a8c1d90"
down_revision: Union[str, Sequence[str], None] = "0f1e2d3c4b5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transaction",
        sa.Column("bill_forecast_month", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "transaction",
        sa.Column("credit_card_last_four", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "transaction",
        sa.Column("purchase_date", sa.Date(), nullable=True),
    )
    op.create_index(
        op.f("ix_transaction_bill_forecast_month"),
        "transaction",
        ["bill_forecast_month"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction_credit_card_last_four"),
        "transaction",
        ["credit_card_last_four"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction_purchase_date"),
        "transaction",
        ["purchase_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_transaction_purchase_date"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_credit_card_last_four"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_bill_forecast_month"), table_name="transaction")
    op.drop_column("transaction", "purchase_date")
    op.drop_column("transaction", "credit_card_last_four")
    op.drop_column("transaction", "bill_forecast_month")
