#!/usr/bin/env python3
"""Mark duplicate transactions after Pluggy re-authentication.

Dry-run by default — pass --apply to actually write changes to the database.
No transactions are ever deleted; this script only sets is_duplicate=True and
duplicate_of_id on stale transactions from inactive accounts.

Algorithm:
  1. Group all transactions by natural key (account_type + normalized_description
     + date + |amount| + installment_number + total_installments).
  2. For each group with 2+ transactions:
     - If there are transactions from BOTH active AND inactive accounts:
       mark inactive-account transactions as is_duplicate=True (the active-
       account copies are the canonical ones).
     - If ALL transactions are from inactive accounts: skip (keep all, nothing
       to choose from).
     - If ALL transactions are from active accounts: skip (might be legitimate
       recurring purchases, not duplicates).
  3. Set duplicate_of_id to the ID of the active-account canonical transaction.

Usage:
    python scripts/mark_duplicate_transactions.py [--db PATH] [--apply]

Options:
    --db PATH    Path to the SQLite database (default: openfinance.db)
    --apply      Write changes to the database (default: dry-run only)
"""
import argparse
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

# Ensure the project root is on sys.path so app imports work when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, create_engine, select

from app.models import Account, Item, Transaction
from app.services.sync import compute_dedupe_key


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", default="openfinance.db", help="Path to the SQLite database"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to the database (default: dry-run)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 60)
    print(f"MARCAR TRANSAÇÕES DUPLICADAS ({mode})")
    print("=" * 60)
    print(f"Database: {db_path}")
    if not args.apply:
        print("(Sem --apply: nenhuma alteração será gravada)")
    print()

    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    with Session(engine) as session:
        # --- load accounts and items ---
        all_accounts: dict[str, Account] = {
            a.id: a for a in session.exec(select(Account)).all()
        }
        active_item_ids = {
            item.id for item in session.exec(select(Item)).all() if item.is_active
        }

        def _is_active(account: Account | None) -> bool:
            if account is None:
                return False
            return bool(account.is_active and account.item_id in active_item_ids)

        all_txs = session.exec(select(Transaction)).all()

        # --- group by natural key ---
        by_key: dict[str, list[Transaction]] = defaultdict(list)
        for tx in all_txs:
            account = all_accounts.get(tx.account_id)
            account_type = account.type if account else "UNKNOWN"
            key = tx.dedupe_key or compute_dedupe_key(
                account_type,
                tx.description,
                tx.date,
                tx.amount,
                tx.installment_number,
                tx.total_installments,
            )
            by_key[key].append(tx)

        # --- decide which transactions to mark ---
        to_mark: list[tuple[Transaction, str]] = []  # (tx, canonical_id)

        for key, txs in by_key.items():
            if len(txs) < 2:
                continue
            active_txs = [
                tx for tx in txs if _is_active(all_accounts.get(tx.account_id))
            ]
            inactive_txs = [
                tx
                for tx in txs
                if not _is_active(all_accounts.get(tx.account_id))
            ]

            # Only act when there is at least one active AND one inactive copy.
            # If all are active or all are inactive we cannot determine which is
            # canonical without extra heuristics — skip to be safe.
            if not active_txs or not inactive_txs:
                continue

            # Use the first active transaction as the canonical one (they should
            # all represent the same purchase).
            canonical_id = active_txs[0].id
            for tx in inactive_txs:
                if not tx.is_duplicate:
                    to_mark.append((tx, canonical_id))

        # --- report what would happen (or what is happening) ---
        total_amount = sum(abs(Decimal(str(tx.amount))) for tx, _ in to_mark)
        print(f"Transações a marcar como is_duplicate=True: {len(to_mark)}")
        print(f"Valor total afetado: R$ {total_amount:.2f}")
        print()

        if to_mark:
            print("Detalhes:")
            print("-" * 60)
            for tx, canonical_id in sorted(to_mark, key=lambda x: (x[0].date, x[0].description)):
                account = all_accounts.get(tx.account_id)
                print(
                    f"  {tx.date}  R${abs(float(tx.amount)):>10.2f}  "
                    f"{tx.description[:40]:40s}  "
                    f"account={tx.account_id[:8]}...  "
                    f"→ canonical={canonical_id[:8]}..."
                )
            print()

        if not to_mark:
            print("Nenhuma duplicata para marcar. Nada a fazer.")
            return

        if not args.apply:
            print(
                "DRY-RUN: nenhuma alteração gravada. "
                "Use --apply para confirmar."
            )
            return

        # --- apply ---
        print("Aplicando alterações...")
        marked_count = 0
        for tx, canonical_id in to_mark:
            tx.is_duplicate = True
            tx.duplicate_of_id = canonical_id
            # Also set dedupe_key if missing so future runs are faster.
            if tx.dedupe_key is None:
                account = all_accounts.get(tx.account_id)
                account_type = account.type if account else "UNKNOWN"
                tx.dedupe_key = compute_dedupe_key(
                    account_type,
                    tx.description,
                    tx.date,
                    tx.amount,
                    tx.installment_number,
                    tx.total_installments,
                )
            session.add(tx)
            marked_count += 1
            if marked_count % 100 == 0:
                session.commit()
                print(f"  {marked_count}/{len(to_mark)} marcadas...")

        session.commit()
        print(f"Concluído: {marked_count} transações marcadas como is_duplicate=True.")
        print()

        # --- refresh monthly snapshots so aggregated views are corrected ---
        print("Recalculando snapshots mensais...")
        from app.services.snapshots import refresh_monthly_balance_snapshots
        refreshed_income, refreshed_invoice, refreshed_balance = (
            refresh_monthly_balance_snapshots(session)
        )
        print(f"  refreshed_income_months:  {refreshed_income}")
        print(f"  refreshed_invoice_months: {refreshed_invoice}")
        print(f"  refreshed_balance_months: {refreshed_balance}")
        print()
        print(
            "NOTA: as transações originais NÃO foram deletadas. "
            "Para removê-las fisicamente (somente após verificação),\n"
            "use DELETE FROM transaction WHERE is_duplicate=1 diretamente no SQLite."
        )


if __name__ == "__main__":
    main()
