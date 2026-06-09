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
- `manual_override`: reserved for future manual override support.
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

## Pending work

- 10D-C: UI de revisão e override manual.
- 10D-D: regras de usuário.
- 10D-E: dashboard refinado por tipo de fluxo/categoria.
- Physical removal of legacy category tables/columns after a reviewed data
  retention and migration plan.
