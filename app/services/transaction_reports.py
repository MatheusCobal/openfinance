from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models import Account, Transaction
from app.services.classification import TransactionClassifier
from app.services.transaction_classifier import (
    CompiledUserRule,
    serialize_transaction_classification,
)
from app.services.user_classification_rules import load_compiled_user_rules
from app.services.transactions import (
    SPENDING_ACCOUNT_TYPES,
    TRACKED_ACCOUNT_TYPES,
    _non_duplicate_clause,
    account_ids_by_type,
    filter_ignored_transactions,
    filter_transactions_by_account_type,
    ignored_description_patterns,
    is_ignored_transaction,
)


def _accounts_by_id(session: Session) -> dict[str, Account]:
    return {account.id: account for account in session.exec(select(Account)).all()}


def _classification_fields(
    tx: Transaction,
    accounts_by_id: dict[str, Account],
    user_rules: tuple[CompiledUserRule, ...] = (),
) -> dict[str, Any]:
    account = accounts_by_id.get(tx.account_id)
    return serialize_transaction_classification(
        tx,
        account_type=account.type if account is not None else None,
        user_rules=user_rules,
    )


def _serialize_transaction_row(
    tx: Transaction,
    accounts_by_id: dict[str, Account],
    ignored: bool = False,
    user_rules: tuple[CompiledUserRule, ...] = (),
) -> dict[str, Any]:
    classification = _classification_fields(tx, accounts_by_id, user_rules)
    return {
        **tx.model_dump(mode="json"),
        "pluggy_category": classification["pluggy_raw_category"],
        "ignored": ignored,
        **classification,
    }


def _transaction_list_query(
    account_id: Optional[str],
    from_date: Optional[date],
    to_date: Optional[date],
    include_future: bool,
    include_duplicates: bool = False,
):
    query = select(Transaction).order_by(Transaction.date.desc())
    if not include_duplicates:
        query = query.where(_non_duplicate_clause())
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    if to_date is not None:
        query = query.where(Transaction.date <= to_date)
    if not include_future and to_date is None:
        query = query.where(Transaction.date <= date.today())
    return query


def _apply_account_type_filter(
    query,
    account_type: Optional[str],
    session: Session,
):
    normalized_account_type = validate_account_type(account_type)
    if normalized_account_type is None:
        return query, False

    account_ids = account_ids_by_type(session, {normalized_account_type})
    if not account_ids:
        return query, True
    return query.where(Transaction.account_id.in_(account_ids)), False


def validate_account_type(account_type: Optional[str]) -> Optional[str]:
    if account_type is None or account_type.upper() == "ALL":
        return None

    normalized_account_type = account_type.upper()
    if normalized_account_type not in TRACKED_ACCOUNT_TYPES:
        raise ValueError("account_type must be CREDIT, BANK or ALL")
    return normalized_account_type


def enriched_transactions(
    session: Session,
    account_id: Optional[str] = None,
    account_type: Optional[str] = "CREDIT",
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
    include_duplicates: bool = False,
) -> list[Dict[str, Any]]:
    query = _transaction_list_query(
        account_id,
        from_date,
        to_date,
        include_future,
        include_duplicates=include_duplicates,
    )
    query, should_return_empty = _apply_account_type_filter(
        query,
        account_type,
        session,
    )
    if should_return_empty:
        return []

    transactions = session.exec(query).all()
    ignored_patterns = ignored_description_patterns(session)
    if not include_ignored and ignored_patterns:
        transactions = [
            tx for tx in transactions if not is_ignored_transaction(tx, ignored_patterns)
        ]

    accounts = _accounts_by_id(session)
    user_rules = load_compiled_user_rules(session)
    rows = []
    for tx in transactions:
        rows.append(
            _serialize_transaction_row(
                tx,
                accounts,
                ignored=is_ignored_transaction(tx, ignored_patterns),
                user_rules=user_rules,
            )
        )

    return rows


def upcoming_summary(
    session: Session,
    include_ignored: bool = False,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    today = today if today is not None else date.today()
    future_txs = session.exec(
        select(Transaction)
        .where(Transaction.date > today, _non_duplicate_clause())
        .order_by(Transaction.date)
    ).all()
    future_txs = filter_transactions_by_account_type(
        future_txs,
        session,
        SPENDING_ACCOUNT_TYPES,
    )
    future_txs = filter_ignored_transactions(
        future_txs,
        session,
        include_ignored,
    )

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    accounts = _accounts_by_id(session)
    user_rules = load_compiled_user_rules(session)
    for tx in future_txs:
        # Exclude credits / refunds / cancellations (amount <= 0) so they
        # don't inflate the scheduled invoice total via abs(amount).
        if tx.amount <= 0:
            continue
        month = tx.date.strftime("%Y-%m")
        by_month[month].append(tx)

    months_out = []
    for month in sorted(by_month.keys()):
        txs = by_month[month]
        month_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
        serialized_transactions = [
            {
                "id": tx.id,
                "date": tx.date.isoformat(),
                "amount": float(abs(tx.amount)),
                "description": tx.description,
                "pluggy_category": _classification_fields(tx, accounts, user_rules)[
                    "pluggy_raw_category"
                ],
                **_classification_fields(tx, accounts, user_rules),
            }
            for tx in txs
        ]
        categories_by_name: Dict[str, dict[str, Any]] = {}
        for tx in serialized_transactions:
            if tx.get("ignored_from_totals") or tx.get("cashflow_type") != "expense":
                continue
            name = tx.get("internal_category") or "Outros"
            bucket = categories_by_name.setdefault(
                name,
                {
                    "id": name,
                    "name": name,
                    "total": Decimal("0"),
                    "count": 0,
                    "transactions": [],
                    "source": "pluggy_based_classification",
                },
            )
            bucket["total"] += Decimal(str(tx["amount"]))
            bucket["count"] += 1
            bucket["transactions"].append(tx)
        months_out.append(
            {
                "month": month,
                "total": float(month_total),
                "count": len(txs),
                "categories": [
                    {
                        **bucket,
                        "total": float(bucket["total"]),
                    }
                    for bucket in sorted(
                        categories_by_name.values(),
                        key=lambda item: item["total"],
                        reverse=True,
                    )
                ],
                "transactions": serialized_transactions,
                "legacy_category_breakdown_removed": False,
            }
        )

    # "Próxima fatura" must mirror the planning/Dashboard invoice for the
    # vigente month instead of the raw sum of future-dated installments,
    # which misses purchases already made in the forming cycle.
    from app.services.credit_card_invoice import (
        _next_calendar_month,
        planning_invoice_for_month,
    )

    vigente_month = _next_calendar_month(today)
    planning_inv = planning_invoice_for_month(session, vigente_month, today=today)
    next_invoice = {
        "year_month": vigente_month,
        "amount": planning_inv["amount"],
        "source": planning_inv["source"],
        "source_label": planning_inv["source_label"],
        "is_estimated": planning_inv["is_estimated"],
    }

    next_invoice_amount = Decimal(str(next_invoice["amount"] or 0))
    vigente_row = next(
        (month for month in months_out if month["month"] == vigente_month),
        None,
    )
    if vigente_row is not None:
        vigente_row["scheduled_total"] = vigente_row["total"]
        vigente_row["scheduled_count"] = vigente_row["count"]
        vigente_row["total"] = float(next_invoice_amount)
        vigente_row["invoice_total"] = float(next_invoice_amount)
        vigente_row["invoice_source"] = next_invoice["source"]
        vigente_row["invoice_source_label"] = next_invoice["source_label"]
        vigente_row["is_current_invoice"] = True
    elif next_invoice_amount > 0:
        months_out.append(
            {
                "month": vigente_month,
                "total": float(next_invoice_amount),
                "count": planning_inv.get("transaction_count", 0),
                "scheduled_total": 0.0,
                "scheduled_count": 0,
                "invoice_total": float(next_invoice_amount),
                "invoice_source": next_invoice["source"],
                "invoice_source_label": next_invoice["source_label"],
                "is_current_invoice": True,
                "categories": [],
                "transactions": [],
                "legacy_category_breakdown_removed": False,
            }
        )
        months_out.sort(key=lambda month: month["month"])

    return {
        "total_count": len(future_txs),
        "months": months_out,
        "next_invoice": next_invoice,
        "legacy_category_breakdown_removed": False,
    }


def monthly_stats_summary(
    session: Session,
    include_ignored: bool = False,
) -> Dict[str, Any]:
    today = date.today()
    start = date(today.year, today.month, 1)
    txs = session.exec(
        select(Transaction)
        .where(Transaction.date >= start, Transaction.date <= today, _non_duplicate_clause())
        .order_by(Transaction.date.asc())
    ).all()
    txs = filter_transactions_by_account_type(txs, session, SPENDING_ACCOUNT_TYPES)
    txs = filter_ignored_transactions(txs, session, include_ignored)
    accounts = _accounts_by_id(session)
    user_rules = load_compiled_user_rules(session)

    totals_by_category: Dict[str, dict[str, Any]] = {}
    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in txs:
        classification = _classification_fields(tx, accounts, user_rules)
        if classification["ignored_from_totals"] or classification["cashflow_type"] != "expense":
            continue
        amount = abs(tx.amount)
        category_name = classification["internal_category"] or "Outros"
        month = tx.date.strftime("%Y-%m")
        totals_by_month[month] += amount
        bucket = totals_by_category.setdefault(
            category_name,
            {
                "id": category_name,
                "name": category_name,
                "total": Decimal("0"),
                "count": 0,
                "cashflow_type": "expense",
                "source": "pluggy_based_classification",
            },
        )
        bucket["total"] += amount
        bucket["count"] += 1

    return {
        "months": [
            {"month": month, "total": float(total)}
            for month, total in sorted(totals_by_month.items())
        ],
        "categories": [
            {
                **bucket,
                "total": float(bucket["total"]),
            }
            for bucket in sorted(
                totals_by_category.values(),
                key=lambda item: item["total"],
                reverse=True,
            )
        ],
        "legacy_category_breakdown_removed": False,
    }


def invoice_summary(
    session: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    exclude_transaction_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Single source of truth for credit-card invoice numbers.

    Always returns BOTH ``invoice_paid_total`` (invoice payments made in the
    period) and ``invoice_open_total`` (credit-card purchases since the last
    payment, up to ``effective_to``) so the caller can pick the right one
    without worrying about silent mode-switches mid-month.

    ``invoice_total``/``invoice_mode`` are kept for backwards compatibility and
    point to the discretionary view. When no ``exclude_transaction_ids`` are
    passed, gross and discretionary values are identical.

    ``exclude_transaction_ids`` is used by the spending-capacity card to
    drop transactions that already count somewhere else (notably fixed
    costs billed on the card), avoiding double counting.
    """
    today = date.today()
    effective_to = to_date if to_date is not None else today
    skip_ids: set[str] = exclude_transaction_ids or set()

    classifier = TransactionClassifier.from_session(session)
    # Restrict to active credit accounts from the start so that deactivated
    # accounts (e.g. after Pluggy re-authentication) never inflate totals or
    # shift last_payment_date via stale duplicate transactions.
    credit_account_ids = set(account_ids_by_type(session, SPENDING_ACCOUNT_TYPES))
    all_up_to = session.exec(
        select(Transaction).where(
            Transaction.date <= effective_to,
            _non_duplicate_clause(),
        )
    ).all()

    payments = [
        tx
        for tx in all_up_to
        if tx.account_id in credit_account_ids and classifier.is_invoice_payment(tx)
    ]

    last_payment_date = max((tx.date for tx in payments), default=None)
    lower = last_payment_date if last_payment_date is not None else date.min
    if from_date is not None and from_date > lower:
        lower = from_date

    def calculate(skip: set[str]) -> Dict[str, Any]:
        skipped_purchase_total = sum(
            (
                abs(tx.amount)
                for tx in all_up_to
                if tx.id in skip
                and tx.account_id in credit_account_ids
                and (from_date is None or tx.date >= from_date)
                and classifier.is_card_purchase(tx)
            ),
            Decimal("0"),
        )
        payments_in_period = [
            tx
            for tx in payments
            if (from_date is None or tx.date >= from_date) and tx.id not in skip
        ]
        paid_total = sum(
            (abs(tx.amount) for tx in payments_in_period),
            Decimal("0"),
        )
        paid_total = max(paid_total - skipped_purchase_total, Decimal("0"))
        paid_count = len(payments_in_period)
        paid_dates = sorted(tx.date.isoformat() for tx in payments_in_period)

        open_txs = [
            tx
            for tx in all_up_to
            if tx.account_id in credit_account_ids and tx.date > lower and tx.id not in skip
            and classifier.is_card_purchase(tx)
        ]
        open_total = sum((abs(tx.amount) for tx in open_txs), Decimal("0"))
        open_count = len(open_txs)
        open_since = last_payment_date.isoformat() if last_payment_date else None

        if payments_in_period:
            invoice_mode = "paid"
            invoice_total = paid_total
            invoice_count = paid_count
            invoice_since: Optional[str] = None
        else:
            invoice_mode = "open"
            invoice_total = open_total
            invoice_count = open_count
            invoice_since = open_since

        return {
            "mode": invoice_mode,
            "total": invoice_total,
            "count": invoice_count,
            "since": invoice_since,
            "paid_dates": paid_dates,
            "paid_total": paid_total,
            "paid_count": paid_count,
            "open_total": open_total,
            "open_count": open_count,
            "open_since": open_since,
        }

    gross = calculate(set())
    discretionary = calculate(skip_ids)

    return {
        "invoice_mode": discretionary["mode"],
        "invoice_total": float(discretionary["total"]),
        "invoice_count": discretionary["count"],
        "invoice_since": discretionary["since"],
        "invoice_paid_dates": discretionary["paid_dates"],
        "invoice_paid_total": float(discretionary["paid_total"]),
        "invoice_paid_count": discretionary["paid_count"],
        "invoice_open_total": float(discretionary["open_total"]),
        "invoice_open_count": discretionary["open_count"],
        "invoice_open_since": discretionary["open_since"],
        "invoice_gross_mode": gross["mode"],
        "invoice_gross_total": float(gross["total"]),
        "invoice_gross_count": gross["count"],
        "invoice_gross_since": gross["since"],
        "invoice_gross_paid_dates": gross["paid_dates"],
        "invoice_paid_gross_total": float(gross["paid_total"]),
        "invoice_paid_gross_count": gross["paid_count"],
        "invoice_open_gross_total": float(gross["open_total"]),
        "invoice_open_gross_count": gross["open_count"],
        "invoice_open_gross_since": gross["open_since"],
        "invoice_discretionary_mode": discretionary["mode"],
        "invoice_discretionary_total": float(discretionary["total"]),
        "invoice_discretionary_count": discretionary["count"],
        "invoice_discretionary_since": discretionary["since"],
        "invoice_discretionary_paid_dates": discretionary["paid_dates"],
        "invoice_paid_discretionary_total": float(discretionary["paid_total"]),
        "invoice_paid_discretionary_count": discretionary["paid_count"],
        "invoice_open_discretionary_total": float(discretionary["open_total"]),
        "invoice_open_discretionary_count": discretionary["open_count"],
        "invoice_open_discretionary_since": discretionary["open_since"],
        "invoice_excluded_total": float(gross["total"] - discretionary["total"]),
        "invoice_excluded_count": gross["count"] - discretionary["count"],
    }


def stats_summary(
    session: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_ignored: bool = False,
) -> Dict[str, Any]:
    today = date.today()
    effective_to = to_date if to_date is not None else today

    query = select(Transaction).where(_non_duplicate_clause())
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    query = query.where(Transaction.date <= effective_to)
    past_transactions = session.exec(query).all()
    past_transactions = filter_transactions_by_account_type(
        past_transactions,
        session,
        SPENDING_ACCOUNT_TYPES,
    )
    past_transactions = filter_ignored_transactions(
        past_transactions,
        session,
        include_ignored,
    )

    future_count = 0
    if to_date is None:
        future_transactions = session.exec(
            select(Transaction).where(Transaction.date > today, _non_duplicate_clause())
        ).all()
        future_transactions = filter_transactions_by_account_type(
            future_transactions,
            session,
            SPENDING_ACCOUNT_TYPES,
        )
        future_count = len(
            filter_ignored_transactions(
                future_transactions,
                session,
                include_ignored,
            )
        )

    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    totals_by_cashflow: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_spent = Decimal("0")
    accounts = _accounts_by_id(session)
    user_rules = load_compiled_user_rules(session)

    for tx in past_transactions:
        classification = _classification_fields(tx, accounts, user_rules)
        if classification["ignored_from_totals"] or classification["cashflow_type"] != "expense":
            continue
        amount = abs(tx.amount)
        totals_by_month[tx.date.strftime("%Y-%m")] += amount
        totals_by_cashflow[classification["cashflow_type"]] += amount
        total_spent += amount

    months = [
        {"month": month, "total": float(total)} for month, total in sorted(totals_by_month.items())
    ]

    invoice = invoice_summary(session, from_date=from_date, to_date=to_date)

    return {
        "total_spent": float(total_spent),
        "transaction_count": len(past_transactions),
        "future_transaction_count": future_count,
        "categories": [],
        "cashflow_types": [
            {"type": key, "total": float(value)}
            for key, value in sorted(totals_by_cashflow.items())
        ],
        "legacy_category_breakdown_removed": False,
        "months": months,
        "invoice_mode": invoice["invoice_mode"],
        "invoice_total": invoice["invoice_total"],
        "invoice_count": invoice["invoice_count"],
        "invoice_since": invoice["invoice_since"],
        "invoice_paid_dates": invoice["invoice_paid_dates"],
        "invoice_paid_total": invoice["invoice_paid_total"],
        "invoice_paid_count": invoice["invoice_paid_count"],
        "invoice_open_total": invoice["invoice_open_total"],
        "invoice_open_count": invoice["invoice_open_count"],
        "invoice_open_since": invoice["invoice_open_since"],
        "invoice_gross_total": invoice["invoice_gross_total"],
        "invoice_gross_count": invoice["invoice_gross_count"],
        "invoice_discretionary_total": invoice["invoice_discretionary_total"],
        "invoice_discretionary_count": invoice["invoice_discretionary_count"],
        "invoice_paid_gross_total": invoice["invoice_paid_gross_total"],
        "invoice_open_gross_total": invoice["invoice_open_gross_total"],
        "invoice_paid_discretionary_total": invoice["invoice_paid_discretionary_total"],
        "invoice_open_discretionary_total": invoice["invoice_open_discretionary_total"],
    }
