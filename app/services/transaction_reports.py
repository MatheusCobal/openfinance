from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.categorization import CategoryResolver
from app.models import Category, Transaction
from app.services.transactions import (
    SPENDING_ACCOUNT_TYPES,
    TRACKED_ACCOUNT_TYPES,
    account_ids_by_type,
    filter_ignored_transactions,
    filter_transactions_by_account_type,
    ignored_description_patterns,
    is_ignored_transaction,
)


def _transaction_list_query(
    account_id: Optional[str],
    from_date: Optional[date],
    to_date: Optional[date],
    include_future: bool,
):
    query = select(Transaction).order_by(Transaction.date.desc())
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
    category_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
) -> list[Dict[str, Any]]:
    resolver = CategoryResolver(session)
    query = _transaction_list_query(
        account_id,
        from_date,
        to_date,
        include_future,
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
            tx
            for tx in transactions
            if not is_ignored_transaction(tx, ignored_patterns)
        ]

    rows = []
    for tx in transactions:
        cat = resolver.resolve(tx.category, tx.description)
        rows.append(
            {
                **tx.model_dump(mode="json"),
                "custom_category_id": cat.id,
                "custom_category_name": cat.name,
                "custom_category_color": cat.color,
                "ignored": is_ignored_transaction(tx, ignored_patterns),
            }
        )

    if category_id is not None:
        rows = [row for row in rows if row["custom_category_id"] == category_id]
    return rows


def transaction_csv_rows(
    session: Session,
    account_type: Optional[str] = "CREDIT",
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_future: bool = False,
    include_ignored: bool = False,
):
    resolver = CategoryResolver(session)
    query = _transaction_list_query(
        None,
        from_date,
        to_date,
        include_future,
    )
    query, should_return_empty = _apply_account_type_filter(
        query,
        account_type,
        session,
    )
    ignored_patterns = ignored_description_patterns(session)

    yield [
        "date",
        "description",
        "amount_original",
        "amount_abs",
        "currency",
        "pluggy_category",
        "category",
        "account_id",
        "transaction_id",
    ]

    if should_return_empty:
        return

    for tx in session.exec(query):
        if (
            not include_ignored
            and ignored_patterns
            and is_ignored_transaction(tx, ignored_patterns)
        ):
            continue
        cat = resolver.resolve(tx.category, tx.description)
        yield [
            tx.date.isoformat(),
            tx.description,
            f"{tx.amount:.2f}",
            f"{abs(tx.amount):.2f}",
            tx.currency_code,
            tx.category or "",
            cat.name,
            tx.account_id,
            tx.id,
        ]


def upcoming_summary(
    session: Session,
    include_ignored: bool = False,
) -> Dict[str, Any]:
    resolver = CategoryResolver(session)
    today = date.today()
    future_txs = session.exec(
        select(Transaction)
        .where(Transaction.date > today)
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

    by_month_cat: Dict[str, Dict[int, list[Transaction]]] = defaultdict(
        lambda: defaultdict(list)
    )
    category_info_by_id: Dict[int, Category] = {}
    for tx in future_txs:
        month = tx.date.strftime("%Y-%m")
        cat = resolver.resolve(tx.category, tx.description)
        by_month_cat[month][cat.id].append(tx)
        category_info_by_id[cat.id] = cat

    months_out = []
    for month in sorted(by_month_cat.keys()):
        cat_groups = by_month_cat[month]
        categories_out = []
        month_total = Decimal("0")
        month_count = 0

        for cat_id, txs in cat_groups.items():
            cat = category_info_by_id[cat_id]
            cat_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
            month_total += cat_total
            month_count += len(txs)
            categories_out.append(
                {
                    "id": cat.id,
                    "name": cat.name,
                    "color": cat.color,
                    "total": float(cat_total),
                    "count": len(txs),
                    "transactions": [
                        {
                            "id": tx.id,
                            "date": tx.date.isoformat(),
                            "amount": float(abs(tx.amount)),
                            "description": tx.description,
                            "pluggy_category": tx.category,
                        }
                        for tx in txs
                    ],
                }
            )

        categories_out.sort(key=lambda category: category["total"], reverse=True)
        months_out.append(
            {
                "month": month,
                "total": float(month_total),
                "count": month_count,
                "categories": categories_out,
            }
        )

    return {"total_count": len(future_txs), "months": months_out}


def monthly_stats_summary(
    session: Session,
    include_ignored: bool = False,
) -> Dict[str, Any]:
    resolver = CategoryResolver(session)
    today = date.today()
    transactions = session.exec(select(Transaction)).all()
    past_transactions = [tx for tx in transactions if tx.date <= today]
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

    matrix: Dict[int, Dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    counts: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    category_info_by_id: Dict[int, Category] = {}
    months_set: set[str] = set()

    for tx in past_transactions:
        cat = resolver.resolve(tx.category, tx.description)
        month = tx.date.strftime("%Y-%m")
        matrix[cat.id][month] += abs(tx.amount)
        counts[cat.id][month] += 1
        category_info_by_id[cat.id] = cat
        months_set.add(month)

    months = sorted(months_set)
    categories = []
    for cat_id, by_month in matrix.items():
        cat = category_info_by_id[cat_id]
        category_total = sum(by_month.values())
        categories.append(
            {
                "id": cat.id,
                "name": cat.name,
                "color": cat.color,
                "sort_order": cat.sort_order,
                "total": float(category_total),
                "by_month": {
                    month: float(by_month.get(month, Decimal("0")))
                    for month in months
                },
                "counts_by_month": {
                    month: counts[cat_id].get(month, 0) for month in months
                },
            }
        )

    categories.sort(key=lambda category: category["total"], reverse=True)
    return {"months": months, "categories": categories}


def stats_summary(
    session: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    include_ignored: bool = False,
) -> Dict[str, Any]:
    resolver = CategoryResolver(session)
    today = date.today()
    effective_to = to_date if to_date is not None else today

    query = select(Transaction)
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
            select(Transaction).where(Transaction.date > today)
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

    totals_by_category_id: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    counts_by_category_id: Dict[int, int] = defaultdict(int)
    category_info_by_id: Dict[int, Category] = {}
    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_spent = Decimal("0")

    for tx in past_transactions:
        amount = abs(tx.amount)
        cat = resolver.resolve(tx.category, tx.description)
        totals_by_category_id[cat.id] += amount
        counts_by_category_id[cat.id] += 1
        category_info_by_id[cat.id] = cat
        totals_by_month[tx.date.strftime("%Y-%m")] += amount
        total_spent += amount

    categories = sorted(
        [
            {
                "id": cat_id,
                "name": category_info_by_id[cat_id].name,
                "color": category_info_by_id[cat_id].color,
                "sort_order": category_info_by_id[cat_id].sort_order,
                "total": float(total),
                "count": counts_by_category_id[cat_id],
            }
            for cat_id, total in totals_by_category_id.items()
        ],
        key=lambda category: category["total"],
        reverse=True,
    )
    months = [
        {"month": month, "total": float(total)}
        for month, total in sorted(totals_by_month.items())
    ]

    return {
        "total_spent": float(total_spent),
        "transaction_count": len(past_transactions),
        "future_transaction_count": future_count,
        "categories": categories,
        "months": months,
    }
