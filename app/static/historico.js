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

function findLastNonZeroMonth(byMonth, months) {
  for (let i = months.length - 1; i >= 0; i--) {
    const m = months[i];
    if ((byMonth[m] || 0) > 0) return m;
  }
  return null;
}

function renderCard(category, months) {
  const color = category.color || FALLBACK_COLOR;
  const totalCount = Object.values(category.counts_by_month).reduce(
    (a, b) => a + b,
    0,
  );
  const lastMonth = findLastNonZeroMonth(category.by_month, months);
  const lastValue = lastMonth ? category.by_month[lastMonth] : 0;
  const lastLabel = lastMonth
    ? `${formatMonthLabel(lastMonth)}: ${currency.format(lastValue)}`
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
        ${pluralCompras(totalCount)} · último: ${escapeHtml(lastLabel)}
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

async function loadData() {
  const response = await fetch('/stats/monthly');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();

  const cards = document.getElementById('cards');
  const empty = document.getElementById('empty');
  const subtitle = document.getElementById('subtitle');

  if (data.categories.length === 0 || data.months.length === 0) {
    cards.innerHTML = '';
    empty.classList.remove('hidden');
    subtitle.textContent = 'Nenhuma transação ainda';
    return;
  }
  empty.classList.add('hidden');

  // Sort by sort_order so categories appear in a stable, intentional order
  // (Alimentação first, Outros last), independent of total.
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
