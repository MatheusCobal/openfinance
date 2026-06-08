#!/usr/bin/env python3
"""Diagnose duplicate transactions after Pluggy re-authentication.

Read-only: this script does NOT modify any data.

Output sections:
  1. Account overview — active vs inactive, transaction counts.
  2. EXACT-key groups — transactions sharing the same dedupe_key
     (account_type + normalized_description + date + |amount| + installments).
     Sub-classified as: markable (active+inactive), orphan (all-inactive),
     ambiguous (all-active).
  3. RELAXED-match candidates — unmatched inactive transactions that have a
     probable active counterpart within ±1 day / ±R$0.01 / similar description.
  4. Financial summary.

Usage:
    python scripts/diagnose_duplicates.py [--db PATH] [--limit N]

Options:
    --db PATH    Path to the SQLite database (default: openfinance.db)
    --limit N    Max groups shown in detail for each section (default: 20)
"""
import argparse
import sys
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, create_engine, select

from app.categorization import normalize_description
from app.models import Account, Item, Transaction
from app.services.sync import compute_dedupe_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_active(account: Optional[Account], active_item_ids: set) -> bool:
    if account is None:
        return False
    return bool(account.is_active and account.item_id in active_item_ids)


def _desc_prefix(description: Optional[str], length: int = 15) -> str:
    return normalize_description(description)[:length]


def _relaxed_matches(
    inactive_tx: Transaction,
    inactive_account: Optional[Account],
    active_tx_index: Dict[Tuple, List[Transaction]],
    amount_tolerance: Decimal = Decimal("0.01"),
    day_tolerance: int = 1,
    desc_prefix_len: int = 12,
) -> List[Transaction]:
    """Find active transactions that are likely the same real-world purchase."""
    if inactive_account is None:
        return []
    account_type = inactive_account.type
    desc_pfx = _desc_prefix(inactive_tx.description, desc_prefix_len)
    inst_key = (
        inactive_tx.installment_number or 0,
        inactive_tx.total_installments or 0,
    )
    abs_amount = abs(inactive_tx.amount)

    candidates = []
    for delta in range(-day_tolerance, day_tolerance + 1):
        search_date = inactive_tx.date + timedelta(days=delta)
        bucket_key = (account_type, search_date)
        for active_tx in active_tx_index.get(bucket_key, []):
            # Amount tolerance
            if abs(abs(active_tx.amount) - abs_amount) > amount_tolerance:
                continue
            # Description prefix similarity
            active_pfx = _desc_prefix(active_tx.description, desc_prefix_len)
            if not desc_pfx or not active_pfx:
                continue
            if active_pfx != desc_pfx:
                continue
            # Installment must match if BOTH sides have installment info
            active_inst = (
                active_tx.installment_number or 0,
                active_tx.total_installments or 0,
            )
            if inst_key != (0, 0) and active_inst != (0, 0) and inst_key != active_inst:
                continue
            candidates.append(active_tx)
    return candidates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="openfinance.db", help="Path to the SQLite database")
    parser.add_argument("--limit", type=int, default=20, help="Max groups shown per section")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    with Session(engine) as session:
        all_accounts: Dict[str, Account] = {
            a.id: a for a in session.exec(select(Account)).all()
        }
        active_item_ids = {
            item.id for item in session.exec(select(Item)).all() if item.is_active
        }

        def is_active(account_id: str) -> bool:
            return _is_active(all_accounts.get(account_id), active_item_ids)

        all_txs = session.exec(select(Transaction)).all()

    # -----------------------------------------------------------------------
    # Section 1: Account overview
    # -----------------------------------------------------------------------
    print("=" * 70)
    print("DIAGNÓSTICO DE TRANSAÇÕES DUPLICADAS")
    print("=" * 70)
    print(f"Database:              {db_path}")
    print(f"Total de transações:   {len(all_txs)}")
    print()

    tx_count_by_account: Dict[str, int] = defaultdict(int)
    for tx in all_txs:
        tx_count_by_account[tx.account_id] += 1

    active_accs = [a for a in all_accounts.values() if _is_active(a, active_item_ids)]
    inactive_accs = [a for a in all_accounts.values() if not _is_active(a, active_item_ids)]

    print(f"Contas ativas ({len(active_accs)}):")
    for a in sorted(active_accs, key=lambda x: -tx_count_by_account.get(x.id, 0)):
        print(f"  {a.name:40s}  type={a.type:6s}  txs={tx_count_by_account.get(a.id,0)}")
    print()
    print(f"Contas inativas ({len(inactive_accs)}):")
    for a in sorted(inactive_accs, key=lambda x: -tx_count_by_account.get(x.id, 0)):
        if tx_count_by_account.get(a.id, 0) == 0:
            continue
        item_ok = a.item_id in active_item_ids
        print(
            f"  {a.name:40s}  type={a.type:6s}  txs={tx_count_by_account.get(a.id,0):4d}"
            f"  deactivated={a.deactivated_at}"
        )
    print()

    # -----------------------------------------------------------------------
    # Section 2: EXACT key groups
    # -----------------------------------------------------------------------
    by_key: Dict[str, List[Transaction]] = defaultdict(list)
    tx_to_key: Dict[str, str] = {}
    for tx in all_txs:
        account = all_accounts.get(tx.account_id)
        account_type = account.type if account else "UNKNOWN"
        key = tx.dedupe_key or compute_dedupe_key(
            account_type, tx.description, tx.date,
            tx.amount, tx.installment_number, tx.total_installments,
        )
        by_key[key].append(tx)
        tx_to_key[tx.id] = key

    # Classify groups
    exact_markable: List[Tuple[str, List[Transaction], List[Transaction]]] = []  # (key, active, inactive)
    exact_orphan: List[Tuple[str, List[Transaction]]] = []    # only-inactive groups
    exact_ambiguous: List[Tuple[str, List[Transaction]]] = [] # only-active duplicates

    for key, txs in by_key.items():
        if len(txs) < 2:
            continue
        active_txs = [tx for tx in txs if is_active(tx.account_id)]
        inactive_txs = [tx for tx in txs if not is_active(tx.account_id)]

        if active_txs and inactive_txs:
            exact_markable.append((key, active_txs, inactive_txs))
        elif not active_txs and inactive_txs:
            exact_orphan.append((key, inactive_txs))
        elif active_txs and not inactive_txs:
            exact_ambiguous.append((key, active_txs))

    already_marked = sum(1 for tx in all_txs if tx.is_duplicate)

    markable_inactive_count = sum(len(inact) for _, _, inact in exact_markable)
    markable_inactive_amount = sum(
        abs(tx.amount) for _, _, inact in exact_markable for tx in inact
    )

    # Track which inactive tx IDs were matched exactly (for relaxed pass)
    exact_matched_inactive_ids = {
        tx.id
        for _, _, inact in exact_markable
        for tx in inact
    }

    print("=" * 70)
    print("SEÇÃO 2: GRUPOS POR CHAVE EXATA (dedupe_key)")
    print("=" * 70)
    print(f"  Grupos marcáveis  (ativo+inativo):  {len(exact_markable):4d}  →  {markable_inactive_count} tx inativas para marcar  R$ {markable_inactive_amount:,.2f}")
    print(f"  Grupos órfãos     (só inativo):      {len(exact_orphan):4d}  →  nada a marcar automaticamente")
    print(f"  Grupos ambíguos   (só ativo, >1):    {len(exact_ambiguous):4d}  →  compras repetidas legítimas, não tocar")
    print(f"  Já marcados como is_duplicate=True:  {already_marked}")
    print()

    if exact_markable:
        print(f"  Detalhes — primeiros {min(args.limit, len(exact_markable))} grupos marcáveis:")
        print("  " + "-" * 66)
        for i, (key, active_txs, inactive_txs) in enumerate(
            sorted(exact_markable, key=lambda x: abs(x[2][0].amount), reverse=True)[: args.limit]
        ):
            repr_tx = (inactive_txs + active_txs)[0]
            total_active = len(active_txs)
            total_inactive = len(inactive_txs)
            print(f"\n  [{i+1}] key={key}  ativo={total_active}  inativo={total_inactive}")
            for tx in inactive_txs:
                dup_marker = " ⚑DUP" if tx.is_duplicate else ""
                print(
                    f"    [INATIVA{dup_marker}]  {tx.date}  R${abs(float(tx.amount)):>10.2f}"
                    f"  {(tx.description or '')[:40]:40s}  acc={tx.account_id[:8]}..."
                )
            for tx in active_txs:
                print(
                    f"    [ATIVA  ]  {tx.date}  R${abs(float(tx.amount)):>10.2f}"
                    f"  {(tx.description or '')[:40]:40s}  acc={tx.account_id[:8]}..."
                )
        print()

    if exact_orphan:
        print(f"  Grupos órfãos (só inativo) — primeiros {min(5, len(exact_orphan))}:")
        for key, txs in exact_orphan[:5]:
            for tx in txs:
                print(
                    f"    [ÓRFÃ]  {tx.date}  R${abs(float(tx.amount)):>10.2f}"
                    f"  {(tx.description or '')[:40]:40s}  acc={tx.account_id[:8]}..."
                )
        print()

    # -----------------------------------------------------------------------
    # Section 3: RELAXED match candidates
    # -----------------------------------------------------------------------
    # Build index of active transactions by (account_type, date)
    active_tx_index: Dict[Tuple, List[Transaction]] = defaultdict(list)
    for tx in all_txs:
        if is_active(tx.account_id):
            account = all_accounts.get(tx.account_id)
            if account:
                active_tx_index[(account.type, tx.date)].append(tx)

    # Find unmatched inactive txs that have a relaxed-match candidate
    relaxed_candidates: List[Tuple[Transaction, List[Transaction]]] = []
    for tx in all_txs:
        if is_active(tx.account_id):
            continue
        if tx.id in exact_matched_inactive_ids:
            continue  # already handled by exact strategy
        account = all_accounts.get(tx.account_id)
        matches = _relaxed_matches(tx, account, active_tx_index)
        if matches:
            relaxed_candidates.append((tx, matches))

    relaxed_amount = sum(abs(tx.amount) for tx, _ in relaxed_candidates)

    print("=" * 70)
    print("SEÇÃO 3: CANDIDATOS POR MATCHING RELAXADO (±1 dia, ±R$0.01, prefixo desc)")
    print("=" * 70)
    print(f"  Tx inativas não cobertas pelo exato, mas com candidato ativo: {len(relaxed_candidates)}  R$ {relaxed_amount:,.2f}")
    if relaxed_candidates:
        print(f"  (requerem revisão manual — use --include-relaxed no mark script)")
        print()
        print(f"  Detalhes — primeiros {min(args.limit, len(relaxed_candidates))}:")
        print("  " + "-" * 66)
        for i, (inactive_tx, candidates) in enumerate(relaxed_candidates[:args.limit]):
            print(
                f"\n  [{i+1}] [INATIVA]  {inactive_tx.date}  R${abs(float(inactive_tx.amount)):>10.2f}"
                f"  {(inactive_tx.description or '')[:40]:40s}"
                f"  acc={inactive_tx.account_id[:8]}..."
            )
            for c in candidates[:3]:
                print(
                    f"       [ATIVA  ]  {c.date}  R${abs(float(c.amount)):>10.2f}"
                    f"  {(c.description or '')[:40]:40s}"
                    f"  acc={c.account_id[:8]}..."
                )
    else:
        print("  Nenhum candidato relaxado encontrado.")
    print()

    # -----------------------------------------------------------------------
    # Section 4: Financial summary
    # -----------------------------------------------------------------------
    total_inactive_txs = sum(1 for tx in all_txs if not is_active(tx.account_id))
    total_inactive_amount = sum(abs(tx.amount) for tx in all_txs if not is_active(tx.account_id))
    total_active_amount = sum(abs(tx.amount) for tx in all_txs if is_active(tx.account_id))

    print("=" * 70)
    print("SEÇÃO 4: RESUMO FINANCEIRO")
    print("=" * 70)
    print(f"  Transações ativas:                     {len(all_txs) - total_inactive_txs:4d}  volume R$ {total_active_amount:,.2f}")
    print(f"  Transações inativas (total):           {total_inactive_txs:4d}  volume R$ {total_inactive_amount:,.2f}")
    print()
    print(f"  ← Estratégia EXATA marcaria:           {markable_inactive_count:4d}  R$ {markable_inactive_amount:,.2f}")
    print(f"  ← Estratégia RELAXADA adicional:       {len(relaxed_candidates):4d}  R$ {relaxed_amount:,.2f}")
    print(f"  ← Grupos órfãos (mantidos):            {sum(len(txs) for _, txs in exact_orphan):4d}  (sem contraparte ativa)")
    print()
    print(f"  Já marcados como is_duplicate=True:    {already_marked:4d}")
    print()
    if exact_markable or relaxed_candidates:
        print(
            "  AÇÃO RECOMENDADA:\n"
            "    python scripts/mark_duplicate_transactions.py          # dry-run\n"
            "    python scripts/mark_duplicate_transactions.py --apply  # confirmar"
        )
    else:
        print("  Nenhuma duplicata encontrada. Nenhuma ação necessária.")


if __name__ == "__main__":
    main()
