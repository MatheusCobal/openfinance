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
const INVOICE_COLOR = '#475569';
const HISTORY_TABS = [
  { key: 'categories', label: 'Categorias' },
  { key: 'invoices', label: 'Faturas cartão' },
];

let activeTab = 'categories';
let categoryHistory = null;
let invoiceHistory = null;

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

function pluralCompras(n) {
  return n === 1 ? '1 compra' : `${n.toLocaleString('pt-BR')} compras`;
}

function pluralFaturas(n) {
  return n === 1 ? '1 pagamento' : `${n.toLocaleString('pt-BR')} pagamentos`;
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
      ? `${base} bg-indigo-600 text-white shadow-sm`
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
    <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
      <div class="flex items-baseline justify-between mb-1">
        <div class="flex items-center gap-2 min-w-0">
          <span class="inline-block size-3 rounded-full shrink-0" style="background:${color}"></span>
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

function renderCategoryHistory() {
  const data = categoryHistory;
  const cards = document.getElementById('cards');
  const invoices = document.getElementById('invoices');
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  cards.classList.remove('hidden');
  invoices.classList.add('hidden');
  invoices.innerHTML = '';

  if (data.categories.length === 0 || data.months.length === 0) {
    cards.innerHTML = '';
    renderEmpty(
      'Nenhuma transação encontrada.',
      'Conecte um banco no dashboard primeiro.',
    );
    subtitle.textContent = 'Nenhuma transação ainda';
    return;
  }
  hideEmpty();

  // Sort by sort_order so categories appear in a stable, intentional order
  // (Mercado first, Outros last), independent of total.
  const ordered = [...data.categories].sort(
    (a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999),
  );

  subtitle.textContent =
    `${ordered.length} categoria${ordered.length === 1 ? '' : 's'}` +
    ` · ${data.months.length} ${data.months.length === 1 ? 'mês' : 'meses'}` +
    ` de histórico`;

  cards.innerHTML = ordered.map((cat) => renderCard(cat, data.months)).join('');
  // Charts must be created AFTER the canvas elements exist in the DOM.
  ordered.forEach((cat) => renderChart(cat, data.months));
}

function renderInvoiceHistory() {
  const data = invoiceHistory;
  const cards = document.getElementById('cards');
  const invoices = document.getElementById('invoices');
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  cards.classList.add('hidden');
  cards.innerHTML = '';
  invoices.classList.remove('hidden');

  if (data.total_count === 0 || data.months.length === 0) {
    invoices.innerHTML = '';
    renderEmpty(
      'Nenhum pagamento de fatura encontrado.',
      'Pagamentos ignorados dos dashboards aparecem aqui para auditoria.',
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
          <span class="block text-sm font-semibold tabular text-slate-900 group-hover:text-indigo-600">
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
      <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Total pago</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(data.total)}</p>
        <p class="text-xs text-slate-500 mt-2">${pluralFaturas(data.total_count)} em ${data.months.length} meses</p>
      </div>
      <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Média mensal</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(average)}</p>
        <p class="text-xs text-slate-500 mt-2">Considerando meses sem pagamento</p>
      </div>
      <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Maior fatura</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(largest.total)}</p>
        <p class="text-xs text-slate-500 mt-2">${escapeHtml(formatMonthLabel(largest.month))}</p>
      </div>
      <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm lg:col-span-3">
        <h2 class="font-semibold text-slate-900 mb-4">Evolução dos pagamentos de fatura</h2>
        <div class="relative h-64">
          <canvas id="chart-invoices"></canvas>
        </div>
      </div>
    </div>
    <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
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
}

function renderActiveTab() {
  if (!categoryHistory || !invoiceHistory) return;
  if (activeTab === 'invoices') {
    renderInvoiceHistory();
  } else {
    renderCategoryHistory();
  }
}

async function loadData() {
  const [categoriesResponse, invoicesResponse] = await Promise.all([
    fetch('/stats/monthly'),
    fetch('/credit-card-payments/monthly?months=12'),
  ]);
  if (!categoriesResponse.ok || !invoicesResponse.ok) {
    throw new Error('Falha ao carregar histórico');
  }

  categoryHistory = await categoriesResponse.json();
  invoiceHistory = await invoicesResponse.json();
  renderTabs();
  renderActiveTab();
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
