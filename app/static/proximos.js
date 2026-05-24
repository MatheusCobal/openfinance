const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
});

const monthLongFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'long',
  year: 'numeric',
});

const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
});

const FALLBACK_COLOR = '#64748b';

let allData = null;
let selectedMonth = null;
let monthChart = null;

function formatMonthShort(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthFormatter.format(new Date(year, month - 1, 1));
}

function formatMonthLong(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  const label = monthLongFormatter.format(new Date(year, month - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatDayLabel(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return dayFormatter.format(new Date(year, month - 1, day));
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function pluralParcelas(n) {
  return n === 1 ? '1 parcela' : `${n.toLocaleString('pt-BR')} parcelas`;
}

function renderOverview() {
  const months = allData.months || [];
  const next = months[0] || null;
  const firstThree = months.slice(0, 3);
  const totalFuture = months.reduce((sum, month) => sum + Number(month.total), 0);
  const totalCount = months.reduce((sum, month) => sum + Number(month.count), 0);
  const quarterTotal = firstThree.reduce((sum, month) => sum + Number(month.total), 0);
  const quarterCount = firstThree.reduce((sum, month) => sum + Number(month.count), 0);
  const largest = months.reduce(
    (best, month) => (!best || Number(month.total) > Number(best.total) ? month : best),
    null,
  );

  document.getElementById('summary-next-total').textContent = next
    ? currency.format(next.total)
    : '—';
  document.getElementById('summary-next-label').textContent = next
    ? `${formatMonthLong(next.month)} · ${pluralParcelas(next.count)}`
    : 'Sem parcelas';
  document.getElementById('summary-quarter-total').textContent =
    currency.format(quarterTotal);
  document.getElementById('summary-quarter-count').textContent =
    pluralParcelas(quarterCount);
  document.getElementById('summary-future-total').textContent =
    currency.format(totalFuture);
  document.getElementById('summary-future-count').textContent =
    pluralParcelas(totalCount);
  document.getElementById('summary-largest-total').textContent = largest
    ? currency.format(largest.total)
    : '—';
  document.getElementById('summary-largest-label').textContent = largest
    ? `${formatMonthLong(largest.month)} · ${pluralParcelas(largest.count)}`
    : 'Sem parcelas';
}

function renderMonthChart() {
  const ctx = document.getElementById('month-chart');
  if (!ctx) return;
  const panel = document.getElementById('month-chart-panel');
  if (typeof Chart === 'undefined') {
    if (monthChart) {
      monthChart.destroy();
      monthChart = null;
    }
    panel?.classList.add('hidden');
    return;
  }
  panel?.classList.remove('hidden');
  if (monthChart) monthChart.destroy();

  monthChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: allData.months.map((month) => formatMonthShort(month.month)),
      datasets: [
        {
          data: allData.months.map((month) => month.total),
          backgroundColor: '#4f46e5',
          borderRadius: 6,
          maxBarThickness: 36,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (evt, elements) => {
        if (elements.length === 0) return;
        selectedMonth = allData.months[elements[0].index].month;
        renderAll();
      },
      onHover: (evt, elements) => {
        evt.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const month = allData.months[ctx.dataIndex];
              return ` ${currency.format(ctx.parsed.y)} · ${pluralParcelas(month.count)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          beginAtZero: true,
          ticks: {
            callback: (v) => currency.format(v).replace('R$', '').trim(),
          },
          grid: { color: '#f1f5f9' },
        },
      },
    },
  });
}

function renderChips() {
  const strip = document.getElementById('chip-strip');
  const html = allData.months
    .map((month) => {
      const isActive = month.month === selectedMonth;
      const base =
        'shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-colors';
      const cls = isActive
        ? `${base} bg-indigo-600 text-white shadow-sm`
        : `${base} bg-white border border-slate-200 text-slate-700 hover:bg-slate-100`;
      return `
        <button class="${cls}" data-month="${month.month}">
          ${escapeHtml(formatMonthShort(month.month))}
        </button>
      `;
    })
    .join('');
  strip.innerHTML = html;

  strip.querySelectorAll('button[data-month]').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectedMonth = btn.dataset.month;
      renderAll();
      btn.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
    });
  });
}

function renderMonthSummary() {
  const month = allData.months.find((item) => item.month === selectedMonth);
  const summary = document.getElementById('month-summary');
  if (!month) {
    summary.classList.add('hidden');
    return;
  }
  summary.classList.remove('hidden');
  document.getElementById('month-label').textContent = formatMonthLong(month.month);
  document.getElementById('month-total').textContent = currency.format(month.total);
  document.getElementById('month-count').textContent = pluralParcelas(month.count);
}

function transactionRows(transactions) {
  return transactions
    .map(
      (tx) => `
        <li class="flex items-baseline justify-between px-5 py-3 border-t border-slate-100">
          <div class="min-w-0 flex-1 pr-4">
            <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
            <p class="text-xs text-slate-500 mt-0.5">
              ${formatDayLabel(tx.date)}
              ${tx.category_name ? ` · ${escapeHtml(tx.category_name)}` : ''}
            </p>
          </div>
          <p class="text-sm font-medium tabular text-slate-900 shrink-0">
            ${currency.format(tx.amount)}
          </p>
        </li>
      `,
    )
    .join('');
}

function renderCategories() {
  const container = document.getElementById('categories');
  const month = allData.months.find((item) => item.month === selectedMonth);
  if (!month || month.categories.length === 0) {
    container.innerHTML = `
      <div class="text-center py-12 text-sm text-slate-500">
        Nenhuma parcela prevista para esse mês.
      </div>
    `;
    return;
  }

  const html = month.categories
    .map((category) => {
      const color = category.color || FALLBACK_COLOR;
      const rows = transactionRows(
        category.transactions.map((tx) => ({
          ...tx,
          category_name: category.name,
          category_color: color,
        })),
      );

      return `
        <details class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <summary class="flex items-center gap-3 px-5 py-4 hover:bg-slate-50">
            <span class="chevron text-slate-400">
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </span>
            <span class="inline-block size-3 rounded-full shrink-0" style="background:${color}"></span>
            <span class="font-medium text-slate-900 flex-1">${escapeHtml(category.name)}</span>
            <span class="text-xs text-slate-500 tabular">${pluralParcelas(category.count)}</span>
            <span class="font-semibold tabular text-slate-900 ml-3">${currency.format(category.total)}</span>
          </summary>
          <ul>${rows}</ul>
        </details>
      `;
    })
    .join('');

  container.innerHTML = html;
}

function renderAll() {
  renderOverview();
  renderMonthChart();
  renderChips();
  renderMonthSummary();
  renderCategories();
}

async function loadData() {
  const response = await fetch('/upcoming');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  allData = await response.json();

  const subtitle = document.getElementById('subtitle');
  const empty = document.getElementById('empty');
  const overview = document.getElementById('overview');
  const monthChartPanel = document.getElementById('month-chart-panel');
  const summary = document.getElementById('month-summary');

  if (!allData.months || allData.months.length === 0) {
    document.getElementById('chip-strip').innerHTML = '';
    document.getElementById('categories').innerHTML = '';
    if (monthChart) monthChart.destroy();
    monthChart = null;
    summary.classList.add('hidden');
    overview.classList.add('hidden');
    monthChartPanel.classList.add('hidden');
    empty.classList.remove('hidden');
    subtitle.textContent = 'Nenhuma parcela a vencer';
    return;
  }
  empty.classList.add('hidden');
  overview.classList.remove('hidden');
  monthChartPanel.classList.remove('hidden');

  subtitle.textContent =
    `${pluralParcelas(allData.total_count)} em ${allData.months.length} ` +
    (allData.months.length === 1 ? 'mês' : 'meses');

  if (selectedMonth === null || !allData.months.some((month) => month.month === selectedMonth)) {
    selectedMonth = allData.months[0].month;
  }
  renderAll();
}

document.getElementById('refresh').addEventListener('click', () => {
  loadData().catch((err) => {
    console.error(err);
    document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
  });
});

document.addEventListener('keydown', (e) => {
  if (!allData || allData.months.length === 0) return;
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  if (e.target.matches('input, textarea')) return;
  const idx = allData.months.findIndex((month) => month.month === selectedMonth);
  const next = e.key === 'ArrowRight' ? idx + 1 : idx - 1;
  if (next < 0 || next >= allData.months.length) return;
  selectedMonth = allData.months[next].month;
  renderAll();
});

loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
