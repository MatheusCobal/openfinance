'use strict';

// Dashboard — consolidated view combining the planning hero with the
// transaction/category breakdown previously only shown in /transacoes.

// ── Constants & shared utilities ────────────────────────────────────────────

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const FALLBACK_COLOR = '#64748b';
const TX_PER_CATEGORY_INITIAL = 50;
const CASHFLOW_CARD_INITIAL_ROWS = 8;

let loadVersion = 0;

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function hexWithAlpha(hex, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
}

function categoryIcon(name) {
  const key = String(name).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const icons = {
    mercado: '🛒', restaurantes: '🍽️', transporte: '🚗', saude: '🩺',
    pets: '🐾', casa: '🏠', lazer: '🎮', assinaturas: '📺',
    educacao: '📚', transferencias: '🔁', outros: '📦',
  };
  return icons[key] ?? '💳';
}

function currentYearMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function rangeForCurrentMonth() {
  const today = new Date();
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  return { from: isoDate(first), to: isoDate(today) };
}

function monthKeyForDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function previousMonthKey(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthKeyForDate(new Date(year, month - 2, 1));
}

function findMonth(months, key) {
  return Array.isArray(months) ? months.find((m) => m.month === key) : null;
}

function formatShortDate(iso) {
  const [y, m, d] = String(iso).split('-');
  return `${d}/${m}/${y}`;
}

const dayFormatter   = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short' });
const monthFormatter = new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit' });

function formatDayLabel(iso) {
  const [year, month, day] = String(iso).split('-').map(Number);
  return dayFormatter.format(new Date(year, month - 1, day));
}

function formatMonthLabel(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthFormatter.format(new Date(year, month - 1, 1));
}

function yearMonthFromIso(iso) {
  return String(iso || '').slice(0, 7);
}

function pluralRecebimentos(n) { return n === 1 ? '1 recebimento' : `${n.toLocaleString('pt-BR')} recebimentos`; }
function pluralSaidas(n)       { return n === 1 ? '1 saída' : `${n.toLocaleString('pt-BR')} saídas`; }
function transactionNoun(n)    { return n === 1 ? 'compra' : 'compras'; }

function planStatusLabel(status) {
  return { healthy: 'saudável', tight: 'apertado', over: 'estourado', unknown: 'sem receita' }[status] || 'sem status';
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function showToast(message, variant = 'info') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.classList.remove('hidden', 'bg-slate-900', 'bg-red-600', 'bg-emerald-600');
  el.classList.add(variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-900');
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => el.classList.add('hidden'), 4000);
}

// ── Planning hero ─────────────────────────────────────────────────────────────

const PLAN_STATUS = {
  healthy: { label: 'Saudável',   cls: 'bg-emerald-50 text-emerald-700' },
  tight:   { label: 'Apertado',   cls: 'bg-amber-50   text-amber-700'   },
  over:    { label: 'Estourado',  cls: 'bg-rose-50    text-rose-700'    },
  unknown: { label: 'Sem receita',cls: 'bg-slate-100  text-slate-600'   },
};

function renderPlanning(section, data, month) {
  const available = data.budget_available_to_spend ?? data.discretionary_available ?? 0;
  const sign = available >= 0 ? '+' : '−';
  const status = PLAN_STATUS[data.plan_status] || PLAN_STATUS.unknown;

  const daysRemaining = data.days_remaining_in_month;
  const daily = data.daily_discretionary_remaining;
  const bits = [];
  if (Number.isFinite(daysRemaining) && daysRemaining > 0) {
    bits.push(`${daysRemaining} dia${daysRemaining === 1 ? '' : 's'} restante${daysRemaining === 1 ? '' : 's'}`);
    if (Number.isFinite(daily) && daily > 0) bits.push(`${currency.format(daily)}/dia`);
  }
  const monthLabel = new Date(`${month}-01T00:00:00`).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });

  section.innerHTML = `
    <div class="rounded-2xl overflow-hidden shadow-md">
      <div class="bg-gradient-to-br from-indigo-600 to-indigo-700 px-8 pt-6 pb-8">
        <div class="flex items-center gap-3 mb-1">
          <p class="text-xs font-semibold text-indigo-300 uppercase tracking-widest">Disponível para gastar</p>
          <span class="text-[11px] font-medium px-2 py-0.5 rounded-full ${status.cls}">${status.label}</span>
        </div>
        <p class="text-5xl font-bold tabular text-white tracking-tight">${sign}${currency.format(Math.abs(available))}</p>
        <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 mt-4 text-sm text-indigo-200">
          <span class="capitalize">${escapeHtml(monthLabel)}</span>
          ${bits.length ? `<span class="text-indigo-400 text-xs">·</span><span>${escapeHtml(bits.join(' · '))}</span>` : ''}
          <span class="text-indigo-400 text-xs">·</span>
          <span>plano em <a href="/custos-fixos" class="text-white font-semibold hover:underline">Planejamento</a></span>
        </div>
      </div>
    </div>`;
  section.classList.remove('hidden');
}

// ── Invoice card ──────────────────────────────────────────────────────────────

function renderInvoiceCard(data, month) {
  const section = document.getElementById('invoice-card');
  if (!section) return;
  const official = data.card_invoice_current_open_total ?? data.card_invoice_official_total ?? data.card_invoice_gross_total ?? 0;
  const src = data.card_invoice_source;
  const sourceLabel =
    src === 'open_cycle_transactions'     ? 'Fatura aberta estimada'          :
    src === 'open_month_transactions'     ? 'Fatura aberta estimada'          :
    src === 'pending_cycle_transactions'  ? 'Fatura aberta estimada'          :
    src === 'pending_month_transactions'  ? 'Fatura aberta estimada'          :
    src === 'account_balance_fallback'    ? 'Saldo do cartão'                  :
    src === 'bill'                        ? 'Fatura oficial (Pluggy)'          :
    src === 'account_balance'             ? 'Fatura aberta / saldo do cartão'  :
                                           'Reconstruída por transações';
  const sourceCls =
    src === 'open_cycle_transactions'     ? 'bg-blue-50    text-blue-700'     :
    src === 'open_month_transactions'     ? 'bg-blue-50    text-blue-700'     :
    src === 'pending_cycle_transactions'  ? 'bg-blue-50    text-blue-700'     :
    src === 'pending_month_transactions'  ? 'bg-blue-50    text-blue-700'     :
    src === 'account_balance_fallback'    ? 'bg-slate-100  text-slate-600'    :
    src === 'bill'                        ? 'bg-emerald-50 text-emerald-700'  :
    src === 'account_balance'             ? 'bg-indigo-50  text-indigo-700'   :
                                           'bg-slate-100  text-slate-600';
  const monthLabel = new Date(`${month}-01T00:00:00`).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
  const cycleStart = data.card_invoice_cycle_start;
  const cycleEnd   = data.card_invoice_cycle_end;
  const txCount    = data.card_invoice_transaction_count || 0;
  const cycleLabel = cycleStart && cycleEnd
    ? `Ciclo: ${formatShortDate(cycleStart)} a ${formatShortDate(cycleEnd)}`
    : null;
  section.innerHTML = `
    <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
      <div class="flex items-center gap-2 mb-3">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Fatura do cartão</p>
        <span class="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 font-medium">Cash-flow</span>
        <span class="text-[10px] px-2 py-0.5 rounded-full ${sourceCls}">${escapeHtml(sourceLabel)}</span>
      </div>
      <p class="text-3xl font-bold tabular text-slate-900">${currency.format(official)}</p>
      <div class="flex flex-wrap items-center gap-x-5 gap-y-1 mt-3 text-sm text-slate-500">
        <span class="capitalize">${escapeHtml(monthLabel)}</span>
        ${cycleLabel ? `<span class="text-slate-300 text-xs">·</span><span class="text-xs">${escapeHtml(cycleLabel)}</span>` : ''}
        ${txCount > 0 ? `<span class="text-slate-300 text-xs">·</span><span class="text-xs">${txCount} transaç${txCount === 1 ? 'ão' : 'ões'} pendente${txCount === 1 ? '' : 's'}</span>` : ''}
        <span class="text-slate-300 text-xs">·</span>
        <span>discricionária ${currency.format(data.card_invoice_discretionary_total || 0)}</span>
        <span class="text-slate-300 text-xs">·</span>
        <span>custos fixos ${currency.format(data.card_invoice_fixed_cost_total || 0)}</span>
      </div>
    </div>`;
  section.classList.remove('hidden');
}

// ── Flow cards ────────────────────────────────────────────────────────────────

const FLOW_TINTS = {
  emerald: { text: 'text-emerald-700', iconBg: 'bg-emerald-100' },
  orange:  { text: 'text-orange-700',  iconBg: 'bg-orange-100'  },
  red:     { text: 'text-red-700',     iconBg: 'bg-red-100'     },
  slate:   { text: 'text-slate-700',   iconBg: 'bg-slate-100'   },
};

function flowDelta(curr, prev, higherIsBetter) {
  if (prev === null || prev === undefined || prev === 0) return '';
  const diff = curr - prev;
  if (diff === 0) return '<span class="text-slate-400">igual ao mês anterior</span>';
  const pct  = (diff / Math.abs(prev)) * 100;
  const sign = diff > 0 ? '+' : '−';
  const color = diff > 0
    ? (higherIsBetter ? 'text-emerald-600' : 'text-red-600')
    : (higherIsBetter ? 'text-red-600' : 'text-emerald-600');
  return `<span class="${color} font-medium">${sign}${Math.abs(pct).toFixed(0)}% vs mês anterior</span>`;
}

function flowCard({ label, help, icon, value, prev, countLabel, tint, higherIsBetter, isNet }) {
  const c = FLOW_TINTS[tint] ?? FLOW_TINTS.slate;
  const formatted = isNet
    ? (value >= 0 ? '+' : '−') + currency.format(Math.abs(value))
    : currency.format(value);
  const delta   = flowDelta(value, prev, higherIsBetter);
  const detail  = countLabel
    ? `<span class="text-slate-500">${escapeHtml(countLabel)}</span>`
    : (help ? `<span class="text-slate-500">${escapeHtml(help)}</span>` : '<span></span>');
  const footer  = isNet
    ? (help ? `<span class="text-slate-500">${escapeHtml(help)}</span>` : '<span></span>')
    : `${detail}${delta ? ` <span class="ml-auto">${delta}</span>` : ''}`;
  return `
    <div class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
      <div class="flex items-center justify-between gap-2 mb-3">
        <span class="text-xs font-medium uppercase tracking-wider text-slate-500">${escapeHtml(label)}</span>
        <span class="size-8 rounded-xl ${c.iconBg} flex items-center justify-center text-base leading-none">${icon}</span>
      </div>
      <p class="text-2xl font-bold tabular ${c.text}">${escapeHtml(formatted)}</p>
      <div class="mt-3 flex items-center gap-2 text-xs">${footer}</div>
    </div>
  `;
}

// ── Flow summary (Resumo do mês) ──────────────────────────────────────────────

function renderFlowSummary(capacityData, cashflowData, month) {
  const section     = document.getElementById('monthly-flow-section');
  const container   = document.getElementById('monthly-flow');
  const periodLabel = document.getElementById('monthly-flow-period');
  if (!section || !container) return;

  const previousKey    = previousMonthKey(month);
  const current        = findMonth(cashflowData?.months, month) || {};
  const previous       = findMonth(cashflowData?.months, previousKey);

  const receivedIncome = capacityData.bank_inflows_total ?? current.income ?? 0;
  const expectedIncome = capacityData.expected_income_total ?? 0;
  const toReceive      = capacityData.income_to_receive ?? 0;
  const receivedHelp   = current.income_count > 0
    ? pluralRecebimentos(current.income_count)
    : 'Entradas bancárias reais';

  const fixedCostActual   = capacityData.fixed_cost_actual_total  || 0;
  const fixedCostPending  = capacityData.fixed_cost_pending_total || 0;
  const fixedCostVariance = capacityData.fixed_cost_variance_total || 0;
  const fixedCostCount    = capacityData.fixed_costs?.entries?.length || 0;
  const fixedCostSubtext  = [
    `${fixedCostCount} itens`,
    `pago ${currency.format(fixedCostActual)}`,
    `pendente ${currency.format(fixedCostPending)}`,
    ...(fixedCostVariance > 0 ? [`acima ${currency.format(fixedCostVariance)}`] : []),
  ].join(' · ');

  const variableBudgetTotal = capacityData.variable_budget_total ?? 0;
  const variableConsumed    = (capacityData.variable_budget_consumed || 0)
    + (capacityData.variable_budget_overage || 0)
    + (capacityData.unbudgeted_variable_spent || 0);
  const unbudgeted = capacityData.unbudgeted_variable_spent || 0;
  const overage    = capacityData.variable_budget_overage  || 0;
  const variableParts = [];
  if (variableBudgetTotal > 0) variableParts.push(`meta ${currency.format(variableBudgetTotal)}`);
  if (unbudgeted > 0) variableParts.push(`sem orçamento ${currency.format(unbudgeted)}`);
  if (overage > 0) variableParts.push(`estouro ${currency.format(overage)}`);
  const variableSubtext = variableParts.length > 0 ? variableParts.join(' · ') : 'sem meta configurada';

  if (periodLabel) periodLabel.textContent = formatMonthLabel(month);

  // Row 1 — Entradas, Saídas, A receber (3 cols)
  const row1 = [
    flowCard({ label: 'Entradas',         icon: '💰', value: receivedIncome,                   prev: previous?.income,  countLabel: receivedHelp,                                              tint: 'emerald', higherIsBetter: true  }),
    flowCard({ label: 'Saídas',           icon: '↗',  value: current.outflow || 0,              prev: previous?.outflow, countLabel: pluralSaidas(current.outflow_count || 0),                  tint: 'red',    higherIsBetter: false }),
    flowCard({ label: 'A receber',        icon: '⏳', value: toReceive,                                                  countLabel: `Receita esperada ${currency.format(expectedIncome)}`,     tint: 'slate'  }),
  ].join('');

  // Row 2 — Custos fixos, Variável usado (2 cols)
  const row2 = [
    flowCard({ label: 'Custos fixos',     icon: '📌', value: capacityData.fixed_cost_reserved_total || 0,               countLabel: fixedCostSubtext,                                          tint: 'red',    higherIsBetter: false }),
    flowCard({ label: 'Variável usado',   icon: '🧾', value: variableConsumed,                                           countLabel: variableSubtext,                                           tint: 'orange', higherIsBetter: false }),
  ].join('');

  container.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">${row1}</div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">${row2}</div>
  `;
  section.classList.remove('hidden');

  renderCashflowWidget(current);
}

// ── Cashflow widget (Entradas e saídas) ───────────────────────────────────────

function cashflowTransactionRow(tx, tint) {
  const amount     = Math.abs(Number(tx.amount) || 0);
  const amountColor = tint === 'emerald' ? 'text-emerald-700' : 'text-red-700';
  const sign       = tint === 'emerald' ? '+' : '−';
  return `
    <li class="flex items-center justify-between gap-3 px-4 py-3 border-t border-slate-100 first:border-t-0">
      <div class="min-w-0 flex-1 pr-4">
        <p class="text-sm font-medium text-slate-900 truncate">${escapeHtml(tx.description || 'Sem descrição')}</p>
        <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}${tx.account_name ? ` · ${escapeHtml(tx.account_name)}` : ''}</p>
      </div>
      <p class="text-sm font-semibold tabular shrink-0 ${amountColor}">${sign}${currency.format(amount)}</p>
    </li>
  `;
}

function cashflowListCard({ title, total, count, transactions, tint, emptyText }) {
  const tintClasses = tint === 'emerald'
    ? { value: 'text-emerald-700', dot: 'bg-emerald-500' }
    : { value: 'text-red-700',     dot: 'bg-red-500'     };
  const visible        = transactions.slice(0, CASHFLOW_CARD_INITIAL_ROWS);
  const hiddenTxs      = transactions.slice(CASHFLOW_CARD_INITIAL_ROWS);
  const visibleRows    = visible.map((tx) => cashflowTransactionRow(tx, tint)).join('');
  const hiddenRows     = hiddenTxs.map((tx) => cashflowTransactionRow(tx, tint)).join('');
  const totalText      = currency.format(total || 0);
  const countText      = count === 1 ? '1 transação' : `${count.toLocaleString('pt-BR')} transações`;
  const totalForLabel  = transactions.length.toLocaleString('pt-BR');
  return `
    <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div class="px-4 py-4 flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <span class="size-2 rounded-full ${tintClasses.dot}"></span>
            <h3 class="font-semibold text-slate-900">${escapeHtml(title)}</h3>
          </div>
          <p class="text-xs text-slate-500 mt-1">${countText}</p>
        </div>
        <p class="font-bold tabular ${tintClasses.value}">${totalText}</p>
      </div>
      ${transactions.length > 0
        ? `<ul>${visibleRows}</ul>${hiddenTxs.length > 0
            ? `<ul class="cashflow-hidden hidden">${hiddenRows}</ul>
               <button type="button" class="cashflow-ver-todas w-full text-center text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-slate-50 py-3 border-t border-slate-100 transition-colors">
                 Ver todas as ${totalForLabel} ${transactions.length === 1 ? 'transação' : 'transações'}
               </button>`
            : ''}`
        : `<p class="px-4 py-5 border-t border-slate-100 text-sm text-slate-500">${escapeHtml(emptyText)}</p>`
      }
    </div>
  `;
}

function renderCashflowWidget(cashflowMonth) {
  const section   = document.getElementById('cashflow-widget-section');
  const container = document.getElementById('cashflow-widget');
  if (!section || !container) return;

  const transactions = Array.isArray(cashflowMonth?.transactions) ? cashflowMonth.transactions : [];
  const incomes  = transactions.filter((tx) => Number(tx.amount) > 0).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const outflows = transactions.filter((tx) => Number(tx.amount) < 0).sort((a, b) => String(b.date).localeCompare(String(a.date)));

  if (!incomes.length && !outflows.length) {
    container.innerHTML = '';
    section.classList.add('hidden');
    return;
  }

  container.innerHTML = [
    cashflowListCard({ title: 'Entradas', total: cashflowMonth.income || 0, count: cashflowMonth.income_count || incomes.length, transactions: incomes, tint: 'emerald', emptyText: 'Nenhuma entrada bancária neste mês.' }),
    cashflowListCard({ title: 'Saídas',   total: cashflowMonth.outflow || 0, count: cashflowMonth.outflow_count || outflows.length, transactions: outflows, tint: 'red', emptyText: 'Nenhuma saída bancária neste mês.' }),
  ].join('');
  section.classList.remove('hidden');

  container.querySelectorAll('button.cashflow-ver-todas').forEach((btn) => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.bg-white');
      const hiddenList = card?.querySelector('ul.cashflow-hidden');
      if (hiddenList) hiddenList.classList.remove('hidden');
      btn.remove();
    });
  });
}

// ── Category bars & accordion ─────────────────────────────────────────────────

let availableCategories    = [];
let transactionsById       = new Map();
let activeFixedCostTx      = null;

function groupTransactionsByCategoryId(transactions) {
  const groups = new Map();
  for (const tx of transactions) {
    const key = tx.custom_category_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(tx);
  }
  return groups;
}

function categorySummariesFromTransactions(transactions) {
  const categoriesById = new Map(availableCategories.map((cat) => [cat.id, cat]));
  const groups         = groupTransactionsByCategoryId(transactions);
  const summaries      = Array.from(groups.entries()).map(([categoryId, txs]) => {
    const known   = categoriesById.get(categoryId);
    const fallback = txs[0] || {};
    const total   = txs.reduce((sum, tx) => sum + Math.abs(Number(tx.amount) || 0), 0);
    return {
      id: categoryId,
      name: known?.name || fallback.custom_category_name || 'Sem categoria',
      color: known?.color || fallback.custom_category_color || FALLBACK_COLOR,
      sort_order: known?.sort_order ?? 999,
      total,
      count: txs.length,
      transactions: txs,
    };
  });
  return summaries.sort(
    (a, b) => a.sort_order - b.sort_order || Math.abs(b.total) - Math.abs(a.total) || a.name.localeCompare(b.name),
  );
}

function renderCategoryBars(categories, totalSpent) {
  const container = document.getElementById('category-bars');
  if (!container) return;
  if (!categories.length) { container.innerHTML = ''; return; }
  const max = categories.reduce((m, c) => Math.max(m, c.total), 0) || 1;
  container.innerHTML = categories.map((cat) => {
    const pct        = Math.round((cat.total / max) * 100);
    const pctOfTotal = totalSpent > 0 ? ((cat.total / totalSpent) * 100).toFixed(1) : '0.0';
    const color      = cat.color || FALLBACK_COLOR;
    return `
      <div class="flex items-center gap-3">
        <div class="w-28 shrink-0 flex items-center gap-2 min-w-0">
          <span class="text-sm leading-none">${categoryIcon(cat.name)}</span>
          <span class="text-sm text-slate-700 font-medium truncate">${escapeHtml(cat.name)}</span>
        </div>
        <div class="flex-1 h-8 rounded-xl bg-slate-100 overflow-hidden">
          <div class="bar-fill h-full rounded-xl flex items-center" style="width:${pct}%;background:${color};min-width:${cat.total > 0 ? '2.5rem' : '0'}">
            <span class="text-white text-xs font-bold tabular px-2.5 truncate">${currency.format(cat.total)}</span>
          </div>
        </div>
        <span class="text-xs text-slate-400 tabular w-10 text-right shrink-0">${pctOfTotal}%</span>
      </div>
    `;
  }).join('');
}

function txAmountHtml(tx) {
  return `<p class="text-sm font-medium tabular text-slate-900">${currency.format(Math.abs(Number(tx.amount) || 0))}</p>`;
}

function renderCategories(transactions) {
  const container = document.getElementById('categories');
  const emptyEl   = document.getElementById('categories-empty');
  transactionsById = new Map(transactions.map((tx) => [tx.id, tx]));

  if (!transactions.length) {
    container.innerHTML = '';
    emptyEl?.classList.remove('hidden');
    return;
  }
  emptyEl?.classList.add('hidden');

  const ordered = categorySummariesFromTransactions(transactions);

  const renderTxRow = (tx) => `
    <li class="flex items-center justify-between gap-3 px-5 py-3 border-t border-slate-100">
      <div class="min-w-0 flex-1 pr-4">
        <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
        <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
      </div>
      <div class="flex items-center gap-3 shrink-0">
        ${txAmountHtml(tx)}
        <button type="button" class="match-fixed-cost size-8 inline-flex items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-900"
          data-tx-id="${escapeHtml(tx.id)}" title="Vincular a custo fixo">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L7.5 16.5 3.75 12.75"/>
            <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 4.5l-3 3"/>
          </svg>
        </button>
        <button type="button" class="categorize-tx size-8 inline-flex items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-900"
          data-tx-id="${escapeHtml(tx.id)}" title="Alterar categoria">
          <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z"/>
          </svg>
        </button>
      </div>
    </li>
  `;

  const html = ordered.map((cat) => {
    const txs        = cat.transactions || [];
    const color      = cat.color || FALLBACK_COLOR;
    const visible    = txs.slice(0, TX_PER_CATEGORY_INITIAL);
    const hiddenTxs  = txs.slice(TX_PER_CATEGORY_INITIAL);
    const visibleRows = visible.map(renderTxRow).join('');
    const hiddenRows  = hiddenTxs.map(renderTxRow).join('');
    const more        = hiddenTxs.length > 0
      ? `<ul class="tx-hidden hidden">${hiddenRows}</ul>
         <button class="ver-mais w-full text-center text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-slate-50 py-3 border-t border-slate-100">
           Ver mais ${hiddenTxs.length} ${hiddenTxs.length === 1 ? 'transação' : 'transações'}
         </button>`
      : '';
    return `
      <details class="rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <summary class="flex items-center gap-3 px-5 py-4 select-none cursor-pointer"
          style="background:linear-gradient(135deg,${hexWithAlpha(color, 0.12)} 0%,${hexWithAlpha(color, 0.05)} 100%)">
          <span class="chevron shrink-0" style="color:${color}">
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
            </svg>
          </span>
          <div class="size-9 rounded-xl flex items-center justify-center shrink-0 text-lg leading-none"
            style="background:${hexWithAlpha(color, 0.18)}">${categoryIcon(cat.name)}</div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-3">
              <span class="font-bold text-slate-900">${escapeHtml(cat.name)}</span>
              <span class="font-bold tabular shrink-0" style="color:${color}">${currency.format(cat.total)}</span>
            </div>
            <p class="text-xs text-slate-500 mt-1">${cat.count} ${transactionNoun(cat.count)}</p>
          </div>
        </summary>
        <ul class="bg-white">${visibleRows}</ul>
        ${more}
      </details>
    `;
  }).join('');

  container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 gap-3">${html}</div>`;

  container.querySelectorAll('details').forEach((det) => {
    det.addEventListener('toggle', () => { det.style.gridColumn = det.open ? '1 / -1' : ''; });
  });
  container.querySelectorAll('button.ver-mais').forEach((btn) => {
    btn.addEventListener('click', () => {
      const details = btn.closest('details');
      details?.querySelector('ul.tx-hidden')?.classList.remove('hidden');
      btn.remove();
    });
  });
  container.querySelectorAll('button.categorize-tx').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tx = transactionsById.get(btn.dataset.txId);
      if (tx) openCategoryModal(tx);
    });
  });
  container.querySelectorAll('button.match-fixed-cost').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tx = transactionsById.get(btn.dataset.txId);
      if (tx) openFixedCostMatchModal(tx);
    });
  });
}

// ── Category modal ────────────────────────────────────────────────────────────

function categoryOptionsHtml(selectedId) {
  return availableCategories.map((cat) => {
    const sel = Number(cat.id) === Number(selectedId) ? 'selected' : '';
    return `<option value="${cat.id}" ${sel}>${escapeHtml(cat.name)}</option>`;
  }).join('');
}

function openCategoryModal(tx) {
  if (!availableCategories.length) { showToast('Nenhuma categoria disponível.', 'error'); return; }
  document.getElementById('category-modal-description').textContent = tx.description;
  document.getElementById('category-rule-pattern').value = tx.description;
  document.getElementById('category-rule-category').innerHTML = categoryOptionsHtml(tx.custom_category_id);
  document.getElementById('category-modal').classList.remove('hidden');
  document.getElementById('category-rule-pattern').focus();
}

function closeCategoryModal() {
  document.getElementById('category-modal').classList.add('hidden');
}

async function saveCategoryRule(event) {
  event.preventDefault();
  const button    = event.currentTarget.querySelector('button[type="submit"]');
  const pattern   = document.getElementById('category-rule-pattern').value.trim();
  const categoryId = Number(document.getElementById('category-rule-category').value);
  if (!pattern || !categoryId) { showToast('Informe o texto e a categoria.', 'error'); return; }
  button.disabled = true;
  try {
    const res = await fetch('/category-rules/description', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pattern, category_id: categoryId }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Falha ao salvar regra (HTTP ${res.status})`);
    }
    const result = await res.json();
    closeCategoryModal();
    await loadData();
    showToast(`${result.affected_count} compra(s) movida(s) para ${result.category_name}.`, 'success');
  } catch (err) {
    showToast(err.message || 'Erro ao salvar regra.', 'error');
  } finally {
    button.disabled = false;
  }
}

// ── Fixed-cost match modal ─────────────────────────────────────────────────────

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

function fixedCostOptionsHtml(costs, txAmount) {
  return [...costs]
    .sort((a, b) => {
      const da = Math.abs((Number(a.amount) || 0) - txAmount);
      const db = Math.abs((Number(b.amount) || 0) - txAmount);
      return da - db || String(a.description).localeCompare(String(b.description));
    })
    .map((c) => `<option value="${c.id}">${escapeHtml(c.description)} · ${escapeHtml(c.category_name || 'Sem categoria')} · ${currency.format(Number(c.amount) || 0)}</option>`)
    .join('');
}

async function openFixedCostMatchModal(tx) {
  activeFixedCostTx = tx;
  const modal  = document.getElementById('fixed-cost-match-modal');
  const select = document.getElementById('fixed-cost-match-cost');
  const amount = Math.abs(Number(tx.amount) || 0);

  document.getElementById('fixed-cost-match-description').textContent = tx.description;
  document.getElementById('fixed-cost-match-amount').textContent      = currency.format(amount);
  document.getElementById('fixed-cost-match-date').textContent        = `${formatDayLabel(tx.date)} · ${yearMonthFromIso(tx.date)}`;
  select.innerHTML = '<option>Carregando…</option>';
  modal.classList.remove('hidden');

  try {
    const costs = await fetchJson('/fixed-costs');
    if (!Array.isArray(costs) || !costs.length) {
      select.innerHTML = '<option value="">Nenhum custo fixo ativo</option>';
      showToast('Cadastre um custo fixo antes de vincular.', 'error');
      return;
    }
    select.innerHTML = fixedCostOptionsHtml(costs, amount);
    select.focus();
  } catch (err) {
    select.innerHTML = '<option value="">Erro ao carregar custos</option>';
    showToast('Erro ao carregar custos fixos.', 'error');
  }
}

function closeFixedCostMatchModal() {
  document.getElementById('fixed-cost-match-modal').classList.add('hidden');
  activeFixedCostTx = null;
}

async function saveFixedCostMatch(event) {
  event.preventDefault();
  const button      = event.currentTarget.querySelector('button[type="submit"]');
  const fixedCostId = Number(document.getElementById('fixed-cost-match-cost').value);
  if (!activeFixedCostTx || !fixedCostId) { showToast('Selecione um custo fixo.', 'error'); return; }
  button.disabled = true;
  try {
    await fetchJson(`/fixed-costs/${fixedCostId}/matches`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ transaction_id: activeFixedCostTx.id, year_month: yearMonthFromIso(activeFixedCostTx.date) }),
    });
    closeFixedCostMatchModal();
    await loadData();
    showToast('Transação vinculada ao custo fixo.', 'success');
  } catch (err) {
    showToast(err.message || 'Erro ao vincular custo fixo.', 'error');
  } finally {
    button.disabled = false;
  }
}

// ── Sync health ───────────────────────────────────────────────────────────────

async function loadSyncHealth(expectedVersion) {
  const section = document.getElementById('sync-health');
  if (!section) return;
  try {
    const res = await fetch('/sync/health');
    if (expectedVersion !== loadVersion) return;
    if (!res.ok) return;
    const items = await res.json();
    if (expectedVersion !== loadVersion) return;
    const noteworthy = (items || []).filter(
      (it) => it.is_running || it.last_sync_error || (it.failed_accounts || []).length > 0,
    );
    if (!noteworthy.length) { section.classList.add('hidden'); section.innerHTML = ''; return; }
    const cards = noteworthy.map((it) => {
      const variant = it.is_running
        ? { bg: 'bg-indigo-50', border: 'border-indigo-200', text: 'text-indigo-900', tag: 'Sincronizando' }
        : { bg: 'bg-amber-50',  border: 'border-amber-200',  text: 'text-amber-900',  tag: 'Atenção' };
      const errs = (it.failed_accounts || []).map((a) =>
        `<li><span class="font-medium">${escapeHtml(a.account_id)}:</span> ${escapeHtml(a.error || '')}</li>`
      ).join('');
      return `
        <div class="rounded-2xl ${variant.bg} border ${variant.border} px-5 py-4">
          <div class="flex items-center gap-3">
            <span class="text-xs font-semibold uppercase tracking-wider ${variant.text}">${variant.tag}</span>
            <span class="font-medium ${variant.text}">${escapeHtml(it.connector_name || it.item_id)}</span>
          </div>
          ${it.last_sync_error ? `<p class="mt-1 text-xs ${variant.text}/80">${escapeHtml(it.last_sync_error)}</p>` : ''}
          ${errs ? `<ul class="mt-2 space-y-1 text-xs ${variant.text}/80">${errs}</ul>` : ''}
        </div>`;
    });
    section.innerHTML = `<div class="space-y-3">${cards.join('')}</div>`;
    section.classList.remove('hidden');
  } catch (err) {
    console.error('sync health failed', err);
  }
}

// ── Connect bank ──────────────────────────────────────────────────────────────

async function openConnectWidget() {
  const button = document.getElementById('connect');
  button.disabled = true;
  try {
    const tokenRes = await fetch('/connect-token', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!tokenRes.ok) throw new Error(`Falha ao obter token (HTTP ${tokenRes.status}). Verifique suas credenciais Pluggy no .env.`);
    const { accessToken } = await tokenRes.json();
    if (typeof PluggyConnect === 'undefined') throw new Error('Script do Pluggy Connect não carregou. Verifique sua conexão.');

    const widget = new PluggyConnect({
      connectToken: accessToken,
      includeSandbox: false,
      language: 'pt',
      countries: ['BR'],
      connectorIds: [200],
      onSuccess: async (data) => {
        const itemId = data?.item?.id;
        if (!itemId) { showToast('Conexão completa mas itemId ausente.', 'error'); return; }
        showToast('Conectado! Sincronizando…');
        try {
          await fetch(`/items/${itemId}`, { method: 'POST' });
          const sync = await fetch(`/items/${itemId}/sync`, { method: 'POST' });
          if (sync.status === 409) { showToast('Sincronização já em andamento para este item.', 'info'); return; }
          const result = await sync.json();
          await loadData();
          const failed = (result.failed_accounts || []).length;
          showToast(failed > 0 ? `Sincronizado (${failed} conta(s) com erro).` : 'Sincronizado com sucesso.', failed > 0 ? 'info' : 'success');
        } catch (err) {
          showToast('Erro ao sincronizar.', 'error');
        }
      },
      onError: (error) => { showToast(`Erro: ${error?.message || 'desconhecido'}`, 'error'); },
    });
    widget.init();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    button.disabled = false;
  }
}

// ── Main load ─────────────────────────────────────────────────────────────────

async function loadData() {
  const myVersion = ++loadVersion;
  const month     = currentYearMonth();
  const { from, to } = rangeForCurrentMonth();
  document.getElementById('subtitle').textContent = 'Atualizando…';

  loadSyncHealth(myVersion);

  try {
    const qs = `?from_date=${from}&to_date=${to}`;
    const [capacityRes, cashflowRes, statsRes, txRes, categoriesRes] = await Promise.all([
      fetch(`/spending-capacity?year_month=${month}`),
      fetch('/bank-cashflow/monthly?months=12'),
      fetch(`/stats${qs}`),
      fetch(`/transactions${qs}`),
      fetch('/categories'),
    ]);
    if (myVersion !== loadVersion) return;

    const capacityData  = capacityRes.ok   ? await capacityRes.json()   : null;
    const cashflowData  = cashflowRes.ok   ? await cashflowRes.json()   : null;
    const stats         = statsRes.ok      ? await statsRes.json()      : null;
    const transactions  = txRes.ok         ? await txRes.json()         : [];
    availableCategories = categoriesRes.ok ? await categoriesRes.json() : [];
    if (myVersion !== loadVersion) return;

    const planningSection = document.getElementById('planning-card');
    if (capacityData && planningSection) {
      renderPlanning(planningSection, capacityData, month);
      renderInvoiceCard(capacityData, month);
      renderFlowSummary(capacityData, cashflowData || { months: [] }, month);
    }

    const chartPanel = document.getElementById('category-chart-panel');
    if (stats?.categories?.length) {
      chartPanel?.classList.remove('hidden');
      renderCategoryBars(stats.categories, stats.total_spent || 0);
    } else {
      chartPanel?.classList.add('hidden');
    }

    renderCategories(Array.isArray(transactions) ? transactions : []);

    const txCount = stats?.transaction_count ?? 0;
    document.getElementById('subtitle').textContent = txCount > 0
      ? `${txCount} compras em ${stats.categories?.length || 0} categoria${(stats.categories?.length || 0) === 1 ? '' : 's'}`
      : new Date().toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });

    const hasData = capacityData || stats || transactions.length > 0;
    document.getElementById('empty-state')?.classList.toggle('hidden', !!hasData);

  } catch (err) {
    console.error('loadData failed:', err);
    if (myVersion === loadVersion) {
      document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
      showToast(err.message || 'Erro ao carregar dados.', 'error');
    }
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────

document.getElementById('refresh').addEventListener('click', () => {
  loadData().catch((err) => { document.getElementById('subtitle').textContent = 'Erro ao carregar dados'; });
});
document.getElementById('connect').addEventListener('click', openConnectWidget);

document.getElementById('category-rule-form').addEventListener('submit', saveCategoryRule);
document.getElementById('category-modal-close').addEventListener('click', closeCategoryModal);
document.getElementById('category-modal-cancel').addEventListener('click', closeCategoryModal);
document.getElementById('category-modal').addEventListener('click', (e) => {
  if (e.target.id === 'category-modal') closeCategoryModal();
});
document.getElementById('fixed-cost-match-form').addEventListener('submit', saveFixedCostMatch);
document.getElementById('fixed-cost-match-close').addEventListener('click', closeFixedCostMatchModal);
document.getElementById('fixed-cost-match-cancel').addEventListener('click', closeFixedCostMatchModal);
document.getElementById('fixed-cost-match-modal').addEventListener('click', (e) => {
  if (e.target.id === 'fixed-cost-match-modal') closeFixedCostMatchModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeCategoryModal(); closeFixedCostMatchModal(); }
});

loadData().catch((err) => {
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
