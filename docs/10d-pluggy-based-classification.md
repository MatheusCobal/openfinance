# 10D-B - Pluggy-based transaction classification

## Objective

10D-B adds a deterministic classification layer based on the raw categories
returned by Pluggy. It replaces the temporary 10D-A empty category surfaces
without reusing the legacy `Category`, `CategoryRule` or `category_id` model as
the source of truth.

No LLM/AI classifier is used. The rules are explicit Python mappings in
`app/services/transaction_classifier.py`.

## Data model

An additive Alembic migration adds nullable classification fields to
`Transaction`:

- `pluggy_raw_category`
- `pluggy_raw_subcategory`
- `pluggy_raw_type`
- `pluggy_merchant`
- `internal_category`
- `cashflow_type`
- `classification_source`
- `classification_confidence`
- `classification_rule_key`
- `is_user_overridden`
- `ignored_from_totals`

`Transaction.category` remains as legacy-compatible raw Pluggy category storage
for existing code and data. It is not an internal category. The old
`category_id` relationship is not reused.

The migration is additive only. It does not drop tables, columns or transaction
data.

## Initial taxonomy

The initial internal categories are intentionally small:

- Alimentação
- Transporte
- Moradia
- Saúde
- Compras
- Assinaturas
- Educação
- Pet
- Lazer
- Viagem
- Presentes
- Beleza / Cuidados pessoais
- Impostos / Taxas
- Financiamentos
- Receitas
- Transferências
- Pagamento de cartão
- Investimentos
- Saque
- Estorno
- Ajustes
- Ignorar
- Outros

## Rule examples

- `food`, `delivery`, `restaurant`, `market`, `groceries`, `Eating out`,
  `Food delivery` -> Alimentação / `expense`
- `transport`, `fuel`, `Gas stations`, `Taxi and ride-hailing`, `Parking` ->
  Transporte / `expense`
- `health`, `Pharmacy`, `Healthcare`, `Dentist` -> Saúde / `expense`
- `Shopping`, `Online shopping`, `Electronics`, `Houseware`, `Clothing`,
  `Office supplies` -> Compras / `expense`
- `income`, `salary`, `Proceeds interests and dividends` -> Receitas /
  `income`
- `transfer`, `Transfer - PIX`, `Transfer - TED`, `Same person transfer` ->
  Transferências / `transfer`
- `credit_card_payment`, `Credit card payment`, `Card payments` -> Pagamento
  de cartão / `credit_card_payment`
- `investment`, `Fixed income`, `Investments`, `Automatic investment` ->
  Investimentos / `investment`
- `refund`, `chargeback` -> Estorno / `refund`
- unknown nonzero values -> Outros / `expense` / `fallback` / `low`

## Cashflow types

The supported cashflow types are:

- `expense`
- `income`
- `transfer`
- `credit_card_payment`
- `refund`
- `investment`
- `cash_withdrawal`
- `adjustment`
- `ignored`
- `unknown`

`transfer`, `credit_card_payment`, `investment`, `cash_withdrawal`,
`adjustment` and `ignored` default to `ignored_from_totals=true` to avoid
double counting operational spending and income. Expenses, income and refunds
remain visible as separate flow types.

## Source and confidence

Each result stores:

- `pluggy_rule`: direct raw Pluggy category/type mapping.
- `system_rule`: deterministic fallback by description or amount/account type.
- `user_rule`: user-defined persistent rule applied after manual overrides and
  before the default Pluggy/system/fallback rules.
- `manual_override`: per-transaction manual override with highest priority.
- `fallback`: explicit low-confidence fallback to `Outros`.
- `unclassified`: reserved for future review queues.

Confidence values are `high`, `medium`, `low` and `unknown`.

## Scripts

Read-only diagnosis:

```bash
.venv/bin/python scripts/inspect_pluggy_classifications.py
```

Dry-run reclassification:

```bash
.venv/bin/python scripts/reclassify_transactions_v2.py --dry-run
```

Apply reclassification:

```bash
.venv/bin/python scripts/reclassify_transactions_v2.py --apply --yes-i-backed-up
```

`--apply` is not run automatically. It preserves future manual overrides and
does not mutate raw Pluggy fields beyond copying the legacy-compatible
`Transaction.category` value into `pluggy_raw_category` when needed.

## UI and APIs

- `GET /transactions` returns the new classification fields.
- `GET /credit-card/current-invoice` groups Dashboard purchase cards by
  `internal_category`.
- `GET /upcoming` groups future purchases by `internal_category`.
- `GET /stats/monthly` returns current-month expense categories from the new
  classification layer.
- Histórico drilldowns show internal category, cashflow type, source/confidence
  and raw Pluggy category.

Legacy category endpoints still return `410 Gone`.

## Local diagnosis

A safe local read-only diagnosis before defining the initial rules showed real
Pluggy values such as `Shopping`, `Eating out`, `Transfer - PIX`, `Pharmacy`,
`Groceries`, `Same person transfer`, `Credit card payment`, `Fixed income` and
`Food delivery`. Descriptions were truncated during diagnosis.

`inspect_pluggy_classifications.py` now groups by raw category, subcategory
and type plus the effective internal classification, supports
`--scope credit|bank|all`, `--only-outros` and `--sort-by count|amount`, and
prints a summary line with total transactions and how many land in `Outros`.

## 10D-B.2 — expanded default rules from real data

The dashboard keeps showing the final **internal categories in Portuguese**;
the raw Pluggy classification (`pluggy_raw_category`, `pluggy_raw_subcategory`,
`pluggy_raw_type`, `pluggy_merchant`) is always preserved for auditing and is
visible in the Histórico drilldown editor and in the Dashboard category modal
meta line.

Rules added in 10D-B.2, all sourced from the local diagnosis (`Outros` count
dropped from 87 to 40 of 3850 transactions):

| Pluggy raw value | internal_category | cashflow_type |
|---|---|---|
| `Food and drinks` | Alimentação | expense |
| `Sports goods` | Compras | expense |
| `Online Courses` | Educação | expense |
| `Tickets` | Lazer | expense |
| `Leisure` | Lazer | expense |
| `Wellness` | Beleza / Cuidados pessoais | expense |
| `Tolls and in vehicle payment` | Transporte | expense |
| `Housing` | Moradia | expense |
| `Rent` | Moradia | expense |
| `Internet` | Assinaturas | expense |
| `Mobile` | Assinaturas | expense |
| `Income taxes` | Impostos / Taxas | expense |
| `Vehicle ownership taxes and fees` | Impostos / Taxas | expense |
| `Transfer - Internal` | Transferências | transfer |
| `Transfer - Bank Slip` | Outros | expense |

The `Transfer - *` rules also fix real bugs:

- `Transfer - Internal` is treated as a structural transfer and ignored from
  totals.
- `Transfer - Bank Slip` is deliberately conservative: it remains
  `Outros / expense` so boleto payments do not become internal transfers and
  disappear from cashflow.

Still in `Outros`, deliberately:

- transactions with an **empty raw category** (genuine fallback);
- `Insurance` — the taxonomy has no "Seguros" category and the value is
  ambiguous (vehicle/health/life); left for a manual override or 10D-D rules;
- `Entrepreneurial activities` — Pluggy applies an income-tree category to
  large outgoing PIX transfers; classifying it automatically as either expense
  or transfer would be a guess, so it stays in the low-confidence fallback for
  the user to override.

`reclassify_transactions_v2.py` additionally reports `no_longer_outros`
(persisted `Outros` rows that the current rules now classify) and
`still_outros` (rows that remain in the fallback) in both dry-run and apply.

### CREDIT vs PIX scope (validated)

The purchase-by-category views only aggregate CREDIT transactions:
`stats_summary`, `monthly_stats_summary` and `upcoming_summary` filter through
`SPENDING_ACCOUNT_TYPES = {"CREDIT"}`, and the current-invoice card is built
per CREDIT account. PIX, transfers, card payments and investments never enter
"Classificação das compras"; bank movements stay in the Receitas / Entradas e
saídas views. No fix was needed — validated by `CreditPurchaseScopeTest`.

## 10D-D — User-defined classification rules

10D-D adds persistent user rules for automatic classification, for examples
like "always classify merchant X as Y", "description containing X as Y" or
"Pluggy raw category/subcategory/type X as Y".

The priority order is:

1. Manual override per transaction.
2. User-defined rule.
3. Default Pluggy-based rule.
4. System rule by description/amount.
5. Fallback to `Outros`.

Manual overrides always win. A user rule never changes a transaction marked
`is_user_overridden=true`, and the reclassification script skips those rows.

### Rule model

Rules live in the additive `user_classification_rules` table. The migration
does not alter transactions, raw Pluggy fields, auth or Pluggy integration.

Fields:

- `id`
- `name`
- `enabled`
- `priority`
- `account_type_scope`
- `match_pluggy_category`
- `match_pluggy_subcategory`
- `match_pluggy_type`
- `match_merchant`
- `match_description`
- `match_amount_sign`
- `target_internal_category`
- `target_cashflow_type`
- `ignored_from_totals`
- `created_at`
- `updated_at`

Lower `priority` wins when more than one rule matches. `enabled=true` by
default. `account_type_scope` accepts `CREDIT`, `BANK` or `ALL`.
`match_amount_sign` accepts `positive`, `negative` or `any`.

Targets are validated against the existing `INTERNAL_CATEGORIES` and
`CASHFLOW_TYPES`; no new taxonomy is introduced. At least one content matcher
is required so a rule cannot accidentally classify the entire portfolio.

### Matching

Matching is conservative and regex-free:

- `match_pluggy_category`, `match_pluggy_subcategory` and `match_pluggy_type`
  use normalized exact matching.
- `match_merchant` and `match_description` use case-insensitive contains.
- `match_amount_sign` filters by positive, negative or any amount.
- `account_type_scope=CREDIT` applies only to card accounts.
- `account_type_scope=BANK` applies only to bank/PIX/debit account movement.
- `account_type_scope=ALL` can apply to both, when the other match criteria
  also match.

When a user rule applies, the automatic classification fields are:

- `classification_source = "user_rule"`
- `classification_confidence = "high"`
- `classification_rule_key = "user_rule:<id>"`

User rules only change:

- `internal_category`
- `cashflow_type`
- `classification_source`
- `classification_confidence`
- `classification_rule_key`
- `ignored_from_totals`

They never change raw Pluggy fields or financial identifiers/values:
`category`, `pluggy_raw_category`, `pluggy_raw_subcategory`,
`pluggy_raw_type`, `pluggy_merchant`, `amount`, `date`, `description`,
`account_id`, `transaction_id` or `item_id`.

If `ignored_from_totals` is left empty, it is derived from the target
`cashflow_type` using the same structural ignored-flow list as 10D-B.

### API and UI

Endpoints:

- `GET /transactions/classification-rules`
- `POST /transactions/classification-rules`
- `PATCH /transactions/classification-rules/{rule_id}`
- `DELETE /transactions/classification-rules/{rule_id}`
- `POST /transactions/classification-rules/preview`
- `POST /transactions/classification-rules/{rule_id}/preview`

The preview endpoint is read-only. It returns the number of matching
non-duplicate, non-manually-overridden transactions plus example rows showing
current and new internal category/cashflow.

`/regras` provides the minimal UI to list, create, edit, enable/disable,
delete and preview rules. It uses the same classification options exposed by
`GET /transactions/classification-options`.

### Safe reclassification

Dry-run user-rule reclassification:

```bash
.venv/bin/python scripts/reclassify_user_rules.py --dry-run
```

Apply user-rule reclassification:

```bash
.venv/bin/python scripts/reclassify_user_rules.py --apply --yes-i-backed-up
```

`--dry-run` is the default. `--apply` requires explicit confirmation and must
only be used after a database backup/recovery path is available. The script
skips manual overrides, never writes raw Pluggy or financial fields, and
reports analyzed rows, rows that would change, matched user rules, category /
cashflow transitions and how many rows remain in `Outros`.

### Safety notes

`SPENDING_ACCOUNT_TYPES = {"CREDIT"}` remains the purchase-classification
boundary. BANK/PIX movements may be classified for budget/cashflow surfaces,
but they do not enter the credit-card purchase breakdown.

`Transfer - Bank Slip` remains conservative (`Outros / expense`) and must not
become `transfer` / `ignored_from_totals=true`. `Transfer - Internal` remains
the structural transfer case.

## Pending work

- 10D-E: dashboard refinado por tipo de fluxo/categoria.
- Physical removal of legacy category tables/columns after a reviewed data
  retention and migration plan.
