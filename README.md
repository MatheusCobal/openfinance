# OpenFinance

Aplicativo pessoal de planejamento financeiro integrado à [Pluggy](https://pluggy.ai), com foco em visibilidade mensal de receitas, custos fixos, faturas futuras do cartão, histórico financeiro e regras de categorização.

Backend em FastAPI + SQLModel/SQLAlchemy + SQLite; frontend em HTML estático + Tailwind + Chart.js, sem build step.

---

## Funcionalidades atuais

### Dashboard (`/dashboard`)
Tela inicial do app. Resumo executivo com:
- Disponível para gastar
- Fatura vigente do cartão via `/credit-card/current-invoice`
- Saldo bancário
- Entradas, saídas, custos fixos e uso de orçamento variável
- Compras por categoria da fatura vigente

### Planejamento (`/planejamento`)
Tela de planejamento e controle mensal. Visão mensal futura com:
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
GET /              → redirect para /dashboard
GET /dashboard     → resumo executivo
GET /planejamento  → tela de planejamento e controle
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
GET  /credit-card/current-invoice         fatura vigente ajustada para o Dashboard

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
├── scripts/
│   └── backup_database.py     backup manual do SQLite local
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
    │   ├── database_backup.py backup seguro do SQLite local
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
    │   ├── dashboard.html    / dashboard.js
    │   ├── planejamento.html / planejamento.js
    │   ├── proximos.html     / proximos.js
    │   ├── historico.html    / historico.js
    │   ├── regras.html       / regras.js
    │   └── styles.css        estilos compartilhados
    └── docs/                  documentação auxiliar e backlog
```

---

## Como rodar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# editar .env com PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET para usar o Pluggy

.venv/bin/python seed_categories.py   # popula categorias e regras base (idempotente)

fastapi dev app/main.py
# ou: .venv/bin/fastapi dev app/main.py
```

Abre em http://127.0.0.1:8000 (redireciona para `/dashboard`).

---

## Variáveis de ambiente

Definidas em `.env` (via `pydantic-settings`):

```text
PLUGGY_CLIENT_ID            client ID do dashboard.pluggy.ai (obrigatório só ao usar Pluggy)
PLUGGY_CLIENT_SECRET        client secret do dashboard.pluggy.ai (obrigatório só ao usar Pluggy)
PLUGGY_BASE_URL             URL base da API Pluggy (padrão: https://api.pluggy.ai)
DATABASE_URL                URL do banco SQLite (padrão: sqlite:///./openfinance.db)
OPENFINANCE_ENV             local | production (padrão: local)
OPENFINANCE_REQUIRE_AUTH    ativa o Basic Auth do app (padrão: false)
OPENFINANCE_ADMIN_TOKEN     senha do Basic Auth (obrigatória quando require_auth=true)
OPENFINANCE_PUBLIC_HEALTH   deixa /health público mesmo com auth (padrão: true)
OPENFINANCE_WEBHOOK_SECRET  segredo do webhook Pluggy, separado do admin token
```

Importar a aplicação, rodar testes e executar migrações Alembic não exigem credenciais Pluggy. As credenciais só são validadas quando o cliente Pluggy é usado, por exemplo em `/connect-token` ou no sync.

---

## Autenticação (antes de expor publicamente)

O app é **local-first** e roda sem autenticação por padrão. **Não exponha publicamente sem ativar a auth.**

Para habilitar a proteção:

```bash
OPENFINANCE_REQUIRE_AUTH=true
OPENFINANCE_ADMIN_TOKEN=<um-token-forte-e-secreto>
```

Com a auth ativa, todas as páginas e APIs exigem **HTTP Basic Auth**. No navegador aparece o diálogo nativo de login:

- **usuário:** qualquer valor (é ignorado);
- **senha:** o valor de `OPENFINANCE_ADMIN_TOKEN`.

O navegador reenvia a credencial automaticamente nas próximas requisições (inclusive nos `fetch()` do frontend), então não há tela de login própria e o frontend não muda.

Exceções (públicas mesmo com auth ativa):

- `/static/*` — sempre público (não contém segredos);
- `/health` — público quando `OPENFINANCE_PUBLIC_HEALTH=true` (padrão); defina `false` para exigir auth também nele.

### Checklist mínimo antes de expor publicamente

1. `OPENFINANCE_ENV=production` — ativa os guardrails de startup.
2. `OPENFINANCE_REQUIRE_AUTH=true` — ativa o Basic Auth.
3. `OPENFINANCE_ADMIN_TOKEN=<token forte e único>` — senha do Basic Auth.
4. `OPENFINANCE_WEBHOOK_SECRET=<segredo forte e diferente>` — se usar webhook Pluggy.
5. Não exponha sem HTTPS (use Caddy, Nginx ou Cloudflare Tunnel como reverse proxy).
6. Prefira também proteger no reverse proxy como defesa em profundidade.

> O app recusa iniciar se `OPENFINANCE_ENV=production` e `OPENFINANCE_REQUIRE_AUTH=false`
> ou `OPENFINANCE_ADMIN_TOKEN` vazio. A validação roda no startup, antes de aceitar conexões.

### Webhook Pluggy

O `/webhooks/pluggy` **não** usa Basic Auth (a Pluggy não envia essas credenciais). Ele é protegido por um segredo próprio na URL:

```bash
OPENFINANCE_WEBHOOK_SECRET=<um-segredo-forte>
```

Configure no painel Pluggy/ngrok a URL com o token na query string:

```text
https://SEU_DOMINIO/webhooks/pluggy?token=<OPENFINANCE_WEBHOOK_SECRET>
```

Sem o token correto, o webhook é rejeitado (403) antes de processar qualquer payload, acionar sync ou alterar o banco. O `OPENFINANCE_ADMIN_TOKEN` **não** funciona como token de webhook.

Quando `OPENFINANCE_WEBHOOK_SECRET` está definido, a validação do token é aplicada **sempre** — inclusive em modo local com `OPENFINANCE_REQUIRE_AUTH=false`. Assim, uma instância local com webhook configurado nunca fica aberta acidentalmente. Com `OPENFINANCE_WEBHOOK_SECRET` vazio e `OPENFINANCE_REQUIRE_AUTH=false`, o endpoint fica aberto (comportamento conveniente para desenvolvimento local sem webhook).

> Em deploy futuro (VPS, Caddy/Nginx, Cloudflare Tunnel), recomenda-se também proteger no reverse proxy como defesa em profundidade. Não implementado aqui.

---

## Backup, restore e retenção do SQLite

O helper de backup cobre apenas bancos SQLite baseados em arquivo (`sqlite:///...`). URLs em memória (`sqlite://` ou `sqlite:///:memory:`) e outros bancos, como PostgreSQL, são ignorados.

### Backup manual

```bash
.venv/bin/python scripts/backup_database.py --reason manual
```

Os arquivos são salvos em `backups/`, com nome do banco, timestamp e razão sanitizada. O diretório é gitignored.

O app também cria backup automaticamente antes de migrações Alembic executadas por `init_db()` e antes do refresh explícito `POST /history/snapshots/refresh`. Antes de syncs Pluggy pesados ou manutenções locais, rode o backup manualmente.

### Restore

> **IMPORTANTE:** pare o app antes de restaurar o banco.

```bash
.venv/bin/python scripts/restore_database.py --from backups/<arquivo>.db
```

O script:
1. Valida que o arquivo de backup é um SQLite válido (`PRAGMA integrity_check`).
2. Cria um backup de segurança do banco atual com razão `pre-restore` antes de sobrescrever.
3. Copia o backup para um arquivo temporário no mesmo diretório do banco.
4. Valida o temporário e substitui o banco destino atomicamente.
5. Não apaga o arquivo de backup usado como origem.

> **Regra:** um backup só conta depois que um restore foi testado com sucesso.

### Retenção/poda de backups

Para evitar crescimento infinito de `backups/`, rode poda explicitamente:

```bash
# Criar backup e já podar os antigos
.venv/bin/python scripts/backup_database.py --reason manual --prune

# Podar sem criar novo backup
.venv/bin/python scripts/backup_database.py --prune-only

# Controlar quantos manter (padrão: 14 mais recentes + 1 por mês)
.venv/bin/python scripts/backup_database.py --prune-only --keep-last 30
.venv/bin/python scripts/backup_database.py --prune-only --keep-last 14 --no-keep-monthly
```

Apenas arquivos com o padrão de timestamp gerado pelo app são removidos. Arquivos fora do padrão são sempre preservados.

### Backup offsite

Backups em `backups/` protegem contra erro humano, mas não contra falha de disco. Para dados financeiros, recomenda-se copiar backups para um destino externo (ex.: `rclone` com Google Drive ou Backblaze B2, de preferência criptografado). Configure um job cron ou systemd timer para rodar periodicamente:

```bash
.venv/bin/python scripts/backup_database.py --reason daily --prune
rclone copy backups/ remote:openfinance-backups/
```

---

## Testes

```bash
.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/python -m compileall app tests
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m pytest
DATABASE_URL=sqlite:////tmp/openfinance-ci.db .venv/bin/alembic upgrade head
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

## Sync Pluggy

O sync Pluggy é uma operação de escrita no banco local. Em SQLite baseado em arquivo, o app cria backup automaticamente antes do sync manual `POST /items/{item_id}/sync`. Em SQLite em memória ou bancos não-SQLite, o helper de backup não cria arquivo.

Para manutenção ou syncs pesados, também é possível executar backup manual antes:

```bash
.venv/bin/python scripts/backup_database.py --reason before-pluggy-sync
```

O backend expõe um endpoint de status de sincronização:

```text
GET /sync/status
GET /sync/health
```

Ele mostra um resumo de itens, contas, transações, faturas e a melhor estimativa disponível da última sincronização.

Como o app não mantém uma tabela dedicada de execuções de sync, `last_sync_status` é calculado a partir dos timestamps e erros persistidos em `Item` e `AccountSync`. Quando não há dados suficientes, o status retorna `unknown` com `last_sync_status_source` igual a `not_tracked`.

Use `/sync/health` para revisar locks de sync (`idle`, `running`, `stale`) e falhas persistidas por conta antes de repetir uma sincronização.

---

## Histórico recente

- `/dashboard` foi reintroduzida como resumo executivo e é o destino de `/`
- `/planejamento` segue como tela de planejamento e controle mensal
- A navegação mantém Dashboard, Planejamento, Próximos, Histórico e Regras
- As rotas `/custos-fixos` e `/orcamento` foram mantidas apenas como redirects legados
- O projeto passou a usar Alembic para migrações de schema
- `seed_dev.py` foi removido do projeto

---

## Limitações intencionais

- Auth desativada por padrão (local-first); proteção mínima via Basic Auth disponível — veja [Autenticação](#autenticação-antes-de-expor-publicamente) antes de expor publicamente
- Em `OPENFINANCE_ENV=production`, app recusa iniciar se auth estiver desativada ou admin token vazio (guardrail de startup)
- Filtro de contas hardcoded em `type == "CREDIT"` (foco em cartão; conta corrente fica de fora)
- Sync incremental com janela de segurança de 7 dias para capturar alterações recentes
- Webhooks dependem do ngrok rodando junto com o app local

---

## Roadmap técnico

- Adicionar GitHub Actions para rodar testes automaticamente
- Expandir política operacional de backup/sync quando necessário
- Melhorar documentação de sync Pluggy
- Revisar e mover scripts auxiliares para `scripts/`
- Continuar simplificando services grandes quando necessário
