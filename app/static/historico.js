const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
});

const charts = new Map();
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
const INVOICE_COLOR = '#475569';
const INCOME_COLOR = '#10b981';
const HISTORY_TABS = [
  { key: 'invoices', label: 'Faturas cartão' },
  { key: 'income', label: 'Receitas' },
  { key: 'cashflow', label: 'Entradas e saídas' },
];

let activeTab = 'invoices';
let categoryHistory = null;
let invoiceHistory = null;
let incomeHistory = null;
let cashflowData = null;
let exclusionRules = null;
let cashflowRules = null;

function formatMonthLabel(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthFormatter.format(new Date(year, month - 1, 1));
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function showToast(message, variant = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden', 'bg-slate-900', 'bg-red-600', 'bg-emerald-600');
  el.classList.add(
    variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-900',
  );
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => el.classList.add('hidden'), 4000);
}

function pluralCompras(n) {
  return n === 1 ? '1 compra' : `${n.toLocaleString('pt-BR')} compras`;
}

function pluralFaturas(n) {
  return n === 1 ? '1 pagamento' : `${n.toLocaleString('pt-BR')} pagamentos`;
}

function pluralRecebimentos(n) {
  return n === 1 ? '1 recebimento' : `${n.toLocaleString('pt-BR')} recebimentos`;
}

function pluralMeses(n) {
  return n === 1 ? '1 mês' : `${n.toLocaleString('pt-BR')} meses`;
}

function pluralRegras(n) {
  return n === 1 ? '1 regra' : `${n.toLocaleString('pt-BR')} regras`;
}

function cashflowDirectionLabel(direction) {
  const normalized = String(direction || 'ALL').toUpperCase();
  if (normalized === 'IN') return 'Entradas';
  if (normalized === 'OUT') return 'Saídas';
  return 'Entradas e saídas';
}

function planStatusLabel(status) {
  const labels = {
    healthy: 'Saudável',
    tight: 'Apertado',
    over: 'Estourado',
    unknown: 'Sem receita',
  };
  return labels[status] || 'Sem status';
}

function planStatusClasses(status) {
  if (status === 'healthy') return 'bg-emerald-50 text-emerald-700';
  if (status === 'tight') return 'bg-amber-50 text-amber-700';
  if (status === 'over') return 'bg-red-50 text-red-700';
  return 'bg-slate-100 text-slate-600';
}
function destroyCharts() {
  charts.forEach((chart) => chart.destroy());
  charts.clear();
}

function renderTabs() {
  const container = document.getElementById('history-tabs');
  container.innerHTML = HISTORY_TABS.map((tab) => {
    const base =
      'px-3.5 py-1.5 rounded-full text-sm font-medium transition-colors';
    const cls = tab.key === activeTab
      ? `${base} bg-blue-700 text-white`
      : `${base} bg-white border border-slate-200 text-slate-700 hover:bg-slate-100`;
    return `<button class="${cls}" data-tab="${tab.key}">${tab.label}</button>`;
  }).join('');

  container.querySelectorAll('button[data-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.tab === activeTab) return;
      activeTab = btn.dataset.tab;
      renderTabs();
      renderActiveTab();
    });
  });
}

function findRecentMonthsWithData(byMonth, months) {
  // Returns [last, prev] — the two most recent months with non-zero values.
  // Skipping zero-value months avoids "+inf%" deltas when comparing to an
  // empty period.
  let last = null;
  let prev = null;
  for (let i = months.length - 1; i >= 0; i--) {
    const v = byMonth[months[i]] || 0;
    if (v > 0) {
      if (last === null) {
        last = months[i];
      } else {
        prev = months[i];
        break;
      }
    }
  }
  return { last, prev };
}

function deltaHtml(lastValue, prevValue, prevMonth) {
  if (!prevMonth || prevValue <= 0) return '';
  const diff = lastValue - prevValue;
  const pct = (diff / prevValue) * 100;
  const sign = diff >= 0 ? '+' : '';
  // Spending less is "green" (good), spending more is "red".
  const color = diff > 0 ? 'text-red-600' : diff < 0 ? 'text-emerald-600' : 'text-slate-500';
  return ` <span class="${color} font-medium">${sign}${pct.toFixed(0)}%</span><span class="text-slate-400"> vs ${escapeHtml(formatMonthLabel(prevMonth))}</span>`;
}

function renderCard(category, months) {
  const color = category.color || FALLBACK_COLOR;
  const totalCount = Object.values(category.counts_by_month).reduce(
    (a, b) => a + b,
    0,
  );
  const { last, prev } = findRecentMonthsWithData(category.by_month, months);
  const lastValue = last ? category.by_month[last] : 0;
  const prevValue = prev ? category.by_month[prev] : 0;
  const lastHtml = last
    ? `${escapeHtml(formatMonthLabel(last))}: ${escapeHtml(currency.format(lastValue))}${deltaHtml(lastValue, prevValue, prev)}`
    : 'sem movimentação';

  return `
    <div class="bg-white rounded-lg border border-slate-200 p-6">
      <div class="flex items-baseline justify-between mb-1">
        <div class="flex items-center gap-2 min-w-0">
          <span class="size-8 rounded-lg flex items-center justify-center shrink-0 text-base leading-none" style="background:${hexWithAlpha(color, 0.12)}">${categoryIcon(category.name)}</span>
          <h3 class="font-semibold text-slate-900 truncate">${escapeHtml(category.name)}</h3>
        </div>
        <p class="font-bold tabular text-slate-900 shrink-0 ml-3">${currency.format(category.total)}</p>
      </div>
      <p class="text-xs text-slate-500 mb-4">
        ${pluralCompras(totalCount)} · ${lastHtml}
      </p>
      <div class="relative h-44">
        <canvas id="chart-${category.id}"></canvas>
      </div>
    </div>
  `;
}

function renderChart(category, months) {
  const ctx = document.getElementById(`chart-${category.id}`);
  if (!ctx) return;

  if (charts.has(category.id)) charts.get(category.id).destroy();

  const color = category.color || FALLBACK_COLOR;
  const data = months.map((m) => category.by_month[m] || 0);
  const counts = months.map((m) => category.counts_by_month[m] || 0);

  const chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: months.map(formatMonthLabel),
      datasets: [
        {
          data,
          backgroundColor: color,
          borderRadius: 4,
          maxBarThickness: 28,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (evt, elements) => {
        if (elements.length === 0) return;
        const idx = elements[0].index;
        const month = months[idx];
        if (counts[idx] > 0) openDrilldown(category, month);
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const value = currency.format(ctx.parsed.y);
              const n = counts[ctx.dataIndex];
              return n > 0 ? ` ${value} · ${pluralCompras(n)}` : ` ${value}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          beginAtZero: true,
          ticks: {
            font: { size: 10 },
            callback: (v) => currency.format(v).replace('R$', '').trim(),
          },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });

  charts.set(category.id, chart);
}

function renderInvoiceChart(data) {
  const ctx = document.getElementById('chart-invoices');
  if (!ctx) return;
  if (typeof Chart === 'undefined') return;

  if (charts.has('invoices')) charts.get('invoices').destroy();

  const chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.months.map((item) => formatMonthLabel(item.month)),
      datasets: [
        {
          data: data.months.map((item) => item.total),
          backgroundColor: INVOICE_COLOR,
          borderRadius: 4,
          maxBarThickness: 32,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (evt, elements) => {
        if (elements.length === 0) return;
        const monthData = data.months[elements[0].index];
        if (monthData && monthData.count > 0) openInvoiceDrilldown(monthData);
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const item = data.months[ctx.dataIndex];
              return ` ${currency.format(ctx.parsed.y)} · ${pluralFaturas(item.count)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          beginAtZero: true,
          ticks: {
            font: { size: 10 },
            callback: (v) => currency.format(v).replace('R$', '').trim(),
          },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });

  charts.set('invoices', chart);
}

function monthBounds(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  const last = new Date(year, month, 0).getDate(); // 0 = last day of previous month
  const pad = (n) => String(n).padStart(2, '0');
  return {
    from: `${year}-${pad(month)}-01`,
    to: `${year}-${pad(month)}-${pad(last)}`,
  };
}

const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
});

function formatDayLabel(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return dayFormatter.format(new Date(year, month - 1, day));
}

const monthLongFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'long',
  year: 'numeric',
});

function formatMonthLong(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  const label = monthLongFormatter.format(new Date(year, month - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

async function openDrilldown(category, month) {
  const modal = document.getElementById('drilldown');
  const color = category.color || FALLBACK_COLOR;
  const total = category.by_month[month] || 0;
  const count = category.counts_by_month[month] || 0;

  document.getElementById('drilldown-color').style.background = color;
  document.getElementById('drilldown-title').textContent =
    `${category.name} · ${formatMonthLong(month)}`;
  document.getElementById('drilldown-subtitle').textContent =
    `${currency.format(total)} · ${pluralCompras(count)}`;

  const body = document.getElementById('drilldown-body');
  body.innerHTML =
    '<p class="text-center text-sm text-slate-500 py-12">Carregando…</p>';
  modal.classList.remove('hidden');

  try {
    const { from, to } = monthBounds(month);
    const params = new URLSearchParams({
      category_id: String(category.id),
      from_date: from,
      to_date: to,
    });
    const response = await fetch(`/transactions?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const txs = await response.json();

    if (txs.length === 0) {
      body.innerHTML =
        '<p class="text-center text-sm text-slate-500 py-12">Sem transações nesse mês.</p>';
      return;
    }

    const rows = txs
      .map(
        (tx) => `
          <li class="flex items-baseline justify-between px-6 py-3 border-t border-slate-100">
            <div class="min-w-0 flex-1 pr-4">
              <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
              <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
            </div>
            <p class="text-sm font-medium tabular text-slate-900 shrink-0">
              ${currency.format(Math.abs(Number(tx.amount)))}
            </p>
          </li>
        `,
      )
      .join('');
    body.innerHTML = `<ul>${rows}</ul>`;
  } catch (err) {
    console.error(err);
    body.innerHTML =
      '<p class="text-center text-sm text-red-600 py-12">Erro ao carregar transações.</p>';
  }
}

function openInvoiceDrilldown(monthData) {
  const modal = document.getElementById('drilldown');

  document.getElementById('drilldown-color').style.background = INVOICE_COLOR;
  document.getElementById('drilldown-title').textContent =
    `Faturas cartão · ${formatMonthLong(monthData.month)}`;
  document.getElementById('drilldown-subtitle').textContent =
    `${currency.format(monthData.total)} · ${pluralFaturas(monthData.count)}`;

  const rows = monthData.transactions
    .map(
      (tx) => `
        <li class="flex items-baseline justify-between px-6 py-3 border-t border-slate-100">
          <div class="min-w-0 flex-1 pr-4">
            <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
            <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
          </div>
          <p class="text-sm font-medium tabular text-slate-900 shrink-0">
            ${currency.format(Number(tx.amount_abs))}
          </p>
        </li>
      `,
    )
    .join('');

  document.getElementById('drilldown-body').innerHTML = `<ul>${rows}</ul>`;
  modal.classList.remove('hidden');
}

function closeDrilldown() {
  document.getElementById('drilldown').classList.add('hidden');
}

document.getElementById('drilldown-close').addEventListener('click', closeDrilldown);
document.getElementById('drilldown').addEventListener('click', (e) => {
  // Click on the backdrop (the modal root itself, not the dialog inside it).
  if (e.target.id === 'drilldown') closeDrilldown();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeDrilldown();
});

function renderEmpty(message, detail) {
  const empty = document.getElementById('empty');
  empty.innerHTML = `
    <p class="text-slate-500">${escapeHtml(message)}</p>
    <p class="text-sm text-slate-400 mt-1">${escapeHtml(detail)}</p>
  `;
  empty.classList.remove('hidden');
}

function hideEmpty() {
  document.getElementById('empty').classList.add('hidden');
}

// Render category spending cards + charts into #cards without touching
// tab-level state (no hideAllTabSections, no destroyCharts).  Called both
// from renderCategoryHistory() (standalone, currently unused) and from
// renderInvoiceHistory() to embed categories below the invoice section.
function renderCategoryContent() {
  const data = categoryHistory;
  const cards = document.getElementById('cards');
  if (!data || data.categories.length === 0 || data.months.length === 0) {
    cards.innerHTML = '';
    cards.classList.add('hidden');
    return;
  }

  const ordered = [...data.categories].sort(
    (a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999),
  );

  cards.innerHTML =
    '<h2 class="col-span-full font-semibold text-slate-900 mb-2">Gastos por categoria</h2>' +
    ordered.map((cat) => renderCard(cat, data.months)).join('');
  cards.classList.remove('hidden');
  // Charts must be created AFTER the canvas elements exist in the DOM.
  ordered.forEach((cat) => renderChart(cat, data.months));
}

function renderCategoryHistory() {
  const data = categoryHistory;
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  hideAllTabSections();

  if (!data || data.categories.length === 0 || data.months.length === 0) {
    renderEmpty(
      'Nenhuma transação encontrada.',
      'Conecte um banco pelo Pluggy primeiro.',
    );
    subtitle.textContent = 'Nenhuma transação ainda';
    return;
  }
  hideEmpty();

  const ordered = [...data.categories].sort(
    (a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999),
  );

  subtitle.textContent =
    `${ordered.length} categoria${ordered.length === 1 ? '' : 's'}` +
    ` · ${data.months.length} ${data.months.length === 1 ? 'mês' : 'meses'}` +
    ` de histórico`;

  renderCategoryContent();
}

function renderInvoiceHistory() {
  const data = invoiceHistory;
  const invoices = document.getElementById('invoices');
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  hideAllTabSections();
  invoices.classList.remove('hidden');

  if (data.total_count === 0 || data.months.length === 0) {
    invoices.innerHTML = '';
    renderEmpty(
      'Nenhum pagamento de fatura encontrado.',
      'Pagamentos ignorados aparecem aqui para auditoria.',
    );
    subtitle.textContent = 'Nenhum pagamento de fatura encontrado';
    return;
  }
  hideEmpty();

  const paidMonths = data.months.filter((item) => item.count > 0);
  const largest = paidMonths.reduce(
    (best, item) => (!best || item.total > best.total ? item : best),
    null,
  );
  const average = data.months.length > 0 ? data.total / data.months.length : 0;
  const rows = [...data.months].reverse().map((item) => {
    const amount = item.count > 0
      ? `
        <button
          type="button"
          class="invoice-month text-right group"
          data-month="${item.month}"
          title="Ver pagamentos da fatura"
        >
          <span class="block text-sm font-semibold tabular text-slate-900 group-hover:text-blue-700">
            ${currency.format(item.total)}
          </span>
        </button>
      `
      : '<span class="text-sm font-medium text-slate-400">Sem pagamento</span>';
    return `
      <li class="flex items-center justify-between gap-4 px-5 py-3 border-t border-slate-100">
        <div>
          <p class="text-sm font-medium text-slate-900">${escapeHtml(formatMonthLong(item.month))}</p>
          <p class="text-xs text-slate-500 mt-0.5">${pluralFaturas(item.count)}</p>
        </div>
        ${amount}
      </li>
    `;
  }).join('');

  subtitle.textContent =
    `Evolução das faturas · últimos ${data.months.length} meses`;

  invoices.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Total pago</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(data.total)}</p>
        <p class="text-xs text-slate-500 mt-2">${pluralFaturas(data.total_count)} em ${data.months.length} meses</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Média mensal</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(average)}</p>
        <p class="text-xs text-slate-500 mt-2">Considerando meses sem pagamento</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Maior fatura</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(largest.total)}</p>
        <p class="text-xs text-slate-500 mt-2">${escapeHtml(formatMonthLabel(largest.month))}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6 lg:col-span-3">
        <h2 class="font-semibold text-slate-900 mb-4">Evolução dos pagamentos de fatura</h2>
        <div class="relative h-64">
          <canvas id="chart-invoices"></canvas>
        </div>
      </div>
    </div>
    <div class="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <div class="px-5 py-4">
        <h2 class="font-semibold text-slate-900">Histórico de faturas</h2>
      </div>
      <ul>${rows}</ul>
    </div>
  `;

  invoices.querySelectorAll('button.invoice-month').forEach((btn) => {
    btn.addEventListener('click', () => {
      const monthData = data.months.find((item) => item.month === btn.dataset.month);
      if (monthData) openInvoiceDrilldown(monthData);
    });
  });

  renderInvoiceChart(data);

  // Show category spending below the invoice history.
  renderCategoryContent();
}

// ── Income (Receitas) tab ───────────────────────────────────────────────

function renderIncomeChart(data) {
  const ctx = document.getElementById('chart-income');
  if (!ctx || typeof Chart === 'undefined') return;
  if (charts.has('income')) charts.get('income').destroy();

  const chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.months.map((m) => formatMonthLabel(m.month)),
      datasets: [{
        data: data.months.map((m) => m.income),
        backgroundColor: INCOME_COLOR,
        borderRadius: 4,
        maxBarThickness: 32,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (evt, elements) => {
        if (elements.length === 0) return;
        const monthData = data.months[elements[0].index];
        if (monthData && monthData.count > 0) openIncomeDrilldown(monthData);
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const item = data.months[ctx.dataIndex];
              return ` ${currency.format(ctx.parsed.y)} · ${pluralRecebimentos(item.count)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          beginAtZero: true,
          ticks: {
            font: { size: 10 },
            callback: (v) => currency.format(v).replace('R$', '').trim(),
          },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });
  charts.set('income', chart);
}

function openIncomeDrilldown(monthData) {
  const modal = document.getElementById('drilldown');
  document.getElementById('drilldown-color').style.background = INCOME_COLOR;
  document.getElementById('drilldown-title').textContent =
    `Receitas · ${formatMonthLong(monthData.month)}`;
  document.getElementById('drilldown-subtitle').textContent =
    `${currency.format(monthData.income)} · ${pluralRecebimentos(monthData.count)}`;

  const rows = (monthData.transactions || []).map((tx) => `
    <li class="flex items-baseline justify-between px-6 py-3 border-t border-slate-100">
      <div class="min-w-0 flex-1 pr-4">
        <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
        <p class="text-xs text-slate-500 mt-0.5">
          ${formatDayLabel(tx.date)}
          ${tx.account_name ? ` · ${escapeHtml(tx.account_name)}` : ''}
          ${tx.pluggy_category ? ` · ${escapeHtml(tx.pluggy_category)}` : ''}
        </p>
      </div>
      <p class="text-sm font-semibold tabular text-emerald-700 shrink-0">
        ${currency.format(Math.abs(Number(tx.amount)))}
      </p>
    </li>
  `).join('');

  document.getElementById('drilldown-body').innerHTML = rows
    ? `<ul>${rows}</ul>`
    : '<p class="text-center text-sm text-slate-500 py-12">Sem transações nesse mês.</p>';
  modal.classList.remove('hidden');
}

function renderExclusionRulesPanel(rules) {
  // Renders the bottom collapsible section on the Receitas tab.
  // Rules are matched against bank-account positive transactions, either
  // by Pluggy category name OR by a substring of the normalized description.
  const list = (rules || []).map((rule) => {
    const kind = rule.pluggy_category
      ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-violet-50 text-violet-700 text-xs font-medium">Categoria Pluggy</span>`
      : `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 text-xs font-medium">Descrição</span>`;
    const value = escapeHtml(rule.pluggy_category || rule.pattern || '—');
    const affected = typeof rule.affected_count === 'number'
      ? `${rule.affected_count.toLocaleString('pt-BR')} ${rule.affected_count === 1 ? 'transação' : 'transações'} excluídas`
      : '';
    return `
      <li class="flex items-center justify-between gap-4 px-5 py-3 border-t border-slate-100">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 mb-0.5">
            ${kind}
            <span class="text-sm font-medium text-slate-900 truncate">${value}</span>
          </div>
          <p class="text-xs text-slate-500">${affected}</p>
        </div>
        <button
          type="button"
          class="rule-delete shrink-0 text-sm text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors"
          data-rule-id="${rule.id}"
          title="Remover regra"
        >Remover</button>
      </li>
    `;
  }).join('');

  return `
    <details class="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <summary class="px-5 py-4 flex items-center justify-between gap-3 select-none cursor-pointer hover:bg-slate-50">
        <div>
          <h2 class="font-semibold text-slate-900">Regras de exclusão de receitas</h2>
          <p class="text-xs text-slate-500 mt-0.5">Filtra transações positivas no banco que não são receita de verdade (transferências, estornos, etc.)</p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <span class="text-xs font-medium text-slate-500">${pluralRegras((rules || []).length)}</span>
          <svg xmlns="http://www.w3.org/2000/svg" class="chevron size-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </summary>
      <div class="border-t border-slate-100 bg-slate-50/50 px-5 py-4">
        <form id="rule-form" class="flex flex-col sm:flex-row gap-2 mb-1">
          <select id="rule-kind" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-50">
            <option value="pluggy_category">Por categoria Pluggy</option>
            <option value="pattern">Por padrão de descrição</option>
          </select>
          <input id="rule-value" type="text" required placeholder="Ex: Transfer, Estorno, PIX recebido"
            class="flex-1 text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-50" />
          <button type="submit"
            class="text-sm font-medium text-white bg-blue-700 hover:bg-blue-800 rounded-lg px-4 py-2 whitespace-nowrap">Adicionar regra</button>
        </form>
        <p class="text-[11px] text-slate-400 mt-2">Ao salvar ou remover uma regra, receitas e balanço são recalculados na hora.</p>
      </div>
      ${list ? `<ul class="bg-white">${list}</ul>` : '<p class="px-5 py-6 text-sm text-center text-slate-500 border-t border-slate-100 bg-white">Nenhuma regra cadastrada.</p>'}
    </details>
  `;
}

function bindExclusionRulesEvents(section) {
  const form = section.querySelector('#rule-form');
  if (form) {
    form.addEventListener('submit', async (evt) => {
      evt.preventDefault();
      const kind = section.querySelector('#rule-kind').value;
      const value = section.querySelector('#rule-value').value.trim();
      if (!value) return;
      const body = kind === 'pluggy_category'
        ? { pluggy_category: value }
        : { pattern: value };
      try {
        const response = await fetch('/bank-income/exclusion-rules', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          showToast(err.detail || `Falha ao criar regra (HTTP ${response.status})`, 'error');
          return;
        }
        await loadData();
        showToast('Regra criada e histórico recalculado.', 'success');
      } catch (err) {
        console.error(err);
        showToast('Erro ao criar regra.', 'error');
      }
    });
  }

  section.querySelectorAll('button.rule-delete').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Remover esta regra?')) return;
      const id = btn.dataset.ruleId;
      try {
        const response = await fetch(`/bank-income/exclusion-rules/${id}`, {
          method: 'DELETE',
        });
        if (!response.ok && response.status !== 204) {
          showToast(`Falha ao remover (HTTP ${response.status})`, 'error');
          return;
        }
        await loadData();
        showToast('Regra removida e histórico recalculado.', 'success');
      } catch (err) {
        console.error(err);
        showToast('Erro ao remover regra.', 'error');
      }
    });
  });
}

function renderIncomeHistory() {
  const data = incomeHistory;
  const section = document.getElementById('income-tab');
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  hideAllTabSections();
  section.classList.remove('hidden');

  const monthsWithIncome = (data.months || []).filter((m) => m.count > 0);
  if (monthsWithIncome.length === 0) {
    section.innerHTML = renderExclusionRulesPanel(exclusionRules);
    bindExclusionRulesEvents(section);
    renderEmpty(
      'Nenhuma receita encontrada.',
      'Conecte uma conta bancária ou ajuste as regras de exclusão.',
    );
    subtitle.textContent = 'Nenhuma receita';
    return;
  }
  hideEmpty();

  const largest = monthsWithIncome.reduce(
    (best, m) => (!best || m.income > best.income ? m : best),
    null,
  );
  const average = (data.total_income || 0) / data.months.length;

  const rows = [...data.months].reverse().map((item) => {
    const amount = item.count > 0
      ? `
        <button type="button" class="income-month text-right group"
          data-month="${item.month}" title="Ver recebimentos">
          <span class="block text-sm font-semibold tabular text-emerald-700 group-hover:text-emerald-800">
            ${currency.format(item.income)}
          </span>
        </button>
      `
      : '<span class="text-sm font-medium text-slate-400">Sem recebimento</span>';
    return `
      <li class="flex items-center justify-between gap-4 px-5 py-3 border-t border-slate-100">
        <div>
          <p class="text-sm font-medium text-slate-900">${escapeHtml(formatMonthLong(item.month))}</p>
          <p class="text-xs text-slate-500 mt-0.5">${pluralRecebimentos(item.count)}</p>
        </div>
        ${amount}
      </li>
    `;
  }).join('');

  subtitle.textContent =
    `Evolução das receitas · ${pluralMeses(data.months.length)}` +
    (data.bank_account_count
      ? ` · ${data.bank_account_count} ${data.bank_account_count === 1 ? 'conta' : 'contas'}`
      : '');

  section.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Total recebido</p>
        <p class="mt-2 text-2xl font-bold tabular text-emerald-700">${currency.format(data.total_income)}</p>
        <p class="text-xs text-slate-500 mt-2">${pluralRecebimentos(data.transaction_count)} em ${pluralMeses(data.months.length)}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Média mensal</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(average)}</p>
        <p class="text-xs text-slate-500 mt-2">Considerando todos os meses</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Maior mês</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(largest.income)}</p>
        <p class="text-xs text-slate-500 mt-2">${escapeHtml(formatMonthLabel(largest.month))}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6 lg:col-span-3">
        <h2 class="font-semibold text-slate-900 mb-4">Evolução das receitas bancárias</h2>
        <div class="relative h-64"><canvas id="chart-income"></canvas></div>
      </div>
    </div>
    <div class="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <div class="px-5 py-4">
        <h2 class="font-semibold text-slate-900">Histórico mensal</h2>
      </div>
      <ul>${rows}</ul>
    </div>
    ${renderExclusionRulesPanel(exclusionRules)}
  `;

  section.querySelectorAll('button.income-month').forEach((btn) => {
    btn.addEventListener('click', () => {
      const monthData = data.months.find((item) => item.month === btn.dataset.month);
      if (monthData) openIncomeDrilldown(monthData);
    });
  });
  bindExclusionRulesEvents(section);

  renderIncomeChart(data);
}

// ── Cashflow (Entradas e saídas) tab ────────────────────────────────────
//
// Computed entirely from bank transactions to avoid the double-counting that
// would happen if we summed credit-card spend AND its eventual invoice
// payment. Entradas = positive amounts hitting bank accounts; saídas = the
// absolute value of negative amounts (which already include invoice
// payments). Net = entradas − saídas is the true cash flow through your
// bank accounts.

function summarizeCashflow(data) {
  const months = (data?.months || []).map((month) => {
    const transactions = month.transactions || [];
    return {
      month: month.month,
      entradas: month.income || 0,
      saidas: month.outflow || 0,
      net: month.net || 0,
      entradas_count: month.income_count || 0,
      saidas_count: month.outflow_count || 0,
      entradas_txs: transactions.filter((tx) => Number(tx.amount) > 0),
      saidas_txs: transactions.filter((tx) => Number(tx.amount) < 0),
    };
  }).filter(
    (month) =>
      month.entradas_count > 0 ||
      month.saidas_count > 0 ||
      month.entradas > 0 ||
      month.saidas > 0,
  );

  return {
    months,
    total_entradas: data?.summary?.income || 0,
    total_saidas: data?.summary?.outflow || 0,
    total_entradas_count: months.reduce((sum, m) => sum + m.entradas_count, 0),
    total_saidas_count: months.reduce((sum, m) => sum + m.saidas_count, 0),
    net: data?.summary?.net || 0,
  };
}

function renderCashflowChart(summary) {
  const ctx = document.getElementById('chart-cashflow');
  if (!ctx || typeof Chart === 'undefined') return;
  if (charts.has('cashflow')) charts.get('cashflow').destroy();

  const labels = summary.months.map((m) => formatMonthLabel(m.month));
  const chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Entradas',
          data: summary.months.map((m) => m.entradas),
          backgroundColor: INCOME_COLOR,
          borderRadius: 4,
          maxBarThickness: 28,
        },
        {
          label: 'Saídas',
          data: summary.months.map((m) => m.saidas),
          backgroundColor: '#ef4444',
          borderRadius: 4,
          maxBarThickness: 28,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (evt, elements) => {
        if (elements.length === 0) return;
        const idx = elements[0].index;
        const monthData = summary.months[idx];
        if (monthData) openCashflowDrilldown(monthData);
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.dataset.label}: ${currency.format(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          beginAtZero: true,
          ticks: {
            font: { size: 10 },
            callback: (v) => currency.format(v).replace('R$', '').trim(),
          },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });
  charts.set('cashflow', chart);
}

function openCashflowDrilldown(monthData) {
  // Combined modal showing entradas (green) on top and saídas (red) below,
  // both sorted by absolute amount desc so the biggest movers surface first.
  const modal = document.getElementById('drilldown');
  document.getElementById('drilldown-color').style.background = INCOME_COLOR;
  document.getElementById('drilldown-title').textContent =
    `Entradas e saídas · ${formatMonthLong(monthData.month)}`;
  const netSign = monthData.net >= 0 ? '+' : '−';
  document.getElementById('drilldown-subtitle').textContent =
    `Entradas ${currency.format(monthData.entradas)} · Saídas ${currency.format(monthData.saidas)} · Saldo ${netSign}${currency.format(Math.abs(monthData.net))}`;

  const renderTxs = (txs, color, sign) => txs
    .slice()
    .sort((a, b) => Math.abs(Number(b.amount)) - Math.abs(Number(a.amount)))
    .map((tx) => `
      <li class="flex items-baseline justify-between px-6 py-3 border-t border-slate-100">
        <div class="min-w-0 flex-1 pr-4">
          <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
          <p class="text-xs text-slate-500 mt-0.5">
            ${formatDayLabel(tx.date)}
            ${tx.account_name ? ` · ${escapeHtml(tx.account_name)}` : ''}
          </p>
        </div>
        <p class="text-sm font-semibold tabular ${color} shrink-0">
          ${sign}${currency.format(Math.abs(Number(tx.amount)))}
        </p>
      </li>
    `).join('');

  const sectionHeader = (label, total, count, color) => `
    <div class="px-6 py-3 bg-slate-50 flex items-center justify-between text-xs uppercase tracking-wider font-medium ${color}">
      <span>${label} · ${count} ${count === 1 ? 'item' : 'itens'}</span>
      <span class="tabular">${currency.format(total)}</span>
    </div>
  `;

  const body = [];
  if (monthData.entradas_count > 0) {
    body.push(sectionHeader('Entradas', monthData.entradas, monthData.entradas_count, 'text-emerald-700'));
    body.push(`<ul>${renderTxs(monthData.entradas_txs, 'text-emerald-700', '+')}</ul>`);
  }
  if (monthData.saidas_count > 0) {
    body.push(sectionHeader('Saídas', monthData.saidas, monthData.saidas_count, 'text-red-700'));
    body.push(`<ul>${renderTxs(monthData.saidas_txs, 'text-red-700', '−')}</ul>`);
  }
  if (body.length === 0) {
    body.push('<p class="text-center text-sm text-slate-500 py-12">Sem transações nesse mês.</p>');
  }

  document.getElementById('drilldown-body').innerHTML = body.join('');
  modal.classList.remove('hidden');
}

function renderCashflowRulesPanel(rules) {
  const list = (rules || []).map((rule) => {
    const kind = rule.pluggy_category
      ? '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-violet-50 text-violet-700 text-xs font-medium">Categoria Pluggy</span>'
      : '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 text-xs font-medium">Descrição</span>';
    const value = escapeHtml(rule.pluggy_category || rule.pattern || '—');
    const affected = typeof rule.affected_count === 'number'
      ? `${rule.affected_count.toLocaleString('pt-BR')} ${rule.affected_count === 1 ? 'transação removida' : 'transações removidas'}`
      : '';
    return `
      <li class="flex items-center justify-between gap-4 px-5 py-3 border-t border-slate-100">
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2 mb-0.5">
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-xs font-medium">${cashflowDirectionLabel(rule.direction)}</span>
            ${kind}
            <span class="text-sm font-medium text-slate-900 truncate">${value}</span>
          </div>
          <p class="text-xs text-slate-500">${affected}</p>
        </div>
        <button
          type="button"
          class="cashflow-rule-delete shrink-0 text-sm text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors"
          data-rule-id="${rule.id}"
          title="Remover regra"
        >Remover</button>
      </li>
    `;
  }).join('');

  return `
    <details class="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <summary class="px-5 py-4 flex items-center justify-between gap-3 select-none cursor-pointer hover:bg-slate-50">
        <div>
          <h2 class="font-semibold text-slate-900">Regras do fluxo de caixa</h2>
          <p class="text-xs text-slate-500 mt-0.5">Remove investimentos, transferências internas e outros ruídos das entradas e saídas bancárias.</p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <span class="text-xs font-medium text-slate-500">${pluralRegras((rules || []).length)}</span>
          <svg xmlns="http://www.w3.org/2000/svg" class="chevron size-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </summary>
      <div class="border-t border-slate-100 bg-slate-50/50 px-5 py-4">
        <form id="cashflow-rule-form" class="flex flex-col lg:flex-row gap-2 mb-1">
          <select id="cashflow-rule-direction" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-50">
            <option value="ALL">Entradas e saídas</option>
            <option value="IN">Somente entradas</option>
            <option value="OUT">Somente saídas</option>
          </select>
          <select id="cashflow-rule-kind" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-50">
            <option value="pluggy_category">Por categoria Pluggy</option>
            <option value="pattern">Por padrão de descrição</option>
          </select>
          <input id="cashflow-rule-value" type="text" required placeholder="Ex: Fixed income, Resgate CDB, Same person transfer"
            class="flex-1 text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-50" />
          <button type="submit"
            class="text-sm font-medium text-white bg-blue-700 hover:bg-blue-800 rounded-lg px-4 py-2 whitespace-nowrap">Adicionar regra</button>
        </form>
        <p class="text-[11px] text-slate-400 mt-2">Essas regras afetam apenas a aba Entradas e saídas.</p>
      </div>
      ${list ? `<ul class="bg-white">${list}</ul>` : '<p class="px-5 py-6 text-sm text-center text-slate-500 border-t border-slate-100 bg-white">Nenhuma regra cadastrada.</p>'}
    </details>
  `;
}

function bindCashflowRulesEvents(section) {
  const form = section.querySelector('#cashflow-rule-form');
  if (form) {
    form.addEventListener('submit', async (evt) => {
      evt.preventDefault();
      const direction = section.querySelector('#cashflow-rule-direction').value;
      const kind = section.querySelector('#cashflow-rule-kind').value;
      const value = section.querySelector('#cashflow-rule-value').value.trim();
      if (!value) return;
      const body = kind === 'pluggy_category'
        ? { direction, pluggy_category: value }
        : { direction, pattern: value };
      try {
        const response = await fetch('/bank-cashflow/exclusion-rules', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          showToast(err.detail || `Falha ao criar regra (HTTP ${response.status})`, 'error');
          return;
        }
        await loadData();
        showToast('Regra criada e fluxo recalculado.', 'success');
      } catch (err) {
        console.error(err);
        showToast('Erro ao criar regra.', 'error');
      }
    });
  }

  section.querySelectorAll('button.cashflow-rule-delete').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Remover esta regra?')) return;
      try {
        const response = await fetch(`/bank-cashflow/exclusion-rules/${btn.dataset.ruleId}`, {
          method: 'DELETE',
        });
        if (!response.ok && response.status !== 204) {
          showToast(`Falha ao remover (HTTP ${response.status})`, 'error');
          return;
        }
        await loadData();
        showToast('Regra removida e fluxo recalculado.', 'success');
      } catch (err) {
        console.error(err);
        showToast('Erro ao remover regra.', 'error');
      }
    });
  });
}

function renderCashflow() {
  const section = document.getElementById('cashflow-tab');
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  hideAllTabSections();
  section.classList.remove('hidden');

  const summary = summarizeCashflow(cashflowData);

  if (summary.months.length === 0) {
    section.innerHTML = '';
    renderEmpty(
      'Sem entradas ou saídas nos últimos 12 meses.',
      'Conecte uma conta bancária pelo Pluggy para começar a acompanhar o fluxo de caixa.',
    );
    subtitle.textContent = 'Sem fluxo de caixa';
    return;
  }
  hideEmpty();

  subtitle.textContent =
    `Fluxo de caixa bancário · ${pluralMeses(summary.months.length)} ativos`;

  const netSign = summary.net >= 0 ? '+' : '−';
  const netColor = summary.net >= 0 ? 'text-emerald-700' : 'text-red-700';

  const tableRows = [...summary.months].reverse().map((m) => {
    const monthNetSign = m.net >= 0 ? '+' : '−';
    const monthNetColor = m.net >= 0 ? 'text-emerald-700' : 'text-red-700';
    return `
      <tr class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer cashflow-row" data-month="${m.month}">
        <td class="px-5 py-3 text-sm font-medium text-slate-900 whitespace-nowrap">${escapeHtml(formatMonthLong(m.month))}</td>
        <td class="px-5 py-3 text-right text-sm text-emerald-700 tabular">
          ${m.entradas > 0 ? currency.format(m.entradas) : '<span class="text-slate-400">—</span>'}
          ${m.entradas_count > 0 ? `<span class="block text-[11px] text-slate-400 font-normal">${m.entradas_count} ${m.entradas_count === 1 ? 'entrada' : 'entradas'}</span>` : ''}
        </td>
        <td class="px-5 py-3 text-right text-sm text-red-700 tabular">
          ${m.saidas > 0 ? currency.format(m.saidas) : '<span class="text-slate-400">—</span>'}
          ${m.saidas_count > 0 ? `<span class="block text-[11px] text-slate-400 font-normal">${m.saidas_count} ${m.saidas_count === 1 ? 'saída' : 'saídas'}</span>` : ''}
        </td>
        <td class="px-5 py-3 text-right text-sm tabular font-medium ${monthNetColor}">
          ${monthNetSign}${currency.format(Math.abs(m.net))}
        </td>
      </tr>
    `;
  }).join('');

  section.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Total de entradas</p>
        <p class="mt-2 text-2xl font-bold tabular text-emerald-700">${currency.format(summary.total_entradas)}</p>
        <p class="text-xs text-slate-500 mt-2">${summary.total_entradas_count.toLocaleString('pt-BR')} ${summary.total_entradas_count === 1 ? 'crédito' : 'créditos'} em ${pluralMeses(summary.months.length)}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Total de saídas</p>
        <p class="mt-2 text-2xl font-bold tabular text-red-700">${currency.format(summary.total_saidas)}</p>
        <p class="text-xs text-slate-500 mt-2">${summary.total_saidas_count.toLocaleString('pt-BR')} ${summary.total_saidas_count === 1 ? 'débito' : 'débitos'} (inclui pagamentos de fatura)</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Saldo (entradas − saídas)</p>
        <p class="mt-2 text-2xl font-bold tabular ${netColor}">${netSign}${currency.format(Math.abs(summary.net))}</p>
        <p class="text-xs text-slate-500 mt-2">Fluxo de caixa líquido no período</p>
      </div>
    </div>

    <div class="bg-white rounded-lg border border-slate-200 p-6">
      <h2 class="font-semibold text-slate-900 mb-1">Entradas vs saídas por mês</h2>
      <p class="text-xs text-slate-500 mb-4">Clique numa barra para ver as transações do mês</p>
      <div class="relative h-72"><canvas id="chart-cashflow"></canvas></div>
    </div>

    <div class="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <h2 class="font-semibold text-slate-900">Detalhamento mensal</h2>
        <p class="text-xs text-slate-500">Apenas movimentações bancárias — cartão de crédito aparece quando a fatura é paga</p>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="text-xs uppercase tracking-wider text-slate-500 bg-slate-50">
              <th class="px-5 py-2 text-left font-medium">Mês</th>
              <th class="px-5 py-2 text-right font-medium">Entradas</th>
              <th class="px-5 py-2 text-right font-medium">Saídas</th>
              <th class="px-5 py-2 text-right font-medium">Saldo</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
    </div>
    ${renderCashflowRulesPanel(cashflowRules)}
  `;

  section.querySelectorAll('tr.cashflow-row').forEach((row) => {
    row.addEventListener('click', () => {
      const monthData = summary.months.find((m) => m.month === row.dataset.month);
      if (monthData) openCashflowDrilldown(monthData);
    });
  });

  renderCashflowChart(summary);
  bindCashflowRulesEvents(section);
}

function hideAllTabSections() {
  ['cards', 'invoices', 'income-tab', 'cashflow-tab', 'planning-tab'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.classList.add('hidden');
      // Don't blow away `cards` content — renderCategoryHistory needs the
      // existing canvas elements; just hide it.
    }
  });
}

function renderUnavailable(message, detail) {
  destroyCharts();
  hideAllTabSections();
  renderEmpty(message, detail);
}

function renderActiveTab() {
  if (activeTab === 'invoices') {
    if (!invoiceHistory) {
      renderUnavailable(
        'Não foi possível carregar as faturas.',
        'Tente atualizar novamente em alguns segundos.',
      );
      return;
    }
    renderInvoiceHistory();
  } else if (activeTab === 'income') {
    if (!incomeHistory) {
      renderUnavailable(
        'Não foi possível carregar as receitas.',
        'Tente atualizar novamente em alguns segundos.',
      );
      return;
    }
    renderIncomeHistory();
  } else if (activeTab === 'cashflow') {
    if (!cashflowData) {
      renderUnavailable(
        'Não foi possível carregar entradas e saídas.',
        'Tente atualizar novamente em alguns segundos.',
      );
      return;
    }
    renderCashflow();
  }
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} retornou HTTP ${response.status}`);
  return response.json();
}

async function loadData() {
  const requests = [
    ['categories', fetchJson('/stats/monthly')],
    ['invoices', fetchJson('/credit-card-payments/monthly?months=12')],
    ['income', fetchJson('/bank-income/monthly?months=12')],
    ['rules', fetchJson('/bank-income/exclusion-rules')],
    ['cashflow', fetchJson('/bank-cashflow/monthly?months=12')],
    ['cashflowRules', fetchJson('/bank-cashflow/exclusion-rules')],
  ];
  const results = await Promise.allSettled(requests.map(([, request]) => request));
  const failures = [];

  results.forEach((result, index) => {
    const key = requests[index][0];
    if (result.status === 'rejected') {
      failures.push(key);
      console.error(result.reason);
      return;
    }
    if (key === 'categories') categoryHistory = result.value;
    if (key === 'invoices') invoiceHistory = result.value;
    if (key === 'income') incomeHistory = result.value;
    if (key === 'rules') exclusionRules = result.value;
    if (key === 'cashflow') cashflowData = result.value;
    if (key === 'cashflowRules') cashflowRules = result.value;
  });

  if (!exclusionRules) exclusionRules = [];
  if (!cashflowRules) cashflowRules = [];
  if (
    !categoryHistory && !invoiceHistory && !incomeHistory &&
    !cashflowData
  ) {
    throw new Error('Falha ao carregar histórico');
  }

  renderTabs();
  renderActiveTab();
  if (failures.length > 0) {
    showToast('Alguns dados do histórico não carregaram.', 'error');
  }
}

document.getElementById('refresh').addEventListener('click', () => {
  loadData().catch((err) => {
    console.error(err);
    document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
  });
});

loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
