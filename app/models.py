import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Item(SQLModel, table=True):
    id: str = Field(primary_key=True)
    connector_id: int
    connector_name: Optional[str] = None
    status: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class Account(SQLModel, table=True):
    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    name: str
    type: str
    subtype: Optional[str] = None
    marketing_name: Optional[str] = None
    number: Optional[str] = None


class AccountSync(SQLModel, table=True):
    account_id: str = Field(foreign_key="account.id", primary_key=True)
    last_synced_at: Optional[datetime.datetime] = None
    last_transaction_date: Optional[datetime.date] = None


class Transaction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    date: datetime.date = Field(index=True)
    amount: Decimal
    description: str
    category: Optional[str] = None
    currency_code: str = "BRL"


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    color: str
    sort_order: int = 0


class CategoryRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pluggy_category: str = Field(unique=True, index=True)
    category_id: int = Field(foreign_key="category.id", index=True)


class DescriptionCategoryRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pattern: str
    pattern_normalized: str = Field(unique=True, index=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class IgnoredDescriptionRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pattern: str
    pattern_normalized: str = Field(unique=True, index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class CreditCardInvoiceMonth(SQLModel, table=True):
    year_month: str = Field(primary_key=True, index=True)
    total: Decimal = Decimal("0")
    payment_count: int = 0
    captured_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class BankIncomeMonth(SQLModel, table=True):
    year_month: str = Field(primary_key=True, index=True)
    total: Decimal = Decimal("0")
    income_count: int = 0
    captured_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class BankIncomeExclusionRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pluggy_category: Optional[str] = Field(default=None, index=True)
    pattern: Optional[str] = None
    pattern_normalized: Optional[str] = Field(default=None, index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class MonthlyBalanceMonth(SQLModel, table=True):
    year_month: str = Field(primary_key=True, index=True)
    income: Decimal = Decimal("0")
    card_spend: Decimal = Decimal("0")
    invoice_paid: Decimal = Decimal("0")
    net_by_purchase_month: Decimal = Decimal("0")
    net_cashflow: Decimal = Decimal("0")
    income_count: int = 0
    card_spend_count: int = 0
    invoice_payment_count: int = 0
    captured_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", unique=True, index=True)
    monthly_target: Decimal


class BudgetOverride(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("category_id", "year_month", name="uq_budgetoverride_month"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    year_month: str = Field(index=True)
    monthly_target: Decimal
