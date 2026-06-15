# Handoff: Cockpit Financeiro — Redesign (Custos Fixos + Dashboard)

## Visão Geral

Este pacote documenta o redesign de duas áreas do app **OpenFinance Cockpit**:

1. **Aba "Custos Fixos"** dentro de `PlanejamentoPage` — reimaginada em 4 direções (Concept A, B, C, D). O usuário deve escolher uma direção para implementar.
2. **DashboardPage** — reorganização da hierarquia visual, mesmos blocos de dados, layout mais limpo.

O app usa **React + TypeScript + Vite + Tailwind CSS** com tokens customizados ("Quiet Cockpit"). A stack já está definida — não mudar frameworks.

---

## Sobre os Arquivos de Design

Os arquivos `.jsx` e `cockpit.html` nesta pasta são **protótipos de referência criados em HTML puro**. Eles mostram intenção visual e de interação, mas **não são para copiar diretamente ao codebase**. A tarefa é recriar esses designs no app existente, usando:

- Os componentes TypeScript já existentes (`Card`, `Button`, `StatusPill`, `Badge`, etc.)
- Os tokens Tailwind já configurados em `tailwind.config.js`
- Os hooks e APIs já existentes (`usePlanejamento`, `useDashboard`, etc.)
- O sistema de roteamento e shell já em vigor

---

## Fidelidade

**Alta fidelidade (hifi).** Os protótipos têm cores, tipografia, espaçamento e interações finais. O desenvolvedor deve recriar pixel-a-pixel usando as libs e padrões existentes do codebase.

---

## Tokens de Design (já existentes no `tailwind.config.js`)

```
Cores:
  primary-600  → #2563eb  (ação principal, links)
  ink-900      → #0f172a  (texto principal)
  ink-500      → #64748b  (texto secundário)
  ink-200      → #e2e8f0  (bordas)
  positive-500 → #10b981  (sucesso/pago)
  warning-500  → #f59e0b  (atenção/em breve)
  danger-500   → #f43f5e  (erro/vencido)
  surface      → #ffffff  (fundo de card)
  surface-muted→ #f6f7f9  (fundo de página)
  cockpit      → #0b1220  (hero escuro)

Border radius:
  rounded-card    → 1rem     (cards principais)
  rounded-control → 0.625rem (botões, chips, badges)

Sombras:
  shadow-card    → sutil (cards em repouso)
  shadow-lift    → elevado (hover de card)
  shadow-cockpit → profundo (hero escuro)

Fonte: Inter (400/500/600/700/800)
```

### Paleta de categorias (definida em `src/lib/categories.ts`)
```
Moradia     → #7c3aed
Saúde       → #dc2626
Assinaturas → #0891b2
Transporte  → #2563eb
Educação    → #ca8a04
Outros      → #64748b
```

---

## 1. PlanejamentoPage — Aba "Custos Fixos"

### Arquivo de origem
`src/pages/PlanejamentoPage.tsx` — aba `tab === "custos-fixos"` (ou similar).

### Problema atual
A aba exibe uma lista longa e plana de custos fixos sem hierarquia, sem visibilidade de status de pagamento, sem visualização do impacto na receita.

### Direção escolhida: **Concept A — "Agenda do Mês"** *(recomendada)*
*(Se o usuário preferir outra, os specs das outras estão abaixo.)*

---

### Concept A — Agenda do Mês

#### Layout geral
```
┌─────────────────────────────────────────────────────┐
│  HERO ESCURO (cockpit-surface)                      │
│  ┌──────────────────────────┐  ┌─────────────────┐  │
│  │ Total + barra pago/a     │  │ Mini-calendário │  │
│  │ pagar + texto de contexto│  │ do mês          │  │
│  └──────────────────────────┘  └─────────────────┘  │
├─────────────────────────────────────────────────────┤
│  TIMELINE (fundo branco, borda ink-200/70)          │
│  [divisor "Hoje · 13 jun"]                          │
│  ┌─────────────────────────────────────────────────┐│
│  │ DayBadge │ Avatar │ Nome + vínculo │ Valor │ ✓  ││
│  │ ...                                             ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

#### Hero escuro (`cockpit-surface`)
- Background: `background: radial-gradient(1200px 380px at 85% -40%, rgba(37,99,235,0.22), transparent 60%), radial-gradient(800px 300px at -10% 120%, rgba(16,185,129,0.10), transparent 55%), linear-gradient(140deg, #0b1220 0%, #101a2e 55%, #0b1220 100%)`
- Grid overlay sutil: `background-image: linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px); background-size: 28px 28px`
- Padding: `p-6`, border-radius: `rounded-card`, sombra: `shadow-cockpit`
- Layout interno: `grid grid-cols-[minmax(0,1fr)_300px] gap-8`

**Coluna esquerda (texto + barra de progresso):**
- Ícone de calendário: `size-8 rounded-control bg-white/10 ring-1 ring-inset ring-white/15`
- Label: `text-sm font-medium text-white/70` — "Custos fixos · Junho 2026"
- Valor total: `text-5xl font-bold tabular text-white` — `money(total)`
- Subtexto: `text-sm text-white/55` com porcentagem da receita
- Barra pago/a-pagar:
  - Track: `h-2.5 rounded-full bg-white/10`
  - Fill pago: `bg-[rgba(52,211,153,0.95)]` — transição `width 0.9s cubic-bezier(0.22,1,0.36,1)`
- Legenda: `text-[11px] text-white/45`

**Mini-calendário (coluna direita):**
- Container: `rounded-card border border-white/10 bg-white/[0.04] backdrop-blur-sm p-4`
- Grid 7 colunas com cabeçalho de dias (D S T Q Q S S)
- Cada célula: `aspect-square rounded-md text-[11px] tabular`
  - Hoje: `bg-primary-500 font-bold text-white`
  - Com vencimento: `bg-white/[0.06] text-white/80` + dot colorido `absolute bottom-1 size-1 rounded-full`
  - Dot colors: `overdue → #fb7185`, `due_soon → #fbbf24`, `paid → #34d399`, `scheduled → #94a3b8`
  - Sem vencimento: `text-white/30`

#### Timeline de pagamentos

Container: `rounded-card border border-ink-200/70 bg-surface p-2 shadow-card`

**Divisor "Hoje":**
```tsx
<li className="flex items-center gap-3 px-3 py-2">
  <span className="rounded-full bg-primary-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
    Hoje · {today} {monthShort}
  </span>
  <span className="h-px flex-1 bg-primary-200" />
</li>
```
Mostrar entre o último item com `dueDay < today` e o primeiro com `dueDay >= today`.

**Cada linha de custo:**
```tsx
<li className="group flex items-center gap-3 rounded-control px-3 py-2.5 transition-colors hover:bg-surface-muted">
  <DayBadge day={c.dueDay} tone={...} />   // componente existente ou novo
  <CatAvatar cost={c} size={38} />          // icon colorido da categoria
  <div className="min-w-0 flex-1">
    <div className="flex items-center gap-2">
      <p className="text-sm font-semibold ...">{c.name}</p>
      <span className="text-xs font-medium" style={{ color: catColor(c.cat) }}>{c.cat}</span>
    </div>
    <p className="text-xs text-ink-500">  // vínculo open-finance ou "sem pagamento vinculado"
  </div>
  <p className="text-sm font-bold tabular">{money(c.amount)}</p>
  <StatusPill status={effStatus(c)} />     // componente existente
  <CheckToggle paid={paid} onToggle={toggle} />  // botão circular
</li>
```

**`DayBadge` (novo componente se não existir):**
```tsx
// size ~38x38, rounded-control
// bg: paid→bg-positive-100 text-positive-700
//     overdue→bg-danger-100 text-danger-700
//     due_soon→bg-warning-100 text-warning-800
//     default→bg-surface-muted text-ink-700
// Mostra: número grande (text-sm font-bold tabular) + "dia" (text-[9px] uppercase opacity-60)
```

**`CatAvatar` (novo componente):**
```tsx
// Container inline-flex size={38} rounded={12}
// background: catColor(cat) + "1A"  (10% opacity)
// color: catColor(cat)
// Ícone lucide correspondente à categoria, ~45% do tamanho
```

**`CheckToggle` (toggle de "pago"):**
```tsx
// Círculo size-7, border-2
// não pago: border-ink-300, text-transparent, hover: border-positive-400
// pago:     border-positive-500 bg-positive-500 text-white
// Check icon strokeWidth={3}
// Transição: duration-200 ease
```

**Estado live:**
- `const [paidIds, setPaidIds] = useState<Set<string>>(() => new Set(costsWithPaidStatus))`
- Toggle local: otimista — reflete imediatamente, chama API em background
- Total e barra de progresso recalculados a partir de `paidIds`

---

### Concept B — Compromissos (Grade de Cards)

#### Layout geral
```
Header + botão "Novo custo"
↓
3 summary cards (Total | Já pago | A pagar)
↓
Filter chips por categoria
↓
Grid 3 colunas de cards de custo
```

**Summary cards:** `grid grid-cols-3 gap-4`
- Cada card: `rounded-card border border-ink-200/70 bg-surface p-4 shadow-card`
- Ícone: `size-9 rounded-control` com bg/text por tom
- Valor: `text-2xl font-bold tabular`

**Filter chips:**
```tsx
// rounded-full border px-3 py-1.5 text-xs font-medium
// ativo: border-ink-900 bg-ink-900 text-white
// inativo: border-ink-200 bg-surface text-ink-600 hover:border-ink-300
// dot colorido para cada categoria (fica branco quando ativo)
```

**Card de custo individual:**
```tsx
// rounded-card border border-ink-200/70 bg-surface p-4 shadow-card
// hover: -translate-y-0.5 shadow-lift (transition-all duration-200)
// Estrutura:
//   CatAvatar size=44 + StatusPill (topo)
//   Nome (text-sm font-semibold) + Categoria colorida
//   Valor (text-2xl font-bold tabular)
//   "vence dia X" (text-xs text-ink-500 + ícone calendar)
//   Botão "Marcar pago" / "Pago" (rounded-control border)
//     pago: border-positive-200 bg-positive-50 text-positive-700
//     não pago: border-ink-200 hover:border-positive-300 hover:bg-positive-50/40
```

---

### Concept C — Cascata da Receita

#### Layout geral
```
Header + valor "Sobra após fixos"
↓
Gráfico de cascata (receita → categorias → sobra)
↓
Grid 2 colunas de cards por categoria com barra de progresso pago
```

**Gráfico de cascata:**
- Container: `rounded-card border border-ink-200/70 bg-surface p-6 shadow-card`
- Altura do chart: 250px
- Cada barra é `absolute`, posicionada por `bottom` e `height` em pixels calculados por escala
- `bottom = after * scale`, `height = value * scale`
- Cor: receita → `#0ea5e9`, sobra → `#10b981`, categorias → cor da categoria
- Grid horizontal: linhas tracejadas a 25/50/75/100% com valores em `text-[10px] text-ink-300`
- Animação: `width 0 → valor final` em `0.9s cubic-bezier(0.22,1,0.36,1)` com `delay` por índice
- Labels abaixo: `text-[11px] font-medium` com dot colorido

**Cards de categoria:**
```tsx
// grid grid-cols-2 gap-4
// Cada card: nome + count + total + barra de progresso pago + legenda "X% dos fixos · Y pago · Z a pagar"
// Barra: cor da categoria, animada no mount
```

---

### Concept D — Painel de Comando

#### Layout geral
```
Header + StatusPill "X% da receita"
↓
grid grid-cols-[360px_minmax(0,1fr)] gap-5
  ┌────────────────────┐  ┌──────────────────────────┐
  │ Donut + legenda    │  │ Progresso do mês         │
  │ por categoria      │  │ (barra + 3 mini-KPIs)    │
  │                    │  ├──────────────────────────┤
  │                    │  │ Próximos vencimentos     │
  │                    │  │ (4 itens com DayBadge)   │
  └────────────────────┘  └──────────────────────────┘
```

**Donut animado:**
- SVG puro, `rotate(-90deg)`, `strokeLinecap="round"`
- Track: `circle` com `stroke="rgba(15,23,42,0.06)"`
- Cada segmento: `strokeDasharray="${len} ${circumference}"` com transição `stroke-dashoffset 1.1s cubic-bezier(0.22,1,0.36,1)` e `transitionDelay` por índice
- Centro: texto "Total fixo" + valor + contagem
- Tamanho recomendado: 210px × 210px, `thickness=24`

**Progresso do mês:**
- Barra `h-10px rounded-full bg-positive-500` animada no mount
- 3 mini-KPIs: `rounded-control bg-surface-muted p-3` com label + valor colorido

**Próximos vencimentos:**
- Lista dos `status !== 'paid'` ordenados por `dueDay`, limitada a 4 itens
- Mesmo padrão de linha: `DayBadge + CatAvatar + nome/cat + StatusPill + valor`

---

## 2. DashboardPage — Reorganização

### Arquivo de origem
`src/pages/DashboardPage.tsx`

### Mudanças de hierarquia

A ordem dos blocos muda para:

```
1. HERO ESCURO — "Disponível para gastar" (foco principal)
2. KPI ROW (4 cards) — Entradas | Fixos | Variável usado | Saldo em conta
3. SEÇÃO DUPLA — Pressão do mês (barras) | Leituras rápidas (insights)
4. SEÇÃO DUPLA — Fatura vigente (detalhes) | Categorias (mini-cards 2×3)
```

### Hero escuro — "Disponível para gastar"

Layout `grid grid-cols-[minmax(0,1fr)_340px] gap-10` dentro do `cockpit-surface`:

**Coluna esquerda:**
- Badge "Disponível para gastar" + `StatusPill tone="positive" inverse` → "Saudável"
- Valor disponível: `text-5xl font-bold tabular text-white`
  - Calculado: `receita - fixos - fatura - metaVariavel`
- Subtexto: `text-sm text-white/55`
- Footer: dias restantes + "R$/dia" + link "Ajustar plano"

**Coluna direita — Composição do mês:**
- Container: `rounded-card border border-white/10 bg-white/[0.04] backdrop-blur-sm p-5`
- Título: "Composição do mês" em `text-[11px] uppercase tracking-[0.14em] text-white/50`
- `FlowBar` (componente existente `FinancialFlow` ou adaptação):
  - Segmentos: Custos fixos `#64748b` | Fatura vigente `#38bdf8` | Meta variável `#a78bfa`
  - Sobra: `#34d399` (ou vermelho se negativa)
  - Total (denominador): receita esperada
- Rodapé: "Receita esperada de R$X em jun"

### KPI Row

`grid grid-cols-4 gap-4` — 4 `MetricCard` com:

| Label | Valor | Sub | Tom | Ícone |
|---|---|---|---|---|
| Entradas recebidas | recebido | "Crédito que já caiu" | positive | banknote |
| Custos fixos | total fixos | "Reservados ou pagos" | neutral | wallet |
| Variável usado | usado | "Meta X · restam Y" | neutral | target |
| Saldo em conta | saldo | "N contas ativas" | primary | banknote |

### Pressão do mês

`rounded-card border bg-surface p-5 shadow-card`

3 barras de pressão:
```
Fatura no mês     →  (fatura / receita) × 100
Custos fixos      →  (fixos / receita) × 100
Meta variável     →  (variávelUsado / metaVariável) × 100
```

Cor da barra por valor:
- `> 95%` → `#e11d48` (danger)
- `> 70%` → `#f59e0b` (warning)
- `≤ 70%` → `#10b981` (positive)

### Insights / Leituras rápidas

Grid de 4 `InsightCard` (componente existente) com ícone + título + corpo.

### Fatura + Categorias

`grid grid-cols-[320px_minmax(0,1fr)] gap-4`

**Fatura vigente (esquerda):**
- `rounded-card border bg-surface p-5`
- Valor grande + ícone `creditCard`
- Box com próxima fatura (julho)

**Categorias (direita):**
- `grid grid-cols-2 gap-3`
- 6 mini-cards (Alimentação, Mercado, Transporte, Compras, Lazer, Outros)
- Cada card: dot colorido + nome + contagem + valor + barra horizontal proporcional ao maior

---

## Interações & Animações

### Barras de progresso
```css
/* Animação de entrada das barras */
transition: width 0.9s cubic-bezier(0.22, 1, 0.36, 1);
/* No mount: width inicia em 0, vai para o valor real */
/* Usar useMemo + estado booleano "mounted" para triggerar */
```

### Cards com hover
```css
transition: transform 0.15s, box-shadow 0.15s;
hover: -translate-y-0.5 shadow-lift
```

### CheckToggle (toggle de pago)
```css
transition: all 0.2s ease;
/* Estado não pago → pago: border muda de ink-300 para positive-500,
   bg aparece (positive-500), cor do check fica white */
```

### Donut SVG
```css
/* Cada arco: stroke-dasharray animado */
/* stroke-dashoffset: valor inicial = circunferência total (invisível) → 0 (visível) */
transition: stroke-dashoffset 1.1s cubic-bezier(0.22, 1, 0.36, 1);
/* transitionDelay: index * 90ms */
```

### Entrada de seções
```css
/* Cada seção: opacity 0 + translateY(10px) → opacity 1 + translateY(0) */
/* Com staggered delay: 0ms, 60ms, 100ms, 140ms */
@media (prefers-reduced-motion: no-preference) {
  animation: rise 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
```

---

## Estado Necessário

### PlanejamentoPage (Custos Fixos)

```typescript
// Novo estado para toggles de pagamento local
const [localPaid, setLocalPaid] = useState<Set<string>>(() => {
  // inicializar com os custos que já têm status "paid" vindos da API
  return new Set(fixedCosts.filter(c => c.status === 'paid').map(c => c.id));
});

// Toggle otimista
const togglePaid = (id: string) => {
  setLocalPaid(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
  // TODO: chamar API para persistir
};

// Status efetivo (sobrepõe o status da API com o toggle local)
const effectiveStatus = (cost: FixedCost): PlanStatusTone => {
  if (localPaid.has(cost.id)) return 'paid';
  if (cost.status === 'paid') return 'scheduled'; // foi desmarcado
  return cost.status;
};

// Totais derivados
const paidTotal = fixedCosts
  .filter(c => localPaid.has(c.id))
  .reduce((sum, c) => sum + c.amount, 0);
```

### DashboardPage

Sem mudanças de estado — apenas reorganização dos blocos JSX existentes.

---

## Novos Componentes Necessários

| Componente | Onde criar | Descrição |
|---|---|---|
| `DayBadge` | `src/components/ui/DayBadge.tsx` | Quadradinho com número do dia e tônica semântica |
| `CatAvatar` | `src/components/ui/CatAvatar.tsx` | Ícone da categoria com fundo tintado |
| `CheckToggle` | `src/components/ui/CheckToggle.tsx` | Círculo toggle de "pago" com animação |
| `Donut` | `src/components/ui/Donut.tsx` | Donut SVG animado com segmentos |

Os outros componentes já existem: `Card`, `Button`, `StatusPill`, `Badge`, `MetricCard`, `InsightCard`, `FinancialFlow` (usar como base para `FlowBar`).

---

## Assets

- Todos os ícones vêm de `lucide-react` (já instalado)
- Fontes: Inter via Google Fonts (já configurado)
- Sem imagens externas

---

## Arquivos de Design Nesta Pasta

| Arquivo | Conteúdo |
|---|---|
| `cockpit.html` | Protótipo interativo completo — abrir no browser para navegar |
| `data.jsx` | Mock data (estrutura real dos dados: `FIXED_COSTS`, `INCOME`, etc.) |
| `primitives.jsx` | Ícones inline + componentes primitivos (`Bar`, `Donut`, `FlowBar`, `DayBadge`, `CatAvatar`) |
| `custos-a-b.jsx` | Implementação dos Concepts A (Agenda) e B (Grade) |
| `custos-c-d.jsx` | Implementação dos Concepts C (Cascata) e D (Painel) |
| `dashboard.jsx` | Dashboard reorganizado |

> **Abrir `cockpit.html`** no Chrome/Safari para ver e interagir com todos os conceitos lado a lado. Use scroll/zoom no canvas e clique em ⤢ para abrir qualquer quadro em tela cheia.

---

## Prompt Sugerido para o Claude Code

Cole este prompt no Claude Code com o projeto aberto:

```
Tenho um redesign de duas áreas do app para implementar. Leia o README em
`design_handoff_cockpit_redesign/README.md` — ele documenta tudo em detalhe.

Resumo das mudanças:

1. `src/pages/PlanejamentoPage.tsx` — aba "Custos Fixos":
   Implementar o **Concept A (Agenda do Mês)** conforme descrito no README.
   Principais mudanças:
   - Hero escuro (cockpit-surface) com total, barra pago/a-pagar e mini-calendário mensal
   - Timeline ordenada por dueDay com divisor "Hoje"
   - Toggle de "pago" por item com estado local otimista
   - Novos componentes: DayBadge, CatAvatar, CheckToggle

2. `src/pages/DashboardPage.tsx` — reorganização:
   Reordenar os blocos existentes na nova hierarquia e ajustar o hero para
   mostrar "Disponível para gastar" como métrica principal com FlowBar.

Para referência visual, abra `design_handoff_cockpit_redesign/cockpit.html`
no browser. O código dos protótipos está em `custos-a-b.jsx` (Concept A)
e `dashboard.jsx`.

Não mudar: stack (React/TS/Vite/Tailwind), tokens existentes, APIs, roteamento.
Manter: todos os outros tabs de Planejamento intactos.
```
