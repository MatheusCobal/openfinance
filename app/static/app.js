// Fallback color if a category somehow arrives without one (shouldn't happen
// once seed_categories.py has been run).
const FALLBACK_COLOR = '#64748b';

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

let categoryChart = null;
let monthChart = null;

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

function renderCategoryChart(categories) {
  const ctx = document.getElementById('chart-categories');
  const colors = categories.map((c) => c.color || FALLBACK_COLOR);

  if (categoryChart) categoryChart.destroy();

  categoryChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: categories.map((c) => c.name),
      datasets: [
        {
          data: categories.map((c) => c.total),
          backgroundColor: colors,
          borderWidth: 0,
          hoverOffset: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            boxWidth: 10,
            boxHeight: 10,
            padding: 12,
            font: { size: 11 },
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.label}: ${currency.format(ctx.parsed)}`,
          },
        },
      },
    },
  });
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

  if (transactions.length === 0) {
    container.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  const groups = groupTransactionsByCategoryId(transactions);
  const orderedCategories = stats.categories;

  const html = orderedCategories
    .map((cat) => {
      const txs = groups.get(cat.id) || [];
      const color = cat.color || FALLBACK_COLOR;
      const rows = txs
        .map(
          (tx) => `
            <li class="flex items-baseline justify-between px-5 py-3 border-t border-slate-100">
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

      return `
        <details class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden group">
          <summary class="flex items-center gap-3 px-5 py-4 hover:bg-slate-50">
            <span class="chevron text-slate-400">
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </span>
            <span class="inline-block size-3 rounded-full shrink-0" style="background:${color}"></span>
            <span class="font-medium text-slate-900 flex-1">${escapeHtml(cat.name)}</span>
            <span class="text-xs text-slate-500 tabular">${cat.count} ${cat.count === 1 ? 'compra' : 'compras'}</span>
            <span class="font-semibold tabular text-slate-900 ml-3">${currency.format(cat.total)}</span>
          </summary>
          <ul>${rows}</ul>
        </details>
      `;
    })
    .join('');

  container.innerHTML = html;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function loadData() {
  const [statsResponse, transactionsResponse] = await Promise.all([
    fetch('/stats'),
    fetch('/transactions'),
  ]);
  if (!statsResponse.ok || !transactionsResponse.ok) {
    throw new Error('Falha ao carregar dados');
  }
  const stats = await statsResponse.json();
  const transactions = await transactionsResponse.json();

  renderSummary(stats);
  renderCategoryChart(stats.categories);
  renderMonthChart(stats.months);
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
          showToast(
            `${result.new_transactions} nova(s) compra(s) sincronizada(s).`,
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

loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
