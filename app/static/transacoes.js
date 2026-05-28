// Fallback color if a category somehow arrives without one (shouldn't happen
// once seed_categories.py has been run).
const FALLBACK_COLOR = '#64748b';

function hexWithAlpha(hex, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
}

function categoryIcon(name) {
  const key = String(name).toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '');
  const icons = {
    mercado:        '🛒',
    restaurantes:   '🍽️',
    transporte:     '🚗',
    saude:          '🩺',
    pets:           '🐾',
    casa:           '🏠',
    lazer:          '🎮',
    assinaturas:    '📺',
    educacao:       '📚',
    transferencias: '🔁',
    outros:         '📦',
  };
  return icons[key] ?? '💳';
}
// Most users only care about the recent transactions. Render the first N
// inside each category accordion; the rest stays one click away.
const TX_PER_CATEGORY_INITIAL = 50;

const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
});

const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
});

let monthChart = null;
let availableCategories = [];
let transactionsById = new Map();
let activeFixedCostTransaction = null;

function formatMonthLabel(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthFormatter.format(new Date(year, month - 1, 1));
}

function formatDayLabel(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return dayFormatter.format(new Date(year, month - 1, day));
}

function yearMonthFromIso(isoDate) {
  return String(isoDate || '').slice(0, 7);
}

function groupTransactionsByCategoryId(transactions) {
  // Groups by custom_category_id (the resolved category from the backend),
  // not by tx.category which is Pluggy's raw English string.
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
  const groups = groupTransactionsByCategoryId(transactions);
  const summaries = Array.from(groups.entries()).map(([categoryId, txs]) => {
    const known = categoriesById.get(categoryId);
    const fallback = txs[0] || {};
    const total = txs.reduce(
      (sum, tx) => sum + Math.abs(Number(tx.amount) || 0),
      0,
    );
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

  // Stable order — uses the curated sort_order from the categories table so
  // categories don't reshuffle when the period changes.
  // Falls back to abs-total for ties (categories without a sort_order).
  return summaries.sort(
    (a, b) =>
      a.sort_order - b.sort_order ||
      Math.abs(b.total) - Math.abs(a.total) ||
      a.name.localeCompare(b.name),
  );
}

function accordionHeaderHtml(cat, color) {
  return `
    <div class="flex items-center justify-between gap-3">
      <span class="font-bold text-slate-900">${escapeHtml(cat.name)}</span>
      <span class="font-bold tabular shrink-0" style="color:${color}">${currency.format(cat.total)}</span>
    </div>
    <p class="text-xs text-slate-500 mt-1">${cat.count} ${transactionNoun(cat.count)}</p>
  `;
}

function transactionNoun(count) {
  return count === 1 ? 'compra' : 'compras';
}

function transactionAmountHtml(tx) {
  const amount = Number(tx.amount) || 0;
  return `
    <p class="text-sm font-medium tabular text-slate-900">
      ${currency.format(Math.abs(amount))}
    </p>
  `;
}

// ── Monthly overview strip ──────────────────────────────────────────────
//
// Follows the selected dashboard period. The home intentionally supports
// only the current month and the previous month, so this summary remains a
// focused monthly snapshot instead of becoming another history screen.

const FLOW_TINTS = {
  emerald: { text: 'text-emerald-700', iconBg: 'bg-emerald-100' },
  orange:  { text: 'text-orange-700',  iconBg: 'bg-orange-100' },
  red:     { text: 'text-red-700',     iconBg: 'bg-red-100' },
  slate:   { text: 'text-slate-700',   iconBg: 'bg-slate-100' },
};

function flowDelta(curr, prev, higherIsBetter) {
  // Returns a small "vs previous month" badge. Skipped when there is no
  // previous baseline (first month of data) or the previous value is zero
  // (avoids "+Infinity%" noise).
  if (prev === null || prev === undefined || prev === 0) return '';
  const diff = curr - prev;
  if (diff === 0) return '<span class="text-slate-400">igual ao mês anterior</span>';
  const pct = (diff / Math.abs(prev)) * 100;
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
  const delta = flowDelta(value, prev, higherIsBetter);
  const detail = countLabel
    ? `<span class="text-slate-500">${escapeHtml(countLabel)}</span>`
    : help
      ? `<span class="text-slate-500">${escapeHtml(help)}</span>`
      : '<span></span>';
  const footer = isNet
    ? (help ? `<span class="text-slate-500">${escapeHtml(help)}</span>` : '<span></span>')
    : `${detail}${delta ? ` <span class="ml-auto">${delta}</span>` : ''}`;
  return `
    <div class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
      <div class="flex items-center justify-between gap-2 mb-3">
        <span class="text-xs font-medium uppercase tracking-wider text-slate-500">${escapeHtml(label)}</span>
        <span class="size-8 rounded-xl ${c.iconBg} flex items-center justify-center text-base leading-none">${icon}</span>
      </div>
      <p class="text-2xl font-bold tabular ${c.text}">${escapeHtml(formatted)}</p>
      <div class="mt-3 flex items-center gap-2 text-xs">
        ${footer}
      </div>
    </div>
  `;
}

function pluralRecebimentos(n) {
  return n === 1 ? '1 recebimento' : `${n.toLocaleString('pt-BR')} recebimentos`;
}

function pluralSaidas(n) {
  return n === 1 ? '1 saída' : `${n.toLocaleString('pt-BR')} saídas`;
}

function pluralCompras(n) {
  return n === 1 ? '1 compra' : `${n.toLocaleString('pt-BR')} compras`;
}

function planStatusLabel(status) {
  const labels = {
    healthy: 'saudável',
    tight: 'apertado',
    over: 'estourado',
    unknown: 'sem receita',
  };
  return labels[status] || 'sem status';
}

function monthKeyForDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

function monthKeyForPeriod(period) {
  const today = new Date();
  if (period === 'prev_month') {
    return monthKeyForDate(new Date(today.getFullYear(), today.getMonth() - 1, 1));
  }
  return monthKeyForDate(new Date(today.getFullYear(), today.getMonth(), 1));
}

function previousMonthKey(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthKeyForDate(new Date(year, month - 2, 1));
}

function findMonth(months, key) {
  return Array.isArray(months) ? months.find((m) => m.month === key) : null;
}

function cashflowTransactionRow(tx, tint) {
  const amount = Math.abs(Number(tx.amount) || 0);
  const amountColor = tint === 'emerald' ? 'text-emerald-700' : 'text-red-700';
  const sign = tint === 'emerald' ? '+' : '−';
  return `
    <li class="flex items-center justify-between gap-3 px-4 py-3 border-t border-slate-100 first:border-t-0">
      <div class="min-w-0 flex-1 pr-4">
        <p class="text-sm font-medium text-slate-900 truncate">${escapeHtml(tx.description || 'Sem descrição')}</p>
        <p class="text-xs text-slate-500 mt-0.5">
          ${formatDayLabel(tx.date)}${tx.account_name ? ` · ${escapeHtml(tx.account_name)}` : ''}
        </p>
      </div>
      <p class="text-sm font-semibold tabular shrink-0 ${amountColor}">
        ${sign}${currency.format(amount)}
      </p>
    </li>
  `;
}

// Initial row cap on each dashboard cash-flow card. Anything beyond this is
// rendered into a hidden <ul> that the "Ver todas" button reveals in place —
// same pattern the category accordion already uses, so the interaction feels
// consistent across the dashboard.
const CASHFLOW_CARD_INITIAL_ROWS = 8;

function cashflowListCard({ title, total, count, transactions, tint, emptyText }) {
  const tintClasses = tint === 'emerald'
    ? { value: 'text-emerald-700', dot: 'bg-emerald-500' }
    : { value: 'text-red-700', dot: 'bg-red-500' };
  const visible = transactions.slice(0, CASHFLOW_CARD_INITIAL_ROWS);
  const hidden = transactions.slice(CASHFLOW_CARD_INITIAL_ROWS);
  const visibleRows = visible.map((tx) => cashflowTransactionRow(tx, tint)).join('');
  const hiddenRows = hidden.map((tx) => cashflowTransactionRow(tx, tint)).join('');
  const totalText = currency.format(total || 0);
  const countText = count === 1 ? '1 transação' : `${count.toLocaleString('pt-BR')} transações`;
  const totalCountForLabel = transactions.length.toLocaleString('pt-BR');
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
      ${
        transactions.length > 0
          ? `<ul>${visibleRows}</ul>${
              hidden.length > 0
                ? `<ul class="cashflow-hidden hidden">${hiddenRows}</ul>
                   <button
                     type="button"
                     class="cashflow-ver-todas w-full text-center text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-slate-50 py-3 border-t border-slate-100 transition-colors"
                     data-count="${hidden.length}"
                   >
                     Ver todas as ${totalCountForLabel} ${transactions.length === 1 ? 'transação' : 'transações'}
                   </button>`
                : ''
            }`
          : `<p class="px-4 py-5 border-t border-slate-100 text-sm text-slate-500">${escapeHtml(emptyText)}</p>`
      }
    </div>
  `;
}

function renderCashflowWidget(cashflowMonth) {
  const section = document.getElementById('cashflow-widget-section');
  const container = document.getElementById('cashflow-widget');
  if (!section || !container) return;

  const transactions = Array.isArray(cashflowMonth?.transactions)
    ? cashflowMonth.transactions
    : [];
  const incomes = transactions
    .filter((tx) => Number(tx.amount) > 0)
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const outflows = transactions
    .filter((tx) => Number(tx.amount) < 0)
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));

  const hasActivity = incomes.length > 0 || outflows.length > 0;
  if (!hasActivity) {
    container.innerHTML = '';
    section.classList.add('hidden');
    return;
  }

  container.innerHTML = [
    cashflowListCard({
      title: 'Entradas',
      total: cashflowMonth.income || 0,
      count: cashflowMonth.income_count || incomes.length,
      transactions: incomes,
      tint: 'emerald',
      emptyText: 'Nenhuma entrada bancária neste mês.',
    }),
    cashflowListCard({
      title: 'Saídas',
      total: cashflowMonth.outflow || 0,
      count: cashflowMonth.outflow_count || outflows.length,
      transactions: outflows,
      tint: 'red',
      emptyText: 'Nenhuma saída bancária neste mês.',
    }),
  ].join('');
  section.classList.remove('hidden');

  // Click handler for "Ver todas as N transações" — reveals the hidden list
  // and removes the button (same one-shot expand pattern as the category
  // accordion, no collapse-back needed).
  container.querySelectorAll('button.cashflow-ver-todas').forEach((btn) => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.bg-white');
      const hidden = card && card.querySelector('ul.cashflow-hidden');
      if (hidden) hidden.classList.remove('hidden');
      btn.remove();
    });
  });
}

function hideCashflowWidget() {
  const section = document.getElementById('cashflow-widget-section');
  const container = document.getElementById('cashflow-widget');
  if (container) container.innerHTML = '';
  if (section) section.classList.add('hidden');
}

function renderMonthlyFlow(cashflowData, balanceData, capacityData, selectedMonth) {
  const section = document.getElementById('monthly-flow-section');
  const container = document.getElementById('monthly-flow');
  const periodLabel = document.getElementById('monthly-flow-period');
  if (
    !cashflowData ||
    !Array.isArray(cashflowData.months) ||
    cashflowData.months.length === 0 ||
    !balanceData ||
    !Array.isArray(balanceData.months) ||
    !capacityData
  ) {
    section.classList.add('hidden');
    hideCashflowWidget();
    return;
  }
  const previousKey = previousMonthKey(selectedMonth);
  const current = findMonth(cashflowData.months, selectedMonth) || {};
  const previous = findMonth(cashflowData.months, previousKey);
  const balanceCurrent = findMonth(balanceData.months, selectedMonth) || {};
  const balancePrevious = findMonth(balanceData.months, previousKey);
  const inv = invoiceValueFromCapacity(capacityData, balanceCurrent.card_spend);
  const budgetAvailableToSpend = capacityData.budget_available_to_spend ?? capacityData.discretionary_available ?? capacityData.available_to_spend ?? 0;
  const dailyAvailable = capacityData.daily_discretionary_remaining ?? null;
  const variableBudgetTotal = capacityData.variable_budget_total ?? capacityData.planned_variable_total ?? 0;
  const variableConsumed = (capacityData.variable_budget_consumed || 0) +
    (capacityData.variable_budget_overage || 0) +
    (capacityData.unbudgeted_variable_spent || 0);
  const expectedIncome = capacityData.expected_income_total ?? capacityData.receita_esperada ?? 0;
  const receivedIncome = capacityData.received_income_total ?? capacityData.valor_recebido ?? current.income ?? 0;
  const receivedHelp = expectedIncome > 0
    ? `de ${currency.format(expectedIncome)} esperados`
    : pluralRecebimentos(current.income_count || capacityData.received_income_count || 0);
  const dailyHelp = dailyAvailable === null
    ? planStatusLabel(capacityData.plan_status)
    : `${planStatusLabel(capacityData.plan_status)} · ${currency.format(dailyAvailable)}/dia`;

  const fixedCostActual = capacityData.fixed_cost_actual_total || 0;
  const fixedCostPending = capacityData.fixed_cost_pending_total || 0;
  const fixedCostVariance = capacityData.fixed_cost_variance_total || 0;
  const fixedCostCount = capacityData.fixed_costs?.entries?.length || 0;
  const fixedCostSubtext = [
    `${fixedCostCount} itens`,
    `pago ${currency.format(fixedCostActual)}`,
    `pendente ${currency.format(fixedCostPending)}`,
    ...(fixedCostVariance > 0 ? [`acima ${currency.format(fixedCostVariance)}`] : []),
    ...(fixedCostVariance < 0 ? [`abaixo ${currency.format(Math.abs(fixedCostVariance))}`] : []),
  ].join(' · ');

  const reserveTarget = capacityData.reserve_target_total || 0;
  const reserveApplied = capacityData.reserve_applied_total || 0;
  const reservePending = capacityData.reserve_pending_total || 0;
  const reserveOver = capacityData.reserve_over_applied_total || 0;
  let reserveSubtext;
  if (reserveTarget === 0 && reserveApplied === 0) {
    reserveSubtext = 'sem meta/aplicação no mês';
  } else {
    const parts = [`meta ${currency.format(reserveTarget)} · aplicado ${currency.format(reserveApplied)}`];
    if (reservePending > 0) parts.push(`falta ${currency.format(reservePending)}`);
    if (reserveOver > 0) parts.push(`acima ${currency.format(reserveOver)}`);
    reserveSubtext = parts.join(' · ');
  }

  const variableParts = [];
  if (variableBudgetTotal > 0) variableParts.push(`meta ${currency.format(variableBudgetTotal)}`);
  const unbudgeted = capacityData.unbudgeted_variable_spent || 0;
  const overage = capacityData.variable_budget_overage || 0;
  if (unbudgeted > 0) variableParts.push(`sem orçamento ${currency.format(unbudgeted)}`);
  if (overage > 0) variableParts.push(`estouro ${currency.format(overage)}`);
  const variableSubtext = variableParts.length > 0 ? variableParts.join(' · ') : 'sem meta configurada';

  periodLabel.textContent = formatMonthLabel(selectedMonth);

  container.innerHTML = [
    flowCard({
      label: 'Recebido',
      icon: '💰',
      value: receivedIncome,
      prev: previous ? previous.income : null,
      countLabel: receivedHelp,
      tint: 'emerald',
      higherIsBetter: true,
    }),
    flowCard({
      label: 'Saídas bancárias',
      icon: '↗',
      value: current.outflow || 0,
      prev: previous ? previous.outflow : null,
      countLabel: pluralSaidas(current.outflow_count || 0),
      tint: 'red',
      higherIsBetter: false,
    }),
    flowCard({
      label: 'Fatura real',
      icon: '💳',
      value: inv.value,
      prev: balancePrevious ? balancePrevious.card_spend : null,
      countLabel: inv.cardSubtext
        ?? pluralCompras(capacityData.invoice_gross_count || balanceCurrent.card_spend_count || 0),
      tint: 'orange',
      higherIsBetter: false,
    }),
    flowCard({
      label: 'Custos fixos',
      icon: '📌',
      value: capacityData.fixed_cost_reserved_total || 0,
      countLabel: fixedCostSubtext,
      tint: 'red',
      higherIsBetter: false,
    }),
    flowCard({
      label: 'Variável usado',
      icon: '🧾',
      value: variableConsumed,
      countLabel: variableSubtext,
      tint: 'orange',
      higherIsBetter: false,
    }),
    flowCard({
      label: 'Reserva',
      icon: '🏦',
      value: capacityData.reserve_reserved_total || 0,
      countLabel: reserveSubtext,
      tint: 'slate',
      higherIsBetter: true,
    }),
    flowCard({
      label: 'Pode gastar',
      icon: '📌',
      value: budgetAvailableToSpend,
      help: dailyHelp,
      tint: budgetAvailableToSpend >= 0 ? 'emerald' : 'red',
      higherIsBetter: true,
      isNet: true,
    }),
  ].join('');

  renderCashflowWidget(current);
  section.classList.remove('hidden');
}

async function loadMonthlyFlow(expectedVersion) {
  // Loaded independently from the main stats fetch so a failure here can't
  // take down the rest of the dashboard.
  const selectedMonth = monthKeyForPeriod(activePeriod);
  try {
    const [cashflowResponse, balanceResponse, capacityResponse] = await Promise.all([
      fetch('/bank-cashflow/monthly?months=12'),
      fetch('/monthly-balance?months=12'),
      fetch(`/spending-capacity?year_month=${selectedMonth}`),
    ]);
    if (expectedVersion !== loadVersion) return;
    if (!cashflowResponse.ok || !balanceResponse.ok || !capacityResponse.ok) {
      hideCashflowWidget();
      return;
    }
    const cashflowData = await cashflowResponse.json();
    const balanceData = await balanceResponse.json();
    const capacityData = await capacityResponse.json();
    if (expectedVersion !== loadVersion) return;
    renderMonthlyFlow(cashflowData, balanceData, capacityData, selectedMonth);
    updateHeroFromCapacity(capacityData);
  } catch (err) {
    console.error('monthly flow load failed:', err);
  }
}

function renderSummary(stats) {
  const {
    total_spent,
    transaction_count,
    categories,
    invoice_mode = 'open',
    invoice_total = 0,
    invoice_count = 0,
    invoice_gross_total = invoice_total,
    invoice_gross_count = invoice_count,
    invoice_since = null,
    invoice_paid_dates = [],
  } = stats;
  const top = categories[0];

  document.getElementById('stat-total').textContent = currency.format(invoice_gross_total);

  let label, supporting;
  if (invoice_mode === 'paid') {
    label = invoice_gross_count === 1 ? 'Fatura paga no período' : 'Faturas pagas no período';
    const datesLabel = invoice_paid_dates.map(formatShortDate).join(', ');
    supporting = invoice_gross_count === 1
      ? `paga em ${datesLabel}`
      : `${invoice_gross_count} pagamentos (${datesLabel})`;
  } else {
    label = 'Fatura real em formação';
    const sinceLabel = invoice_since
      ? `desde ${formatShortDate(invoice_since)}`
      : 'desde sempre (sem pagamento registrado)';
    supporting = invoice_gross_count === 0
      ? `nenhuma compra ${sinceLabel}`
      : `${invoice_gross_count.toLocaleString('pt-BR')} compra${invoice_gross_count === 1 ? '' : 's'} ${sinceLabel}`;
  }
  document.getElementById('stat-label').textContent = label;
  document.getElementById('stat-payment-count').textContent = supporting;
  document.getElementById('stat-count').textContent = `${transaction_count.toLocaleString('pt-BR')} (${currency.format(total_spent)})`;
  document.getElementById('stat-top').textContent = top ? top.name : '—';

  const subtitle = transaction_count === 0
    ? 'Nenhuma transação ainda'
    : `${transaction_count} compras em ${categories.length} categoria${categories.length === 1 ? '' : 's'}`;
  document.getElementById('subtitle').textContent = subtitle;
}

function invoiceValueFromCapacity(cd, balanceFallback) {
  const source = cd?.card_invoice_source;
  if (source === 'account_balance') {
    return {
      value: cd.card_open_balance_total ?? 0,
      heroLabel: 'Fatura aberta / saldo do cartão',
      heroSupporting: 'dados do saldo do cartão',
      cardSubtext: 'saldo do cartão',
    };
  }
  if (source === 'bill') {
    const dueDates = cd.credit_card_due_dates;
    const dueLabel = Array.isArray(dueDates) && dueDates.length > 0
      ? `vencimento: ${dueDates.map(formatShortDate).join(', ')}`
      : 'fatura fechada do cartão';
    return {
      value: cd.card_invoice_official_total ?? 0,
      heroLabel: 'Fatura oficial Pluggy',
      heroSupporting: dueLabel,
      cardSubtext: `fatura oficial · ${dueLabel}`,
    };
  }
  if (source === 'transaction_fallback') {
    return {
      value: cd.card_invoice_gross_total ?? 0,
      heroLabel: 'Fatura reconstruída por transações',
      heroSupporting: 'fallback — sem fatura oficial disponível',
      cardSubtext: 'reconstruída por transações',
    };
  }
  return {
    value: balanceFallback ?? 0,
    heroLabel: null,
    heroSupporting: null,
    cardSubtext: null,
  };
}

function updateHeroFromCapacity(capacityData) {
  if (!capacityData?.card_invoice_source) return;
  const inv = invoiceValueFromCapacity(capacityData);
  if (inv.heroLabel) document.getElementById('stat-label').textContent = inv.heroLabel;
  document.getElementById('stat-total').textContent = currency.format(inv.value);
  if (inv.heroSupporting !== null) {
    document.getElementById('stat-payment-count').textContent = inv.heroSupporting;
  }
}

function formatShortDate(iso) {
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}

function renderCategoryBars(categories, totalSpent) {
  const container = document.getElementById('category-bars');
  if (!container) return;
  if (categories.length === 0) {
    container.innerHTML = '';
    return;
  }
  const max = categories.reduce((m, c) => Math.max(m, c.total), 0) || 1;
  container.innerHTML = categories
    .map((cat) => {
      const pct = Math.round((cat.total / max) * 100);
      const pctOfTotal =
        totalSpent > 0 ? ((cat.total / totalSpent) * 100).toFixed(1) : '0.0';
      const color = cat.color || FALLBACK_COLOR;
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
    })
    .join('');
}

function renderMonthChart(months) {
  const ctx = document.getElementById('chart-months');

  if (monthChart) monthChart.destroy();

  monthChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: months.map((m) => formatMonthLabel(m.month)),
      datasets: [
        {
          data: months.map((m) => m.total),
          backgroundColor: '#4f46e5',
          borderRadius: 6,
          maxBarThickness: 36,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${currency.format(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          ticks: {
            callback: (v) => currency.format(v).replace('R$', '').trim(),
          },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });
}

function renderCategories(transactions) {
  const container = document.getElementById('categories');
  const empty = document.getElementById('empty');
  transactionsById = new Map(transactions.map((tx) => [tx.id, tx]));

  if (transactions.length === 0) {
    container.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  const orderedCategories = categorySummariesFromTransactions(transactions);

  const renderTxRow = (tx) => {
    return `
      <li class="flex items-center justify-between gap-3 px-5 py-3 border-t border-slate-100">
        <div class="min-w-0 flex-1 pr-4">
          <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
          <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          ${transactionAmountHtml(tx)}
          <button
            type="button"
            class="match-fixed-cost size-8 inline-flex items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            data-tx-id="${escapeHtml(tx.id)}"
            title="Vincular a custo fixo"
            aria-label="Vincular a custo fixo"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L7.5 16.5 3.75 12.75" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 4.5l-3 3" />
            </svg>
          </button>
          <button
            type="button"
            class="categorize-tx size-8 inline-flex items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            data-tx-id="${escapeHtml(tx.id)}"
            title="Alterar categoria"
            aria-label="Alterar categoria"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
            </svg>
          </button>
        </div>
      </li>
    `;
  };

  const html = orderedCategories
    .map((cat) => {
      const txs = cat.transactions || [];
      const color = cat.color || FALLBACK_COLOR;
      const visible = txs.slice(0, TX_PER_CATEGORY_INITIAL);
      const hidden = txs.slice(TX_PER_CATEGORY_INITIAL);
      const visibleRows = visible.map(renderTxRow).join('');
      const hiddenRows = hidden.map(renderTxRow).join('');
      const moreSection =
        hidden.length > 0
          ? `
            <ul class="tx-hidden hidden">${hiddenRows}</ul>
            <button
              class="ver-mais w-full text-center text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-slate-50 py-3 border-t border-slate-100"
              data-count="${hidden.length}"
            >
              Ver mais ${hidden.length} ${hidden.length === 1 ? 'transação' : 'transações'}
            </button>
          `
          : '';

      const headerHtml = accordionHeaderHtml(cat, color);
      return `
        <details class="rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <summary class="flex items-center gap-3 px-5 py-4 select-none cursor-pointer" style="background:linear-gradient(135deg,${hexWithAlpha(color, 0.12)} 0%,${hexWithAlpha(color, 0.05)} 100%)">
            <span class="chevron shrink-0" style="color:${color}">
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </span>
            <div class="size-9 rounded-xl flex items-center justify-center shrink-0 text-lg leading-none" style="background:${hexWithAlpha(color, 0.18)}">
              ${categoryIcon(cat.name)}
            </div>
            <div class="flex-1 min-w-0">
              ${headerHtml}
            </div>
          </summary>
          <ul class="bg-white">${visibleRows}</ul>
          ${moreSection}
        </details>
      `;
    })
    .join('');

  container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 gap-3">${html}</div>`;

  // Span full width when a category accordion is open so the transaction
  // list has room to breathe; collapse back to one column when closed.
  container.querySelectorAll('details').forEach((det) => {
    det.addEventListener('toggle', () => {
      det.style.gridColumn = det.open ? '1 / -1' : '';
    });
  });

  // Wire up the "Ver mais" buttons to reveal the hidden rows.
  container.querySelectorAll('button.ver-mais').forEach((btn) => {
    btn.addEventListener('click', () => {
      const details = btn.closest('details');
      const hiddenList = details.querySelector('ul.tx-hidden');
      if (hiddenList) hiddenList.classList.remove('hidden');
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

function categoryOptionsHtml(selectedId) {
  return availableCategories
    .map((category) => {
      const selected = Number(category.id) === Number(selectedId) ? 'selected' : '';
      return `
        <option value="${category.id}" ${selected}>
          ${escapeHtml(category.name)}
        </option>
      `;
    })
    .join('');
}

function openCategoryModal(tx) {
  if (availableCategories.length === 0) {
    showToast('Nenhuma categoria disponível.', 'error');
    return;
  }
  document.getElementById('category-modal-description').textContent = tx.description;
  document.getElementById('category-rule-pattern').value = tx.description;
  document.getElementById('category-rule-category').innerHTML =
    categoryOptionsHtml(tx.custom_category_id);
  document.getElementById('category-modal').classList.remove('hidden');
  document.getElementById('category-rule-pattern').focus();
}

function closeCategoryModal() {
  document.getElementById('category-modal').classList.add('hidden');
}

async function saveCategoryRule(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const pattern = document.getElementById('category-rule-pattern').value.trim();
  const categoryId = Number(document.getElementById('category-rule-category').value);

  if (!pattern || !categoryId) {
    showToast('Informe o texto e a categoria.', 'error');
    return;
  }

  button.disabled = true;
  try {
    const response = await fetch('/category-rules/description', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pattern, category_id: categoryId }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Falha ao salvar regra (HTTP ${response.status})`);
    }
    const result = await response.json();
    closeCategoryModal();
    await loadData();
    showToast(
      `${result.affected_count} compra(s) movida(s) para ${result.category_name}.`,
      'success',
    );
  } catch (err) {
    console.error(err);
    showToast(err.message || 'Erro ao salvar regra.', 'error');
  } finally {
    button.disabled = false;
  }
}

async function fetchJsonStrict(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function fixedCostOptionsHtml(costs, txAmount) {
  const sorted = [...costs].sort((a, b) => {
    const deltaA = Math.abs((Number(a.amount) || 0) - txAmount);
    const deltaB = Math.abs((Number(b.amount) || 0) - txAmount);
    return deltaA - deltaB || String(a.description).localeCompare(String(b.description));
  });
  return sorted
    .map((cost) => {
      const amount = Number(cost.amount) || 0;
      return `
        <option value="${cost.id}">
          ${escapeHtml(cost.description)} · ${escapeHtml(cost.category_name || 'Sem categoria')} · ${currency.format(amount)}
        </option>
      `;
    })
    .join('');
}

async function openFixedCostMatchModal(tx) {
  activeFixedCostTransaction = tx;
  const modal = document.getElementById('fixed-cost-match-modal');
  const select = document.getElementById('fixed-cost-match-cost');
  const amount = Math.abs(Number(tx.amount) || 0);

  document.getElementById('fixed-cost-match-description').textContent = tx.description;
  document.getElementById('fixed-cost-match-amount').textContent = currency.format(amount);
  document.getElementById('fixed-cost-match-date').textContent =
    `${formatDayLabel(tx.date)} · ${yearMonthFromIso(tx.date)}`;
  select.innerHTML = '<option>Carregando…</option>';
  modal.classList.remove('hidden');

  try {
    const costs = await fetchJsonStrict('/fixed-costs');
    if (!Array.isArray(costs) || costs.length === 0) {
      select.innerHTML = '<option value="">Nenhum custo fixo ativo</option>';
      showToast('Cadastre um custo fixo antes de vincular.', 'error');
      return;
    }
    select.innerHTML = fixedCostOptionsHtml(costs, amount);
    select.focus();
  } catch (err) {
    console.error(err);
    select.innerHTML = '<option value="">Erro ao carregar custos</option>';
    showToast('Erro ao carregar custos fixos.', 'error');
  }
}

function closeFixedCostMatchModal() {
  document.getElementById('fixed-cost-match-modal').classList.add('hidden');
  activeFixedCostTransaction = null;
}

async function saveFixedCostMatch(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const fixedCostId = Number(document.getElementById('fixed-cost-match-cost').value);
  if (!activeFixedCostTransaction || !fixedCostId) {
    showToast('Selecione um custo fixo.', 'error');
    return;
  }

  button.disabled = true;
  try {
    await fetchJsonStrict(`/fixed-costs/${fixedCostId}/matches`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        transaction_id: activeFixedCostTransaction.id,
        year_month: yearMonthFromIso(activeFixedCostTransaction.date),
      }),
    });
    closeFixedCostMatchModal();
    await loadData();
    showToast('Transação vinculada ao custo fixo.', 'success');
  } catch (err) {
    console.error(err);
    showToast(err.message || 'Erro ao vincular custo fixo.', 'error');
  } finally {
    button.disabled = false;
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Transações is scoped to the CURRENT month only. Previous months live in
// Histórico, so the period selector was removed — activePeriod is pinned.
let activePeriod = 'month';

// Monotonic version counter so a late-arriving fetch from a previous filter
// click doesn't overwrite a more recent render. Bumped at the start of every
// loadData(); each fetch captures its own version and aborts if a newer one
// has started.
let loadVersion = 0;

function shouldShowMonthChart() {
  return false;
}

function updateChartPanels() {
  const monthPanel = document.getElementById('month-chart-panel');
  const showMonthChart = shouldShowMonthChart();
  if (monthPanel) monthPanel.classList.toggle('hidden', !showMonthChart);
  if (!showMonthChart && monthChart) {
    monthChart.destroy();
    monthChart = null;
  }
}

function isoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function rangeForPeriod(period) {
  const today = new Date();
  const todayIso = isoDate(today);
  if (period === 'month') {
    const first = new Date(today.getFullYear(), today.getMonth(), 1);
    return { from: isoDate(first), to: todayIso };
  }
  if (period === 'prev_month') {
    const first = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const last = new Date(today.getFullYear(), today.getMonth(), 0);
    return { from: isoDate(first), to: isoDate(last) };
  }
  return {};
}

function renderPeriodFilter() {
  // No more period selector — just a static label showing the current month
  // so the user knows Transações only covers the ongoing month.
  const container = document.getElementById('period-filter');
  if (!container) return;
  const label = new Date().toLocaleDateString('pt-BR', {
    month: 'long',
    year: 'numeric',
  });
  container.innerHTML =
    `<span class="px-3.5 py-1.5 rounded-full text-sm font-medium bg-white/20 border border-white/30 text-white capitalize">${label}</span>`;
}

async function loadData() {
  const myVersion = ++loadVersion;
  const { from, to } = rangeForPeriod(activePeriod);
  const params = new URLSearchParams();
  if (from) params.set('from_date', from);
  if (to) params.set('to_date', to);
  const qs = params.toString() ? `?${params.toString()}` : '';

  const [statsResponse, transactionsResponse, categoriesResponse] = await Promise.all([
    fetch(`/stats${qs}`),
    fetch(`/transactions${qs}`),
    fetch('/categories'),
  ]);
  if (myVersion !== loadVersion) return; // a newer loadData() superseded this one
  if (!statsResponse.ok || !transactionsResponse.ok || !categoriesResponse.ok) {
    throw new Error('Falha ao carregar dados');
  }
  const stats = await statsResponse.json();
  const transactions = await transactionsResponse.json();
  availableCategories = await categoriesResponse.json();
  if (myVersion !== loadVersion) return;

  renderSummary(stats);
  renderCategoryBars(stats.categories, stats.total_spent);
  updateChartPanels();
  if (shouldShowMonthChart()) renderMonthChart(stats.months);
  renderCategories(transactions);

  // Cash-flow strip is fetched separately so its failure (or slowness)
  // doesn't block the dashboard's primary stats from rendering.
  loadMonthlyFlow(myVersion);
  loadSyncHealth(myVersion);
  loadSnapshot(myVersion);
}

async function loadSnapshot(expectedVersion) {
  const section = document.getElementById('snapshot-section');
  if (!section) return;
  try {
    const response = await fetch('/dashboard/snapshot');
    if (expectedVersion !== loadVersion) return;
    if (!response.ok) {
      section.classList.add('hidden');
      return;
    }
    const data = await response.json();
    if (expectedVersion !== loadVersion) return;
    renderSnapshot(section, data);
  } catch (err) {
    console.error('snapshot load failed', err);
    section.classList.add('hidden');
  }
}

function renderSnapshot(section, data) {
  const bank = data.bank || {};
  const credit = data.credit || {};
  const investments = data.investments || {};

  // Nothing synced yet → keep the strip hidden rather than showing zeros.
  const anything =
    bank.has_balance || credit.has_balance || investments.has_investments;
  if (!anything) {
    section.classList.add('hidden');
    section.innerHTML = '';
    return;
  }

  const card = (label, value, sub, valueClass = 'text-slate-900') => `
    <div class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
      <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">${label}</p>
      <p class="mt-2 text-2xl font-bold tabular ${valueClass}">${value}</p>
      <p class="text-xs text-slate-500 mt-1">${sub}</p>
    </div>`;

  const cards = [];
  cards.push(
    card(
      'Saldo em conta',
      bank.has_balance ? currency.format(bank.total) : '—',
      `${bank.account_count || 0} conta${(bank.account_count || 0) === 1 ? '' : 's'}`,
      'text-emerald-700',
    ),
  );
  const creditSub = credit.limit
    ? `limite ${currency.format(credit.limit)} · livre ${currency.format(credit.available)}`
    : `${credit.account_count || 0} cartã${(credit.account_count || 0) === 1 ? 'o' : 'os'}`;
  cards.push(
    card(
      'Cartão em uso',
      credit.has_balance ? currency.format(credit.used) : '—',
      creditSub,
      'text-slate-900',
    ),
  );
  cards.push(
    card(
      'Investimentos',
      investments.has_investments ? currency.format(investments.total) : '—',
      `${investments.investment_count || 0} posiç${(investments.investment_count || 0) === 1 ? 'ão' : 'ões'}`,
      'text-indigo-700',
    ),
  );
  cards.push(
    card(
      'Reserva',
      investments.has_investments ? currency.format(investments.reserve_total) : '—',
      `${investments.reserve_investment_count || 0} elegíve${(investments.reserve_investment_count || 0) === 1 ? 'l' : 'is'}`,
      'text-indigo-700',
    ),
  );

  document.getElementById('snapshot-cards').innerHTML = cards.join('');
  section.classList.remove('hidden');
}

async function loadSyncHealth(expectedVersion) {
  const section = document.getElementById('sync-health');
  if (!section) return;
  try {
    const response = await fetch('/sync/health');
    if (expectedVersion !== loadVersion) return;
    if (!response.ok) return;
    const items = await response.json();
    renderSyncHealth(section, items);
  } catch (err) {
    console.error('sync health failed', err);
  }
}

function renderSyncHealth(section, items) {
  const noteworthy = (items || []).filter(
    (it) => it.is_running || it.last_sync_error || (it.failed_accounts || []).length > 0,
  );
  if (noteworthy.length === 0) {
    section.classList.add('hidden');
    section.innerHTML = '';
    return;
  }

  const cards = noteworthy.map((it) => {
    const running = it.is_running;
    const itemError = it.last_sync_error;
    const accountErrors = it.failed_accounts || [];
    const variant = running
      ? { bg: 'bg-indigo-50', border: 'border-indigo-200', text: 'text-indigo-900', tag: 'Sincronizando' }
      : { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-900', tag: 'Atenção' };
    const name = escapeHtml(it.connector_name || it.item_id);
    const accountList = accountErrors.length
      ? `<ul class="mt-2 space-y-1 text-xs ${variant.text}/80">${accountErrors
          .map(
            (a) =>
              `<li><span class="font-medium">${escapeHtml(a.account_id)}:</span> ${escapeHtml(a.error || '')}</li>`,
          )
          .join('')}</ul>`
      : '';
    const itemErrorLine = itemError
      ? `<p class="mt-1 text-xs ${variant.text}/80">${escapeHtml(itemError)}</p>`
      : '';
    return `
      <div class="rounded-2xl ${variant.bg} border ${variant.border} px-5 py-4">
        <div class="flex items-center gap-3">
          <span class="text-xs font-semibold uppercase tracking-wider ${variant.text}">${variant.tag}</span>
          <span class="font-medium ${variant.text}">${name}</span>
        </div>
        ${itemErrorLine}
        ${accountList}
      </div>`;
  });

  section.innerHTML = `<div class="space-y-3">${cards.join('')}</div>`;
  section.classList.remove('hidden');
}

function showToast(message, variant = 'info') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.classList.remove('hidden', 'bg-slate-900', 'bg-red-600', 'bg-emerald-600');
  el.classList.add(
    variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-900',
  );
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => el.classList.add('hidden'), 4000);
}

async function openConnectWidget() {
  const button = document.getElementById('connect');
  button.disabled = true;
  try {
    const tokenResponse = await fetch('/connect-token', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!tokenResponse.ok) {
      throw new Error(`Falha ao obter token (HTTP ${tokenResponse.status}). Verifique suas credenciais Pluggy no .env.`);
    }
    const { accessToken } = await tokenResponse.json();

    if (typeof PluggyConnect === 'undefined') {
      throw new Error('Script do Pluggy Connect não carregou. Verifique sua conexão.');
    }

    const widget = new PluggyConnect({
      connectToken: accessToken,
      // Set includeSandbox to true if you want to test against Pluggy Bank again.
      // In production we let the dashboard's enabled connectors (e.g. MeuPluggy)
      // drive what's shown.
      includeSandbox: false,
      language: 'pt',
      countries: ['BR'],
      // 200 = MeuPluggy connector. Add more IDs here if you enable other
      // connectors in dashboard.pluggy.ai and want them to appear in the widget.
      connectorIds: [200],
      onSuccess: async (data) => {
        const itemId = data?.item?.id;
        if (!itemId) {
          showToast('Conexão completa mas itemId ausente.', 'error');
          return;
        }
        showToast('Conectado! Sincronizando compras…');
        try {
          await fetch(`/items/${itemId}`, { method: 'POST' });
          const sync = await fetch(`/items/${itemId}/sync`, { method: 'POST' });
          if (sync.status === 409) {
            showToast('Sincronização já em andamento para este item.', 'info');
            return;
          }
          const result = await sync.json();
          await loadData();
          const updated = result.updated_transactions || 0;
          const syncSummary = updated > 0
            ? `${result.new_transactions} nova(s) e ${updated} atualizada(s)`
            : `${result.new_transactions} nova(s)`;
          const failed = (result.failed_accounts || []).length;
          const failureSuffix = failed > 0 ? ` (${failed} conta(s) com erro)` : '';
          showToast(
            `${syncSummary} compra(s) sincronizada(s).${failureSuffix}`,
            failed > 0 ? 'info' : 'success',
          );
        } catch (err) {
          console.error(err);
          showToast('Erro ao sincronizar compras.', 'error');
        }
      },
      onError: (error) => {
        console.error('Pluggy onError:', error);
        showToast(`Erro: ${error?.message || 'desconhecido'}`, 'error');
      },
    });
    widget.init();
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  } finally {
    button.disabled = false;
  }
}

document.getElementById('refresh').addEventListener('click', () => {
  loadData().catch((err) => {
    console.error(err);
    document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
  });
});

document.getElementById('connect').addEventListener('click', openConnectWidget);

document.getElementById('category-rule-form').addEventListener('submit', saveCategoryRule);
document.getElementById('category-modal-close').addEventListener('click', closeCategoryModal);
document.getElementById('category-modal-cancel').addEventListener('click', closeCategoryModal);
document.getElementById('category-modal').addEventListener('click', (event) => {
  if (event.target.id === 'category-modal') closeCategoryModal();
});
document.getElementById('fixed-cost-match-form').addEventListener('submit', saveFixedCostMatch);
document.getElementById('fixed-cost-match-close').addEventListener('click', closeFixedCostMatchModal);
document.getElementById('fixed-cost-match-cancel').addEventListener('click', closeFixedCostMatchModal);
document.getElementById('fixed-cost-match-modal').addEventListener('click', (event) => {
  if (event.target.id === 'fixed-cost-match-modal') closeFixedCostMatchModal();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeCategoryModal();
    closeFixedCostMatchModal();
  }
});

renderPeriodFilter();
loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
