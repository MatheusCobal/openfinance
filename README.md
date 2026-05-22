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
| `/` | Dashboard com totais, gráficos, lista de transações por categoria. Filtros: Este mês / 30 dias / 90 dias / Ano / Tudo |
| `/historico` | Cards por categoria com gráfico mensal e comparação mês a mês |
| `/proximos` | Parcelas futuras (parcelado a vencer) organizadas por mês |

## Endpoints principais

| Método | Caminho | O que faz |
|---|---|---|
| GET | `/stats` | Totais agregados (aceita `from_date`, `to_date`) |
| GET | `/stats/monthly` | Matriz categoria × mês |
| GET | `/transactions` | Lista de transações (filtros: `category_id`, `from_date`, `to_date`, `include_future`) |
| GET | `/upcoming` | Parcelas futuras agrupadas por mês |
| GET | `/categories` | Lista de categorias customizadas |
| GET | `/items` / `/accounts` | Conexões e contas |
| POST | `/connect-token` | Token pro widget Pluggy Connect |
| POST | `/items/{id}/sync` | Força sincronização |
| POST | `/webhooks/pluggy` | Recebe eventos do Pluggy (precisa URL pública via ngrok) |
| GET | `/export/transactions.csv` | Export CSV |

## Categorias

9 categorias custom (Alimentação, Transporte, Saúde, Casa, Objetos, Lazer, Educação, Transferências, Outros) mapeadas das ~150 categorias granulares do Pluggy via `CategoryRule`.

Pra ajustar: edita `seed_categories.py` e roda de novo (`.venv/bin/python seed_categories.py`). É idempotente.

## Webhooks (opcional)

Pra sync automático após o refresh diário do Pluggy:

```bash
brew install ngrok
ngrok config add-authtoken SEU_TOKEN  # cadastra em dashboard.ngrok.com
ngrok http 8000                        # em terminal separado, junto com o fastapi dev
```

Pega a URL pública (`https://...ngrok-free.dev`) e cadastra como webhook no dashboard.pluggy.ai apontando pra `/webhooks/pluggy`. O endpoint trata `item/created` e `item/updated`.

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
    ├── models.py              Item, Account, Transaction, Category, CategoryRule
    ├── pluggy_client.py       httpx wrapper paginado
    ├── categorization.py      resolver pluggy_category → Category
    ├── main.py                rotas FastAPI
    └── static/
        ├── index.html, app.js
        ├── historico.html, historico.js
        └── proximos.html, proximos.js
```

## Limitações intencionais

- Sem autenticação (uso local apenas, não exponha publicamente sem adicionar)
- Sem testes automatizados
- Sem Alembic — schema mudou? Drop o `openfinance.db` e reconecta
- Filtro de contas hardcoded em `type == "CREDIT"` (só cartão; conta corrente fica de fora)
- Webhooks de free-tier ngrok têm URL rotativa (precisa atualizar no Pluggy se reiniciar o túnel)
