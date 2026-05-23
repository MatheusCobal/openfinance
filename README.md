# OpenFinance

Dashboard pessoal de gastos de cartão de crédito via [Pluggy](https://pluggy.ai) (com [Meu Pluggy](https://meu.pluggy.ai) como passport pra Open Finance gratuito).

FastAPI + SQLModel + SQLite no backend; HTML estático + Tailwind + Chart.js no frontend, sem build step.

## Setup inicial

```bash
cd ~/projects/openfinance
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
# edita .env com PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET (do dashboard.pluggy.ai)
.venv/bin/python seed_categories.py   # popula categorias e regras
```

## Como rodar

```bash
fastapi dev app/main.py    # com o venv ativo, ou:
.venv/bin/fastapi dev app/main.py
```

Abre em http://127.0.0.1:8000.

## Como conectar um banco

1. Cria conta grátis em [meu.pluggy.ai](https://meu.pluggy.ai) e conecta seu banco lá
2. No dashboard.pluggy.ai, habilita o conector **MeuPluggy** (ID 200) na sua Application
3. No nosso app: clica **"+ Conectar banco"** → escolhe MeuPluggy → autoriza
4. Os dados sincronizam automaticamente

## Páginas

| Rota | Descrição |
|---|---|
| `/` | Dashboard com totais, gráficos, lista de transações por categoria, filtro por período e export CSV |
| `/historico` | Cards por categoria com gráfico mensal e comparação mês a mês |
| `/proximos` | Parcelas futuras (parcelado a vencer) organizadas por mês |
| `/orcamento` | Metas por categoria, com meta padrão ou ajuste específico por mês |

## Endpoints principais

| Método | Caminho | O que faz |
|---|---|---|
| GET | `/stats` | Totais agregados (aceita `from_date`, `to_date`, `include_ignored`) |
| GET | `/stats/monthly` | Matriz categoria × mês (aceita `include_ignored`) |
| GET | `/transactions` | Lista de transações (filtros: `category_id`, `from_date`, `to_date`, `include_future`, `include_ignored`) |
| GET | `/upcoming` | Parcelas futuras agrupadas por mês (aceita `include_ignored`) |
| GET | `/ignored-transactions/monthly` | Histórico mensal de transações ignoradas, como pagamentos de fatura |
| GET | `/categories` | Lista de categorias customizadas |
| POST | `/category-rules/description` | Cria/atualiza regra manual por texto da descrição |
| GET | `/transaction-ignore-rules/description` | Lista regras de transações ignoradas por descrição |
| POST | `/transaction-ignore-rules/description` | Cria/atualiza regra de transação ignorada por descrição |
| GET | `/budgets/progress` | Progresso por categoria no mês (`year_month=YYYY-MM`, aceita `include_ignored`) |
| PUT | `/budgets/{category_id}` | Cria/atualiza meta padrão da categoria |
| DELETE | `/budgets/{category_id}` | Remove meta padrão da categoria |
| PUT | `/budgets/{category_id}/months/{YYYY-MM}` | Cria/atualiza meta específica de um mês |
| DELETE | `/budgets/{category_id}/months/{YYYY-MM}` | Remove meta específica de um mês |
| GET | `/items` / `/accounts` | Conexões e contas |
| POST | `/connect-token` | Token pro widget Pluggy Connect |
| POST | `/items/{id}/sync` | Força sincronização |
| POST | `/webhooks/pluggy` | Recebe eventos do Pluggy (precisa URL pública via ngrok) |
| GET | `/export/transactions.csv` | Export CSV com valor original e valor absoluto (aceita `include_ignored`) |

## Categorias

Categorias custom mapeadas das categorias granulares do Pluggy via `CategoryRule`. Regras manuais por descrição ficam em `DescriptionCategoryRule` e têm prioridade sobre o mapeamento automático. Regras em `IgnoredDescriptionRule` removem pagamentos de fatura e outros lançamentos não computáveis dos dashboards por padrão; use `include_ignored=true` para auditar tudo.

Pra ajustar: edita `seed_categories.py` e roda de novo (`.venv/bin/python seed_categories.py`). É idempotente.

## Webhooks (opcional)

Pra sync automático após o refresh diário do Pluggy:

```bash
brew install ngrok
ngrok config add-authtoken SEU_TOKEN  # cadastra em dashboard.ngrok.com
ngrok http 8000 --url https://SEU_DOMINIO.ngrok-free.dev  # terminal separado, junto com o fastapi dev
```

Cadastra a URL do webhook no dashboard.pluggy.ai:

```text
https://SEU_DOMINIO.ngrok-free.dev/webhooks/pluggy
```

O endpoint trata `item/created` e `item/updated`. O ngrok precisa ficar rodando enquanto o app local estiver recebendo webhooks.

## Estrutura

```
openfinance/
├── pyproject.toml
├── seed_categories.py         9 categorias + 106 regras
├── seed_dev.py                seed de transações fake (uso opcional)
├── openfinance.db             SQLite local (gitignored)
└── app/
    ├── config.py              .env via pydantic-settings
    ├── database.py            engine SQLite
    ├── models.py              Item, Account, AccountSync, Transaction, Category, CategoryRule, DescriptionCategoryRule, IgnoredDescriptionRule, Budget, BudgetOverride
    ├── pluggy_client.py       httpx wrapper paginado
    ├── categorization.py      resolver pluggy_category → Category
    ├── main.py                rotas FastAPI
    └── static/
        ├── index.html, app.js
        ├── historico.html, historico.js
        ├── proximos.html, proximos.js
        └── orcamento.html, orcamento.js
```

## Limitações intencionais

- Sem autenticação (uso local apenas, não exponha publicamente sem adicionar)
- Sem testes automatizados
- Sem Alembic — schema mudou? Drop o `openfinance.db` e reconecta
- Filtro de contas hardcoded em `type == "CREDIT"` (só cartão; conta corrente fica de fora)
- Sync incremental por conta com janela de segurança de 7 dias para capturar alterações recentes
- Webhooks dependem do processo do ngrok estar rodando junto com o app local
