"""pluggy_snapshot

Persist Pluggy-native data (account balances, bankData, creditData,
credit-card bills, investments and investment transactions) so the
dashboard/reserve/credit-card numbers come from the bank, not from
re-deriving them from raw transactions.

Revision ID: e1f5a8c92d10
Revises: 30d7b2b7997f
Create Date: 2026-05-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "e1f5a8c92d10"
down_revision: Union[str, Sequence[str], None] = "30d7b2b7997f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columns we add to ``account``. Each column is nullable on purpose:
#   - many Pluggy connectors don't expose every field
#   - existing rows would need a default otherwise
ACCOUNT_COLUMNS: list[sa.Column] = [
    sa.Column("balance", sa.Numeric(), nullable=True),
    sa.Column("currency_code", sa.String(), nullable=True),
    sa.Column("owner", sa.String(), nullable=True),
    sa.Column("tax_number", sa.String(), nullable=True),
    sa.Column("bank_closing_balance", sa.Numeric(), nullable=True),
    sa.Column("bank_automatically_invested_balance", sa.Numeric(), nullable=True),
    sa.Column("bank_overdraft_contracted_limit", sa.Numeric(), nullable=True),
    sa.Column("bank_overdraft_used_limit", sa.Numeric(), nullable=True),
    sa.Column("credit_level", sa.String(), nullable=True),
    sa.Column("credit_brand", sa.String(), nullable=True),
    sa.Column("credit_balance_close_date", sa.Date(), nullable=True),
    sa.Column("credit_balance_due_date", sa.Date(), nullable=True),
    sa.Column("credit_available_limit", sa.Numeric(), nullable=True),
    sa.Column("credit_limit", sa.Numeric(), nullable=True),
    sa.Column("credit_minimum_payment", sa.Numeric(), nullable=True),
    sa.Column("credit_status", sa.String(), nullable=True),
    sa.Column("credit_holder_type", sa.String(), nullable=True),
    sa.Column("balance_updated_at", sa.DateTime(), nullable=True),
]


def upgrade() -> None:
    with op.batch_alter_table("account") as batch:
        for column in ACCOUNT_COLUMNS:
            batch.add_column(column.copy())

    op.create_table(
        "creditcardbill",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("account_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Numeric(), nullable=True),
        sa.Column("minimum_payment_amount", sa.Numeric(), nullable=True),
        sa.Column("allows_installments", sa.Boolean(), nullable=True),
        sa.Column("payments_total", sa.Numeric(), nullable=True),
        sa.Column("finance_charges_total", sa.Numeric(), nullable=True),
        sa.Column("currency_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creditcardbill_account_id", "creditcardbill", ["account_id"], unique=False
    )
    op.create_index(
        "ix_creditcardbill_due_date", "creditcardbill", ["due_date"], unique=False
    )

    op.create_table(
        "investment",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("item_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("subtype", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("balance", sa.Numeric(), nullable=True),
        sa.Column("amount_original", sa.Numeric(), nullable=True),
        sa.Column("amount_profit", sa.Numeric(), nullable=True),
        sa.Column("amount_withdrawal", sa.Numeric(), nullable=True),
        sa.Column("rate", sa.Numeric(), nullable=True),
        sa.Column("rate_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("fixed_annual_rate", sa.Numeric(), nullable=True),
        sa.Column("issuer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("currency_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("provider_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investment_item_id", "investment", ["item_id"], unique=False
    )
    op.create_index(
        "ix_investment_type", "investment", ["type"], unique=False
    )

    op.create_table(
        "investmenttransaction",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "investment_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("net_amount", sa.Numeric(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("currency_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["investment_id"], ["investment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investmenttransaction_investment_id",
        "investmenttransaction",
        ["investment_id"],
        unique=False,
    )
    op.create_index(
        "ix_investmenttransaction_date",
        "investmenttransaction",
        ["date"],
        unique=False,
    )
    op.create_index(
        "ix_investmenttransaction_type",
        "investmenttransaction",
        ["type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investmenttransaction_type", table_name="investmenttransaction"
    )
    op.drop_index(
        "ix_investmenttransaction_date", table_name="investmenttransaction"
    )
    op.drop_index(
        "ix_investmenttransaction_investment_id",
        table_name="investmenttransaction",
    )
    op.drop_table("investmenttransaction")

    op.drop_index("ix_investment_type", table_name="investment")
    op.drop_index("ix_investment_item_id", table_name="investment")
    op.drop_table("investment")

    op.drop_index("ix_creditcardbill_due_date", table_name="creditcardbill")
    op.drop_index("ix_creditcardbill_account_id", table_name="creditcardbill")
    op.drop_table("creditcardbill")

    with op.batch_alter_table("account") as batch:
        for column in reversed(ACCOUNT_COLUMNS):
            batch.drop_column(column.name)
