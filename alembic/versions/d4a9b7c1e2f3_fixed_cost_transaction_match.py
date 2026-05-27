"""fixed_cost_transaction_match

Revision ID: d4a9b7c1e2f3
Revises: c3f7a2e51b90
Create Date: 2026-05-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a9b7c1e2f3"
down_revision: Union[str, Sequence[str], None] = "c3f7a2e51b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fixedcosttransactionmatch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixed_cost_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.String(), nullable=False),
        sa.Column("year_month", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fixed_cost_id"], ["fixedcost.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fixed_cost_id",
            "year_month",
            name="uq_fixedcosttransactionmatch_entry_month",
        ),
        sa.UniqueConstraint(
            "transaction_id",
            name="uq_fixedcosttransactionmatch_transaction",
        ),
    )
    op.create_index(
        op.f("ix_fixedcosttransactionmatch_fixed_cost_id"),
        "fixedcosttransactionmatch",
        ["fixed_cost_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fixedcosttransactionmatch_transaction_id"),
        "fixedcosttransactionmatch",
        ["transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fixedcosttransactionmatch_year_month"),
        "fixedcosttransactionmatch",
        ["year_month"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_fixedcosttransactionmatch_year_month"),
        table_name="fixedcosttransactionmatch",
    )
    op.drop_index(
        op.f("ix_fixedcosttransactionmatch_transaction_id"),
        table_name="fixedcosttransactionmatch",
    )
    op.drop_index(
        op.f("ix_fixedcosttransactionmatch_fixed_cost_id"),
        table_name="fixedcosttransactionmatch",
    )
    op.drop_table("fixedcosttransactionmatch")
