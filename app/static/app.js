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

function renderCategories(stats, transactions) {
  const container = document.getElementById('categories');
  const empty = document.getElementById('empty');
  transactionsById = new Map(transactions.map((tx) => [tx.id, tx]));

  if (transactions.length === 0) {
    container.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  const groups = groupTransactionsByCategoryId(transactions);
  const orderedCategories = stats.categories;

  const renderTxRow = (tx) => `
    <li class="flex items-center justify-between gap-3 px-5 py-3 border-t border-slate-100">
      <div class="min-w-0 flex-1 pr-4">
        <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
        <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
      </div>
      <div class="flex items-center gap-3 shrink-0">
        <p class="text-sm font-medium tabular text-slate-900">
          ${currency.format(Math.abs(Number(tx.amount)))}
        </p>
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

  const html = orderedCategories
    .map((cat) => {
      const txs = groups.get(cat.id) || [];
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
              <div class="flex items-center justify-between gap-3">
                <span class="font-bold text-slate-900">${escapeHtml(cat.name)}</span>
                <span class="font-bold tabular shrink-0" style="color:${color}">${currency.format(cat.total)}</span>
              </div>
              <p class="text-xs text-slate-500 mt-1">${cat.count} ${cat.count === 1 ? 'compra' : 'compras'}</p>
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

// Append a two-digit hex alpha byte to a #RRGGBB color string so it can be
// used as a CSS background color with partial transparency.
function hexWithAlpha(hex, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
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

function updateExportLink() {
  const { from, to } = rangeForPeriod(activePeriod);
  const params = new URLSearchParams();
  if (from) params.set('from_date', from);
  if (to) params.set('to_date', to);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const link = document.getElementById('export');
  if (link) link.href = `/export/transactions.csv${qs}`;
}

async function loadData() {
  const { from, to } = rangeForPeriod(activePeriod);
  const params = new URLSearchParams();
  if (from) params.set('from_date', from);
  if (to) params.set('to_date', to);
  const qs = params.toString() ? `?${params.toString()}` : '';
  updateExportLink();

  const [statsResponse, transactionsResponse, categoriesResponse] = await Promise.all([
    fetch(`/stats${qs}`),
    fetch(`/transactions${qs}`),
    fetch('/categories'),
  ]);
  if (!statsResponse.ok || !transactionsResponse.ok || !categoriesResponse.ok) {
    throw new Error('Falha ao carregar dados');
  }
  const stats = await statsResponse.json();
  const transactions = await transactionsResponse.json();
  availableCategories = await categoriesResponse.json();

  renderSummary(stats);
  renderCategoryBars(stats.categories, stats.total_spent);
  updateChartPanels();
  if (shouldShowMonthChart()) renderMonthChart(stats.months);
  renderCategories(stats, transactions);
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
loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
