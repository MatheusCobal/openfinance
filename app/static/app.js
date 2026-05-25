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

function formatMonthLabel(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthFormatter.format(new Date(year, month - 1, 1));
}

function formatDayLabel(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return dayFormatter.format(new Date(year, month - 1, day));
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
  // Builds the per-category summary the accordion renders. For CREDIT mode
  // every transaction is an outflow, so `total` is the abs-sum (what was
  // spent). For BANK mode we keep entradas and saídas separate to avoid
  // mixing a R$5.000 salary with a R$200 transfer-out into a misleading
  // R$5.200 "total" — the header instead shows the net balance with sign,
  // plus a breakdown of the two sides.
  const isBank = activeAccountType === 'BANK';
  const categoriesById = new Map(availableCategories.map((cat) => [cat.id, cat]));
  const groups = groupTransactionsByCategoryId(transactions);
  const summaries = Array.from(groups.entries()).map(([categoryId, txs]) => {
    const known = categoriesById.get(categoryId);
    const fallback = txs[0] || {};
    let entradas = 0;
    let saidas = 0;
    let entradasCount = 0;
    let saidasCount = 0;
    for (const tx of txs) {
      const amount = Number(tx.amount) || 0;
      if (amount > 0) {
        entradas += amount;
        entradasCount += 1;
      } else if (amount < 0) {
        saidas += Math.abs(amount);
        saidasCount += 1;
      }
    }
    const net = entradas - saidas;
    const total = isBank ? net : entradas + saidas;
    return {
      id: categoryId,
      name: known?.name || fallback.custom_category_name || 'Sem categoria',
      color: known?.color || fallback.custom_category_color || FALLBACK_COLOR,
      sort_order: known?.sort_order ?? 999,
      total,
      net,
      entradas,
      saidas,
      entradas_count: entradasCount,
      saidas_count: saidasCount,
      count: txs.length,
      transactions: txs,
    };
  });

  // Stable order — uses the curated sort_order from the categories table so
  // categories don't reshuffle when the period or account-type chip changes.
  // Falls back to abs-total for ties (categories without a sort_order).
  return summaries.sort(
    (a, b) =>
      a.sort_order - b.sort_order ||
      Math.abs(b.total) - Math.abs(a.total) ||
      a.name.localeCompare(b.name),
  );
}

function bankAccordionHeaderHtml(cat, color) {
  const net = cat.net;
  const sign = net >= 0 ? '+' : '−';
  const netColor = net >= 0 ? '#047857' : '#b91c1c'; // emerald-700 / red-700
  const entradasLabel = `${cat.entradas_count} ${cat.entradas_count === 1 ? 'entrada' : 'entradas'}`;
  const saidasLabel = `${cat.saidas_count} ${cat.saidas_count === 1 ? 'saída' : 'saídas'}`;
  return `
    <div class="flex items-center justify-between gap-3">
      <span class="font-bold text-slate-900">${escapeHtml(cat.name)}</span>
      <span class="font-bold tabular shrink-0" style="color:${netColor}">
        ${sign}${currency.format(Math.abs(net))}
      </span>
    </div>
    <div class="text-xs text-slate-500 mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
      ${cat.entradas_count > 0
        ? `<span class="inline-flex items-center gap-1"><span class="text-emerald-600">↑</span>${currency.format(cat.entradas)} <span class="text-slate-400">·</span> ${entradasLabel}</span>`
        : ''}
      ${cat.saidas_count > 0
        ? `<span class="inline-flex items-center gap-1"><span class="text-red-600">↓</span>${currency.format(cat.saidas)} <span class="text-slate-400">·</span> ${saidasLabel}</span>`
        : ''}
    </div>
  `;
}

function creditAccordionHeaderHtml(cat, color) {
  return `
    <div class="flex items-center justify-between gap-3">
      <span class="font-bold text-slate-900">${escapeHtml(cat.name)}</span>
      <span class="font-bold tabular shrink-0" style="color:${color}">${currency.format(cat.total)}</span>
    </div>
    <p class="text-xs text-slate-500 mt-1">${cat.count} ${transactionNoun(cat.count)}</p>
  `;
}

function transactionNoun(count) {
  if (activeAccountType === 'CREDIT') {
    return count === 1 ? 'compra' : 'compras';
  }
  return count === 1 ? 'transação' : 'transações';
}

function transactionAmountHtml(tx) {
  const amount = Number(tx.amount) || 0;
  const showSign = activeAccountType !== 'CREDIT';
  const sign = showSign && amount > 0 ? '+' : showSign && amount < 0 ? '-' : '';
  const color = showSign && amount > 0 ? 'text-emerald-700' : 'text-slate-900';
  return `
    <p class="text-sm font-medium tabular ${color}">
      ${sign}${currency.format(Math.abs(amount))}
    </p>
  `;
}

// ── Monthly cash-flow strip ─────────────────────────────────────────────
//
// Always shows the CURRENT calendar month, independent of the dashboard's
// period filter, since "cash flow this month" is a status snapshot rather
// than a historical view.

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
  const footer = isNet
    ? (help ? `<span class="text-slate-500">${escapeHtml(help)}</span>` : '<span></span>')
    : `${countLabel ? `<span class="text-slate-500">${escapeHtml(countLabel)}</span>` : '<span></span>'}${delta ? ` <span class="ml-auto">${delta}</span>` : ''}`;
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

function renderMonthlyFlow(cashflowData, balanceData) {
  const section = document.getElementById('monthly-flow-section');
  const container = document.getElementById('monthly-flow');
  const periodLabel = document.getElementById('monthly-flow-period');
  if (
    !cashflowData ||
    !Array.isArray(cashflowData.months) ||
    cashflowData.months.length === 0
  ) {
    section.classList.add('hidden');
    return;
  }
  const current = cashflowData.months[cashflowData.months.length - 1];
  const previous = cashflowData.months.length > 1
    ? cashflowData.months[cashflowData.months.length - 2]
    : null;
  const balanceCurrent = balanceData?.months?.[balanceData.months.length - 1] || {};
  const balancePrevious = balanceData?.months?.length > 1
    ? balanceData.months[balanceData.months.length - 2]
    : null;

  // Hide the section entirely if the current month has no activity at all
  // (avoids showing four R$ 0,00 cards for accounts that just synced).
  const hasActivity = (current.income || 0) > 0
    || (current.outflow || 0) > 0
    || (balanceCurrent.card_spend || 0) > 0;
  if (!hasActivity) {
    section.classList.add('hidden');
    return;
  }

  periodLabel.textContent = formatMonthLabel(current.month);

  container.innerHTML = [
    flowCard({
      label: 'Entradas',
      icon: '💰',
      value: current.income || 0,
      prev: previous ? previous.income : null,
      countLabel: pluralRecebimentos(current.income_count || 0),
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
      label: 'Saldo bancário',
      help: 'Entradas − saídas bancárias',
      icon: '📊',
      value: current.net || 0,
      tint: (current.net || 0) >= 0 ? 'emerald' : 'red',
      isNet: true,
    }),
    flowCard({
      label: 'Gastos no cartão',
      icon: '💳',
      value: balanceCurrent.card_spend || 0,
      prev: balancePrevious ? balancePrevious.card_spend : null,
      countLabel: `${(balanceCurrent.card_spend_count || 0).toLocaleString('pt-BR')} ${balanceCurrent.card_spend_count === 1 ? 'compra' : 'compras'}`,
      tint: 'orange',
      higherIsBetter: false,
    }),
  ].join('');

  section.classList.remove('hidden');
}

async function loadMonthlyFlow() {
  // Loaded independently from the main stats fetch so a failure here can't
  // take down the rest of the dashboard.
  try {
    const [cashflowResponse, balanceResponse] = await Promise.all([
      fetch('/bank-cashflow/monthly?months=12'),
      fetch('/monthly-balance?months=12'),
    ]);
    if (!cashflowResponse.ok || !balanceResponse.ok) return;
    const cashflowData = await cashflowResponse.json();
    const balanceData = await balanceResponse.json();
    renderMonthlyFlow(cashflowData, balanceData);
  } catch (err) {
    console.error('monthly flow load failed:', err);
  }
}

function renderSummary(stats) {
  const { total_spent, transaction_count, categories } = stats;
  const avg = transaction_count > 0 ? total_spent / transaction_count : 0;
  const top = categories[0];

  document.getElementById('stat-total').textContent = currency.format(total_spent);
  document.getElementById('stat-count').textContent = transaction_count.toLocaleString('pt-BR');
  document.getElementById('stat-avg').textContent = currency.format(avg);
  document.getElementById('stat-top').textContent = top ? top.name : '—';

  const subtitle = transaction_count === 0
    ? 'Nenhuma transação ainda'
    : `${transaction_count} compras em ${categories.length} categoria${categories.length === 1 ? '' : 's'}`;
  document.getElementById('subtitle').textContent = subtitle;
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
    // The "alterar categoria" rule editor is phrased around spending ("Mover
    // compras de X para Y"), so it doesn't make sense for incoming bank
    // transactions. Hide the button on positive amounts in BANK mode.
    const amount = Number(tx.amount) || 0;
    const showCategorize = !(activeAccountType === 'BANK' && amount > 0);
    return `
      <li class="flex items-center justify-between gap-3 px-5 py-3 border-t border-slate-100">
        <div class="min-w-0 flex-1 pr-4">
          <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
          <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          ${transactionAmountHtml(tx)}
          ${showCategorize ? `
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
          ` : ''}
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

      const headerHtml = activeAccountType === 'BANK'
        ? bankAccordionHeaderHtml(cat, color)
        : creditAccordionHeaderHtml(cat, color);
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

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Label for the year chip is computed at load time so it auto-updates when
// the calendar year flips.
const CURRENT_YEAR = new Date().getFullYear();

const PERIODS = [
  { key: 'month', label: 'Este mês' },
  { key: 'prev_month', label: 'Mês anterior' },
  { key: 'year', label: String(CURRENT_YEAR) },
  { key: 'prev_year', label: String(CURRENT_YEAR - 1) },
];

let activePeriod = 'month';

// Account-type filter for the bottom transactions list (NOT the hero stats,
// which intentionally remain credit-card-focused since "total gasto" only
// makes semantic sense for spending accounts). "ALL" is intentionally NOT
// offered because mixing credit and bank in one view double-counts (e.g.
// a R$100 purchase shows up both as a credit-card expense AND, later, as
// a bank outflow when the invoice is paid). Use the Histórico "Entradas e
// saídas" tab for a true cash-flow view.
const ACCOUNT_TYPES = [
  { key: 'CREDIT', label: 'Cartão' },
  { key: 'BANK',   label: 'Banco' },
];
let activeAccountType = 'CREDIT';

// Monotonic version counter so a late-arriving fetch from a previous filter
// click doesn't overwrite a more recent render. Bumped at the start of every
// loadData(); each fetch captures its own version and aborts if a newer one
// has started.
let loadVersion = 0;

function shouldShowMonthChart() {
  return activePeriod === 'year' || activePeriod === 'prev_year';
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
  if (period === 'year') {
    const first = new Date(today.getFullYear(), 0, 1);
    return { from: isoDate(first), to: todayIso };
  }
  if (period === 'prev_year') {
    const year = today.getFullYear() - 1;
    return { from: `${year}-01-01`, to: `${year}-12-31` };
  }
  return {};
}

function renderPeriodFilter() {
  const container = document.getElementById('period-filter');
  if (!container) return;
  container.innerHTML = PERIODS.map((p) => {
    const isActive = p.key === activePeriod;
    const base = 'px-3.5 py-1.5 rounded-full text-sm font-medium transition-colors';
    const cls = isActive
      ? `${base} bg-white text-indigo-700 shadow-sm`
      : `${base} bg-white/20 border border-white/30 text-white hover:bg-white/30`;
    return `<button class="${cls}" data-period="${p.key}">${p.label}</button>`;
  }).join('');
  container.querySelectorAll('button[data-period]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.period === activePeriod) return;
      activePeriod = btn.dataset.period;
      renderPeriodFilter();
      loadData().catch((err) => {
        console.error(err);
        document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
      });
    });
  });
}

function renderAccountTypeFilter() {
  const container = document.getElementById('account-type-filter');
  const hint = document.getElementById('account-type-hint');
  if (!container) return;
  container.innerHTML = ACCOUNT_TYPES.map((t) => {
    const isActive = t.key === activeAccountType;
    const base = 'px-2.5 py-1 rounded-md text-xs font-medium transition-colors';
    const cls = isActive
      ? `${base} bg-indigo-600 text-white shadow-sm`
      : `${base} bg-white border border-slate-200 text-slate-600 hover:bg-slate-100`;
    return `<button class="${cls}" data-account-type="${t.key}">${t.label}</button>`;
  }).join('');
  container.querySelectorAll('button[data-account-type]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.accountType === activeAccountType) return;
      activeAccountType = btn.dataset.accountType;
      renderAccountTypeFilter();
      loadData().catch((err) => {
        console.error(err);
        document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
      });
    });
  });

  if (hint) {
    if (activeAccountType === 'BANK') {
      hint.classList.remove('hidden');
      hint.textContent =
        'Transações bancárias (entradas e saídas). Os totais acima continuam sendo de cartão.';
    } else {
      hint.classList.add('hidden');
      hint.textContent = '';
    }
  }
}

function updateExportLink() {
  const { from, to } = rangeForPeriod(activePeriod);
  const params = new URLSearchParams();
  if (from) params.set('from_date', from);
  if (to) params.set('to_date', to);
  params.set('account_type', activeAccountType);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const link = document.getElementById('export');
  if (link) link.href = `/export/transactions.csv${qs}`;
}

async function loadData() {
  const myVersion = ++loadVersion;
  const { from, to } = rangeForPeriod(activePeriod);
  const params = new URLSearchParams();
  if (from) params.set('from_date', from);
  if (to) params.set('to_date', to);
  const qs = params.toString() ? `?${params.toString()}` : '';
  updateExportLink();

  // /transactions feeds the bottom accordion and respects the chip selector.
  // /stats stays credit-only on purpose — see ACCOUNT_TYPES comment.
  const txParams = new URLSearchParams(params);
  txParams.set('account_type', activeAccountType);
  const txQs = `?${txParams.toString()}`;

  const [statsResponse, transactionsResponse, categoriesResponse] = await Promise.all([
    fetch(`/stats${qs}`),
    fetch(`/transactions${txQs}`),
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
  loadMonthlyFlow();
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
          const result = await sync.json();
          await loadData();
          const updated = result.updated_transactions || 0;
          const syncSummary = updated > 0
            ? `${result.new_transactions} nova(s) e ${updated} atualizada(s)`
            : `${result.new_transactions} nova(s)`;
          showToast(
            `${syncSummary} compra(s) sincronizada(s).`,
            'success',
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
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeCategoryModal();
});

renderPeriodFilter();
renderAccountTypeFilter();
loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
