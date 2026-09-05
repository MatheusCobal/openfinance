# OpenFinance — relatório da reformulação do frontend

Data: 5 de setembro de 2026. Alterações deixadas no diretório de trabalho, sem commit.

O redesign foi implementado nas quatro áreas principais, na navegação, nos componentes compartilhados, no login, na página de rota não encontrada e na apresentação pública. A identidade combina organização de SaaS com destaques financeiros em azul petróleo. A implementação usa os dados e contratos existentes.

## Inspeção inicial

### Arquitetura encontrada

- React 18, TypeScript 5.6, React Router 6 e Vite 5.
- Tailwind CSS 3, CSS global e componentes próprios; não há biblioteca adicional de componentes de interface.
- Lucide React para ícones; Chart.js 4 para gráficos; Inter como fonte existente.
- `frontend/src/pages` concentra as telas; `components/layout` organiza a estrutura global; `components/ui` contém os componentes reutilizáveis; `components/charts` contém o gráfico compartilhado.
- As camadas `api`, `auth`, `types` e os adaptadores em `lib` separam comunicação, sessão, contratos e normalização.
- O build React é servido pelo FastAPI em `app/static/react`. A página pública usa HTML, CSS e JavaScript próprios em `app/static/landing.*`.
- Os scripts disponíveis são `dev`, `typecheck`, `lint`, `build` e `preview`. Não há comando de testes de frontend nem suíte E2E configurada.

### Mapa das telas e dos recursos

| Tela/rota | Finalidade e informações | Ações e componentes preservados | Direção aplicada |
| --- | --- | --- | --- |
| Dashboard — `/dashboard` | Situação financeira, disponibilidade, faturas, custos, categorias e transações recentes | Atualização e conexão bancária existentes, acesso ao planejamento, categorias detalhadas e carregamento de mais transações; resumo financeiro, listas, tabela e modal | Disponibilidade como foco inicial; obrigações próximas ao resumo; exploração e transações abaixo |
| Planejamento — `/planejamento` | Plano do mês, custos fixos, gastos variáveis e receita | Quatro abas, seleção de mês, receitas, custos recorrentes, ajustes mensais, categorias, vínculos de pagamentos, metas e respectivas ações existentes; formulários, menus, listas e indicadores | Período comum acima das abas; previsto, realizado e pendente próximos; separação entre agenda do mês e cadastro recorrente |
| Histórico — `/historico` | Faturas do cartão, gastos por categoria, entradas e saídas | Três abas, seleção de mês, gráficos, cartões, transações e edição de classificação; tabelas e modais | Comparação dos meses e detalhes selecionados no mesmo contexto; categorias em linhas comparáveis |
| Próximos — `/proximos` | Fatura em aberto e parcelamentos futuros | Atualização, seleção de mês, gráfico, detalhamento por cartão/categoria e expansão das parcelas | Resumo do compromisso atual e futuro, seguido de evolução e detalhamento |
| Login — `/login` | Entrada na conta | Mesmos campos, envio, validação, mensagens e fluxo de sessão | Marca e formulário em duas colunas no desktop, leitura sequencial no celular |
| Rota não encontrada — fallback React | Recuperação de navegação | Retorno ao Dashboard | Mensagem e ação consistentes com o restante do aplicativo |
| Página pública — `/` | Apresentação do OpenFinance | Links e chamadas para abrir o aplicativo | Cores, hierarquia e apresentação coerentes com a área interna |

Não havia uma área independente de transações, faturas ou cartões: esses recursos estão nas telas acima. Não havia um componente de drawer que precisasse ser migrado; os detalhes continuam usando modais, expansão de conteúdo e formulários existentes. O fallback React foi preservado; a resposta do servidor para URLs arbitrárias não foi alterada.

### Problemas e oportunidades identificados

Havia muitos blocos com peso visual semelhante, pouco destaque para a informação principal e diferenças de espaçamento entre páginas. Planejamento concentrava ações e dados densos sem separar claramente o mês selecionado do cadastro recorrente. Histórico repetia o detalhamento do mês selecionado e dispersava comparação e exploração. Formulários e ações secundárias precisavam de melhor localização e legibilidade.

Cards, tabelas, resumos e gráficos tinham padrões que podiam ser aproximados sem trocar a arquitetura. Também havia oportunidades de melhorar foco por teclado, retorno de foco dos modais, leitura dos gráficos sem mouse, feedback de salvamento e estados vazios.

A inspeção e a proposta foram apresentadas antes da implementação. O trabalho seguiu as camadas de fundação visual, componentes compartilhados, páginas e revisão de interação/responsividade.

## Design system implementado

| Elemento | Padrão |
| --- | --- |
| Identidade principal | Azul petróleo: `#123e4b` para a navegação e os destaques; `#176073` e `#18778a` para ações e orientação |
| Superfícies | Branco para conteúdo, `#f3f7f8` para o fundo e `#eaf0f2` para áreas rebaixadas |
| Significado financeiro | Esmeralda para receitas/positivo, rosa ou coral para despesas/erros, âmbar para atenção/pendências, azul claro para informação |
| Categorias | Cores próprias dos dados preservadas, inclusive quando diferentes da identidade principal |
| Tipografia | Inter existente; títulos, rótulos e valores com hierarquia consistente; números tabulares nas informações financeiras |
| Espaçamento | Escala do Tailwind existente, containers e intervalos padronizados; resumos mais destacados e detalhes mais compactos |
| Forma | Raio de 18 px nos cards e 10 px nos controles; bordas leves e sombras discretas |
| Navegação | Sidebar em petróleo no desktop, identificação da página e contexto no cabeçalho, navegação inferior em telas menores |
| Interação | Estados de hover, foco, disabled, carregamento e salvamento; transições curtas com respeito a movimento reduzido |
| Gráficos | Paleta compartilhada, tooltip monetário, seleção de período e tabela acessível com os mesmos valores |

Botões, campos, selects, abas, faixa de meses, badges, cards, métricas, tabelas, modais, estados e notificações foram ajustados em componentes reutilizáveis. Não foram adicionadas dependências nem um novo sistema de temas. O aplicativo continua com tema claro.

O acesso por teclado recebeu link para pular ao conteúdo, foco visível, navegação nas abas e meses por setas/Home/End, contenção e restauração de foco nos modais e acesso aos valores dos gráficos. Ícones e textos complementam as cores. Tabelas densas mantêm rolagem horizontal interna quando necessário.

## O que mudou em cada página

### Dashboard

A disponibilidade financeira ocupa o destaque principal, acompanhada das obrigações existentes. Categorias e transações formam uma sequência de exploração mais clara. A busca local por descrição/categoria nas transações carregadas facilita encontrar um lançamento; a ação de carregar mais continua disponível. Os acessos ao planejamento, à atualização e aos detalhes foram preservados.

### Planejamento

A seleção do mês fica antes das quatro abas. A visão geral reúne os valores já fornecidos de receita prevista, recebida e restante, custos realizados e pendentes, fatura e sobra. A agenda mensal e a base de custos recorrentes têm hierarquia própria. As ações de adicionar ficaram mais visíveis; os formulários abertos recebem foco e rolagem adequada. Menus e linhas foram ajustados para telas estreitas. Durante a troca de mês, os dados do mês anterior não ficam apresentados como se pertencessem ao novo período.

O intervalo de planejamento existente, que começa no mês seguinte, foi mantido. As regras de metas e disponibilidade também foram mantidas, incluindo as alterações que já estavam no diretório antes desta tarefa.

### Histórico

As três abas continuam disponíveis. O gráfico de faturas e os cartões do mês selecionado ficam lado a lado no desktop. A grade de meses seleciona esse mesmo detalhamento, eliminando a repetição visual. Categorias usam linhas comparáveis e mini gráficos acionáveis pelo teclado. Entradas e saídas têm ações explícitas para abrir as transações correspondentes.

Os detalhes contam com busca. A edição de classificação apresenta carregamento das opções, erro com nova tentativa e bloqueio durante o salvamento. Após salvar, a consulta é atualizada e o detalhe anterior é fechado para evitar exibir informação desatualizada. O payload e a regra de classificação permanecem os mesmos.

### Próximos

A fatura em aberto e o total das parcelas futuras aparecem primeiro. O gráfico e a faixa de meses usam os mesmos valores do backend. Cartões e categorias ficam próximos do mês selecionado; as categorias continuam expansíveis para mostrar compras e parcelas. Em telas estreitas, rótulos sobre as barras são omitidos quando não há espaço suficiente; tooltip e tabela mantêm os valores exatos acessíveis.

### Login, página pública e rota não encontrada

Receberam a mesma identidade, tipografia e linguagem dos controles. No login, a alteração é de apresentação: handlers e fluxo de autenticação não mudaram. A página pública mantém suas chamadas existentes e passa a apresentar também a área de próximos compromissos. A página de erro mantém o retorno ao Dashboard.

## Funcionalidades e limites de escopo preservados

- As rotas e as quatro áreas principais permanecem; Planejamento mantém quatro abas e Histórico mantém três.
- As ações existentes de consulta, atualização, seleção de mês, edição, cadastro, exclusão, configuração, vínculo, classificação, metas e exploração continuam no código e nos respectivos pontos de entrada, respeitando suas condições anteriores de disponibilidade.
- A comparação das chamadas nas páginas Dashboard e Planejamento confirmou os mesmos nomes e argumentos: 6 chamadas no Dashboard e 26 no Planejamento.
- Antes da preparação da entrega, a conferência por hash de 76 arquivos protegidos não encontrou alterações funcionais do redesign. Na preparação para `main`, nove arquivos Python foram normalizados pelo formatador obrigatório do CI; a revisão do diff confirmou que as diferenças adicionais são somente de formatação.
- Nenhum contrato de API, regra de cálculo, classificação, sincronização bancária, integração Pluggy, modelo de banco ou migration foi alterado por este redesign.
- Nenhuma nova dependência foi instalada. Não foram criados indicadores financeiros, datas de vencimento/fechamento ou comparações sem suporte nos dados existentes.
- As alterações manuais de validação ocorreram somente em uma cópia descartável. Dados históricos reais foram usados para exercitar a interface; nenhuma fonte de dados fictícios foi adicionada ao aplicativo.

Essas confirmações combinam revisão de código, comparação com o estado inicial, testes automatizados e os fluxos manuais descritos abaixo. Não significam execução manual de todas as combinações possíveis de operações financeiras.

## Validações executadas

| Verificação | Resultado |
| --- | --- |
| `npm run typecheck`, em `frontend` | Passou |
| `npm run lint`, em `frontend` | Passou, sem erros reportados |
| `npm run build`, em `frontend` | Passou; build de produção atualizado |
| `npm audit --omit=dev --audit-level=high`, em `frontend` | Passou no limite do CI; duas vulnerabilidades moderadas conhecidas no React Router foram registradas nos riscos |
| `.venv/bin/python -m pytest -q`, com `DATABASE_URL` apontando para banco temporário isolado | **543 testes passaram** na execução de liberação, em 15,54 s |
| `.venv/bin/ruff check .` | Passou |
| `.venv/bin/ruff format --check .` | Passou após normalizar nove arquivos que estavam fora do formato exigido pelo CI |
| `.venv/bin/python -m compileall app tests`, com cache temporário | Passou |
| `.venv/bin/alembic upgrade head`, com banco temporário isolado | Passou por todas as migrations até o head |
| `git diff --check` | Passou |
| Revisão do diff e comparação dos arquivos protegidos | Sem alterações funcionais adicionais nas áreas protegidas pelo redesign; formatação de liberação registrada abaixo |

A execução inicial da suíte também tinha 543 testes aprovados. Após a reorganização visual, duas verificações de código-fonte em `test_invoice_history.py` falharam por depender de texto/layout antigos e do detalhe de cartão duplicado. Foram atualizadas para verificar o novo detalhamento selecionado e os controles correspondentes. As asserções financeiras não foram removidas. A suíte completa passou novamente.

Não havia testes de frontend nem E2E configurados para executar; não foi acrescentada uma nova infraestrutura de testes nesta tarefa.

### Validação manual

Foi utilizado o build de produção servido pelo FastAPI, no fluxo existente do projeto. Foram revisadas as quatro páginas principais e também login, página pública e fallback React.

As larguras verificadas foram **1440 px, 1280 px, 768 px e 390 px**, cobrindo desktop, notebook, tablet e tela reduzida. Não foi observado transbordamento horizontal da página nas telas verificadas; faixas de meses e tabelas podem rolar dentro de seus containers.

Foram exercitados navegação principal e secundária, troca de mês, seleção por teclado, busca de transações, carregamento de mais resultados, seleção de categorias, gráficos e respectivas tabelas, expansão de parcelas, abertura e cancelamento de formulários, edição de custo recorrente e salvamento da classificação de uma transação. Também foram conferidos o acesso aos candidatos para vincular pagamento, a contenção/retorno de foco e o fechamento dos modais por Escape.

O salvamento de custo e de classificação foi feito mantendo os valores selecionados, exclusivamente na cópia de teste. Não foi efetivado um novo vínculo financeiro. Foram revisados os estados vazios das quatro áreas. Com autenticação habilitada em um servidor temporário, foram verificados o redirecionamento de rota protegida e a mensagem de credenciais inválidas. Login válido, sessão, logout e integração bancária contam com cobertura da suíte automatizada; não foi realizada conexão bancária real durante a revisão.

### Origem da prévia

O banco local configurado estava vazio. Para revisar telas preenchidas, foi criada uma base temporária isolada com registros reais de um backup local existente. Como o backup tinha esquema antigo, seus campos compatíveis foram importados para uma cópia descartável com o esquema atual; os valores financeiros de origem foram preservados. Essa base é somente uma amostra histórica para revisão, sem garantia de atualização bancária.

A prévia local foi usada durante a revisão e não faz parte da publicação. O build de produção é gerado pelo primeiro estágio do `Dockerfile` e servido pelo FastAPI, conforme o fluxo documentado no README.

## Arquivos alterados por esta tarefa

### Identidade e estrutura global

```text
frontend/tailwind.config.js
frontend/src/styles/globals.css
frontend/src/components/layout/AppShell.tsx
frontend/src/components/layout/MobileNav.tsx
frontend/src/components/layout/PageContainer.tsx
frontend/src/components/layout/Sidebar.tsx
frontend/src/components/layout/Topbar.tsx
```

### Componentes compartilhados

```text
frontend/src/components/charts/BarChart.tsx
frontend/src/lib/chartTheme.ts
frontend/src/components/ui/Badge.tsx
frontend/src/components/ui/Button.tsx
frontend/src/components/ui/Card.tsx
frontend/src/components/ui/CategoryBreakdown.tsx
frontend/src/components/ui/ChartCard.tsx
frontend/src/components/ui/EmptyState.tsx
frontend/src/components/ui/ErrorState.tsx
frontend/src/components/ui/FormField.tsx
frontend/src/components/ui/Input.tsx
frontend/src/components/ui/LoadingState.tsx
frontend/src/components/ui/MetricCard.tsx
frontend/src/components/ui/Modal.tsx
frontend/src/components/ui/MonthStrip.tsx
frontend/src/components/ui/SectionHeader.tsx
frontend/src/components/ui/Select.tsx
frontend/src/components/ui/Table.tsx
frontend/src/components/ui/Tabs.tsx
frontend/src/hooks/useToast.tsx
```

### Páginas, testes e documentação

```text
frontend/src/pages/DashboardPage.tsx
frontend/src/pages/PlanejamentoPage.tsx
frontend/src/pages/HistoricoPage.tsx
frontend/src/pages/ProximosPage.tsx
frontend/src/pages/LoginPage.tsx
frontend/src/pages/NotFoundPage.tsx
app/static/landing.css
app/static/landing.html
tests/test_invoice_history.py
docs/frontend-redesign.md
README.md
.gitignore
.dockerignore
```

Os arquivos gerados pelo build em `app/static/react` continuam ignorados pelo Git.

Na preparação para `main`, o formatador exigido pelo pipeline também normalizou
`app/services/credit_card_invoice.py`, `app/services/history.py`,
`app/services/spending_capacity.py`, `app/services/sync.py`,
`tests/test_credit_card_invoice_payment_status.py`,
`tests/test_current_card_invoice.py`, `tests/test_pluggy_snapshot.py`,
`tests/test_sync_service.py` e `tests/test_variable_budgets.py`. As diferenças
adicionais nesses arquivos são somente de formatação; as mudanças funcionais em
`spending_capacity.py` e `test_variable_budgets.py` já existiam no diretório.

### Alterações que já existiam

O diretório já tinha alterações em `app/services/spending_capacity.py`, `frontend/src/components/ui/FinancialFlow.tsx`, `frontend/src/lib/planning.ts` e `tests/test_variable_budgets.py`. Esses quatro arquivos não foram modificados por esta tarefa. Dashboard e Planejamento também já estavam alterados; o redesign foi aplicado preservando os ajustes financeiros existentes. Os arquivos locais não rastreados do SQLite e o diretório `tmp` também já existiam e não foram removidos.

## Riscos e pendências reais

1. **Categorias elegíveis para metas:** antes do redesign, `normalizePlanningOverview` já retornava `eligible_categories: []`. Isso continua limitando a criação de uma meta pela interface. O problema está registrado em [`frontend/src/lib/planning.ts`](../frontend/src/lib/planning.ts#L73). A disponibilidade dessa funcionalidade não foi alterada; corrigir a origem das categorias merece uma tarefa própria, com validação das regras existentes.
2. **Cobertura manual das metas:** o estado vazio foi revisado, mas criação, replicação e exclusão de metas preenchidas não foram exercitadas manualmente devido à limitação acima. Seus controles/handlers foram preservados e a suíte de regras de orçamento continua passando.
3. **Validação externa:** não houve login manual com uma conta real nem nova conexão/sincronização Pluggy. Os testes automatizados dessas áreas passaram, e seu código não foi alterado.
4. **Alcance da revisão visual:** a revisão foi feita no navegador disponível nesta sessão e nas dimensões indicadas. Não equivale a uma auditoria completa com leitores de tela, dispositivos físicos e todos os navegadores.
5. **Dependência React Router:** a auditoria npm reporta duas vulnerabilidades moderadas na versão instalada. Uma envolve URLs com barras invertidas e a outra hidratação SSR, recurso que esta aplicação cliente não usa. Não há vulnerabilidades altas ou críticas no limite usado pelo CI; a atualização deve ser feita separadamente com teste de todas as rotas.

Não restaram falhas conhecidas nos comandos de qualidade executados. A prévia histórica não representa necessariamente a posição financeira atual.

## Sugestões futuras, não implementadas

- Corrigir a alimentação das categorias elegíveis para metas a partir da fonte existente, sem redefinir as regras de elegibilidade.
- Avaliar filtros personalizados e comparação entre anos quando houver consulta e dados adequados; isso amplia a funcionalidade analítica existente.
- Apresentar fechamento e vencimento dos cartões somente quando esses campos forem fornecidos de forma confiável pelo contrato existente ou por uma extensão própria do backend.
- Acrescentar uma suíte E2E com cenários de edição, metas, vínculos e sessão, além de testes visuais em outros navegadores.

Nenhuma dessas sugestões foi incorporada ao escopo desta execução.
