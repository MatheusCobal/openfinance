# OpenFinance

Aplicativo pessoal de planejamento financeiro integrado à [Pluggy](https://pluggy.ai), com foco em visibilidade mensal de receitas, custos fixos, faturas futuras do cartão, histórico financeiro e regras de categorização.

Backend em FastAPI + SQLModel/SQLAlchemy + SQLite; frontend em HTML estático + Tailwind + Chart.js, sem build step.

---

## Funcionalidades atuais

### Planejamento (`/planejamento`)
Tela principal do app. Visão mensal futura com:
- Receita esperada
- Custos fixos
- Metas variáveis (budgets)
- Fatura planejada do cartão
- Resultado/sobra planejada

### Próximos (`/proximos`)
- Parcelas e faturas futuras do cartão
- Agrupamento por mês
- Lista de próximos compromissos financeiros

### Histórico (`/historico`)
- Faturas do cartão por mês
- Categorias abaixo das faturas
- Histórico de receitas bancárias

### Regras (`/regras`)
- Regras de categorização de transações por descrição
- Regras de exclusão de transações (ex: pagamento de fatura)
- Regras de exclusão de receitas bancárias

### Sync Pluggy
- Sincronização de dados via API Pluggy preservada no backend
- Webhooks opcionais para sync automático após refresh diário

---

## Rotas principais

### Páginas

```text
GET /              → redirect para /planejamento
GET /planejamento  → tela principal (Planejamento)
GET /proximos      → tela Próximos
GET /historico     → tela Histórico
GET /regras        → tela Regras
GET /health        → health check

GET /custos-fixos  → redirect legado para /planejamento
GET /orcamento     → redirect legado para /planejamento
```

### API

```text
GET  /planning/month/{year_month}        agregado mensal do Planejamento

GET  /upcoming                           parcelas futuras agrupadas por mês
GET  /transactions                       lista de transações (filtros: category_id, from_date, to_date, include_future, include_ignored)
GET  /stats                              totais agregados
GET  /stats/monthly                      matriz categoria × mês

GET  /fixed-costs                        custos fixos cadastrados
GET  /fixed-costs/by-month               custos fixos por mês
GET  /fixed-costs/upcoming               próximos custos fixos
GET  /fixed-cost-categories              categorias de custo fixo
GET  /spending-capacity                  disponibilidade financeira calculada

GET  /expected-income                    receitas esperadas
GET  /expected-income/forecast           previsão de receitas
GET  /expected-income/by-month           receitas por mês

GET  /credit-card/invoice/{year_month}   fatura do cartão de crédito

GET  /history/...                        histórico financeiro (ver routes/history.py)
GET  /rules/...                          regras de categorização e exclusão

GET  /items                              conexões Pluggy
GET  /accounts                           contas conectadas
POST /connect-token                      token para widget Pluggy Connect
POST /items/{item_id}/sync               força sincronização de um item
POST /webhooks/pluggy                    recebe eventos do Pluggy
```

---

## Estrutura do projeto

```text
openfinance/
├── pyproject.toml
├── alembic/                   migrações de schema
├── seed_categories.py         popula categorias e regras base
├── openfinance.db             SQLite local (gitignored)
└── app/
    ├── config.py              variáveis de ambiente via pydantic-settings
    ├── database.py            engine e sessão SQLite
    ├── models.py              modelos/tabelas SQLModel
    ├── pluggy_client.py       cliente HTTP paginado para API Pluggy
    ├── routes/                rotas HTTP por domínio
    │   ├── pages.py           rotas de páginas HTML
    │   ├── planning.py        endpoint do Planejamento
    │   ├── fixed_costs.py     custos fixos e spending capacity
    │   ├── expected_income.py receitas esperadas
    │   ├── credit_card.py     fatura do cartão
    │   ├── history.py         histórico financeiro
    │   ├── transactions.py    transações e categorias
    │   ├── rules.py           regras de categorização e exclusão
    │   ├── budgets.py         metas por categoria
    │   ├── sync.py            sync Pluggy e conexões
    │   └── pluggy_webhooks.py recepção de webhooks Pluggy
    ├── services/              regras de negócio
    │   ├── planning.py        agregador do Planejamento mensal
    │   ├── spending_capacity.py cálculo de disponibilidade
    │   ├── credit_card_invoice.py lógica de fatura/cartão
    │   ├── fixed_costs.py     domínio de custos fixos
    │   ├── expected_income.py receitas esperadas
    │   ├── budgets.py         metas variáveis
    │   ├── history.py         dados do Histórico
    │   ├── transaction_reports.py agrupamentos de transações
    │   ├── sync.py            orquestra sync Pluggy
    │   ├── pluggy_snapshot.py persistência de dados vindos da Pluggy
    │   ├── rules.py           regras de categorização
    │   ├── classification.py  classificação de transações
    │   └── transactions.py    consultas de transações
    ├── static/                frontend HTML/JS
    │   ├── planejamento.html / planejamento.js
    │   ├── proximos.html     / proximos.js
    │   ├── historico.html    / historico.js
    │   └── regras.html       / regras.js
    └── docs/                  documentação auxiliar e backlog
```

---

## Como rodar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# editar .env com PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET

.venv/bin/python seed_categories.py   # popula categorias e regras base (idempotente)

fastapi dev app/main.py
# ou: .venv/bin/fastapi dev app/main.py
```

Abre em http://127.0.0.1:8000 (redireciona para `/planejamento`).

---

## Variáveis de ambiente

Definidas em `.env` (via `pydantic-settings`):

```text
PLUGGY_CLIENT_ID       client ID do dashboard.pluggy.ai (obrigatório)
PLUGGY_CLIENT_SECRET   client secret do dashboard.pluggy.ai (obrigatório)
PLUGGY_BASE_URL        URL base da API Pluggy (padrão: https://api.pluggy.ai)
DATABASE_URL           URL do banco SQLite (padrão: sqlite:///./openfinance.db)
```

---

## Testes

```bash
.venv/bin/python -m unittest discover -s tests
```

Estado atual:

```text
Ran 175 tests in ~3.7s
OK
```

Os testes cobrem:
- Rotas de página (pages)
- Planejamento mensal
- Próximos gastos e faturas futuras
- Histórico e faturas do cartão
- Regras de categorização e exclusão
- Sync Pluggy e webhooks
- Custos fixos e receitas esperadas
- Lifecycle de itens e contas

---

## Como conectar um banco

1. Cria conta em [meu.pluggy.ai](https://meu.pluggy.ai) e conecta seu banco
2. No [dashboard.pluggy.ai](https://dashboard.pluggy.ai), habilita o conector MeuPluggy (ID 200) na sua Application
3. No app: acessa `/items` ou usa o widget Pluggy Connect via `/connect-token`
4. Os dados sincronizam via `/items/{id}/sync`

---

## Webhooks Pluggy (opcional)

Para sync automático após o refresh diário:

```bash
brew install ngrok
ngrok config add-authtoken SEU_TOKEN
ngrok http 8000 --url https://SEU_DOMINIO.ngrok-free.dev
```

Cadastra no dashboard.pluggy.ai:

```text
https://SEU_DOMINIO.ngrok-free.dev/webhooks/pluggy
```

O endpoint trata `item/created` e `item/updated`.

---

## Histórico recente

- A Dashboard antiga foi removida
- Planejamento virou a tela principal
- A navegação foi reduzida para Planejamento, Próximos, Histórico e Regras
- As rotas `/custos-fixos` e `/orcamento` foram mantidas apenas como redirects legados
- O projeto passou a usar Alembic para migrações de schema
- `seed_dev.py` foi removido do projeto

---

## Limitações intencionais

- Sem autenticação (uso local apenas — não exponha publicamente sem adicionar auth)
- Filtro de contas hardcoded em `type == "CREDIT"` (foco em cartão; conta corrente fica de fora)
- Sync incremental com janela de segurança de 7 dias para capturar alterações recentes
- Webhooks dependem do ngrok rodando junto com o app local

---

## Roadmap técnico

- Adicionar GitHub Actions para rodar testes automaticamente
- Criar rotina segura de backup do banco local
- Melhorar documentação de sync Pluggy
- Revisar e mover scripts auxiliares para `scripts/`
- Continuar simplificando services grandes quando necessário
