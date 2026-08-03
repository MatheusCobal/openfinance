# Auditoria e plano de reestruturação do OpenFinance

Data da análise: 15 de julho de 2026
Escopo: backend, frontend, banco, testes, segurança e execução atual na AWS.
Estado: correções da primeira fase implementadas no branch `codex/major-restructure`; produção não alterada.

## Resumo executivo

O sistema tem uma base funcional e uma cobertura de backend incomum para um projeto desse tamanho: 510 testes passam. O risco principal não é duplicação literal de linhas — a medição encontrou cerca de 0,53% de clones — e sim concentração excessiva de responsabilidades, contratos de API redundantes e algumas garantias operacionais ausentes.

Os maiores pontos de concentração atuais são:

| Arquivo | Linhas | Problema dominante |
|---|---:|---|
| `frontend/src/pages/PlanejamentoPage.tsx` | 2.923 | página, regras, formulários e quatro visualizações no mesmo módulo |
| `app/services/fixed_costs.py` | 1.096 | CRUD, matching, calendário, serialização e agregação misturados |
| `app/services/credit_card_invoice.py` | 1.049 | resolução de ciclo, fontes, reconciliação e apresentação no mesmo serviço |
| `app/services/history.py` | 871 | consulta, classificação e montagem de vários relatórios |
| `frontend/src/pages/HistoricoPage.tsx` | 831 | três produtos analíticos em uma página |
| `app/services/transaction_reports.py` | 676 | vários relatórios e contratos ad hoc |
| `app/services/sync.py` | 665 | lock, lifecycle, upsert, reconciliação, snapshots e tolerância a falhas |

O maior método do backend, `spending_capacity_summary`, tinha aproximadamente 442 linhas e alta complexidade condicional. No frontend, `DashboardPage` e componentes internos de Planejamento também acumulam muitas decisões de negócio.

## Correções já implementadas

### Banco e integridade

- SQLite passa a habilitar `foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000` e `synchronous=NORMAL` em cada conexão da aplicação.
- Backups automáticos agora mantêm os 14 mais recentes e um histórico mensal, em vez de crescerem indefinidamente.
- A migração de idempotência de webhook limpa apenas o identificador das entregas históricas duplicadas, preserva as linhas e cria um índice único para novos `event_id`.
- A migração foi testada sobre um banco sintético já contendo duplicatas; o resultado preservou duas entregas, manteve um único identificador ativo e rejeitou uma terceira duplicata.

### Sincronização e Pluggy

- `transactions/deleted` agora tem efeito real: a janela retornada pela Pluggy é reconciliada, transações que desapareceram são removidas e vínculos de custo fixo são limpos antes, respeitando as chaves estrangeiras.
- O cliente Pluggy usa uma conexão HTTP reutilizável, retry de conexão, refresh de chave protegido contra corrida entre threads e um único paginador compartilhado.
- A paginação repetida de itens, faturas, investimentos e transações foi removida.
- Um usuário sem propriedade do item deixa de disparar backup antes de receber `404`.
- Erros internos e corpos de resposta da Pluggy deixam de ser devolvidos ao navegador.

### Contrato de planejamento e redução de trabalho

- `/planning/month/{year_month}` calculava renda, custos fixos, orçamento variável e fatura uma vez diretamente e outra dentro de `spending_capacity_summary`.
- O endpoint agora executa um único cálculo, reutiliza as seções produzidas e devolve `capacity` como contrato canônico.
- O envelope redundante `raw.spending_capacity` deixou de ser produzido. O frontend mantém apenas uma leitura de compatibilidade temporária.
- Foram removidos aliases sem consumidor (`receita_esperada`, `valor_recebido`, `receita_a_receber`, `planned_variable_total`, `discretionary_available`) e um campo que era sempre `null` (`projected_cash_available`).
- A validação e o deslocamento de `YYYY-MM` foram centralizados. A rota que aceitava `abcd-01` e podia gerar erro 500 agora retorna 400.

### Autenticação e segurança

- Novas sessões guardam somente SHA-256 do token no banco; o token reutilizável existe apenas no cookie. Sessões antigas continuam válidas durante a janela de compatibilidade.
- O corpo de login ganhou limites de tamanho e rejeição de campos extras.
- O Caddy passa a remover o cabeçalho do servidor e enviar HSTS, `nosniff`, proteção contra iframe, política de referência e política de permissões.
- Os logs dos dois containers passam a rotacionar em três arquivos de 10 MB.

### Frontend

- `useAsync` agora ignora respostas antigas, não atualiza estado depois do unmount e elimina a corrida em que uma requisição lenta sobrescrevia uma resposta nova.
- As páginas são carregadas sob demanda. O bundle-base ficou em aproximadamente 222 kB; Planejamento, Dashboard, Histórico e Próximos viraram chunks separados.
- Tipos que na prática eram apenas `string` por conterem `| string` foram fechados para os valores reais de status e fluxo de caixa.
- O Dashboard não esconde mais falhas de saldo/próximos compromissos e diferencia sincronização concluída, já em andamento e parcialmente falha.
- A verificação em navegador cobriu as quatro rotas e encontrou/corrigiu o texto “próximos 1 meses”. Não houve erro no console.

### CI e qualidade

- O CI deixou de executar a mesma suíte duas vezes (`unittest` e depois `pytest`).
- Passou a verificar dependências Python, auditoria npm, tipos, lint e build do frontend.
- O bloqueio existente de formatação foi resolvido em 19 arquivos.
- Resultado final local: Ruff, formatação, `pip check`, 510 testes, auditoria npm sem vulnerabilidades, typecheck, lint, build e `git diff --check` aprovados.

## Evidências da AWS atual

A inspeção foi somente leitura. A instância e os containers não foram reiniciados nem modificados.

- EC2 `t3.small`, cerca de 1,9 GiB de RAM; containers saudáveis e sem reinícios/OOM no período observado.
- Disco raiz com aproximadamente 55% de uso.
- Código remoto limpo e no mesmo commit de `main` que existia localmente antes deste branch.
- SQLite em produção ainda usa `journal_mode=delete` e `foreign_keys=0`; as correções acima só entram após publicação.
- Integridade do banco retornou OK e não havia violações de FK detectadas, mas a garantia não estava ativa.
- Foram encontrados 23 grupos de `event_id` duplicado em webhooks.
- Havia 68 backups, aproximadamente 117 MB, produzidos em seis dias e armazenados no mesmo volume físico do banco.
- Não há IAM Role associada à instância.
- O Caddy recebe o arquivo completo de ambiente, embora precise apenas de domínio e e-mail ACME.
- O ambiente ainda contém `OPENFINANCE_ADMIN_TOKEN`, configuração já removida do código.
- A chave SSH ativa está fora do repositório, no diretório SSH do usuário; não deve voltar para a árvore do projeto.
- A resposta pública não enviava os cabeçalhos defensivos adicionados neste branch.

## Problemas restantes e solução recomendada

### Prioridade 0 — antes ou junto da próxima publicação

1. **Jobs de webhook não são duráveis.** `BackgroundTasks` vive dentro do processo; um restart entre o 202 e a conclusão pode perder a sincronização.
   - Solução: tabela outbox com estados `pending/running/completed/failed`, worker separado e recuperação de jobs presos no startup. Para escala maior, SQS é a evolução natural.

2. **Backups continuam no mesmo disco do banco.** Retenção evita lotação, mas não protege contra perda da instância/volume.
   - Solução: snapshots EBS automatizados com DLM e cópia periódica criptografada para S3 com versionamento e lifecycle. Usar IAM Role, não credenciais permanentes na VM.

3. **Login não tem limite de tentativas.** Argon2 torna cada tentativa cara e o endpoint público pode ser usado para força bruta ou consumo de CPU.
   - Solução: limite por IP + identificador, janela progressiva, contador externo/durável e alerta. No desenho atual de uma instância, Redis ou uma tabela curta com expiração são suficientes.

4. **Segredos excessivos chegam ao Caddy.** Um comprometimento do proxy expõe credenciais Pluggy e webhook sem necessidade.
   - Solução: arquivo de ambiente exclusivo do Caddy contendo apenas `OPENFINANCE_DOMAIN` e `ACME_EMAIL`; remover o token administrativo morto; preferir SSM Parameter Store/Secrets Manager com IAM Role.

5. **A publicação precisa ser migration-aware.** A nova migração toca IDs duplicados e o WAL muda o comportamento do SQLite.
   - Solução: backup fora da instância, ensaio em cópia do banco, publicação, confirmação de `alembic current`, PRAGMAs, `/health`, logs e contagem de duplicatas.

### Prioridade 1 — arquitetura do backend

1. **Dividir serviços por caso de uso, não apenas por entidade.**
   - `fixed_costs.py`: `repository`, `matching`, `calendar`, `commands`, `queries` e schemas.
   - `credit_card_invoice.py`: `cycle`, `sources`, `reconciliation` e `presenter`.
   - `sync.py`: `lock`, `item_sync`, `account_sync`, `transaction_reconciliation` e `snapshot_orchestrator`.
   - `history.py`/`transaction_reports.py`: um query service por relatório.

2. **Substituir dicionários livres por modelos de resposta.** Há 91 rotas e somente três declarações de `response_model`; foram encontrados mais de cem usos de `Dict[str, Any]`/`dict[str, Any]` em rotas e serviços.
   - Solução: modelos Pydantic por boundary, dataclasses internas e geração dos tipos TypeScript a partir do OpenAPI.

3. **Dinheiro vira `float` na fronteira sem política explícita.** Isso funciona para exibição, mas facilita diferenças de centavos em somas/reconciliações.
   - Solução: `Decimal` internamente, quantização central em centavos e serialização por schema. Definir claramente se a API usa string decimal ou inteiro em centavos.

4. **Relógio global espalhado.** Há mais de 50 chamadas a `date.today()`/`datetime.utcnow()`, várias datetimes ingênuas e testes que precisam injetar datas manualmente.
   - Solução: serviço `Clock`, UTC timezone-aware para persistência e conversão explícita para `America/Sao_Paulo` nas regras mensais.

5. **Erros HTTP são repetidos em dezenas de handlers.**
   - Solução: exceções de domínio tipadas + handlers globais FastAPI; isso reduz código repetido e padroniza status/corpo/log.

6. **Delete remoto hoje apaga a linha.** A correção torna os totais corretos, mas perde histórico de classificação manual.
   - Solução de longo prazo: tombstone (`deleted_at`, `deleted_source`) e filtro central, com job posterior de retenção. Isso preserva auditoria sem contaminar relatórios.

7. **Autorização é apenas por usuário autenticado.** Endpoints de diagnóstico podem expor payloads financeiros amplos a qualquer usuário válido.
   - Solução: papéis mínimos (`owner`, `viewer`, `operator`) e restrição dos endpoints `/debug`/operação.

8. **Middleware e dependências resolvem a sessão mais de uma vez.**
   - Solução: middleware resolve uma vez, grava usuário seguro em `request.state` e a dependency apenas consome o valor; manter uma seam explícita para testes.

### Prioridade 1 — arquitetura do frontend

1. **Quebrar `PlanejamentoPage.tsx`.** Estrutura sugerida:
   - `features/planning/overview`
   - `features/planning/fixed-costs`
   - `features/planning/variable-budgets`
   - `features/planning/income`
   - hooks de query/mutation por feature; a página fica apenas com rota, mês e tabs.

2. **Quebrar `HistoricoPage.tsx` por produto analítico.** Faturas, categorias e fluxo de caixa devem ter containers e schemas próprios.

3. **Adicionar testes do frontend.** Hoje não há suíte React.
   - Solução: Vitest + Testing Library para hooks/normalizadores/componentes e Playwright para login, troca de rota, estados vazio/stale e fluxo de sincronização.

4. **Cancelar rede, além de ignorar respostas.** `useAsync` agora protege estado, mas a requisição antiga continua consumindo rede.
   - Solução: aceitar `AbortSignal` no cliente e migrar gradualmente para uma camada de query/cache.

5. **Remover os `any` restantes nas bordas Pluggy/cartão.**
   - Solução: schemas explícitos do SDK e das respostas; `unknown` + validação quando o payload vem de terceiro.

### Prioridade 2 — infraestrutura e operação

- Fixar imagens por versão/digest (`node`, `python`, `caddy`) e gerar lock das dependências Python.
- Adicionar limites/reservas de CPU e memória e política de observabilidade.
- Métricas e alertas para disco, memória, 5xx, falhas de sync, jobs presos e idade do último backup externo.
- Separar readiness de liveness; `/health` hoje confirma processo, não necessariamente banco/migração/Pluggy.
- Avaliar PostgreSQL quando houver múltiplos workers, volume maior ou necessidade real de concorrência. No formato atual de uma única VM, SQLite + WAL continua viável.
- Remover Tailwind carregado em runtime e scripts inline da landing para permitir CSP forte e eliminar dependência de CDN em tempo de execução.

## Como diminuir o tamanho sem piorar o projeto

O caminho seguro não é criar abstrações genéricas para tudo: a duplicação literal é baixa. As maiores reduções úteis são:

1. Gerar tipos TypeScript a partir dos schemas OpenAPI e apagar normalizadores/aliases de compatibilidade após uma janela de migração.
2. Usar um handler de exceções de domínio e remover os muitos blocos `try/except -> HTTPException` repetidos.
3. Extrair um executor paginado/HTTP único — já realizado no cliente Pluggy.
4. Remover contratos duplicados e cálculos repetidos — já realizado em Planejamento.
5. Criar componentes de formulário somente onde a estrutura e a regra são realmente iguais; não unificar telas diferentes apenas para reduzir linhas.
6. Depois da migração do frontend, remover `raw` e fallbacks antigos definitivamente.

Esta primeira fase reduziu os hotspots de Planejamento, cliente Pluggy e capacidade mensal, mas o patch total cresce porque adiciona garantias, migração e testes. “Menos linhas” não deve vencer integridade financeira ou legibilidade.

## Sequência recomendada

1. Revisar este branch e publicar a primeira fase com o checklist de migração.
2. Implementar outbox/worker e backup externo com IAM Role.
3. Separar segredos do Caddy e adicionar rate limit.
4. Criar schemas de API e gerar tipos do frontend.
5. Modularizar Planejamento, Histórico e os três maiores serviços de backend, uma feature por PR.
6. Adicionar a suíte React/E2E e só então remover os contratos de compatibilidade restantes.

Referências AWS: [IAM Roles for Amazon EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html), [Amazon Data Lifecycle Manager para snapshots EBS](https://docs.aws.amazon.com/ebs/latest/userguide/snapshot-lifecycle-dlm.html), [S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html).
