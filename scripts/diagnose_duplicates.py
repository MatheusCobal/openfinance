#!/usr/bin/env python3
"""Diagnose duplicate transactions after Pluggy re-authentication.

Read-only: this script does NOT modify any data.

Usage:
    python scripts/diagnose_duplicates.py [--db PATH] [--limit N]

Options:
    --db PATH    Path to the SQLite database (default: openfinance.db)
    --limit N    Show at most N duplicate groups in detail (default: 20)
"""
import argparse
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

# Ensure the project root is on sys.path so app imports work when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, create_engine, select

from app.categorization import normalize_description
from app.models import Account, Item, Transaction
from app.services.sync import compute_dedupe_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="openfinance.db", help="Path to the SQLite database")
    parser.add_argument("--limit", type=int, default=20, help="Max duplicate groups to show in detail")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    with Session(engine) as session:
        # --- load accounts and items ---
        all_accounts: dict[str, Account] = {
            a.id: a for a in session.exec(select(Account)).all()
        }
        active_item_ids = {
            item.id for item in session.exec(select(Item)).all() if item.is_active
        }

        def _is_active(account: Account) -> bool:
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

        # --- summary ---
        print("=" * 60)
        print("DIAGNÓSTICO DE TRANSAÇÕES DUPLICADAS")
        print("=" * 60)
        print(f"Database: {db_path}")
        print(f"Total de transações: {len(all_txs)}")
        print(f"Total de contas: {len(all_accounts)}")

        active_accounts = [a for a in all_accounts.values() if _is_active(a)]
        inactive_accounts = [a for a in all_accounts.values() if not _is_active(a)]
        print(f"  Contas ativas:   {len(active_accounts)}")
        print(f"  Contas inativas: {len(inactive_accounts)}")
        print()

        # --- inactive accounts with transactions ---
        tx_count_by_account: dict[str, int] = defaultdict(int)
        for tx in all_txs:
            tx_count_by_account[tx.account_id] += 1

        inactive_with_txs = [
            (a, tx_count_by_account.get(a.id, 0))
            for a in inactive_accounts
            if tx_count_by_account.get(a.id, 0) > 0
        ]
        if inactive_with_txs:
            print("CONTAS INATIVAS COM TRANSAÇÕES:")
            for account, count in sorted(inactive_with_txs, key=lambda x: -x[1]):
                item_active = account.item_id in active_item_ids
                print(
                    f"  {account.name:30s}  type={account.type}  "
                    f"is_active={account.is_active}  item_active={item_active}  "
                    f"txs={count}  deactivated={account.deactivated_at}"
                )
            print()
        else:
            print("Nenhuma conta inativa com transações encontrada.")
            print()

        # --- duplicate groups ---
        dup_groups = [
            (key, txs)
            for key, txs in by_key.items()
            if len(txs) >= 2
        ]
        dup_groups.sort(key=lambda kv: len(kv[1]), reverse=True)

        total_inactive_duplicates = 0
        total_inactive_amount = Decimal("0")
        already_marked = sum(1 for tx in all_txs if tx.is_duplicate)

        print(f"Grupos com chave duplicada (≥2 transações): {len(dup_groups)}")
        print(f"Já marcados como is_duplicate=True: {already_marked}")
        print()

        if dup_groups:
            print(f"Detalhes (primeiros {min(args.limit, len(dup_groups))} grupos):")
            print("-" * 60)
            for i, (key, txs) in enumerate(dup_groups[: args.limit]):
                active_txs = [tx for tx in txs if _is_active(all_accounts.get(tx.account_id))]
                inactive_txs = [tx for tx in txs if not _is_active(all_accounts.get(tx.account_id))]
                total_inactive_duplicates += len(inactive_txs)
                total_inactive_amount += sum(abs(tx.amount) for tx in inactive_txs)

                print(f"\nGrupo {i + 1}/{len(dup_groups)}  key={key}")
                print(f"  Total no grupo: {len(txs)}  (ativas: {len(active_txs)}, inativas: {len(inactive_txs)})")
                for tx in txs:
                    account = all_accounts.get(tx.account_id)
                    active = _is_active(account) if account else False
                    dup_marker = "[DUPLICATA]" if tx.is_duplicate else ""
                    print(
                        f"  {'[ATIVA]' if active else '[INATIVA]':10s} {dup_marker:12s} "
                        f"{tx.date}  R${abs(tx.amount):>10.2f}  {tx.description[:40]}"
                        f"  account={tx.account_id[:8]}..."
                    )
        else:
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
                if key in by_key:
                    total_inactive_duplicates += sum(
                        1 for t in by_key[key] if not _is_active(all_accounts.get(t.account_id))
                    )
                    total_inactive_amount += sum(
                        abs(t.amount)
                        for t in by_key[key]
                        if not _is_active(all_accounts.get(t.account_id))
                    )

        print()
        print("=" * 60)
        print("RESUMO")
        print("=" * 60)
        total_inactive_in_groups = sum(
            len([t for t in txs if not _is_active(all_accounts.get(t.account_id))])
            for _, txs in dup_groups
        )
        total_inactive_amt = sum(
            abs(t.amount)
            for _, txs in dup_groups
            for t in txs
            if not _is_active(all_accounts.get(t.account_id))
        )
        print(f"Grupos duplicados encontrados:       {len(dup_groups)}")
        print(f"Transações duplicadas (inativas):    {total_inactive_in_groups}")
        print(f"Valor total das duplicatas:          R$ {total_inactive_amt:.2f}")
        print(f"Já marcados como is_duplicate=True:  {already_marked}")
        print()
        if dup_groups:
            print(
                "AÇÃO RECOMENDADA: execute 'python scripts/mark_duplicate_transactions.py' "
                "(dry-run) para ver o que seria marcado,\n"
                "depois com --apply para confirmar."
            )
        else:
            print("Nenhuma duplicata encontrada. Nenhuma ação necessária.")


if __name__ == "__main__":
    main()
