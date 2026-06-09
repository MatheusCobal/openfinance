# 10D-C — Manual transaction classification override

Lets the user pin a specific transaction to an internal category / cashflow
type, see that correction reflected in Histórico and Dashboard, and undo it
back to the automatic 10D-B classification.

This is **per-transaction only**. Automatic user rules ("always classify
merchant X as Y") are out of scope and reserved for 10D-D.

## Endpoints

### `GET /transactions/classification-options`

Returns the controlled vocabularies for the edit UI, sourced directly from the
10D-B classifier constants (`INTERNAL_CATEGORIES`, `CASHFLOW_TYPES`,
`IGNORED_CASHFLOW_TYPES` in `app/services/transaction_classifier.py` — no
duplicated lists):

```json
{
  "internal_categories": ["Alimentação", "Transporte", "..."],
  "cashflow_types": ["adjustment", "cash_withdrawal", "..."],
  "suggested_ignored_from_totals": {"expense": false, "transfer": true, "...": true}
}
```

### `PATCH /transactions/{transaction_id}/classification`

```json
{
  "internal_category": "Alimentação",
  "cashflow_type": "expense",
  "ignored_from_totals": false
}
```

`ignored_from_totals` is optional; when omitted the backend derives it from the
cashflow type using the same `IGNORED_CASHFLOW_TYPES` rule the automatic
classifier applies (transfer / credit_card_payment / investment /
cash_withdrawal / adjustment / ignored → `true`).

On success the transaction is updated to:

| Field | Value |
|---|---|
| `internal_category` | user-chosen value |
| `cashflow_type` | user-chosen value |
| `ignored_from_totals` | user-chosen or derived |
| `classification_source` | `manual_override` |
| `classification_confidence` | `high` |
| `classification_rule_key` | `manual_override` |
| `is_user_overridden` | `true` |

Validation: `internal_category` must be in the 10D-B taxonomy and
`cashflow_type` in the supported set, otherwise HTTP 400. Unknown transaction →
HTTP 404.

Fields that are **never** touched: `amount`, `date`, `description`,
`account_id`, `dedupe_key`, `category` (legacy raw), `pluggy_raw_category`,
`pluggy_raw_subcategory`, `pluggy_raw_type`, `pluggy_merchant`. No
`Category`/`category_id` legacy table is read or written.

### `DELETE /transactions/{transaction_id}/classification-override`

Removes the override: re-runs the 10D-B automatic classifier
(`classify_transaction`) with the account type and persists the result with
`is_user_overridden = false`. If no rule matches, the new-layer fallback
applies (`Outros` / `fallback` / `low`) — the transaction is never left
unclassified.

## UI (Histórico)

In every drilldown (Faturas cartão, Receitas, Entradas e saídas) each
transaction row shows:

- badges: **Manual** (overridden), **Revisar** (fallback + low confidence),
  **Ignorada dos totais** (`ignored_from_totals`);
- the classification meta line (category, cashflow type, source/confidence,
  raw Pluggy category);
- an **Editar classificação** link that opens an inline editor with category
  select, cashflow select, "Ignorar dos totais" checkbox, raw Pluggy details,
  **Salvar**, **Restaurar automático** (only when overridden) and **Cancelar**.

Changing the cashflow select pre-fills the checkbox from
`suggested_ignored_from_totals`; the user can still toggle it and the backend
persists the explicit value. Saving or restoring closes the drilldown and
reloads the page data, so totals refresh immediately.

## Effect on Dashboard / Histórico

All monthly views classify through `serialize_transaction_classification` /
`TransactionClassifier`, both of which prefer the **persisted** fields when
present. A manual override therefore flows automatically into:

- expense category cards (`internal_category`);
- expense totals (`ignored_from_totals` + `cashflow_type != "expense"` guard);
- invoice-payment detection (`cashflow_type == "credit_card_payment"`);
- bank income / cashflow views (`transfer` / `investment` overrides become
  structural exclusions).

**Known limitation:** snapshot-based history aggregates (`BankIncomeMonth`,
`CreditCardInvoiceMonth`, `MonthlyBalanceMonth`) are recomputed on the next
sync or via `POST /history/snapshots/refresh`, not at override time. The live
monthly endpoints used by the Histórico tabs recompute on every request and
reflect overrides immediately.

## Reclassification script

`scripts/reclassify_transactions_v2.py` skips rows with
`is_user_overridden = true` in both `--dry-run` and `--apply`, and reports the
count in the `skipped_overrides` output line. The sync upsert
(`app/services/sync.py`) likewise refreshes raw Pluggy fields but never
overwrites the classification fields of an overridden transaction.

## Left for later

- **10D-D** — automatic user rules ("always classify merchant/description X as
  Y"), bulk edit, rule management UI.
- **10D-E** — dashboard/budget refinement on top of internal categories
  (budgets per internal category, snapshot invalidation on override).
