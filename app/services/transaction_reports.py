from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from app.models import Account, CreditCardBill, Item, Transaction
from app.services.caixa_invoice import (
    CAIXA_CLOSING_DAY,
    CAIXA_CREDIT_CATEGORY,
    CaixaInvoiceEntry,
    caixa_invoice_entries_by_month,
    is_caixa_account,
    serialize_caixa_invoice_entry,
)
from app.services.classification import (
    SPENDING_ACCOUNT_TYPES,
    TRACKED_ACCOUNT_TYPES,
    TransactionClassifier,
    card_invoice_signed_amount,
)
from app.services.credit_categories import (
    credit_category_payload,
    resolve_credit_internal_category,
)
from app.services.transaction_classifier import serialize_transaction_classification
from app.services.scoping import scope_query
from app.services.transactions import (
    _non_duplicate_clause,
    account_ids_by_type,
    filter_ignored_transactions,
    filter_transactions_by_account_type,
    ignored_description_patterns,
    is_ignored_transaction,
    month_key,
    shift_month,
)


def _upcoming_categories(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories_by_name: Dict[str, dict[str, Any]] = {}
    for tx in transactions:
        if tx.get("ignored_from_totals"):
            continue
        signed_amount = Decimal(str(tx.get("signed_amount", tx.get("amount") or 0)))
        is_credit = signed_amount < 0
        if not is_credit and tx.get("cashflow_type") != "expense":
            continue
        name = CAIXA_CREDIT_CATEGORY if is_credit else tx.get("effective_category") or "Outros"
        bucket = categories_by_name.setdefault(
            name,
            {
                "id": name,
                "name": name,
                "effective_category": name,
                "resolved_category": name,
                "credit_category": name,
                "total": Decimal("0"),
                "count": 0,
                "transactions": [],
                "source": "pluggy_based_classification",
            },
        )
        bucket["total"] += signed_amount
        bucket["count"] += 1
        bucket["transactions"].append(tx)
    return [
        {**bucket, "total": float(bucket["total"])}
        for bucket in sorted(
            categories_by_name.values(),
            key=lambda item: abs(item["total"]),
            reverse=True,
        )
    ]


def _accounts_by_id(session: Session, user_id: Optional[int] = None) -> dict[str, Account]:
    return {
        account.id: account
        for account in session.exec(scope_query(select(Account), Account.user_id, user_id)).all()
    }


def _classification_fields(
    tx: Transaction,
    accounts_by_id: dict[str, Account],
) -> dict[str, Any]:
    account = accounts_by_id.get(tx.account_id)
    return serialize_transaction_classification(
        tx,
        account_type=account.type if account is not None else None,
    )


def _serialize_transaction_row(
    tx: Transaction,
    accounts_by_id: dict[str, Account],
    ignored: bool = False,
) -> dict[str, Any]:
    classification = _classification_fields(tx, accounts_by_id)
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
    user_id: Optional[int] = None,
):
    query = scope_query(select(Transaction), Transaction.user_id, user_id).order_by(
        Transaction.date.desc()
    )
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
    user_id: Optional[int] = None,
):
    normalized_account_type = validate_account_type(account_type)
    if normalized_account_type is None:
        return query, False

    account_ids = account_ids_by_type(session, {normalized_account_type}, user_id=user_id)
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
    user_id: Optional[int] = None,
) -> list[Dict[str, Any]]:
    query = _transaction_list_query(
        account_id,
        from_date,
        to_date,
        include_future,
        include_duplicates=include_duplicates,
        user_id=user_id,
    )
    query, should_return_empty = _apply_account_type_filter(
        query,
        account_type,
        session,
        user_id=user_id,
    )
    if should_return_empty:
        return []

    transactions = session.exec(query).all()
    ignored_patterns = ignored_description_patterns(session, user_id=user_id)
    if not include_ignored and ignored_patterns:
        transactions = [
            tx for tx in transactions if not is_ignored_transaction(tx, ignored_patterns)
        ]

    accounts = _accounts_by_id(session, user_id=user_id)
    rows = []
    for tx in transactions:
        rows.append(
            _serialize_transaction_row(
                tx,
                accounts,
                ignored=is_ignored_transaction(tx, ignored_patterns),
            )
        )

    return rows


def upcoming_summary(
    session: Session,
    include_ignored: bool = False,
    today: Optional[date] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    today = today if today is not None else date.today()
    candidate_txs = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.date > today,
                _non_duplicate_clause(),
            ),
            Transaction.user_id,
            user_id,
        ).order_by(Transaction.date)
    ).all()
    candidate_txs = filter_transactions_by_account_type(
        candidate_txs,
        session,
        SPENDING_ACCOUNT_TYPES,
        user_id=user_id,
    )
    candidate_txs = filter_ignored_transactions(
        candidate_txs,
        session,
        include_ignored,
        user_id=user_id,
    )

    by_month: Dict[str, list[Transaction]] = defaultdict(list)
    accounts = _accounts_by_id(session, user_id=user_id)
    items_by_id = {
        item.id: item
        for item in session.exec(scope_query(select(Item), Item.user_id, user_id)).all()
    }

    def account_identity(account_id: Optional[str]) -> dict[str, Any]:
        account = accounts.get(account_id or "")
        if account is None:
            return {}
        item = items_by_id.get(account.item_id)
        number = "".join(
            character for character in str(account.number or "") if character.isdigit()
        )
        return {
            "account_id": account.id,
            "account_name": account.marketing_name or account.name,
            "card_brand": account.credit_brand,
            "card_last_four": number[-4:] if number else None,
            "institution_name": item.connector_name if item is not None else None,
        }

    classifier = TransactionClassifier.from_session(session, user_id=user_id)
    from app.services.current_card_invoice import current_card_invoice_summary

    dashboard_invoice = current_card_invoice_summary(session, today=today, user_id=user_id)
    current_invoice_transaction_ids = {
        str(tx["id"])
        for tx in dashboard_invoice.get("raw_purchase_transactions", [])
        if tx.get("id") is not None
    }
    for tx in candidate_txs:
        if tx.id in current_invoice_transaction_ids or not classifier.is_card_purchase(tx):
            continue
        invoice_month = month_key(tx.date)
        by_month[invoice_month].append(tx)

    months_out = []
    vigente_month = month_key(shift_month(today.replace(day=1), 1))
    if vigente_month not in by_month:
        by_month[vigente_month] = []

    official_bills = session.exec(
        scope_query(select(CreditCardBill), CreditCardBill.user_id, user_id)
    ).all()
    active_credit_account_ids = set(
        account_ids_by_type(session, SPENDING_ACCOUNT_TYPES, user_id=user_id)
    )
    for bill in official_bills:
        if bill.due_date is None or bill.account_id not in active_credit_account_ids:
            continue
        bill_month = month_key(bill.due_date)
        if bill_month >= vigente_month and bill_month not in by_month:
            by_month[bill_month] = []

    from app.services.credit_card_invoice import planning_invoice_for_month

    reported_invoice_total = Decimal(str(dashboard_invoice.get("amount") or 0))

    for month in sorted(by_month):
        txs = by_month[month]
        month_total = sum((abs(tx.amount) for tx in txs), Decimal("0"))
        is_current_invoice = month == vigente_month
        planned_invoice = planning_invoice_for_month(
            session,
            month,
            today=today,
            user_id=user_id,
        )
        if is_current_invoice:
            invoice_total = reported_invoice_total
            invoice_source = "pending_current_invoice"
            invoice_source_label = dashboard_invoice.get("source_label") or "Fatura vigente"
        else:
            planned_amount = planned_invoice.get("amount")
            invoice_total = Decimal(str(month_total if planned_amount is None else planned_amount))
            invoice_source = planned_invoice.get("source") or "scheduled_installments"
            invoice_source_label = planned_invoice.get("source_label") or "Fatura Pluggy do mês"
        serialized_transactions = []
        for tx in txs:
            classification = _classification_fields(tx, accounts)
            effective_category = resolve_credit_internal_category(
                tx,
                account_type="CREDIT",
                current_internal_category=classification.get("internal_category"),
            )
            serialized_transactions.append(
                {
                    "id": tx.id,
                    "date": tx.date.isoformat(),
                    "amount": float(abs(tx.amount)),
                    "description": tx.description,
                    "pluggy_category": classification["pluggy_raw_category"],
                    **account_identity(tx.account_id),
                    **classification,
                    **credit_category_payload(effective_category),
                }
            )
        categories_by_name: Dict[str, dict[str, Any]] = {}
        for tx in serialized_transactions:
            if tx.get("ignored_from_totals") or tx.get("cashflow_type") != "expense":
                continue
            name = tx.get("effective_category") or "Outros"
            bucket = categories_by_name.setdefault(
                name,
                {
                    "id": name,
                    "name": name,
                    "effective_category": name,
                    "resolved_category": name,
                    "credit_category": name,
                    "total": Decimal("0"),
                    "count": 0,
                    "transactions": [],
                    "source": "pluggy_based_classification",
                },
            )
            bucket["total"] += Decimal(str(tx["amount"]))
            bucket["count"] += 1
            bucket["transactions"].append(tx)
        categories = [
            {
                **bucket,
                "total": float(bucket["total"]),
            }
            for bucket in sorted(
                categories_by_name.values(),
                key=lambda item: item["total"],
                reverse=True,
            )
        ]
        row_count = len(txs)
        if is_current_invoice:
            serialized_transactions = list(dashboard_invoice.get("raw_purchase_transactions", []))
            categories = list(dashboard_invoice.get("categories", []))
            month_total = reported_invoice_total
            row_count = int(dashboard_invoice.get("transaction_count") or 0)
            cards = list(dashboard_invoice.get("cards", []))
        else:
            cards = [
                {**card, **account_identity(card.get("account_id"))}
                for card in planned_invoice.get("cards", [])
            ]
        months_out.append(
            {
                "month": month,
                "total": float(invoice_total),
                "detailed_total": float(month_total),
                "count": row_count,
                "transaction_month": month,
                "invoice_total": float(invoice_total),
                "invoice_source": invoice_source,
                "invoice_source_label": invoice_source_label,
                "is_current_invoice": is_current_invoice,
                "cards": cards,
                "categories": categories,
                "transactions": serialized_transactions,
                "reported_invoice_total": (
                    float(reported_invoice_total) if is_current_invoice else None
                ),
                "reported_difference": (0.0 if is_current_invoice else None),
            }
        )

    caixa_account_ids = {
        account_id
        for account_id in active_credit_account_ids
        if is_caixa_account(accounts.get(account_id))
    }
    if caixa_account_ids:
        # "Próximos" starts at the vigente invoice (next calendar month) for
        # every card.  Keeping CAIXA at the current calendar month made an
        # already-paid official bill linger after Itaú had rolled forward.
        minimum_invoice_month = vigente_month
        caixa_by_month = caixa_invoice_entries_by_month(
            session,
            caixa_account_ids,
            minimum_invoice_month,
            classifier,
            today=today,
            include_ignored=include_ignored,
            user_id=user_id,
        )

        caixa_bills: Dict[tuple[str, str], list[CreditCardBill]] = defaultdict(list)
        for bill in official_bills:
            if (
                bill.account_id in caixa_account_ids
                and bill.due_date is not None
                and bill.total_amount is not None
                and month_key(bill.due_date) >= minimum_invoice_month
            ):
                caixa_bills[(bill.account_id, month_key(bill.due_date))].append(bill)

        rows_by_month = {row["month"]: row for row in months_out}
        target_months = set(rows_by_month) | set(caixa_by_month)
        target_months.update(month for _, month in caixa_bills)
        for month in target_months:
            if month not in rows_by_month:
                rows_by_month[month] = {
                    "month": month,
                    "total": 0.0,
                    "detailed_total": 0.0,
                    "count": 0,
                    "transaction_month": month,
                    "invoice_total": 0.0,
                    "invoice_source": "caixa_closing_cycle",
                    "invoice_source_label": "Ciclo da fatura CAIXA",
                    "is_current_invoice": month == vigente_month,
                    "cards": [],
                    "categories": [],
                    "transactions": [],
                    "reported_invoice_total": None,
                    "reported_difference": None,
                }

        def serialize_caixa_transaction(entry: CaixaInvoiceEntry) -> dict[str, Any]:
            tx = entry.transaction
            identity = account_identity(tx.account_id)
            if tx.credit_card_last_four:
                identity["card_last_four"] = tx.credit_card_last_four
            return {
                **serialize_caixa_invoice_entry(entry),
                **identity,
            }

        for month in sorted(target_months):
            row = rows_by_month[month]
            non_caixa_transactions = [
                tx
                for tx in row.get("transactions", [])
                if tx.get("account_id") not in caixa_account_ids
            ]
            caixa_transactions = [
                serialize_caixa_transaction(entry) for entry in caixa_by_month.get(month, [])
            ]
            serialized_transactions = non_caixa_transactions + caixa_transactions

            detailed_by_account: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            counts_by_account: Dict[str, int] = defaultdict(int)
            projected_by_account: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            projected_counts_by_account: Dict[str, int] = defaultdict(int)
            credits_by_account: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            forecast_accounts: set[str] = set()
            for tx in serialized_transactions:
                account_id = tx.get("account_id")
                if not account_id:
                    continue
                signed_amount = Decimal(str(tx.get("signed_amount", tx.get("amount") or 0)))
                detailed_by_account[account_id] += signed_amount
                counts_by_account[account_id] += 1
                if tx.get("is_projected"):
                    projected_by_account[account_id] += signed_amount
                    projected_counts_by_account[account_id] += 1
                if signed_amount < 0:
                    credits_by_account[account_id] += abs(signed_amount)
                if tx.get("invoice_assignment_source") in {
                    "pluggy_forecast",
                    "installment_projection",
                }:
                    forecast_accounts.add(account_id)

            cards_by_account: dict[str, dict[str, Any]] = {}
            for card in row.get("cards", []):
                account_id = card.get("account_id")
                if not account_id or account_id in caixa_account_ids:
                    continue
                cards_by_account[account_id] = {
                    **card,
                    **account_identity(account_id),
                    "detailed_total": float(detailed_by_account[account_id]),
                }

            for account_id, detailed_total in detailed_by_account.items():
                if account_id in caixa_account_ids or account_id in cards_by_account:
                    continue
                cards_by_account[account_id] = {
                    **account_identity(account_id),
                    "total_amount": float(detailed_total),
                    "detailed_total": float(detailed_total),
                    "transaction_count": counts_by_account[account_id],
                    "invoice_source": "scheduled_transactions",
                }

            has_caixa_official_bill = False
            for account_id in caixa_account_ids:
                bills = caixa_bills.get((account_id, month), [])
                detailed_total = detailed_by_account[account_id]
                if not bills and not detailed_total:
                    continue
                official_total = sum(
                    (bill.total_amount or Decimal("0") for bill in bills),
                    Decimal("0"),
                )
                has_official_bill = bool(bills)
                has_caixa_official_bill = has_caixa_official_bill or has_official_bill
                invoice_total = official_total if has_official_bill else detailed_total
                account = accounts[account_id]
                cards_by_account[account_id] = {
                    **account_identity(account_id),
                    "total_amount": float(invoice_total),
                    "detailed_total": float(detailed_total),
                    "transaction_count": counts_by_account[account_id],
                    "due_date": bills[0].due_date.isoformat() if bills else None,
                    "closing_day": CAIXA_CLOSING_DAY,
                    "invoice_source": (
                        "caixa_official_bill"
                        if has_official_bill
                        else "caixa_pluggy_forecast"
                        if account_id in forecast_accounts
                        else "caixa_closing_cycle"
                    ),
                    "is_official": has_official_bill,
                    "used_credit": float(account.balance) if account.balance is not None else None,
                    "projected_total": float(projected_by_account[account_id]),
                    "projected_count": projected_counts_by_account[account_id],
                    "credits_total": float(credits_by_account[account_id]),
                    "reconciliation_difference": float(invoice_total - detailed_total),
                }

            cards = list(cards_by_account.values())

            def card_total(card: dict[str, Any]) -> Decimal:
                pending_total = card.get("pending_total")
                value = pending_total if pending_total is not None else card.get("total_amount")
                return Decimal(str(value or 0))

            invoice_total = sum((card_total(card) for card in cards), Decimal("0"))
            detailed_total = sum(detailed_by_account.values(), Decimal("0"))
            difference = invoice_total - detailed_total
            row.update(
                {
                    "total": float(invoice_total),
                    "detailed_total": float(detailed_total),
                    "count": len(serialized_transactions),
                    "invoice_total": float(invoice_total),
                    "cards": cards,
                    "categories": _upcoming_categories(serialized_transactions),
                    "transactions": serialized_transactions,
                    "reported_invoice_total": float(invoice_total),
                    "reported_difference": float(difference),
                }
            )
            if has_caixa_official_bill:
                row["invoice_source"] = "per_card_invoice"
                row["invoice_source_label"] = "Faturas por cartão · CAIXA oficial"
            elif forecast_accounts.intersection(caixa_account_ids):
                row["invoice_source"] = "caixa_pluggy_forecast"
                row["invoice_source_label"] = "Previsão Pluggy + parcelas projetadas"

        months_out = [rows_by_month[month] for month in sorted(rows_by_month)]

    vigente_row = next(month for month in months_out if month["month"] == vigente_month)
    next_invoice = {
        "year_month": vigente_month,
        "transaction_month": vigente_row["transaction_month"],
        "amount": vigente_row["total"],
        "source": vigente_row["invoice_source"],
        "source_label": vigente_row["invoice_source_label"],
        "reported_amount": vigente_row["reported_invoice_total"],
        "is_estimated": True,
    }

    return {
        "total_count": sum(month["count"] for month in months_out),
        "months": months_out,
        "next_invoice": next_invoice,
    }


def monthly_stats_summary(
    session: Session,
    include_ignored: bool = False,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    today = date.today()
    start = date(today.year, today.month, 1)
    txs = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.date >= start, Transaction.date <= today, _non_duplicate_clause()
            ),
            Transaction.user_id,
            user_id,
        ).order_by(Transaction.date.asc())
    ).all()
    txs = filter_transactions_by_account_type(txs, session, SPENDING_ACCOUNT_TYPES, user_id=user_id)
    txs = filter_ignored_transactions(txs, session, include_ignored, user_id=user_id)
    accounts = _accounts_by_id(session, user_id=user_id)

    totals_by_category: Dict[str, dict[str, Any]] = {}
    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in txs:
        classification = _classification_fields(tx, accounts)
        if classification["ignored_from_totals"] or classification["cashflow_type"] != "expense":
            continue
        # Negative rows on CREDIT are refunds/cancellations, not spending —
        # abs() must not turn them into positive expense.
        if tx.amount <= 0:
            continue
        amount = abs(tx.amount)
        category_name = resolve_credit_internal_category(
            tx,
            account_type="CREDIT",
            current_internal_category=classification.get("internal_category"),
        )
        month = tx.date.strftime("%Y-%m")
        totals_by_month[month] += amount
        bucket = totals_by_category.setdefault(
            category_name,
            {
                "id": category_name,
                "name": category_name,
                "effective_category": category_name,
                "resolved_category": category_name,
                "credit_category": category_name,
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
    }


def invoice_summary(
    session: Session,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    exclude_transaction_ids: Optional[set[str]] = None,
    user_id: Optional[int] = None,
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

    classifier = TransactionClassifier.from_session(session, user_id=user_id)
    # Restrict to active credit accounts from the start so that deactivated
    # accounts (e.g. after Pluggy re-authentication) never inflate totals or
    # shift last_payment_date via stale duplicate transactions.
    credit_account_ids = set(account_ids_by_type(session, SPENDING_ACCOUNT_TYPES, user_id=user_id))
    all_up_to = session.exec(
        scope_query(
            select(Transaction).where(
                Transaction.date <= effective_to,
                _non_duplicate_clause(),
            ),
            Transaction.user_id,
            user_id,
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

        open_net = Decimal("0")
        open_count = 0
        for tx in all_up_to:
            if tx.account_id not in credit_account_ids or tx.date <= lower or tx.id in skip:
                continue
            classification = classifier.classify(tx)
            open_net += card_invoice_signed_amount(tx, classification)
            if classification.is_card_purchase:
                open_count += 1
        open_total = max(open_net, Decimal("0"))
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
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    today = date.today()
    effective_to = to_date if to_date is not None else today

    query = scope_query(
        select(Transaction).where(_non_duplicate_clause()), Transaction.user_id, user_id
    )
    if from_date is not None:
        query = query.where(Transaction.date >= from_date)
    query = query.where(Transaction.date <= effective_to)
    past_transactions = session.exec(query).all()
    past_transactions = filter_transactions_by_account_type(
        past_transactions,
        session,
        SPENDING_ACCOUNT_TYPES,
        user_id=user_id,
    )
    past_transactions = filter_ignored_transactions(
        past_transactions,
        session,
        include_ignored,
        user_id=user_id,
    )

    future_count = 0
    if to_date is None:
        future_transactions = session.exec(
            scope_query(
                select(Transaction).where(Transaction.date > today, _non_duplicate_clause()),
                Transaction.user_id,
                user_id,
            )
        ).all()
        future_transactions = filter_transactions_by_account_type(
            future_transactions,
            session,
            SPENDING_ACCOUNT_TYPES,
            user_id=user_id,
        )
        future_count = len(
            filter_ignored_transactions(
                future_transactions,
                session,
                include_ignored,
                user_id=user_id,
            )
        )

    totals_by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    totals_by_cashflow: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_spent = Decimal("0")
    accounts = _accounts_by_id(session, user_id=user_id)

    for tx in past_transactions:
        classification = _classification_fields(tx, accounts)
        if classification["ignored_from_totals"] or classification["cashflow_type"] != "expense":
            continue
        # Negative rows on CREDIT are refunds/cancellations, not spending —
        # abs() must not turn them into positive expense.
        if tx.amount <= 0:
            continue
        amount = abs(tx.amount)
        totals_by_month[tx.date.strftime("%Y-%m")] += amount
        totals_by_cashflow[classification["cashflow_type"]] += amount
        total_spent += amount

    months = [
        {"month": month, "total": float(total)} for month, total in sorted(totals_by_month.items())
    ]

    invoice = invoice_summary(session, from_date=from_date, to_date=to_date, user_id=user_id)

    return {
        "total_spent": float(total_spent),
        "transaction_count": len(past_transactions),
        "future_transaction_count": future_count,
        "categories": [],
        "cashflow_types": [
            {"type": key, "total": float(value)}
            for key, value in sorted(totals_by_cashflow.items())
        ],
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
