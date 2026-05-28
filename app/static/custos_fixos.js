'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const MONTH_WINDOW = 6;
const MAX_CUSTOM_CATEGORIES = 5;
const TRANSACTION_SUGGESTIONS_INITIAL = 5;
const TRANSACTION_SUGGESTIONS_MAX = 50;
const MONTH_LABELS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

// ── Description matching helpers (mirrors backend _token_set / normalize_description) ──

function normalizeDescJs(text) {
  if (!text) return '';
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function tokenSetJs(value) {
  const stopwords = new Set(['de', 'da', 'do', 'das', 'dos', 'e', 'em', 'com', 'pagamento', 'compra', 'pix', 'qr', 'code']);
  return new Set(
    normalizeDescJs(value).split(/\s+/).filter((t) => t.length >= 3 && !stopwords.has(t))
  );
}

const TEMPLATE_EMOJIS = {
  'Aluguel': '🏠', 'Condomínio': '🏢', 'Internet': '🌐',
  'Energia': '⚡', 'Água': '💧', 'Escola': '📚',
  'Plano de saúde': '🏥', 'Streaming': '📺', 'Seguro': '🛡️', 'Pet': '🐾',
  'Academia': '🏋️',
};

let selectedMonth = null;
let monthStrip = [];
let categories = [];
let fixedCosts = [];
let incomeSelectedMonth = null;
let incomeMonthStrip = [];
let expandedOverviewPanel = null;

const STATUS_CFG = {
  paid:        { label: 'Pago',           icon: '✓', bg: 'bg-emerald-100', text: 'text-emerald-700' },
  due_soon:    { label: 'Vence em breve', icon: '⏰', bg: 'bg-amber-100',   text: 'text-amber-700'   },
  overdue:     { label: 'Vencido',        icon: '⚠', bg: 'bg-red-100',     text: 'text-red-700'     },
  scheduled:   { label: 'Previsto',       icon: '·',  bg: 'bg-slate-100',  text: 'text-slate-500'   },
  unconfirmed: { label: 'Não confirmado', icon: '?',  bg: 'bg-slate-100',  text: 'text-slate-500'   },
};

// ── Utilities ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function showToast(message, variant = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className =
    'fixed top-4 right-4 z-50 max-w-sm rounded-xl text-white text-sm px-4 py-3 shadow-lg ' +
    (variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-800');
  toast.classList.remove('hidden');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add('hidden'), 3500);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json())?.detail || ''; } catch {}
    throw new Error(detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function selectedPlanningTabFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  if (['custos', 'variaveis', 'receita', 'transacao'].includes(tab)) return tab;
  return 'overview';
}

function setPlanningTab(tabName, updateUrl = true) {
  const allowedTabs = ['overview', 'custos', 'variaveis', 'receita', 'transacao'];
  const activeTab = allowedTabs.includes(tabName) ? tabName : 'overview';
  const panels = {
    overview: 'overview-tab',
    custos: 'fixed-costs-tab',
    variaveis: 'variable-goals-tab',
    receita: 'income-planning-tab',
    transacao: 'transaction-cost-tab',
  };
  Object.entries(panels).forEach(([tab, panelId]) => {
    document.getElementById(panelId)?.classList.toggle('hidden', activeTab !== tab);
  });
  document.querySelectorAll('#planning-tabs [data-tab]').forEach((button) => {
    const active = button.dataset.tab === activeTab;
    button.className =
      'text-sm font-medium px-3 py-2 rounded-lg transition-colors ' +
      (active ? 'bg-indigo-600 text-white shadow-sm' : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-100 hover:text-slate-900');
  });
  const subtitles = {
    overview: 'Veja os principais números do planejamento mensal.',
    custos: 'Cadastre e edite compromissos recorrentes.',
    variaveis: 'Defina metas para gastos variáveis do mês.',
    receita: 'Cadastre o que você espera receber em cada mês.',
    transacao: 'Crie um novo custo recorrente a partir de uma transação.',
  };
  document.getElementById('subtitle').textContent = subtitles[activeTab];
  if (updateUrl) {
    const url = new URL(window.location.href);
    if (activeTab === 'overview') url.searchParams.delete('tab');
    else url.searchParams.set('tab', activeTab);
    window.history.replaceState({}, '', url);
  }
}

function currentYearMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function shiftYearMonth(ym, offset) {
  const [year, month] = ym.split('-').map(Number);
  const zeroBased = year * 12 + (month - 1) + offset;
  return `${String(Math.floor(zeroBased / 12)).padStart(4, '0')}-${String((zeroBased % 12) + 1).padStart(2, '0')}`;
}

function formatMonthShort(ym) {
  const [year, month] = ym.split('-').map(Number);
  return `${MONTH_LABELS[month - 1]}/${String(year).slice(2)}`;
}

function formatDate(iso) {
  const [year, month, day] = String(iso).split('-');
  if (!year || !month || !day) return iso;
  return `${day}/${month}`;
}

// ── Month strip ────────────────────────────────────────────────────────────

function renderMonthStrip() {
  const strip = document.getElementById('month-strip');
  strip.innerHTML = '';
  for (const ym of monthStrip) {
    const button = document.createElement('button');
    const active = ym === selectedMonth;
    button.type = 'button';
    button.className =
      'shrink-0 text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ' +
      (active ? 'bg-indigo-600 text-white shadow-sm' : 'bg-slate-100 text-slate-700 hover:bg-slate-200');
    button.textContent = formatMonthShort(ym);
    button.addEventListener('click', () => {
      if (ym === selectedMonth) return;
      selectedMonth = ym;
      renderMonthStrip();
      loadMonthData();
    });
    strip.appendChild(button);
  }
}

// ── Capacity flow ──────────────────────────────────────────────────────────

function renderCapacityFlow(capacity) {
  const container = document.getElementById('capacity-summary');

  // ── Values ──
  const planningMode  = capacity.planning_mode || (capacity.is_future_month ? 'future_month' : 'current_month');
  const isFuture      = planningMode === 'future_month';
  const sobra         = capacity.budget_available_to_spend ?? capacity.discretionary_available ?? capacity.available_to_spend ?? 0;
  const sobraPositive = sobra >= 0;
  const income        = capacity.expected_income_total     || 0;
  const received      = capacity.received_income_total     || 0;
  const toReceive     = capacity.income_to_receive         || 0;
  const fixedReserved = capacity.fixed_cost_reserved_total || 0;
  const fixedPlanned  = capacity.fixed_cost_planned_total  || 0;
  const varConsumed   = capacity.variable_budget_consumed  || 0;
  const varOverage    = capacity.variable_budget_overage   || 0;
  const unbudgeted    = capacity.unbudgeted_variable_spent        || 0;
  const reserve       = isFuture
    ? (capacity.reserve_target_total       || 0)
    : (capacity.reserve_reserved_total     || 0);
  const ccRemaining         = capacity.card_invoice_remaining_to_reserve || 0;
  const futureCardObligation= capacity.future_card_obligation_total      || 0;
  const varBudgetTotal= capacity.variable_budget_total            || 0;
  const varReserved   = capacity.variable_budget_reserved         || 0;
  const daily         = capacity.daily_discretionary_remaining    || 0;
  const daysRemaining = capacity.days_remaining_in_month         || 0;

  // ── Plan status badge ──
  const PLAN_STATUS_CFG = {
    healthy: { label: 'Saudável',   cls: 'bg-emerald-100 text-emerald-700' },
    tight:   { label: 'Apertado',   cls: 'bg-amber-100   text-amber-700'   },
    over:    { label: 'Estourado',  cls: 'bg-rose-100    text-rose-700'    },
    unknown: { label: 'Sem receita',cls: 'bg-slate-100   text-slate-600'   },
  };
  const planStatus = PLAN_STATUS_CFG[capacity.plan_status] || PLAN_STATUS_CFG.unknown;

  // ── Progress bar ──
  // unbudgeted is NOT part of the formula — informational only, shown separately.
  // For future months: fixedPlanned, varBudgetTotal, futureCardObligation, reserveTarget.
  // For current/past: fixedReserved, consumed+overage, ccRemaining, reserveReserved.
  const fixedBarAmt  = isFuture ? fixedPlanned  : fixedReserved;
  const cardBarAmt   = isFuture ? futureCardObligation : ccRemaining;
  const fixedPct     = income > 0 ? Math.min(100, (fixedBarAmt   / income) * 100) : 0;
  const varConsPct   = income > 0 ? Math.min(100, (varConsumed   / income) * 100) : 0;
  const varOverPct   = income > 0 ? Math.min(100, (varOverage    / income) * 100) : 0;
  const varResPct    = income > 0 ? Math.min(100, (varReserved   / income) * 100) : 0;
  const reservePct   = income > 0 ? Math.min(100, (reserve       / income) * 100) : 0;
  const ccRemPct     = income > 0 ? Math.min(100, (cardBarAmt    / income) * 100) : 0;
  const freePct      = Math.max(0, 100 - fixedPct - varResPct - reservePct - ccRemPct);
  const varTotalPct  = isFuture ? varResPct : varConsPct + varOverPct;

  // ── Credit card context ──
  const ccOfficial  = capacity.card_invoice_official_total ?? capacity.card_invoice_gross_total ?? 0;
  const ccGross     = capacity.card_invoice_gross_total    || 0;
  const ccSource    = capacity.card_invoice_source;
  const ccSourceLabel =
    ccSource === 'bill'            ? 'Fatura oficial (Pluggy)' :
    ccSource === 'account_balance' ? 'Saldo da conta cartão'   :
                                     'Reconstruída por transações';
  const ccSourceCls =
    ccSource === 'bill'            ? 'bg-emerald-100 text-emerald-700' :
    ccSource === 'account_balance' ? 'bg-indigo-100  text-indigo-700'  :
                                     'bg-slate-100   text-slate-600';
  const dueDates = capacity.credit_card_due_dates || [];

  // ── Pre-build accordion panel content (avoids nested template-literal issues) ──
  const rReceita  = expandedOverviewPanel === 'receita'  ? buildOverviewPanelContent('receita',  capacity, sobra, sobraPositive) : '';
  const rCustos   = expandedOverviewPanel === 'custos'   ? buildOverviewPanelContent('custos',   capacity, sobra, sobraPositive) : '';
  const rVariavel = expandedOverviewPanel === 'variavel' ? buildOverviewPanelContent('variavel', capacity, sobra, sobraPositive) : '';
  const rReserva  = expandedOverviewPanel === 'reserva'  ? buildOverviewPanelContent('reserva',  capacity, sobra, sobraPositive) : '';

  // ── Calculation breakdown rows ──
  const bRows = [
    { label: 'Receita esperada', value: income, op: '', cls: 'text-slate-700' },
    isFuture
      ? { label: 'Custos fixos planejados',   value: fixedPlanned,   op: '−', cls: 'text-slate-500' }
      : { label: 'Custos fixos reservados',   value: fixedReserved,  op: '−', cls: 'text-slate-500' },
    isFuture
      ? { label: 'Orçamentos variáveis',      value: varBudgetTotal, op: '−', cls: 'text-slate-500' }
      : { label: 'Variável consumido',        value: varConsumed,    op: '−', cls: 'text-slate-500' },
  ];
  if (!isFuture && varOverage > 0) bRows.push({ label: 'Estouro variável', value: varOverage, op: '−', cls: 'text-red-500' });
  if (isFuture && futureCardObligation > 0) bRows.push({ label: 'Parcelas/fatura prevista', value: futureCardObligation, op: '−', cls: 'text-amber-600' });
  bRows.push({
    label: isFuture ? 'Reserva planejada' : 'Reserva planejada / aplicada',
    value: reserve,
    op: '−',
    cls: 'text-slate-500',
  });
  if (!isFuture && ccRemaining > 0) bRows.push({ label: 'Fatura ainda não contemplada', value: ccRemaining, op: '−', cls: 'text-amber-600' });
  bRows.push({ label: 'Disponível para gastar', value: sobra, op: '=', cls: sobraPositive ? 'text-emerald-700 font-bold' : 'text-red-600 font-bold' });

  const breakdownHtml = bRows.map((r, i) => `
    <div class="flex items-baseline gap-2 ${i === bRows.length - 1 ? 'border-t border-slate-200 pt-2 mt-0.5' : ''}">
      <span class="w-4 text-center text-xs text-slate-400 shrink-0">${r.op}</span>
      <span class="flex-1 text-xs text-slate-600">${r.label}</span>
      <span class="text-xs tabular ${r.cls}">${currency.format(r.value)}</span>
    </div>
  `).join('');

  // ── Daily verba line ──
  const dailyHtml = (daysRemaining > 0 && daily > 0) ? `
    <div class="text-right shrink-0">
      <p class="text-[11px] text-slate-500 mb-0.5">${currency.format(daily)}/dia disponível</p>
      <p class="text-[11px] text-slate-400">${daysRemaining} dia${daysRemaining === 1 ? '' : 's'} restante${daysRemaining === 1 ? '' : 's'}</p>
    </div>` : '';

  // ── Credit card card HTML ──
  let ccHtml = '';
  if (isFuture) {
    // Future month: show the official bill (prior billing cycle) reserved as a separate line.
    // Never show Account.balance here.
    if (futureCardObligation > 0) {
      ccHtml = `
    <div class="rounded-xl border border-amber-200 bg-amber-50/40 px-4 py-3 mb-4">
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Fatura prevista</p>
        <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700">Fatura oficial (Pluggy)</span>
      </div>
      <p class="text-lg font-bold tabular text-slate-800 mb-1">${currency.format(futureCardObligation)}</p>
      ${dueDates.length > 0 ? `<p class="text-[11px] text-slate-500 mb-1">Vencimento: ${dueDates.map((d) => escapeHtml(String(d))).join(' · ')}</p>` : ''}
      <p class="text-[11px] text-slate-400 leading-snug border-t border-amber-100 pt-2 mt-2">
        Fatura do ciclo anterior com vencimento neste mês. Já reservada na projeção acima como "Parcelas/fatura prevista".
        As compras planejadas para este mês constam nos orçamentos variáveis — sem dupla contagem.
      </p>
    </div>`;
    }
  } else if (ccOfficial > 0 || ccSource) {
    ccHtml = `
    <div class="rounded-xl border border-amber-200 bg-amber-50/40 px-4 py-3 mb-4">
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Fatura do cartão</p>
        <span class="text-[10px] px-1.5 py-0.5 rounded-full ${ccSourceCls}">${escapeHtml(ccSourceLabel)}</span>
      </div>
      <p class="text-lg font-bold tabular text-slate-800 mb-1">${currency.format(ccOfficial)}</p>
      ${dueDates.length > 0 ? `<p class="text-[11px] text-slate-500 mb-1">Vencimento: ${dueDates.map((d) => escapeHtml(String(d))).join(' · ')}</p>` : ''}
      <div class="space-y-1 mt-2 mb-2">
        <div class="flex items-baseline gap-2">
          <span class="flex-1 text-[11px] text-slate-500">Total já contemplado no planejamento</span>
          <span class="text-[11px] tabular text-slate-600">${currency.format(ccGross)}</span>
        </div>
        <div class="flex items-baseline gap-2">
          <span class="flex-1 text-[11px] ${ccRemaining > 0 ? 'text-amber-700 font-medium' : 'text-slate-500'}">Obrigação adicional (ainda não contemplada)</span>
          <span class="text-[11px] tabular ${ccRemaining > 0 ? 'text-amber-700 font-semibold' : 'text-slate-500'}">${currency.format(ccRemaining)}</span>
        </div>
      </div>
      <p class="text-[11px] text-slate-400 leading-snug border-t border-amber-100 pt-2">
        As compras individuais já constam nos orçamentos variáveis e custos fixos acima — a fatura inteira não é subtraída para evitar dupla contagem.
        ${ccRemaining > 0 ? 'O valor adicional acima representa a diferença entre a fatura oficial e as transações individuais registradas (carry-over, juros, cobranças não sincronizadas).' : 'A fatura está totalmente contemplada nas transações individuais registradas.'}
      </p>
    </div>`;
  }

  container.innerHTML = `
    <!-- ── Hero: Disponível para gastar ── -->
    <div class="rounded-xl border ${sobraPositive ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'} px-5 py-4 mb-4 flex flex-wrap items-start gap-4">
      <div class="flex-1 min-w-[160px]">
        <div class="flex items-center gap-2 mb-1">
          <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">${isFuture ? 'Projeção: livre para gastar' : 'Disponível para gastar'}</p>
          <span class="text-[10px] font-medium px-2 py-0.5 rounded-full ${planStatus.cls}">${planStatus.label}</span>
          ${isFuture ? '<span class="text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">Plano projetado</span>' : ''}
        </div>
        <p class="text-3xl font-bold tabular ${sobraPositive ? 'text-emerald-700' : 'text-red-600'}">${currency.format(sobra)}</p>
        ${isFuture ? '<p class="text-[11px] text-slate-400 mt-1">Projeção antes do mês começar — baseada em metas planejadas.</p>' : ''}
      </div>
      ${dailyHtml}
    </div>

    <!-- ── Progress bar ── -->
    ${income > 0 ? `
      <div class="flex h-1.5 w-full rounded-full overflow-hidden bg-slate-100 mb-2">
        <div class="h-full bg-slate-400"  style="width:${fixedPct.toFixed(1)}%"   title="Custos fixos reservados"></div>
        ${isFuture
          ? `<div class="h-full bg-amber-400" style="width:${varResPct.toFixed(1)}%" title="Variável planejado (meta)"></div>`
          : `<div class="h-full bg-amber-400"  style="width:${varConsPct.toFixed(1)}%" title="Variável consumido"></div><div class="h-full bg-orange-400" style="width:${varOverPct.toFixed(1)}%" title="Estouro variável"></div>`
        }
        <div class="h-full bg-indigo-300" style="width:${reservePct.toFixed(1)}%" title="Reserva planejada"></div>
        ${ccRemPct > 0 ? `<div class="h-full bg-yellow-500" style="width:${ccRemPct.toFixed(1)}%" title="Fatura ainda não contemplada"></div>` : ''}
        <div class="h-full ${sobraPositive ? 'bg-emerald-300' : 'bg-red-300'}" style="width:${freePct.toFixed(1)}%" title="Livre"></div>
      </div>
      <div class="flex flex-wrap gap-x-4 gap-y-0.5 mb-4">
        <span class="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <span class="size-2 rounded-full bg-slate-400 shrink-0"></span>Fixos ${fixedPct.toFixed(0)}%
        </span>
        <span class="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <span class="size-2 rounded-full bg-amber-400 shrink-0"></span>Variável ${varTotalPct.toFixed(0)}%
        </span>
        ${reservePct > 0 ? `<span class="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <span class="size-2 rounded-full bg-indigo-300 shrink-0"></span>Reserva ${reservePct.toFixed(0)}%
        </span>` : ''}
        ${ccRemPct > 0 ? `<span class="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <span class="size-2 rounded-full bg-yellow-500 shrink-0"></span>Fatura não contemplada ${ccRemPct.toFixed(0)}%
        </span>` : ''}
        <span class="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <span class="size-2 rounded-full ${sobraPositive ? 'bg-emerald-300' : 'bg-red-300'} shrink-0"></span>Livre ${freePct.toFixed(0)}%
        </span>
      </div>
    ` : ''}

    <!-- ── Accordion ── -->
    <div class="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden mb-4" id="ov-accordion">

      <!-- Receita row: shows received / expected / to-receive -->
      <div>
        <button type="button" data-panel="receita"
          class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors">
          <span class="text-sm leading-none shrink-0">💰</span>
          <span class="flex-1 text-sm font-medium text-slate-700">Receita</span>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 mr-2 text-[11px]">
            <span class="text-slate-500">esperada <span class="text-slate-700 font-semibold tabular">${currency.format(income)}</span></span>
            ${received > 0 ? `<span class="text-emerald-600">recebido <span class="font-semibold tabular">${currency.format(received)}</span></span>` : ''}
            ${toReceive > 0 ? `<span class="text-amber-600">a receber <span class="font-semibold tabular">${currency.format(toReceive)}</span></span>` : ''}
          </div>
          <span class="text-slate-300 text-xs shrink-0 transition-transform ${expandedOverviewPanel === 'receita' ? 'rotate-180' : ''}" style="display:inline-block">▼</span>
        </button>
        <div class="${expandedOverviewPanel === 'receita' ? '' : 'hidden'} px-4 pb-4 pt-1 bg-slate-50 border-t border-slate-100">
          ${rReceita}
        </div>
      </div>

      <!-- Custos fixos row -->
      <div>
        <button type="button" data-panel="custos"
          class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors">
          <span class="text-sm leading-none shrink-0">🏠</span>
          <span class="flex-1 text-sm font-medium text-slate-700">Custos fixos reservados</span>
          <span class="text-sm font-semibold tabular text-slate-600 shrink-0">${currency.format(fixedReserved)}</span>
          <span class="text-slate-300 text-xs ml-1 shrink-0 transition-transform ${expandedOverviewPanel === 'custos' ? 'rotate-180' : ''}" style="display:inline-block">▼</span>
        </button>
        <div class="${expandedOverviewPanel === 'custos' ? '' : 'hidden'} px-4 pb-4 pt-1 bg-slate-50 border-t border-slate-100">
          ${rCustos}
        </div>
      </div>

      <!-- Variável row: shows consumed / overage / unbudgeted separately -->
      <div>
        <button type="button" data-panel="variavel"
          class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors">
          <span class="text-sm leading-none shrink-0">🎯</span>
          <span class="flex-1 text-sm font-medium text-slate-700">Gastos variáveis</span>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 mr-2 text-[11px]">
            ${isFuture
              ? `<span class="text-slate-500">planejado <span class="text-slate-700 font-semibold tabular">${currency.format(varBudgetTotal)}</span></span>
                 ${varConsumed > 0 ? `<span class="text-slate-400">comprometido <span class="font-semibold tabular">${currency.format(varConsumed)}</span></span>` : ''}`
              : `<span class="text-slate-500">consumido <span class="text-slate-700 font-semibold tabular">${currency.format(varConsumed)}</span></span>
                 ${varOverage > 0 ? `<span class="text-red-500">estouro <span class="font-semibold tabular">${currency.format(varOverage)}</span></span>` : ''}`
            }
            ${unbudgeted > 0 ? `<span class="text-amber-500">para revisar <span class="font-semibold tabular">${currency.format(unbudgeted)}</span></span>` : ''}
          </div>
          <span class="text-slate-300 text-xs shrink-0 transition-transform ${expandedOverviewPanel === 'variavel' ? 'rotate-180' : ''}" style="display:inline-block">▼</span>
        </button>
        <div class="${expandedOverviewPanel === 'variavel' ? '' : 'hidden'} px-4 pb-4 pt-1 bg-slate-50 border-t border-slate-100">
          ${rVariavel}
          ${expandedOverviewPanel === 'variavel' ? `
            <p class="text-[11px] text-slate-400 pt-2 mt-2 border-t border-slate-100 leading-snug">
              As compras individuais do cartão já consomem estas metas. Transações conciliadas como custo fixo são excluídas dos gastos variáveis para evitar dupla contagem.
            </p>` : ''}
        </div>
      </div>

      <!-- Reserva row -->
      <div>
        <button type="button" data-panel="reserva"
          class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors">
          <span class="text-sm leading-none shrink-0">🐷</span>
          <span class="flex-1 text-sm font-medium text-slate-700">Reserva planejada</span>
          <span class="text-sm font-semibold tabular text-slate-600 shrink-0">${currency.format(reserve)}</span>
          <span class="text-slate-300 text-xs ml-1 shrink-0 transition-transform ${expandedOverviewPanel === 'reserva' ? 'rotate-180' : ''}" style="display:inline-block">▼</span>
        </button>
        <div class="${expandedOverviewPanel === 'reserva' ? '' : 'hidden'} px-4 pb-4 pt-1 bg-slate-50 border-t border-slate-100">
          ${rReserva}
        </div>
      </div>

    </div>

    <!-- ── Credit card context card ── -->
    ${ccHtml}

    <!-- ── Calculation breakdown ── -->
    <div class="rounded-xl border border-slate-200 bg-white px-4 py-3 mb-4">
      <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Como calculamos "disponível para gastar"</p>
      <div class="space-y-1">${breakdownHtml}</div>
    </div>

    <!-- ── Unbudgeted audit card ── -->
    ${unbudgeted > 0 ? `
    <div class="rounded-xl border border-amber-200 bg-amber-50/40 px-4 py-3 mb-4">
      <div class="flex flex-wrap items-center gap-2 mb-1">
        <p class="text-[11px] font-semibold text-amber-700 uppercase tracking-wider">Fora do planejamento · para revisar</p>
      </div>
      <p class="text-lg font-bold tabular text-amber-800">${currency.format(unbudgeted)}</p>
      <p class="text-[11px] text-amber-700 leading-snug mt-1">
        Gastos em categorias sem orçamento definido. Este valor <strong>não reduz o "Disponível para gastar"</strong> —
        defina um orçamento para essas categorias para incluí-las no planejamento.
      </p>
    </div>` : ''}

    <!-- ── Audit note ── -->
    <p class="text-[11px] text-slate-400 leading-relaxed pt-2 border-t border-slate-100">
      Apenas contas ativas são consideradas nestes cálculos. Contas desativadas (ex: CAIXA, C6) estão excluídas.
      Transações conciliadas como custo fixo são excluídas dos gastos variáveis para evitar dupla contagem.
    </p>
  `;

  // Wire accordion click handlers
  container.querySelectorAll('[data-panel]').forEach((btn) => {
    btn.addEventListener('click', () => {
      expandedOverviewPanel = expandedOverviewPanel === btn.dataset.panel ? null : btn.dataset.panel;
      renderCapacityFlow(capacity);
    });
  });
}

function buildOverviewPanelContent(key, capacity, sobra, sobraPositive) {
  if (key === 'receita') {
    const entries = capacity.expected_income?.entries || [];
    if (!entries.length) return '<p class="text-xs text-slate-400 py-2">Nenhuma entrada cadastrada.</p>';
    return `
      <ul class="divide-y divide-slate-200">
        ${entries.map((e) => `
          <li class="flex items-center gap-3 py-2">
            <span class="inline-flex items-center justify-center size-7 rounded-lg bg-white border border-slate-200 text-xs font-bold tabular text-slate-600 shrink-0">${e.expected_day}</span>
            <span class="flex-1 min-w-0 text-sm text-slate-700 truncate">${escapeHtml(e.description)}</span>
            ${e.is_override ? '<span class="text-[10px] text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded-full shrink-0">ajustado</span>' : ''}
            <span class="text-sm font-semibold tabular text-emerald-700 shrink-0">${currency.format(e.amount)}</span>
          </li>
        `).join('')}
      </ul>
    `;
  }

  if (key === 'custos') {
    const entries = capacity.fixed_costs?.entries || [];
    if (!entries.length) return '<p class="text-xs text-slate-400 py-2">Nenhum custo fixo ativo.</p>';
    const groups = new Map();
    for (const e of entries) {
      if (!groups.has(e.category_name)) groups.set(e.category_name, { color: e.category_color, items: [], total: 0 });
      const g = groups.get(e.category_name);
      g.items.push(e);
      g.total += Number(e.amount || 0);
    }
    return [...groups.entries()].map(([catName, g]) => `
      <div class="mb-3 last:mb-0">
        <div class="flex items-center gap-2 mb-1">
          <span class="size-2 rounded-full shrink-0" style="background:${escapeHtml(g.color)}"></span>
          <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex-1">${escapeHtml(catName)}</span>
          <span class="text-xs font-semibold tabular text-slate-600">${currency.format(g.total)}</span>
        </div>
        <ul class="divide-y divide-slate-200 pl-4">
          ${g.items.map((e) => `
            <li class="flex items-center gap-3 py-1.5">
              <span class="inline-flex items-center justify-center size-6 rounded-md bg-white border border-slate-200 text-[11px] font-bold tabular text-slate-500 shrink-0">${e.due_day}</span>
              <span class="flex-1 text-sm text-slate-700 truncate">${escapeHtml(e.description)}</span>
              ${e.is_override ? '<span class="text-[10px] text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded-full shrink-0">ajustado</span>' : ''}
              <span class="text-sm font-semibold tabular text-slate-700 shrink-0">${currency.format(e.amount)}</span>
            </li>
          `).join('')}
        </ul>
      </div>
    `).join('');
  }

  if (key === 'variavel') {
    const allItems = capacity.variable_budgets?.items || [];
    const budgeted = allItems.filter((i) => i.target !== null && i.target > 0);
    const unbudgeted = allItems.filter(
      (i) => (i.target === null || i.target <= 0) && (i.actual_spent + i.future_spent) > 0
    );
    const unbudgetedTotal = unbudgeted.reduce((s, i) => s + i.actual_spent + i.future_spent, 0);
    const unbudgetedCount = unbudgeted.reduce((s, i) => s + (i.actual_count || 0) + (i.future_count || 0), 0);

    if (!budgeted.length && !unbudgeted.length) {
      return '<p class="text-xs text-slate-400 py-2">Nenhuma meta definida e nenhum gasto variável no mês.</p>';
    }

    const budgetedHtml = budgeted.length > 0 ? `
      <ul class="space-y-3 pt-1">
        ${budgeted.map((item) => {
          const pct = Math.min(100, item.actual_progress_pct || 0);
          const bar = pct >= 100 ? 'bg-red-400' : pct >= 80 ? 'bg-amber-400' : 'bg-emerald-400';
          return `
            <li>
              <div class="flex items-center gap-2 mb-1">
                <span class="size-2 rounded-full shrink-0" style="background:${escapeHtml(item.category_color)}"></span>
                <span class="flex-1 text-sm text-slate-700 truncate">${escapeHtml(item.category_name)}</span>
                <span class="text-xs tabular text-slate-500">${currency.format(item.actual_spent)}</span>
                <span class="text-xs text-slate-300 mx-0.5">/</span>
                <span class="text-xs font-semibold tabular text-slate-700">${currency.format(item.target)}</span>
              </div>
              <div class="h-1.5 w-full bg-slate-200 rounded-full overflow-hidden">
                <div class="h-full rounded-full ${bar}" style="width:${pct.toFixed(1)}%"></div>
              </div>
            </li>
          `;
        }).join('')}
      </ul>
    ` : '';

    const unbudgetedHtml = unbudgeted.length > 0 ? `
      <div class="${budgeted.length > 0 ? 'mt-3 pt-2 border-t border-slate-200' : 'pt-1'}">
        <div class="flex items-center justify-between mb-1.5">
          <p class="text-[11px] font-semibold text-amber-600 uppercase tracking-wider">
            Sem orçamento definido
            ${unbudgetedCount > 0 ? `<span class="font-normal text-amber-500 normal-case">(${unbudgetedCount} transação${unbudgetedCount === 1 ? '' : 'ões'})</span>` : ''}
          </p>
          <span class="text-xs font-bold tabular text-amber-700">${currency.format(unbudgetedTotal)}</span>
        </div>
        <ul class="space-y-1">
          ${unbudgeted.map((item) => {
            const spent = item.actual_spent + item.future_spent;
            const count = (item.actual_count || 0) + (item.future_count || 0);
            return `
              <li class="flex items-center gap-2 py-0.5">
                <span class="size-2 rounded-full shrink-0" style="background:${escapeHtml(item.category_color)}"></span>
                <span class="flex-1 text-xs text-slate-700 truncate">${escapeHtml(item.category_name)}</span>
                <span class="text-[10px] text-slate-400 shrink-0">${count} tx</span>
                <span class="text-xs font-semibold tabular text-amber-600 shrink-0">${currency.format(spent)}</span>
              </li>
            `;
          }).join('')}
        </ul>
        <p class="text-[11px] text-slate-400 mt-2 leading-snug">
          Estes gastos não têm meta e reduzem diretamente o "Disponível para gastar".
          Defina metas na aba <strong>Metas variáveis</strong> para ter controle granular.
        </p>
      </div>
    ` : '';

    return budgetedHtml + unbudgetedHtml;
  }

  if (key === 'reserva') {
    const target  = capacity.reserve_target_total    || 0;
    const applied = capacity.reserve_applied_total   || 0;
    const pending = capacity.reserve_pending_total   || 0;
    const over    = capacity.reserve_over_applied_total || 0;
    return `
      <div class="space-y-2 pt-1">
        <div class="flex items-baseline gap-3">
          <span class="w-4"></span>
          <span class="flex-1 text-xs text-slate-500">Meta mensal</span>
          <span class="text-sm tabular text-slate-700">${currency.format(target)}</span>
        </div>
        <div class="flex items-baseline gap-3">
          <span class="w-4"></span>
          <span class="flex-1 text-xs text-slate-500">Aplicado no mês</span>
          <span class="text-sm tabular text-slate-700">${currency.format(applied)}</span>
        </div>
        ${pending > 0 ? `<div class="flex items-baseline gap-3">
          <span class="w-4"></span>
          <span class="flex-1 text-xs text-amber-600">Falta aplicar</span>
          <span class="text-sm tabular text-amber-700">${currency.format(pending)}</span>
        </div>` : ''}
        ${over > 0 ? `<div class="flex items-baseline gap-3">
          <span class="w-4"></span>
          <span class="flex-1 text-xs text-indigo-600">Aplicado além da meta</span>
          <span class="text-sm tabular text-indigo-700">${currency.format(over)}</span>
        </div>` : ''}
        <p class="text-[11px] text-slate-400 pt-1 border-t border-slate-100 mt-1">
          Reserva não é despesa, mas reduz o dinheiro livre porque é um compromisso planejado.
        </p>
      </div>
    `;
  }

  if (key === 'livre') {
    const lVarConsumed  = capacity.variable_budget_consumed          || 0;
    const lVarOverage   = capacity.variable_budget_overage           || 0;
    const lVarTotal     = capacity.variable_budget_total             || 0;
    const lVarReserved  = capacity.variable_budget_reserved          || 0;
    const lIsFuture     = capacity.is_future_month                   || false;
    const lUnbudgeted   = capacity.unbudgeted_variable_spent         || 0;
    const lReserve      = capacity.reserve_reserved_total            || 0;
    const lCcRem        = capacity.card_invoice_remaining_to_reserve || 0;
    const eq = [
      { label: 'Receita esperada',           value: capacity.expected_income_total     || 0, op: '',  cls: 'text-slate-700' },
      { label: 'Custos fixos reservados',    value: capacity.fixed_cost_reserved_total || 0, op: '−', cls: 'text-slate-600' },
      lIsFuture
        ? { label: 'Variável planejado (meta)', value: lVarTotal,    op: '−', cls: 'text-slate-600' }
        : { label: 'Variável consumido',        value: lVarConsumed, op: '−', cls: 'text-slate-600' },
      ...(!lIsFuture && lVarOverage > 0 ? [{ label: 'Estouro variável', value: lVarOverage, op: '−', cls: 'text-slate-600' }] : []),
      { label: 'Reserva planejada/aplic.',   value: lReserve,                                op: '−', cls: 'text-slate-600' },
      ...(lCcRem > 0 ? [{ label: 'Fatura ainda não contemplada', value: lCcRem,             op: '−', cls: 'text-amber-600' }] : []),
      { label: 'Pode gastar',                value: sobra,                                   op: '=', cls: sobraPositive ? 'text-emerald-700 font-bold' : 'text-red-600 font-bold' },
    ];
    return `
      <div class="space-y-2 pt-1">
        ${eq.map((r, i) => `
          <div class="flex items-baseline gap-3 ${i === eq.length - 1 ? 'border-t border-slate-200 pt-2 mt-1' : ''}">
            <span class="w-4 text-center text-xs text-slate-400 shrink-0">${r.op}</span>
            <span class="flex-1 text-sm text-slate-600">${r.label}</span>
            <span class="text-sm tabular ${r.cls}">${currency.format(r.value)}</span>
          </div>
        `).join('')}
        <p class="text-[11px] text-slate-400 pt-1 border-t border-slate-100 mt-1">
          Reserva não é despesa, mas reduz o dinheiro livre porque é um compromisso planejado.
        </p>
      </div>
    `;
  }
  return '';
}

// ── Category stacked bar ────────────────────────────────────────────────────

function renderCategoryBar(fixed) {
  const container = document.getElementById('category-bar');
  if (!container || fixed.total <= 0 || !fixed.categories?.length) {
    if (container) container.innerHTML = '';
    return;
  }
  const bars = fixed.categories
    .filter((cat) => cat.total > 0)
    .map((cat) => {
      const pct = (cat.total / fixed.total) * 100;
      return `
        <div
          class="h-full rounded-sm first:rounded-l-full last:rounded-r-full transition-all"
          style="width:${pct.toFixed(1)}%;background:${escapeHtml(cat.category_color)}"
          title="${escapeHtml(cat.category_name)}: ${currency.format(cat.total)}"
        ></div>
      `;
    }).join('');

  const legend = fixed.categories
    .filter((cat) => cat.total > 0)
    .map((cat) => `
      <span class="inline-flex items-center gap-1 text-xs text-slate-600">
        <span class="size-2 rounded-full shrink-0 inline-block" style="background:${escapeHtml(cat.category_color)}"></span>
        ${escapeHtml(cat.category_name)}
        <span class="text-slate-400">${currency.format(cat.total)}</span>
      </span>
    `).join('');

  container.innerHTML = `
    <div class="flex h-2.5 w-full rounded-full overflow-hidden gap-px mb-2">${bars}</div>
    <div class="flex flex-wrap gap-x-4 gap-y-1">${legend}</div>
  `;
}

// ── Status badge ────────────────────────────────────────────────────────────

function statusBadge(status) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.scheduled;
  return `
    <span class="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.text}">
      <span>${cfg.icon}</span>${cfg.label}
    </span>
  `;
}

// ── Month breakdown ─────────────────────────────────────────────────────────

async function loadMonthData() {
  if (!selectedMonth) return;
  expandedOverviewPanel = null;   // reset expanded card when month changes
  try {
    const [fixed, capacity] = await Promise.all([
      fetchJson(`/fixed-costs/by-month?year_month=${selectedMonth}`),
      fetchJson(`/spending-capacity?year_month=${selectedMonth}`),
    ]);
    const free = capacity.discretionary_available ?? capacity.available_to_spend ?? capacity.remaining_after_plan ?? capacity.remaining_after_invoice;
    document.getElementById('month-total').textContent = currency.format(fixed.total);
    document.getElementById('fixed-month-total').textContent = currency.format(fixed.total);
    document.getElementById('capacity-total').textContent = currency.format(free);
    renderCapacityFlow(capacity);
    renderCategoryBar(fixed);
    renderMonthBreakdown(fixed);
  } catch (err) {
    showToast(`Erro ao carregar mês: ${err.message}`, 'error');
  }
  // Budget progress is independent — a failure here shouldn't block the rest
  await loadBudgetProgress();
}

function renderMonthBreakdown(fixed) {
  const list = document.getElementById('month-breakdown');
  list.innerHTML = '';
  if (fixed.entries.length === 0) {
    list.innerHTML = '<li class="py-8 text-sm text-slate-500 text-center">Nenhum custo fixo ativo. Cadastre um custo base abaixo.</li>';
    return;
  }

  // Group by category preserving order
  const groups = new Map();
  for (const item of fixed.entries) {
    if (!groups.has(item.category_id)) {
      groups.set(item.category_id, {
        category_name: item.category_name,
        category_color: item.category_color,
        items: [],
        total: 0,
      });
    }
    const group = groups.get(item.category_id);
    group.items.push(item);
    group.total += Number(item.amount || 0);
  }

  for (const group of groups.values()) {
    const groupLi = document.createElement('li');
    groupLi.className = 'py-2';

    // Category header
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between gap-3 px-3 py-2 rounded-lg mb-1';
    header.style.borderLeft = `3px solid ${group.category_color}`;
    header.style.backgroundColor = hexToFaint(group.category_color);
    header.innerHTML = `
      <div class="flex items-center gap-2 min-w-0">
        <p class="font-semibold text-slate-900 text-sm truncate">${escapeHtml(group.category_name)}</p>
        <span class="text-xs text-slate-500">${group.items.length} item${group.items.length !== 1 ? 's' : ''}</span>
      </div>
      <p class="font-bold tabular text-slate-900 text-sm shrink-0">${currency.format(group.total)}</p>
    `;
    groupLi.appendChild(header);

    // Items
    const inner = document.createElement('ul');
    inner.className = 'divide-y divide-slate-100 rounded-xl border border-slate-100 overflow-hidden ml-1';
    for (const item of group.items) inner.appendChild(buildMonthRow(item));
    groupLi.appendChild(inner);
    list.appendChild(groupLi);
  }
}

// Turn a hex color into a very faint tint for backgrounds
function hexToFaint(hex) {
  try {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},0.05)`;
  } catch {
    return 'transparent';
  }
}

function buildMonthRow(item) {
  const li = document.createElement('li');
  // No flex on li itself — the row div inside handles layout; picker can expand below
  li.className = 'bg-white transition-colors';

  const overrideBadge = item.is_override
    ? `<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded-full">ajustado</span>`
    : '';
  const baseHint = item.is_override
    ? `<button type="button" data-action="revert" class="text-[10px] text-indigo-500 hover:text-indigo-700 underline">↩ reverter (${currency.format(item.base_amount)})</button>`
    : '';

  // ── Match section ──
  let matchLine = '';
  let linkBtn = '';
  if (item.matched_transaction) {
    const tx = item.matched_transaction;
    const isManual = item.match_source === 'manual';
    const sourceTag = isManual
      ? '<span class="text-[9px] font-semibold uppercase tracking-wide bg-emerald-100 text-emerald-700 px-1 py-px rounded">manual</span>'
      : '<span class="text-[9px] font-semibold uppercase tracking-wide bg-slate-100 text-slate-500 px-1 py-px rounded">auto</span>';
    const unlinkHtml = isManual
      ? `<button type="button" data-action="unlink"
           class="text-[10px] font-medium text-red-500 hover:text-red-700 underline ml-1">
           Desvincular
         </button>`
      : '';
    matchLine = `
      <span class="inline-flex flex-wrap items-center gap-1 text-[10px] text-emerald-700">
        ↳ ${sourceTag}
        <span class="font-medium truncate max-w-[18rem]">${escapeHtml((tx.description || '').slice(0, 40))}</span>
        <span class="tabular font-semibold">${currency.format(tx.amount_abs ?? Math.abs(Number(tx.amount)))}</span>
        <span class="text-slate-400">${formatDate(tx.date)}</span>
        ${unlinkHtml}
      </span>
    `;
  } else {
    linkBtn = `
      <button type="button" data-action="link"
        class="text-[10px] font-semibold text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded transition-colors">
        Vincular pagamento
      </button>
    `;
  }

  li.innerHTML = `
    <div class="py-3 px-3 flex items-start gap-3 hover:bg-slate-50">
      <div class="flex flex-col items-center shrink-0 pt-0.5">
        <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-bold text-sm tabular">${item.due_day}</span>
        <span class="text-[9px] text-slate-400 mt-0.5">dia</span>
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex flex-wrap items-center gap-1.5 mb-0.5">
          <p class="font-medium text-slate-900 text-sm">${escapeHtml(item.description)}</p>
          ${overrideBadge}
          ${statusBadge(item.status)}
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
          <span>vence ${formatDate(item.due_date)}</span>
          ${matchLine}
          ${baseHint}
          ${linkBtn}
        </div>
      </div>
      <input
        type="number" step="0.01" min="0" data-action="edit"
        class="w-28 text-right text-sm font-semibold tabular rounded-lg border border-slate-200 px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 shrink-0"
        value="${Number(item.amount).toFixed(2)}"
      />
    </div>
    <!-- Inline transaction picker — shown when user clicks "Vincular pagamento" -->
    <div data-tx-picker class="hidden">
      <div class="mx-3 mb-3 ml-14 rounded-xl border border-indigo-200 bg-indigo-50/50 px-3 pt-2 pb-3">
        <div class="flex items-center justify-between mb-2">
          <p class="text-xs font-semibold text-slate-700">
            Vincular <span class="text-indigo-700">${escapeHtml(item.description)}</span> a qual transação?
          </p>
          <button type="button" data-action="cancel-link" class="text-[11px] text-slate-400 hover:text-slate-700 px-1">✕ fechar</button>
        </div>
        <div data-tx-picker-list class="space-y-1 max-h-60 overflow-y-auto pr-0.5"></div>
      </div>
    </div>
  `;

  // ── Amount override input ──
  const input = li.querySelector('input[data-action="edit"]');
  const commit = async () => {
    const newAmount = Number(input.value);
    if (Number.isNaN(newAmount) || newAmount < 0) { input.value = Number(item.amount).toFixed(2); return; }
    if (Math.abs(newAmount - Number(item.amount)) < 0.005) return;
    if (Math.abs(newAmount - Number(item.base_amount)) < 0.005 && item.is_override) {
      try {
        await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, { method: 'DELETE' });
        await loadMonthData();
        showToast('Ajuste removido, voltou ao base.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    try {
      await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: newAmount }),
      });
      await loadMonthData();
      showToast('Valor do mês atualizado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
    if (event.key === 'Escape') { input.value = Number(item.amount).toFixed(2); input.blur(); }
  });

  // ── Revert override ──
  const revertBtn = li.querySelector('[data-action="revert"]');
  if (revertBtn) {
    revertBtn.addEventListener('click', async () => {
      try {
        await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, { method: 'DELETE' });
        await loadMonthData();
        showToast('Ajuste removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }

  // ── Vincular pagamento ──
  const linkButton = li.querySelector('[data-action="link"]');
  if (linkButton) {
    const pickerEl = li.querySelector('[data-tx-picker]');
    const pickerList = li.querySelector('[data-tx-picker-list]');
    linkButton.addEventListener('click', () => {
      pickerEl.classList.remove('hidden');
      openTransactionPicker(pickerList, item);
    });
    li.querySelector('[data-action="cancel-link"]').addEventListener('click', () => {
      pickerEl.classList.add('hidden');
    });
  }

  // ── Desvincular ──
  const unlinkButton = li.querySelector('[data-action="unlink"]');
  if (unlinkButton) {
    unlinkButton.addEventListener('click', async () => {
      if (!confirm(`Desvincular o pagamento de "${item.description}"?`)) return;
      try {
        await fetchJson(`/fixed-costs/matches/${item.fixed_cost_transaction_match_id}`, { method: 'DELETE' });
        await loadMonthData();
        showToast('Vínculo removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }

  return li;
}

// ── Transaction picker (inline panel below the fixed-cost row) ──────────────

async function openTransactionPicker(listEl, item) {
  listEl.innerHTML = '<p class="text-xs text-slate-400 py-3 text-center">Carregando transações…</p>';

  const [year, month] = selectedMonth.split('-').map(Number);
  const fromDate = `${selectedMonth}-01`;
  const lastDay = new Date(year, month, 0).getDate();
  const toDate = `${selectedMonth}-${String(lastDay).padStart(2, '0')}`;

  try {
    const transactions = await fetchJson(
      `/transactions?account_type=ALL&from_date=${fromDate}&to_date=${toDate}&include_future=true&include_ignored=true`
    );

    // Show only outflows (money leaving the user)
    const outflows = transactions.filter((tx) => Number(tx.amount) < 0);
    if (outflows.length === 0) {
      listEl.innerHTML = '<p class="text-xs text-slate-400 py-3 text-center">Nenhuma saída encontrada neste mês.</p>';
      return;
    }

    // Score candidates: amount proximity + description token overlap
    const costTokens = tokenSetJs(item.description);
    const tolerance = Math.max(Number(item.amount) * 0.15, 10);
    const scored = outflows.map((tx) => {
      const txAbs = Math.abs(Number(tx.amount));
      const amountDelta = Math.abs(txAbs - Number(item.amount));
      const txTokens = tokenSetJs(tx.description || '');
      const overlap = [...costTokens].filter((t) => txTokens.has(t)).length;
      const closeAmount = amountDelta <= tolerance;
      return { tx, txAbs, amountDelta, overlap, closeAmount };
    }).sort((a, b) => {
      // Good candidates (close amount) first, then by token overlap, then by amount delta
      if (a.closeAmount !== b.closeAmount) return a.closeAmount ? -1 : 1;
      if (b.overlap !== a.overlap) return b.overlap - a.overlap;
      return a.amountDelta - b.amountDelta;
    });

    listEl.innerHTML = '';
    const showing = scored.slice(0, 20);

    // Header hint
    if (showing.some((s) => s.closeAmount && s.overlap > 0)) {
      const hint = document.createElement('p');
      hint.className = 'text-[10px] text-slate-400 mb-1';
      hint.textContent = 'Candidatos com melhor compatibilidade aparecem primeiro.';
      listEl.appendChild(hint);
    }

    for (const { tx, txAbs, closeAmount, overlap } of showing) {
      const isGood = closeAmount && overlap > 0;
      const row = document.createElement('div');
      row.className = `flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors hover:bg-white/80 ${isGood ? 'bg-emerald-50/70 border border-emerald-100' : 'bg-white/40'}`;

      const categoryLabel = escapeHtml(tx.custom_category_name || tx.category || '');
      const accountHint = categoryLabel ? `<span class="text-slate-400 text-[9px]">${categoryLabel}</span>` : '';

      row.innerHTML = `
        <span class="text-[10px] text-slate-500 tabular shrink-0 w-10">${formatDate(tx.date)}</span>
        <div class="flex-1 min-w-0">
          <p class="text-xs text-slate-800 truncate" title="${escapeHtml(tx.description)}">${escapeHtml(tx.description)}</p>
          ${accountHint}
        </div>
        <span class="text-xs font-semibold tabular ${isGood ? 'text-emerald-700' : 'text-slate-700'} shrink-0">${currency.format(txAbs)}</span>
        <button type="button"
          class="shrink-0 text-[11px] font-semibold text-white bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 px-2.5 py-1 rounded-lg transition-colors whitespace-nowrap">
          Vincular
        </button>
      `;

      row.querySelector('button').addEventListener('click', async () => {
        try {
          await fetchJson(`/fixed-costs/${item.fixed_cost_id}/matches`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ transaction_id: tx.id, year_month: selectedMonth }),
          });
          await loadMonthData();
          showToast(`"${item.description}" vinculado ao pagamento.`, 'success');
        } catch (err) {
          showToast(err.message, 'error');
        }
      });

      listEl.appendChild(row);
    }

    if (scored.length > 20) {
      const more = document.createElement('p');
      more.className = 'text-[10px] text-slate-400 text-center pt-1';
      more.textContent = `+${scored.length - 20} transações não exibidas. Refine buscando pelo valor esperado.`;
      listEl.appendChild(more);
    }
  } catch (err) {
    listEl.innerHTML = `<p class="text-xs text-red-500 py-3 text-center">${escapeHtml(err.message)}</p>`;
  }
}

// ── Categories & costs (base section) ──────────────────────────────────────

async function loadCategories() {
  categories = await fetchJson('/fixed-cost-categories');
  renderQuickCostCategoryOptions();
  const customCount = categories.filter((cat) => !cat.is_default).length;
  const remaining = Math.max(0, MAX_CUSTOM_CATEGORIES - customCount);
  document.getElementById('custom-category-count').textContent =
    `${customCount}/${MAX_CUSTOM_CATEGORIES} personalizadas · ${remaining} restante${remaining === 1 ? '' : 's'}`;
  const addButton = document.querySelector('#category-form button[type="submit"]');
  if (addButton) {
    addButton.disabled = customCount >= MAX_CUSTOM_CATEGORIES;
    addButton.classList.toggle('opacity-50', customCount >= MAX_CUSTOM_CATEGORIES);
    addButton.classList.toggle('cursor-not-allowed', customCount >= MAX_CUSTOM_CATEGORIES);
  }
  renderCategoryCostList();
}

function renderQuickCostCategoryOptions(selectedId = null) {
  const select = document.getElementById('quick-cost-category');
  if (!select) return;
  select.innerHTML = categories.map((cat) => {
    const selected = Number(cat.id) === Number(selectedId) ? 'selected' : '';
    return `<option value="${cat.id}" ${selected}>${escapeHtml(cat.name)}</option>`;
  }).join('');
}

function buildCategoryCostGroup(category, costs) {
  const wrapper = document.createElement('section');
  wrapper.className = 'rounded-xl border border-slate-200 overflow-hidden';
  wrapper.style.borderTopColor = category.color;
  wrapper.style.borderTopWidth = '3px';

  const activeTotal = costs.filter((c) => c.active).reduce((sum, c) => sum + Number(c.amount || 0), 0);
  const activeCostCount = costs.filter((c) => c.active).length;
  const customBadge = category.is_default
    ? ''
    : '<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded-full">personalizada</span>';
  const deleteButton = category.is_default
    ? ''
    : '<button type="button" data-action="delete" class="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors">Excluir</button>';

  wrapper.innerHTML = `
    <div class="px-4 py-3 flex items-center justify-between gap-2 bg-slate-50">
      <!-- Left side: click to expand/collapse -->
      <button type="button" data-action="toggle-expand"
        class="flex items-center gap-2 min-w-0 flex-1 text-left">
        <span data-chevron class="text-slate-400 text-[10px] transition-transform duration-150">▶</span>
        <span class="size-2.5 rounded-full shrink-0" style="background:${escapeHtml(category.color)}"></span>
        <h3 class="font-semibold text-slate-900 text-sm truncate">${escapeHtml(category.name)}</h3>
        ${customBadge}
        <span class="text-xs text-slate-400 shrink-0">${activeCostCount} ${activeCostCount === 1 ? 'custo' : 'custos'}</span>
      </button>
      <!-- Right side: total + actions (never trigger expand) -->
      <div class="flex items-center gap-2 shrink-0">
        <span class="text-sm font-semibold tabular text-slate-700">${currency.format(activeTotal)}</span>
        <button type="button" data-action="toggle-add"
          class="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors">
          <span class="text-base leading-none" aria-hidden="true">＋</span> Adicionar
        </button>
        ${deleteButton}
      </div>
    </div>

    <!-- Collapsible body (hidden by default) -->
    <div data-body class="hidden">
      <div data-add-form class="hidden px-4 py-3 bg-indigo-50/40 border-b border-indigo-100">
        <form class="grid grid-cols-1 lg:grid-cols-[1fr_140px_90px_auto] gap-2" data-add-category="${category.id}">
          <input name="description" type="text" required value="${escapeHtml(category.name)}"
            placeholder="Descrição" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
          <input name="amount" type="number" step="0.01" min="0.01" required placeholder="Valor (R$)"
            class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
          <input name="due_day" type="number" min="1" max="31" required placeholder="Dia"
            class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
          <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg px-4 py-2">Salvar</button>
        </form>
      </div>
      <ul class="divide-y divide-slate-100 text-sm border-t border-slate-100"></ul>
    </div>
  `;

  const body = wrapper.querySelector('[data-body]');
  const addFormContainer = wrapper.querySelector('[data-add-form]');
  const chevron = wrapper.querySelector('[data-chevron]');

  function openBody() {
    body.classList.remove('hidden');
    chevron.style.transform = 'rotate(90deg)';
  }
  function closeBody() {
    body.classList.add('hidden');
    chevron.style.transform = '';
    addFormContainer.classList.add('hidden');
  }

  // Expand/collapse on left-side click
  wrapper.querySelector('[data-action="toggle-expand"]').addEventListener('click', () => {
    body.classList.contains('hidden') ? openBody() : closeBody();
  });

  // "＋ Adicionar" always opens body + shows form
  wrapper.querySelector('[data-action="toggle-add"]').addEventListener('click', () => {
    openBody();
    addFormContainer.classList.remove('hidden');
    const descInput = addFormContainer.querySelector('input[name="description"]');
    descInput.value = category.name;
    addFormContainer.querySelector('input[name="amount"]').focus();
  });

  // Submit add form
  const form = wrapper.querySelector('form[data-add-category]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const description = String(data.get('description') || '').trim();
    const amount = Number(data.get('amount'));
    const due_day = Number(data.get('due_day'));
    if (!description || !amount || !due_day) return;
    try {
      await fetchJson('/fixed-costs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: category.id, description, amount, due_day }),
      });
      form.reset();
      addFormContainer.classList.add('hidden');
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo fixo adicionado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  // Cost list
  const innerList = wrapper.querySelector('ul');
  if (costs.length === 0) {
    const emptyLi = document.createElement('li');
    emptyLi.className = 'py-6 mx-3 my-3 flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-200';
    emptyLi.innerHTML = `
      <span class="text-2xl opacity-25">📋</span>
      <p class="text-xs text-slate-400 text-center leading-relaxed">
        Nenhum custo cadastrado.<br>Clique em <strong class="font-semibold text-slate-500">＋ Adicionar</strong> para criar.
      </p>
    `;
    innerList.appendChild(emptyLi);
  } else {
    for (const cost of costs) innerList.appendChild(buildCostRow(cost));
  }

  // Delete category
  const deleteAction = wrapper.querySelector('[data-action="delete"]');
  if (deleteAction) {
    deleteAction.addEventListener('click', async () => {
      if (!confirm(`Excluir categoria "${category.name}"?`)) return;
      try {
        await fetchJson(`/fixed-cost-categories/${category.id}`, { method: 'DELETE' });
        await Promise.all([loadCategories(), loadCosts(), loadMonthData()]);
        showToast('Categoria excluída.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
  return wrapper;
}

function renderCategoryCostList() {
  const list = document.getElementById('category-cost-list');
  if (!list) return;
  list.innerHTML = '';
  const categoriesWithCosts = categories
    .map((category) => ({
      category,
      costs: fixedCosts.filter((cost) => Number(cost.category_id) === Number(category.id)),
    }))
    .filter((entry) => entry.costs.length > 0);
  if (categoriesWithCosts.length === 0) {
    list.innerHTML = '<div class="py-8 text-sm text-slate-500 text-center rounded-xl border border-dashed border-slate-200">Nenhum custo fixo cadastrado ainda. Adicione o primeiro custo abaixo.</div>';
    return;
  }
  for (const { category, costs } of categoriesWithCosts) {
    list.appendChild(buildCategoryCostGroup(category, costs));
  }
}

async function loadTemplates() {
  const list = document.getElementById('template-list');
  if (!list) return;
  try {
    const templates = await fetchJson('/fixed-costs/templates');
    list.innerHTML = templates.map((template) => {
      const emoji = TEMPLATE_EMOJIS[template.label] || '📋';
      return `
        <button type="button" data-template="${escapeHtml(template.label)}"
          class="inline-flex items-center gap-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 px-3 py-1.5 rounded-lg transition-colors shadow-sm">
          <span>${emoji}</span>${escapeHtml(template.label)}
        </button>
      `;
    }).join('');
    list.querySelectorAll('button[data-template]').forEach((button) => {
      button.addEventListener('click', () => {
        const template = templates.find((item) => item.label === button.dataset.template);
        if (!template) return;
        fillQuickCostForm(template);
      });
    });
  } catch (err) {
    list.innerHTML = '<span class="text-xs text-slate-500">Templates indisponíveis.</span>';
  }
}

function fillQuickCostForm(template) {
  renderQuickCostCategoryOptions(template.category_id);
  document.getElementById('quick-cost-description').value = template.description;
  document.getElementById('quick-cost-day').value = template.due_day;
  document.getElementById('quick-cost-amount').focus();
}

async function loadCosts() {
  const showInactive = document.getElementById('show-inactive').checked;
  const costs = await fetchJson('/fixed-costs' + (showInactive ? '?include_inactive=true' : ''));
  fixedCosts = costs;
  document.getElementById('cost-count').textContent =
    costs.length === 1 ? '1 custo' : `${costs.length} custos`;
  const activeTotal = costs.filter((c) => c.active).reduce((sum, c) => sum + Number(c.amount || 0), 0);
  document.getElementById('active-total').textContent = currency.format(activeTotal);
  renderCategoryCostList();
}

function buildCostRow(cost) {
  const li = document.createElement('li');
  li.className = 'py-3 px-4 flex items-center gap-3 hover:bg-slate-50 transition-colors';
  li.innerHTML = `
    <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-bold text-sm shrink-0 tabular">${cost.due_day}</span>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-sm break-words ${cost.active ? 'text-slate-900' : 'text-slate-400 line-through'}">${escapeHtml(cost.description)}</p>
      <p class="text-xs text-slate-400 mt-0.5">dia ${cost.due_day} de cada mês</p>
    </div>
    <p class="font-semibold tabular text-sm shrink-0 ${cost.active ? 'text-slate-900' : 'text-slate-400'}">${currency.format(cost.amount)}</p>
    <div class="flex items-center gap-1 shrink-0">
      <button type="button" data-action="edit"
        class="text-xs text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors">Editar</button>
      <button type="button" data-action="toggle"
        class="text-xs text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-2 py-1 rounded-lg transition-colors">${cost.active ? 'Desativar' : 'Reativar'}</button>
      <button type="button" data-action="delete"
        class="text-xs text-red-500 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors">Excluir</button>
    </div>
  `;

  li.querySelector('[data-action="edit"]').addEventListener('click', () => renderCostEditRow(li, cost));
  li.querySelector('[data-action="toggle"]').addEventListener('click', async () => {
    try {
      await fetchJson(`/fixed-costs/${cost.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !cost.active }),
      });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast(cost.active ? 'Custo desativado.' : 'Custo reativado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  li.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    if (!confirm(`Excluir "${cost.description}"?`)) return;
    try {
      await fetchJson(`/fixed-costs/${cost.id}`, { method: 'DELETE' });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo excluído.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  return li;
}

function categoryOptions(selectedId) {
  return categories.map((cat) => {
    const selected = Number(cat.id) === Number(selectedId) ? 'selected' : '';
    return `<option value="${cat.id}" ${selected}>${escapeHtml(cat.name)}</option>`;
  }).join('');
}

function renderCostEditRow(li, cost) {
  li.className = 'py-3 px-4 bg-indigo-50/40';
  li.innerHTML = `
    <form class="grid grid-cols-1 lg:grid-cols-[160px_1fr_140px_90px_auto_auto] gap-2 w-full">
      <select name="category_id" required
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white">
        ${categoryOptions(cost.category_id)}
      </select>
      <input name="description" type="text" required value="${escapeHtml(cost.description)}"
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <input name="amount" type="number" step="0.01" min="0.01" required value="${Number(cost.amount).toFixed(2)}"
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <input name="due_day" type="number" min="1" max="31" required value="${cost.due_day}"
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg px-3 py-2">Salvar</button>
      <button type="button" data-action="cancel"
        class="text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg hover:bg-slate-100">Cancelar</button>
    </form>
  `;
  li.querySelector('[data-action="cancel"]').addEventListener('click', () => li.replaceWith(buildCostRow(cost)));
  li.querySelector('form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(li.querySelector('form'));
    try {
      await fetchJson(`/fixed-costs/${cost.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category_id: Number(data.get('category_id')),
          description: String(data.get('description') || '').trim(),
          amount: Number(data.get('amount')),
          due_day: Number(data.get('due_day')),
        }),
      });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo atualizado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Budget progress (metas variáveis) ──────────────────────────────────────

const BUDGET_STATUS_CFG = {
  ok:      { bar: 'bg-emerald-500', text: 'text-emerald-700', label: 'ok'      },
  warning: { bar: 'bg-amber-500',   text: 'text-amber-700',   label: 'atenção' },
  over:    { bar: 'bg-red-500',     text: 'text-red-700',     label: 'excedido' },
};

async function loadBudgetProgress() {
  if (!selectedMonth) return;
  try {
    const progress = await fetchJson(`/budgets/progress?year_month=${selectedMonth}`);
    const label = document.getElementById('budget-month-label');
    if (label) label.textContent = formatMonthShort(selectedMonth);
    renderBudgetList(progress);
  } catch (err) {
    const list = document.getElementById('budget-list');
    if (list) list.innerHTML =
      `<div class="py-4 text-sm text-red-600 text-center">${escapeHtml(err.message)}</div>`;
  }
}

function renderBudgetList(progress) {
  const list = document.getElementById('budget-list');
  if (!list) return;
  list.innerHTML = '';
  const items = progress.items || [];
  if (items.length === 0) {
    list.innerHTML = '<div class="py-8 text-sm text-slate-500 text-center">Nenhuma categoria disponível.</div>';
    return;
  }
  for (const item of items) list.appendChild(buildBudgetItem(item));
}

function buildBudgetItem(item) {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex items-start gap-3 py-3 px-4 bg-slate-50 rounded-xl border border-slate-100';

  const hasTarget = item.target !== null && item.target > 0;
  const actualPct  = hasTarget ? Math.min(100, item.actual_progress_pct  || 0) : 0;
  const projectedPct = hasTarget ? Math.min(100, item.progress_pct || 0) : 0;
  const cfg = BUDGET_STATUS_CFG[item.status] || BUDGET_STATUS_CFG.ok;
  const scopeBadge = item.target_scope === 'month'
    ? '<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded-full ml-1">mês</span>'
    : '';

  const progressArea = hasTarget ? `
    <div class="relative h-1.5 w-full bg-slate-200 rounded-full overflow-hidden mt-1.5">
      <div class="absolute inset-y-0 left-0 rounded-full opacity-35 ${cfg.bar}" style="width:${projectedPct.toFixed(1)}%"></div>
      <div class="absolute inset-y-0 left-0 rounded-full ${cfg.bar}" style="width:${actualPct.toFixed(1)}%"></div>
    </div>
    <div class="flex items-center justify-between text-[11px] mt-1">
      <span class="text-slate-400">
        <span class="tabular text-slate-600 font-medium">${currency.format(item.actual_spent)}</span> gasto
        ${item.future_spent > 0 ? `· <span class="tabular">${currency.format(item.future_spent)}</span> previsto` : ''}
      </span>
      <span class="font-semibold tabular ${cfg.text}">${Math.round(item.actual_progress_pct || 0)}%</span>
    </div>
  ` : `
    <p class="text-[11px] text-slate-400 mt-1">
      Gasto: <span class="tabular text-slate-600">${currency.format(item.actual_spent + item.future_spent)}</span>
      · <span class="text-slate-400">sem meta</span>
    </p>
  `;

  const targetCell = hasTarget
    ? `<input type="number" step="0.01" min="0" data-target-input
         value="${Number(item.target).toFixed(2)}"
         class="w-28 text-right text-sm font-semibold tabular rounded-lg border border-slate-200 px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />`
    : `<button type="button" data-action="set-target"
         class="text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap">
         Definir meta
       </button>`;

  const removeCell = hasTarget
    ? `<button type="button" data-action="remove-target" title="Remover meta"
         class="text-slate-300 hover:text-red-500 hover:bg-red-50 p-1.5 rounded-lg transition-colors text-xs leading-none">✕</button>`
    : '';

  wrapper.innerHTML = `
    <span class="size-2.5 rounded-full shrink-0 mt-2" style="background:${escapeHtml(item.category_color)}"></span>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-1">
        <p class="font-medium text-sm text-slate-900">${escapeHtml(item.category_name)}</p>
        ${scopeBadge}
      </div>
      ${progressArea}
    </div>
    <div class="flex items-center gap-1 shrink-0 mt-0.5">
      ${targetCell}
      ${removeCell}
    </div>
  `;

  // Edit existing target on blur/enter
  const targetInput = wrapper.querySelector('[data-target-input]');
  if (targetInput) {
    const commit = async () => {
      const val = Number(targetInput.value);
      if (Number.isNaN(val) || val < 0) { targetInput.value = Number(item.target).toFixed(2); return; }
      if (Math.abs(val - Number(item.target)) < 0.005) return;
      try {
        if (val === 0) {
          await _deleteBudget(item);
        } else {
          await fetchJson(`/budgets/${item.category_id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monthly_target: val }),
          });
          showToast('Meta atualizada.', 'success');
        }
        await loadBudgetProgress();
      } catch (err) { showToast(err.message, 'error'); }
    };
    targetInput.addEventListener('blur', commit);
    targetInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); targetInput.blur(); }
      if (event.key === 'Escape') { targetInput.value = Number(item.target).toFixed(2); targetInput.blur(); }
    });
  }

  // "Definir meta" — replace button with inline input
  const setTargetBtn = wrapper.querySelector('[data-action="set-target"]');
  if (setTargetBtn) {
    setTargetBtn.addEventListener('click', () => {
      const cell = setTargetBtn.closest('div');
      cell.innerHTML = `
        <input type="number" step="0.01" min="0.01" placeholder="R$ meta"
          class="w-28 text-right text-sm font-semibold tabular rounded-lg border border-indigo-300 px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      `;
      const input = cell.querySelector('input');
      input.focus();
      const save = async () => {
        const val = Number(input.value);
        if (!val || val <= 0) { await loadBudgetProgress(); return; }
        try {
          await fetchJson(`/budgets/${item.category_id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monthly_target: val }),
          });
          await loadBudgetProgress();
          showToast('Meta definida.', 'success');
        } catch (err) { showToast(err.message, 'error'); }
      };
      input.addEventListener('blur', save);
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
        if (event.key === 'Escape') { loadBudgetProgress(); }
      });
    });
  }

  // Remove target
  const removeBtn = wrapper.querySelector('[data-action="remove-target"]');
  if (removeBtn) {
    removeBtn.addEventListener('click', async () => {
      try {
        await _deleteBudget(item);
        await loadBudgetProgress();
        showToast('Meta removida.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }

  return wrapper;
}

async function _deleteBudget(item) {
  // If the active target is a month override, remove just the override first
  if (item.target_scope === 'month') {
    await fetchJson(`/budgets/${item.category_id}/months/${selectedMonth}`, { method: 'DELETE' });
    // If there's no underlying default, nothing else to do
    return;
  }
  // Otherwise delete the global default
  await fetchJson(`/budgets/${item.category_id}`, { method: 'DELETE' });
}

// ── Category form ───────────────────────────────────────────────────────────

document.getElementById('category-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.getElementById('category-name').value.trim();
  const color = document.getElementById('category-color').value;
  const sort_order = Number(document.getElementById('category-order').value || 0);
  if (!name) return;
  if (categories.filter((c) => !c.is_default).length >= MAX_CUSTOM_CATEGORIES) {
    showToast('Limite de 5 categorias personalizadas atingido.', 'error');
    return;
  }
  try {
    await fetchJson('/fixed-cost-categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, color, sort_order }),
    });
    document.getElementById('category-name').value = '';
    await loadCategories();
    showToast('Categoria adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

document.getElementById('quick-cost-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const category_id = Number(document.getElementById('quick-cost-category').value);
  const description = document.getElementById('quick-cost-description').value.trim();
  const amount = Number(document.getElementById('quick-cost-amount').value);
  const due_day = Number(document.getElementById('quick-cost-day').value);
  if (!category_id || !description || !amount || !due_day) return;
  try {
    await fetchJson('/fixed-costs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category_id, description, amount, due_day }),
    });
    document.getElementById('quick-cost-description').value = '';
    document.getElementById('quick-cost-amount').value = '';
    document.getElementById('quick-cost-day').value = '';
    await Promise.all([loadCosts(), loadMonthData()]);
    showToast('Custo fixo adicionado.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

document.getElementById('show-inactive').addEventListener('change', loadCosts);

// ── Transaction suggestions ─────────────────────────────────────────────────

async function loadTransactionSuggestions() {
  const list = document.getElementById('transaction-suggestions');
  if (!list) return;
  try {
    const transactions = await fetchJson('/transactions?account_type=ALL&include_ignored=true');
    const rows = transactions.slice(0, TRANSACTION_SUGGESTIONS_MAX);
    if (rows.length === 0) {
      list.innerHTML = '<li class="py-8 text-sm text-slate-500 text-center">Nenhuma transação recente encontrada.</li>';
      return;
    }
    list.innerHTML = '';
    rows.forEach((tx, index) => {
      const row = buildTransactionSuggestionRow(tx);
      if (index >= TRANSACTION_SUGGESTIONS_INITIAL) row.classList.add('transaction-suggestion-extra', 'hidden');
      list.appendChild(row);
    });
    if (rows.length > TRANSACTION_SUGGESTIONS_INITIAL) {
      const more = document.createElement('li');
      more.className = 'py-3 text-center';
      more.innerHTML = `
        <button type="button" data-action="show-more"
          class="inline-flex items-center gap-2 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-3 py-2 rounded-lg transition-colors">
          <span aria-hidden="true">＋</span>
          Ver mais ${rows.length - TRANSACTION_SUGGESTIONS_INITIAL} transações
        </button>
      `;
      more.querySelector('[data-action="show-more"]').addEventListener('click', () => {
        list.querySelectorAll('.transaction-suggestion-extra').forEach((row) => row.classList.remove('hidden'));
        more.remove();
      });
      list.appendChild(more);
    }
  } catch (err) {
    list.innerHTML = `<li class="py-6 text-sm text-red-600 text-center">${escapeHtml(err.message)}</li>`;
  }
}

function buildTransactionSuggestionRow(tx) {
  const li = document.createElement('li');
  li.className = 'py-3 px-1 flex items-center gap-3 hover:bg-slate-50 rounded-lg transition-colors';

  const txDate = new Date(tx.date + 'T00:00:00');
  const day = String(txDate.getDate()).padStart(2, '0');
  const monthLabel = MONTH_LABELS[txDate.getMonth()];

  li.innerHTML = `
    <div class="flex flex-col items-center justify-center size-10 rounded-xl bg-slate-100 shrink-0">
      <span class="text-base font-bold text-slate-700 leading-none tabular">${day}</span>
      <span class="text-[9px] text-slate-400 uppercase tracking-wide leading-none mt-0.5">${monthLabel}</span>
    </div>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-slate-900 text-sm truncate">${escapeHtml(tx.description)}</p>
      <p class="text-xs text-slate-400 mt-0.5">${escapeHtml(tx.custom_category_name || tx.category || 'Sem categoria')}</p>
    </div>
    <p class="font-semibold tabular text-sm text-slate-800 shrink-0">${currency.format(Math.abs(Number(tx.amount) || 0))}</p>
    <button type="button" data-action="use"
      class="shrink-0 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-lg transition-colors">
      + Criar custo
    </button>
  `;
  li.querySelector('[data-action="use"]').addEventListener('click', async () => {
    try {
      await fetchJson('/fixed-costs/from-transaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transaction_id: tx.id }),
      });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo fixo criado a partir da transação.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  return li;
}

// ── Expected income tab ────────────────────────────────────────────────────

function renderIncomeMonthStrip() {
  const strip = document.getElementById('income-month-strip');
  if (!strip) return;
  strip.innerHTML = '';
  for (const ym of incomeMonthStrip) {
    const button = document.createElement('button');
    const active = ym === incomeSelectedMonth;
    button.type = 'button';
    button.className =
      'shrink-0 text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ' +
      (active ? 'bg-indigo-600 text-white shadow-sm' : 'bg-slate-100 text-slate-700 hover:bg-slate-200');
    button.textContent = formatMonthShort(ym);
    button.addEventListener('click', () => {
      if (ym === incomeSelectedMonth) return;
      incomeSelectedMonth = ym;
      renderIncomeMonthStrip();
      loadIncomeMonthBreakdown();
    });
    strip.appendChild(button);
  }
}

function buildIncomeEntryRow(entry) {
  const li = document.createElement('li');
  li.className =
    'rounded-xl border overflow-hidden transition-colors ' +
    (entry.active ? 'border-slate-200 bg-white' : 'border-slate-100 bg-slate-50 opacity-60');

  li.innerHTML = `
    <div class="flex items-center gap-3 px-4 py-3">
      <div class="flex flex-col items-center shrink-0">
        <span class="inline-flex items-center justify-center size-9 rounded-lg font-bold text-sm tabular
          ${entry.active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'}">${entry.expected_day}</span>
        <span class="text-[9px] text-slate-400 mt-0.5">dia</span>
      </div>
      <div class="flex-1 min-w-0">
        <p class="font-medium text-sm ${entry.active ? 'text-slate-900' : 'text-slate-400 line-through'} truncate">${escapeHtml(entry.description)}</p>
        <p class="text-xs text-slate-400 mt-0.5">recorrente · todo mês</p>
      </div>
      <p class="font-bold tabular text-sm shrink-0 ${entry.active ? 'text-emerald-700' : 'text-slate-400'}">${currency.format(entry.amount)}</p>
      <div class="flex items-center gap-1 shrink-0">
        <button type="button" data-action="edit"
          class="text-xs text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors">Editar</button>
        <button type="button" data-action="toggle"
          class="text-xs text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-2 py-1 rounded-lg transition-colors">${entry.active ? 'Desativar' : 'Reativar'}</button>
        <button type="button" data-action="delete"
          class="text-xs text-red-500 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors">Excluir</button>
      </div>
    </div>
  `;

  li.querySelector('[data-action="edit"]').addEventListener('click', () => renderIncomeEntryEditRow(li, entry));
  li.querySelector('[data-action="toggle"]').addEventListener('click', async () => {
    try {
      await fetchJson(`/expected-income/${entry.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !entry.active }),
      });
      await Promise.all([loadIncomeEntries(), loadIncomeMonthBreakdown(), loadMonthData()]);
      showToast(entry.active ? 'Entrada desativada.' : 'Entrada reativada.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  li.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    if (!confirm(`Excluir "${entry.description}"?`)) return;
    try {
      await fetchJson(`/expected-income/${entry.id}`, { method: 'DELETE' });
      await Promise.all([loadIncomeEntries(), loadIncomeMonthBreakdown(), loadMonthData()]);
      showToast('Entrada excluída.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  return li;
}

function renderIncomeEntryEditRow(li, entry) {
  li.className = 'rounded-xl border border-indigo-200 bg-indigo-50/40 overflow-hidden';
  li.innerHTML = `
    <form class="flex flex-wrap gap-2 px-4 py-3 items-center">
      <input name="description" type="text" required value="${escapeHtml(entry.description)}"
        placeholder="Descrição"
        class="flex-1 min-w-[140px] text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <input name="amount" type="number" step="0.01" min="0.01" required value="${Number(entry.amount).toFixed(2)}"
        placeholder="Valor (R$)"
        class="w-36 text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <input name="expected_day" type="number" min="1" max="31" required value="${entry.expected_day}"
        placeholder="Dia"
        class="w-20 text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg px-4 py-2">Salvar</button>
      <button type="button" data-action="cancel"
        class="text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg hover:bg-slate-100 transition-colors">Cancelar</button>
    </form>
  `;
  li.querySelector('[data-action="cancel"]').addEventListener('click', () => li.replaceWith(buildIncomeEntryRow(entry)));
  li.querySelector('form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(li.querySelector('form'));
    try {
      await fetchJson(`/expected-income/${entry.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: String(data.get('description') || '').trim(),
          amount: Number(data.get('amount')),
          expected_day: Number(data.get('expected_day')),
        }),
      });
      await Promise.all([loadIncomeEntries(), loadIncomeMonthBreakdown(), loadMonthData()]);
      showToast('Entrada atualizada.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
}

async function loadIncomeEntries() {
  const showInactive = document.getElementById('income-show-inactive')?.checked;
  const entries = await fetchJson('/expected-income' + (showInactive ? '?include_inactive=true' : ''));
  const list = document.getElementById('income-entry-list');
  if (!list) return;
  list.innerHTML = '';
  document.getElementById('income-entry-count').textContent =
    entries.length === 1 ? '1 entrada' : `${entries.length} entradas`;
  // Note: income-active-total (hero card) is owned by loadIncomeMonthBreakdown,
  // which shows the effective month total (with overrides). We don't overwrite it here.
  if (entries.length === 0) {
    list.innerHTML = `
      <li class="py-6 mx-0 flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-200">
        <span class="text-2xl opacity-25">💰</span>
        <p class="text-xs text-slate-400 text-center leading-relaxed">
          Nenhuma entrada cadastrada.<br>Use o formulário abaixo para criar.
        </p>
      </li>`;
    return;
  }
  for (const entry of entries) list.appendChild(buildIncomeEntryRow(entry));
}

async function loadIncomeMonthBreakdown() {
  if (!incomeSelectedMonth) return;
  const data = await fetchJson(`/expected-income/by-month?year_month=${incomeSelectedMonth}`);
  document.getElementById('income-month-total').textContent = currency.format(data.total);
  // Hero card shows the effective month total (includes any overrides)
  const heroEl = document.getElementById('income-active-total');
  if (heroEl) heroEl.textContent = currency.format(data.total);
  const list = document.getElementById('income-month-breakdown');
  list.innerHTML = '';
  if (data.entries.length === 0) {
    list.innerHTML = `
      <li class="py-8 flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-200">
        <span class="text-2xl opacity-25">💰</span>
        <p class="text-xs text-slate-400 text-center">Nenhuma entrada ativa para este mês.</p>
      </li>`;
    return;
  }
  for (const item of data.entries) list.appendChild(buildIncomeBreakdownRow(item));
}

function buildIncomeBreakdownRow(item) {
  const li = document.createElement('li');
  li.className = 'py-3 px-3 flex items-start gap-3 hover:bg-slate-50 transition-colors';
  const overrideBadge = item.is_override
    ? `<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded-full">ajustado</span>`
    : '';
  const baseHint = item.is_override
    ? `<button type="button" data-action="revert" class="text-[10px] text-indigo-500 hover:text-indigo-700 underline">↩ reverter (${currency.format(item.base_amount)})</button>`
    : '';
  li.innerHTML = `
    <div class="flex flex-col items-center shrink-0 pt-0.5">
      <span class="inline-flex items-center justify-center size-9 rounded-lg bg-emerald-100 text-emerald-700 font-bold text-sm tabular">${item.expected_day}</span>
      <span class="text-[9px] text-slate-400 mt-0.5">dia</span>
    </div>
    <div class="flex-1 min-w-0">
      <div class="flex flex-wrap items-center gap-1.5 mb-0.5">
        <p class="font-medium text-slate-900 text-sm">${escapeHtml(item.description)}</p>
        ${overrideBadge}
      </div>
      <div class="flex flex-wrap items-center gap-x-3 text-[11px] text-slate-400">
        ${baseHint}
      </div>
    </div>
    <input
      type="number" step="0.01" min="0" data-action="edit"
      class="w-28 text-right text-sm font-bold tabular rounded-lg border border-slate-200 px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 shrink-0 text-emerald-700"
      value="${Number(item.amount).toFixed(2)}"
    />
  `;
  const input = li.querySelector('input[data-action="edit"]');
  const commit = async () => {
    const newAmount = Number(input.value);
    if (Number.isNaN(newAmount) || newAmount < 0) {
      input.value = Number(item.amount).toFixed(2);
      return;
    }
    if (Math.abs(newAmount - Number(item.amount)) < 0.005) return;
    if (Math.abs(newAmount - Number(item.base_amount)) < 0.005 && item.is_override) {
      try {
        await fetchJson(`/expected-income/${item.expected_income_id}/overrides/${incomeSelectedMonth}`, { method: 'DELETE' });
        await Promise.all([loadIncomeMonthBreakdown(), loadMonthData()]);
        showToast('Ajuste removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    try {
      await fetchJson(`/expected-income/${item.expected_income_id}/overrides/${incomeSelectedMonth}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: newAmount }),
      });
      await Promise.all([loadIncomeMonthBreakdown(), loadMonthData()]);
      showToast('Valor do mês atualizado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
    if (event.key === 'Escape') { input.value = Number(item.amount).toFixed(2); input.blur(); }
  });
  const revertBtn = li.querySelector('[data-action="revert"]');
  if (revertBtn) {
    revertBtn.addEventListener('click', async () => {
      try {
        await fetchJson(`/expected-income/${item.expected_income_id}/overrides/${incomeSelectedMonth}`, { method: 'DELETE' });
        await Promise.all([loadIncomeMonthBreakdown(), loadMonthData()]);
        showToast('Ajuste removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
  return li;
}

document.getElementById('income-entry-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const description = document.getElementById('income-entry-description').value.trim();
  const amount = Number(document.getElementById('income-entry-amount').value);
  const expected_day = Number(document.getElementById('income-entry-day').value);
  if (!description || !amount || !expected_day) return;
  try {
    await fetchJson('/expected-income', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description, amount, expected_day }),
    });
    document.getElementById('income-entry-description').value = '';
    document.getElementById('income-entry-amount').value = '';
    document.getElementById('income-entry-day').value = '';
    document.getElementById('income-entry-description').focus();
    await Promise.all([loadIncomeEntries(), loadIncomeMonthBreakdown(), loadMonthData()]);
    showToast('Entrada adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

document.getElementById('income-show-inactive')?.addEventListener('change', loadIncomeEntries);

// ── Init ───────────────────────────────────────────────────────────────────

(async () => {
  selectedMonth = currentYearMonth();
  monthStrip = Array.from({ length: MONTH_WINDOW }, (_, i) => shiftYearMonth(selectedMonth, i));
  incomeSelectedMonth = selectedMonth;
  incomeMonthStrip = [...monthStrip];
  document.querySelectorAll('#planning-tabs [data-tab]').forEach((button) => {
    button.addEventListener('click', () => setPlanningTab(button.dataset.tab));
  });
  setPlanningTab(selectedPlanningTabFromUrl(), false);
  renderMonthStrip();
  renderIncomeMonthStrip();
  try {
    await loadCategories();
    await Promise.all([
      loadTemplates(),
      loadCosts(),
      loadMonthData(),
      loadTransactionSuggestions(),
      loadIncomeEntries(),
      loadIncomeMonthBreakdown(),
    ]);
    setPlanningTab(selectedPlanningTabFromUrl(), false);
  } catch (err) {
    showToast(err.message, 'error');
    document.getElementById('subtitle').textContent = 'Erro ao carregar planejamento.';
  }
})();
