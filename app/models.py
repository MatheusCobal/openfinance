import datetime
from decimal import Decimal
from typing import ClassVar, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Item(SQLModel, table=True):
    id: str = Field(primary_key=True)
    connector_id: int
    connector_name: Optional[str] = None
    status: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    sync_started_at: Optional[datetime.datetime] = None
    sync_finished_at: Optional[datetime.datetime] = None
    last_sync_error: Optional[str] = None
    is_active: bool = Field(default=True)
    last_seen_at: Optional[datetime.datetime] = None
    deactivated_at: Optional[datetime.datetime] = None


class Account(SQLModel, table=True):
    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    name: str
    type: str
    subtype: Optional[str] = None
    marketing_name: Optional[str] = None
    number: Optional[str] = None
    # ---- Pluggy snapshot (set by the sync layer) ----
    # ``balance`` is the live account balance Pluggy reports:
    #   BANK: current available cash in the account.
    #   CREDIT: current open invoice / used credit.
    # We persist it instead of re-deriving so the dashboard has a real
    # number even before the first transaction sync is processed.
    balance: Optional[Decimal] = None
    currency_code: Optional[str] = None
    owner: Optional[str] = None
    tax_number: Optional[str] = None
    # bankData.* (only meaningful for BANK accounts)
    bank_closing_balance: Optional[Decimal] = None
    bank_automatically_invested_balance: Optional[Decimal] = None
    bank_overdraft_contracted_limit: Optional[Decimal] = None
    bank_overdraft_used_limit: Optional[Decimal] = None
    # creditData.* (only meaningful for CREDIT accounts)
    credit_level: Optional[str] = None
    credit_brand: Optional[str] = None
    credit_balance_close_date: Optional[datetime.date] = None
    credit_balance_due_date: Optional[datetime.date] = None
    credit_available_limit: Optional[Decimal] = None
    credit_limit: Optional[Decimal] = None
    credit_minimum_payment: Optional[Decimal] = None
    credit_status: Optional[str] = None
    credit_holder_type: Optional[str] = None
    balance_updated_at: Optional[datetime.datetime] = None
    is_active: bool = Field(default=True)
    last_seen_at: Optional[datetime.datetime] = None
    deactivated_at: Optional[datetime.datetime] = None


class CreditCardBill(SQLModel, table=True):
    """Pluggy-issued credit card bill (the official invoice for a billing cycle)."""

    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    due_date: Optional[datetime.date] = Field(default=None, index=True)
    total_amount: Optional[Decimal] = None
    minimum_payment_amount: Optional[Decimal] = None
    allows_installments: Optional[bool] = None
    payments_total: Optional[Decimal] = None
    finance_charges_total: Optional[Decimal] = None
    currency_code: Optional[str] = None
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class Investment(SQLModel, table=True):
    """Pluggy-issued investment position (CDB, fund, treasury, equity, …)."""

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    name: Optional[str] = None
    type: Optional[str] = Field(default=None, index=True)
    subtype: Optional[str] = None
    amount: Optional[Decimal] = None
    balance: Optional[Decimal] = None
    amount_original: Optional[Decimal] = None
    amount_profit: Optional[Decimal] = None
    amount_withdrawal: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    rate_type: Optional[str] = None
    fixed_annual_rate: Optional[Decimal] = None
    issuer: Optional[str] = None
    issue_date: Optional[datetime.date] = None
    due_date: Optional[datetime.date] = None
    status: Optional[str] = None
    currency_code: Optional[str] = None
    provider_id: Optional[str] = None
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class InvestmentTransaction(SQLModel, table=True):
    """Individual movement on an Investment (BUY / SELL / TAX / TRANSFER)."""

    id: str = Field(primary_key=True)
    investment_id: str = Field(foreign_key="investment.id", index=True)
    date: Optional[datetime.date] = Field(default=None, index=True)
    trade_date: Optional[datetime.date] = None
    type: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    net_amount: Optional[Decimal] = None
    quantity: Optional[Decimal] = None
    value: Optional[Decimal] = None
    currency_code: Optional[str] = None
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class AccountSync(SQLModel, table=True):
    account_id: str = Field(foreign_key="account.id", primary_key=True)
    last_synced_at: Optional[datetime.datetime] = None
    last_transaction_date: Optional[datetime.date] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime.datetime] = None


class Transaction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    account_id: str = Field(foreign_key="account.id", index=True)
    date: datetime.date = Field(index=True)
    amount: Decimal
    description: str
    # 10D-A: despite the generic column name, this is preserved as the raw
    # Pluggy category string. It must not be treated as an internal category.
    category: Optional[str] = None
    pluggy_raw_category: Optional[str] = Field(default=None, index=True)
    pluggy_raw_subcategory: Optional[str] = Field(default=None, index=True)
    pluggy_raw_type: Optional[str] = Field(default=None, index=True)
    pluggy_merchant: Optional[str] = Field(default=None, index=True)
    internal_category: Optional[str] = Field(default=None, index=True)
    cashflow_type: Optional[str] = Field(default=None, index=True)
    classification_source: Optional[str] = Field(default=None, index=True)
    classification_confidence: Optional[str] = Field(default=None, index=True)
    classification_rule_key: Optional[str] = Field(default=None, index=True)
    is_user_overridden: bool = Field(default=False, index=True)
    ignored_from_totals: bool = Field(default=False, index=True)
    currency_code: str = "BRL"
    # Pluggy bill/installment metadata (CREDIT accounts)
    status: Optional[str] = None
    bill_id: Optional[str] = Field(default=None, index=True)
    installment_number: Optional[int] = None
    total_installments: Optional[int] = None
    total_amount: Optional[Decimal] = None
    # Deduplication fields (populated by mark_duplicate_transactions.py)
    # ``dedupe_key`` is a stable hash of the natural key so duplicate detection
    # works even when Pluggy assigns a new transaction ID after re-authentication.
    dedupe_key: Optional[str] = Field(default=None, index=True)
    is_duplicate: bool = Field(default=False, index=True)
    # ID of the "canonical" transaction this row duplicates (informational).
    duplicate_of_id: Optional[str] = Field(default=None)


# 10D-A legacy storage only. These tables are intentionally left mapped so
# existing databases remain readable until a later reviewed migration removes
# them physically. New code must not use them as a category source of truth.
class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    color: str
    sort_order: int = 0
    parent_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)


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


class UserClassificationRule(SQLModel, table=True):
    """User-defined rule that overlays the deterministic 10D-B classifier.

    Applied in classify_input AFTER manual per-transaction overrides and
    BEFORE the default Pluggy-based rules (see 10D-D). A rule only changes
    classification fields — raw Pluggy data and financial fields are never
    touched. ``account_type_scope`` accepts CREDIT, BANK or ALL.
    ``match_amount_sign`` accepts positive, negative or any. At least one
    match_* criterion must be set (enforced by the service layer).
    """

    __tablename__: ClassVar[str] = "user_classification_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    enabled: bool = Field(default=True, index=True)
    # Lower priority value = evaluated first = wins on conflicts.
    priority: int = Field(default=100, index=True)
    account_type_scope: str = Field(default="ALL", index=True)
    # Pluggy raw matchers: normalized exact match.
    match_pluggy_category: Optional[str] = Field(default=None, index=True)
    match_pluggy_subcategory: Optional[str] = None
    match_pluggy_type: Optional[str] = None
    # Free-text matchers: case-insensitive "contains".
    match_merchant: Optional[str] = None
    match_description: Optional[str] = None
    match_amount_sign: str = Field(default="any")
    # Targets validated against INTERNAL_CATEGORIES / CASHFLOW_TYPES.
    target_internal_category: str
    target_cashflow_type: str
    # None lets the classifier derive the flag from the cashflow type.
    ignored_from_totals: Optional[bool] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


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


class BankCashflowExclusionRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    direction: str = Field(default="ALL", index=True)
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


# 10D-A legacy storage only: variable budgets are tied to the removed internal
# Category model and are disabled in services/routes until the new layer exists.
class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", unique=True, index=True)
    monthly_target: Decimal


class ExpectedIncome(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    description: str
    amount: Decimal
    expected_day: int
    active: bool = Field(default=True, index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class ExpectedIncomeOverride(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "expected_income_id",
            "year_month",
            name="uq_expectedincomeoverride_entry_month",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    expected_income_id: int = Field(foreign_key="expectedincome.id", index=True)
    year_month: str = Field(index=True)
    amount: Decimal


class FixedCostCategory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    color: str = "#64748b"
    sort_order: int = 0
    is_default: bool = Field(default=False, index=True)


class FixedCost(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="fixedcostcategory.id", index=True)
    description: str
    amount: Decimal
    due_day: int
    active: bool = Field(default=True, index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class FixedCostOverride(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "fixed_cost_id",
            "year_month",
            name="uq_fixedcostoverride_entry_month",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    fixed_cost_id: int = Field(foreign_key="fixedcost.id", index=True)
    year_month: str = Field(index=True)
    amount: Decimal


class FixedCostTransactionMatch(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "fixed_cost_id",
            "year_month",
            name="uq_fixedcosttransactionmatch_entry_month",
        ),
        UniqueConstraint(
            "transaction_id",
            name="uq_fixedcosttransactionmatch_transaction",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    fixed_cost_id: int = Field(foreign_key="fixedcost.id", index=True)
    transaction_id: str = Field(foreign_key="transaction.id", index=True)
    year_month: str = Field(index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class BudgetOverride(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("category_id", "year_month", name="uq_budgetoverride_month"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", index=True)
    year_month: str = Field(index=True)
    monthly_target: Decimal
