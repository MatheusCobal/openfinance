# 10D-A - Legacy category removal

## What changed

The legacy internal financial category layer was removed as an active source of
truth. This includes the automatic default taxonomy, the `"Outros"` fallback,
Pluggy-to-internal-category mappings, description-to-category rules, category
budget progress, and dashboard/history/upcoming aggregations grouped by the old
category model.

The database tables and columns tied to the legacy model were not physically
dropped in this task. They remain as legacy storage only so real transaction
data and existing databases are not destroyed without a reviewed migration.

## Why

Transactions come from Pluggy with their own raw classification fields. The app
had built an internal category taxonomy before preserving and modeling those
Pluggy classifications cleanly. Keeping the old layer active would make the new
Pluggy-based design inherit incorrect assumptions and fallbacks.

## Temporarily broken or suspended

- `/categories` returns `410 Gone`.
- `/category-rules/description*` returns `410 Gone`.
- Variable budget write endpoints under `/budgets/{category_id}` return
  `410 Gone`.
- `/stats/monthly` returns an empty legacy category matrix.
- Dashboard category cards show a temporary 10D-B message.
- Histórico no longer renders category spending cards under invoice history.
- Planejamento keeps fixed costs and income, but variable category goals are
  suspended with an empty progress response.
- Próximos lists future transactions without grouping them into legacy
  categories.

## Pluggy data preserved

The sync/import flow continues to store the existing transaction fields:

- original description;
- amount;
- date;
- account id;
- currency;
- status;
- bill id;
- installment metadata;
- total amount;
- dedupe key;
- `Transaction.category`, preserved as the raw Pluggy category string.

Account, item, credit-card bill and investment snapshot fields are unchanged.

## Pluggy data still pending

The current sync persists `raw_tx["category"]` into `Transaction.category`, but
does not yet persist separate Pluggy classification fields such as raw
subcategory, raw type, merchant, full raw payload, or confidence/source
metadata. If those fields are present in the Pluggy transaction payload, 10D-B
should add explicit columns or a raw payload store in `app/services/sync.py`
inside `upsert_transaction()`.

## Decisions for 10D-B

- Model Pluggy raw category/subcategory/type separately from any user-facing
  internal category.
- Define how raw Pluggy classifications map to user-owned categories.
- Decide how user overrides and rule provenance are stored.
- Replace suspended dashboard/history/planning category surfaces with the new
  Pluggy-based classification layer.
- Add a reviewed migration for physically removing legacy tables/columns after
  data retention is confirmed.
