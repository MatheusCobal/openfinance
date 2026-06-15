"""variable_budgets

Revision ID: f7c1a2b3d4e5
Revises: e2f4a6b8c9d0
Create Date: 2026-06-13 00:00:00.000000

10D-C: monthly variable spending goals per category. Replaces the legacy
category budgets removed in 10D-A, rebuilt on top of the Pluggy-based
classification. One row = one category goal for one month.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7c1a2b3d4e5"
down_revision: Union[str, Sequence[str], None] = "e2f4a6b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "variable_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year_month", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("target_amount", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "year_month",
            "category",
            name="uq_variablebudget_month_category",
        ),
    )
    op.create_index(
        op.f("ix_variable_budgets_year_month"),
        "variable_budgets",
        ["year_month"],
        unique=False,
    )
    op.create_index(
        op.f("ix_variable_budgets_category"),
        "variable_budgets",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_variable_budgets_category"),
        table_name="variable_budgets",
    )
    op.drop_index(
        op.f("ix_variable_budgets_year_month"),
        table_name="variable_budgets",
    )
    op.drop_table("variable_budgets")
