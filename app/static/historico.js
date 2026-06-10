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
const INCOME_COLOR = '#10b981';
const CATEGORY_COLORS = {
  'Alimentação': '#16a34a',
  'Transporte': '#2563eb',
  'Moradia': '#7c3aed',
  'Saúde': '#dc2626',
  'Compras': '#ea580c',
  'Assinaturas': '#0891b2',
  'Educação': '#4f46e5',
  'Pet': '#db2777',
  'Lazer': '#9333ea',
  'Viagem': '#0d9488',
  'Presentes': '#f59e0b',
  'Beleza / Cuidados pessoais': '#e11d48',
  'Impostos / Taxas': '#64748b',
  'Financiamentos': '#92400e',
  'Outros': '#475569',
};
const HISTORY_TABS = [
  { key: 'invoices', label: 'Faturas cartão' },
  { key: 'cashflow', label: 'Entradas e saídas' },
];

let activeTab = 'invoices';
let invoiceHistory = null;
let cashflowData = null;
let cashflowRules = null;
let selectedInvoiceMonth = null;

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

function categoryColor(name) {
  return CATEGORY_COLORS[name] || FALLBACK_COLOR;
}

function pluralCompras(n) {
  return n === 1 ? '1 compra' : `${n.toLocaleString('pt-BR')} compras`;
}

function pluralMeses(n) {
  return n === 1 ? '1 mês' : `${n.toLocaleString('pt-BR')} meses`;
}

function invoiceDisplayTotal(item) {
  return Number(item?.invoice_display_total ?? item?.total ?? 0);
}

function classifiedPurchaseTotal(item) {
  return Number(item?.classified_purchase_total ?? item?.total ?? 0);
}

function hasInvoiceMonthData(item) {
  return invoiceDisplayTotal(item) > 0 || Number(item?.count || 0) > 0;
}

function invoiceSourceLabel(item) {
  const labels = {
    pluggy_official_bill: 'Fatura oficial Pluggy',
    dashboard_current_invoice: 'Fatura vigente Dashboard',
    missing_official_bill_fallback: 'Total classificado',
  };
  return labels[item?.invoice_total_source] || 'Fatura';
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

function classificationMeta(tx) {
  const parts = [];
  if (tx.internal_category) parts.push(tx.internal_category);
  if (tx.cashflow_type) parts.push(tx.cashflow_type);
  if (tx.classification_source && tx.classification_confidence) {
    parts.push(`${tx.classification_source}/${tx.classification_confidence}`);
  }
  if (tx.pluggy_category) parts.push(`Pluggy: ${tx.pluggy_category}`);
  return parts.map(escapeHtml).join(' · ');
}

// ── Manual classification override (10D-C) ──────────────────────────────

let classificationOptions = null;
const drilldownTxById = new Map();

async function ensureClassificationOptions() {
  if (classificationOptions) return classificationOptions;
  classificationOptions = await fetchJson('/transactions/classification-options');
  return classificationOptions;
}

function registerDrilldownTxs(transactions) {
  drilldownTxById.clear();
  (transactions || []).forEach((tx) => {
    if (tx && tx.id) drilldownTxById.set(tx.id, tx);
  });
}

function classificationBadges(tx) {
  const badges = [];
  if (tx.is_user_overridden) {
    badges.push(
      '<span class="inline-flex items-center px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] font-medium">Manual</span>',
    );
  } else if (tx.classification_source === 'fallback' && tx.classification_confidence === 'low') {
    badges.push(
      '<span class="inline-flex items-center px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 text-[10px] font-medium">Revisar</span>',
    );
  }
  if (tx.ignored_from_totals) {
    badges.push(
      '<span class="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px] font-medium">Ignorada dos totais</span>',
    );
  }
  return badges.join(' ');
}

function txEditButton(tx) {
  if (!tx || !tx.id) return '';
  return `
    <button type="button" class="tx-edit-btn text-[11px] text-blue-600 hover:text-blue-800 hover:underline"
      data-tx-id="${escapeHtml(tx.id)}">Editar classificação</button>
  `;
}

function txClassificationFooter(tx) {
  const meta = classificationMeta(tx);
  const badges = classificationBadges(tx);
  if (!meta && !badges && !(tx && tx.id)) return '';
  return `
    <div class="flex flex-wrap items-center gap-x-2 gap-y-1 mt-0.5">
      ${badges}
      ${meta ? `<span class="text-[11px] text-slate-400">${meta}</span>` : ''}
      ${txEditButton(tx)}
    </div>
  `;
}

function classificationEditorHtml(tx, options) {
  const categoryOptions = options.internal_categories
    .map((name) => `<option value="${escapeHtml(name)}" ${name === tx.internal_category ? 'selected' : ''}>${escapeHtml(name)}</option>`)
    .join('');
  const cashflowOptions = options.cashflow_types
    .map((name) => `<option value="${escapeHtml(name)}" ${name === tx.cashflow_type ? 'selected' : ''}>${escapeHtml(name)}</option>`)
    .join('');
  const rawParts = [
    tx.pluggy_raw_category ? `Categoria: ${tx.pluggy_raw_category}` : null,
    tx.pluggy_raw_subcategory ? `Subcategoria: ${tx.pluggy_raw_subcategory}` : null,
    tx.pluggy_raw_type ? `Tipo: ${tx.pluggy_raw_type}` : null,
    tx.pluggy_merchant ? `Merchant: ${tx.pluggy_merchant}` : null,
  ].filter(Boolean);
  const sourceParts = [
    tx.classification_source ? `Origem: ${tx.classification_source}` : null,
    tx.classification_confidence ? `Confiança: ${tx.classification_confidence}` : null,
  ].filter(Boolean);
  return `
    <div class="tx-editor mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2" data-tx-id="${escapeHtml(tx.id)}">
      <div class="flex flex-col sm:flex-row gap-2">
        <label class="flex-1 text-xs text-slate-600">
          Categoria interna
          <select class="tx-editor-category mt-1 w-full text-sm rounded-lg border border-slate-300 px-2 py-1.5 bg-white outline-none focus:border-blue-500">
            ${categoryOptions}
          </select>
        </label>
        <label class="flex-1 text-xs text-slate-600">
          Tipo de fluxo
          <select class="tx-editor-cashflow mt-1 w-full text-sm rounded-lg border border-slate-300 px-2 py-1.5 bg-white outline-none focus:border-blue-500">
            ${cashflowOptions}
          </select>
        </label>
      </div>
      <label class="flex items-center gap-2 text-xs text-slate-700">
        <input type="checkbox" class="tx-editor-ignored rounded border-slate-300" ${tx.ignored_from_totals ? 'checked' : ''} />
        Ignorar dos totais
      </label>
      ${sourceParts.length ? `<p class="text-[11px] text-slate-400">${sourceParts.map(escapeHtml).join(' · ')}</p>` : ''}
      ${rawParts.length ? `<p class="text-[11px] text-slate-400">Pluggy bruto — ${rawParts.map(escapeHtml).join(' · ')}</p>` : ''}
      <div class="flex flex-wrap items-center gap-2 pt-1">
        <button type="button" class="tx-editor-save text-xs font-medium text-white bg-blue-700 hover:bg-blue-800 rounded-lg px-3 py-1.5">Salvar</button>
        ${tx.is_user_overridden
          ? '<button type="button" class="tx-editor-reset text-xs font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-100 rounded-lg px-3 py-1.5">Restaurar automático</button>'
          : ''}
        <button type="button" class="tx-editor-cancel text-xs text-slate-500 hover:text-slate-700 px-2 py-1.5">Cancelar</button>
      </div>
    </div>
  `;
}

async function openClassificationEditor(button) {
  const txId = button.dataset.txId;
  const tx = drilldownTxById.get(txId);
  if (!tx) return;
  let options;
  try {
    options = await ensureClassificationOptions();
  } catch (err) {
    console.error(err);
    showToast('Não foi possível carregar as opções de classificação.', 'error');
    return;
  }
  const row = button.closest('li');
  if (!row) return;
  const existing = row.querySelector('.tx-editor');
  if (existing) {
    existing.remove();
    return;
  }
  // Only one editor open at a time inside the drilldown.
  document.querySelectorAll('#drilldown-body .tx-editor').forEach((el) => el.remove());
  const host = row.querySelector('.min-w-0') || row;
  host.insertAdjacentHTML('beforeend', classificationEditorHtml(tx, options));

  const editor = host.querySelector('.tx-editor');
  const cashflowSelect = editor.querySelector('.tx-editor-cashflow');
  const ignoredCheckbox = editor.querySelector('.tx-editor-ignored');
  cashflowSelect.addEventListener('change', () => {
    const suggested = options.suggested_ignored_from_totals[cashflowSelect.value];
    if (typeof suggested === 'boolean') ignoredCheckbox.checked = suggested;
  });
}

async function saveClassificationOverride(editor) {
  const txId = editor.dataset.txId;
  const body = {
    internal_category: editor.querySelector('.tx-editor-category').value,
    cashflow_type: editor.querySelector('.tx-editor-cashflow').value,
    ignored_from_totals: editor.querySelector('.tx-editor-ignored').checked,
  };
  try {
    const response = await fetch(`/transactions/${encodeURIComponent(txId)}/classification`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      showToast(err.detail || `Falha ao salvar (HTTP ${response.status})`, 'error');
      return;
    }
    closeDrilldown();
    await loadData();
    showToast('Classificação manual salva.', 'success');
  } catch (err) {
    console.error(err);
    showToast('Erro ao salvar classificação.', 'error');
  }
}

async function resetClassificationOverride(editor) {
  const txId = editor.dataset.txId;
  try {
    const response = await fetch(
      `/transactions/${encodeURIComponent(txId)}/classification-override`,
      { method: 'DELETE' },
    );
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      showToast(err.detail || `Falha ao restaurar (HTTP ${response.status})`, 'error');
      return;
    }
    closeDrilldown();
    await loadData();
    showToast('Classificação automática restaurada.', 'success');
  } catch (err) {
    console.error(err);
    showToast('Erro ao restaurar classificação.', 'error');
  }
}

document.getElementById('drilldown-body').addEventListener('click', (e) => {
  const editBtn = e.target.closest('.tx-edit-btn');
  if (editBtn) {
    openClassificationEditor(editBtn);
    return;
  }
  const editor = e.target.closest('.tx-editor');
  if (!editor) return;
  if (e.target.closest('.tx-editor-save')) saveClassificationOverride(editor);
  else if (e.target.closest('.tx-editor-reset')) resetClassificationOverride(editor);
  else if (e.target.closest('.tx-editor-cancel')) editor.remove();
});

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
          data: data.months.map((item) => invoiceDisplayTotal(item)),
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
              return ` ${currency.format(invoiceDisplayTotal(item))} · ${pluralCompras(item.count)}`;
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

function openInvoiceDrilldown(monthData) {
  const modal = document.getElementById('drilldown');

  document.getElementById('drilldown-color').style.background = INVOICE_COLOR;
  document.getElementById('drilldown-title').textContent =
    `Faturas cartão · ${formatMonthLong(monthData.month)}`;
  document.getElementById('drilldown-subtitle').textContent =
    `${currency.format(invoiceDisplayTotal(monthData))} · ${pluralCompras(monthData.count)}`;

  registerDrilldownTxs(monthData.transactions);
  const rows = monthData.transactions
    .map(
      (tx) => `
        <li class="flex items-baseline justify-between px-6 py-3 border-t border-slate-100">
          <div class="min-w-0 flex-1 pr-4">
            <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
            <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
            ${txClassificationFooter(tx)}
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

function openInvoiceCategoryDrilldown(category, monthData) {
  const modal = document.getElementById('drilldown');
  const color = categoryColor(category.name);

  document.getElementById('drilldown-color').style.background = color;
  document.getElementById('drilldown-title').textContent =
    `${category.name} · ${formatMonthLong(monthData.month)}`;
  document.getElementById('drilldown-subtitle').textContent =
    `${currency.format(category.total)} · ${pluralCompras(category.count)}`;

  registerDrilldownTxs(category.transactions);
  const rows = (category.transactions || [])
    .slice()
    .sort((a, b) => Math.abs(Number(b.amount_abs)) - Math.abs(Number(a.amount_abs)))
    .map(
      (tx) => `
        <li class="flex items-baseline justify-between px-6 py-3 border-t border-slate-100">
          <div class="min-w-0 flex-1 pr-4">
            <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
            <p class="text-xs text-slate-500 mt-0.5">
              ${formatDayLabel(tx.date)}
              ${tx.account_name ? ` · ${escapeHtml(tx.account_name)}` : ''}
            </p>
            ${txClassificationFooter(tx)}
          </div>
          <p class="text-sm font-medium tabular text-slate-900 shrink-0">
            ${currency.format(Number(tx.amount_abs))}
          </p>
        </li>
      `,
    )
    .join('');

  document.getElementById('drilldown-body').innerHTML = rows
    ? `<ul>${rows}</ul>`
    : '<p class="text-center text-sm text-slate-500 py-12">Sem transações nessa categoria.</p>';
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

function differenceLabel(category) {
  const diff = Number(category.difference_from_average || 0);
  const avg = Number(category.average_12m || 0);
  if (avg <= 0) {
    return '<span class="text-slate-400">sem média anterior</span>';
  }
  const sign = diff >= 0 ? '+' : '-';
  const color = diff > 0 ? 'text-red-600' : diff < 0 ? 'text-emerald-600' : 'text-slate-500';
  const pct = typeof category.difference_percent === 'number'
    ? ` · ${sign}${Math.abs(category.difference_percent).toFixed(0)}%`
    : '';
  return `<span class="${color}">${sign}${currency.format(Math.abs(diff))}${pct}</span>`;
}

function renderInvoiceCategoryCard(category, monthData) {
  const color = categoryColor(category.name);
  const averageMonths = Number(category.average_months_used || 0);
  const averageLabel = averageMonths > 0
    ? `${currency.format(category.average_12m)} em ${pluralMeses(averageMonths)}`
    : 'sem histórico anterior';
  return `
    <button
      type="button"
      class="invoice-category-card text-left bg-white rounded-lg border border-slate-200 p-5 hover:border-blue-200 hover:shadow-sm transition"
      data-category-id="${escapeHtml(category.id)}"
    >
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <div class="flex items-center gap-2 min-w-0">
            <span class="size-2.5 rounded-sm shrink-0" style="background:${color}"></span>
            <h3 class="font-semibold text-slate-900 truncate">${escapeHtml(category.name)}</h3>
          </div>
          <p class="text-xs text-slate-500 mt-1">${pluralCompras(category.count)}</p>
        </div>
        <p class="font-bold tabular text-slate-900 shrink-0">${currency.format(category.total)}</p>
      </div>
      <div class="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-slate-100 pt-3 text-xs">
        <div>
          <p class="text-slate-500">Média 12m</p>
          <p class="mt-0.5 font-semibold tabular text-slate-800">${averageLabel}</p>
        </div>
        <div>
          <p class="text-slate-500">Vs. média</p>
          <p class="mt-0.5 font-semibold tabular">${differenceLabel(category)}</p>
        </div>
      </div>
    </button>
  `;
}

function renderCategoryContent(monthData) {
  const cards = document.getElementById('cards');
  if (!cards) return;
  const categories = monthData?.categories || [];
  if (!monthData || categories.length === 0) {
    cards.innerHTML = '';
    cards.classList.add('hidden');
    return;
  }

  cards.innerHTML = `
    <div class="col-span-full flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2 mb-1">
      <div>
        <h2 class="font-semibold text-slate-900">Gastos por classificação</h2>
        <p class="text-xs text-slate-500 mt-0.5">${escapeHtml(formatMonthLong(monthData.month))} · ${pluralCompras(monthData.count)}</p>
      </div>
      <button
        type="button"
        class="invoice-all-month text-xs font-medium text-blue-700 hover:text-blue-800"
      >Ver transações do mês</button>
    </div>
    ${categories.map((category) => renderInvoiceCategoryCard(category, monthData)).join('')}
  `;
  cards.classList.remove('hidden');
  cards.querySelector('.invoice-all-month')?.addEventListener('click', () => {
    openInvoiceDrilldown(monthData);
  });
  cards.querySelectorAll('.invoice-category-card').forEach((button) => {
    button.addEventListener('click', () => {
      const category = categories.find((item) => item.id === button.dataset.categoryId);
      if (category) openInvoiceCategoryDrilldown(category, monthData);
    });
  });
}

function renderInvoiceHistory() {
  const data = invoiceHistory;
  const invoices = document.getElementById('invoices');
  const subtitle = document.getElementById('subtitle');

  destroyCharts();
  hideAllTabSections();
  invoices.classList.remove('hidden');

  const monthsWithInvoiceData = data.months.filter((item) => hasInvoiceMonthData(item));
  if (monthsWithInvoiceData.length === 0 || data.months.length === 0) {
    invoices.innerHTML = '';
    renderEmpty(
      'Nenhuma fatura de cartão encontrada.',
      'Faturas oficiais e compras CREDIT válidas aparecerão aqui.',
    );
    subtitle.textContent = 'Nenhuma fatura de cartão encontrada';
    return;
  }
  hideEmpty();

  if (!selectedInvoiceMonth || !data.months.some((item) => item.month === selectedInvoiceMonth)) {
    const latest = [...monthsWithInvoiceData].pop() || data.months[data.months.length - 1];
    selectedInvoiceMonth = latest.month;
  }
  const activeMonth = data.months.find((item) => item.month === selectedInvoiceMonth) || data.months[data.months.length - 1];
  const largest = monthsWithInvoiceData.reduce(
    (best, item) => (!best || invoiceDisplayTotal(item) > invoiceDisplayTotal(best) ? item : best),
    null,
  );
  const periodTotal = invoiceDisplayTotal(data);
  const periodClassifiedTotal = classifiedPurchaseTotal(data);
  const average = data.months.length > 0 ? periodTotal / data.months.length : 0;
  const rows = [...data.months].reverse().map((item) => {
    const amount = hasInvoiceMonthData(item)
      ? `
        <button
          type="button"
          class="invoice-month text-right group"
          data-month="${item.month}"
          title="Selecionar mês"
        >
          <span class="block text-sm font-semibold tabular text-slate-900 group-hover:text-blue-700">
            ${currency.format(invoiceDisplayTotal(item))}
          </span>
        </button>
      `
      : '<span class="text-sm font-medium text-slate-400">Sem fatura</span>';
    const activeClass = item.month === activeMonth.month ? 'bg-blue-50/60' : '';
    return `
      <li class="flex items-center justify-between gap-4 px-5 py-3 border-t border-slate-100 ${activeClass}">
        <div>
          <p class="text-sm font-medium text-slate-900">${escapeHtml(formatMonthLong(item.month))}</p>
          <p class="text-xs text-slate-500 mt-0.5">${invoiceSourceLabel(item)} · ${pluralCompras(item.count)}</p>
        </div>
        ${amount}
      </li>
    `;
  }).join('');

  subtitle.textContent =
    `Faturas de cartão · ${formatMonthLong(activeMonth.month)}`;

  invoices.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Faturas no período</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(periodTotal)}</p>
        <p class="text-xs text-slate-500 mt-2">${pluralCompras(data.total_count)} classificadas · ${currency.format(periodClassifiedTotal)}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Mês selecionado</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(invoiceDisplayTotal(activeMonth))}</p>
        <p class="text-xs text-slate-500 mt-2">${escapeHtml(formatMonthLong(activeMonth.month))} · ${invoiceSourceLabel(activeMonth)} · ${pluralCompras(activeMonth.count)}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Maior mês</p>
        <p class="mt-2 text-2xl font-bold tabular text-slate-900">${currency.format(invoiceDisplayTotal(largest))}</p>
        <p class="text-xs text-slate-500 mt-2">${escapeHtml(formatMonthLabel(largest.month))} · média ${currency.format(average)}</p>
      </div>
      <div class="bg-white rounded-lg border border-slate-200 p-6 lg:col-span-3">
        <h2 class="font-semibold text-slate-900 mb-4">Evolução das faturas de cartão</h2>
        <div class="relative h-64">
          <canvas id="chart-invoices"></canvas>
        </div>
      </div>
    </div>
    <div class="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <div class="px-5 py-4">
        <h2 class="font-semibold text-slate-900">Histórico mensal</h2>
      </div>
      <ul>${rows}</ul>
    </div>
  `;

  invoices.querySelectorAll('button.invoice-month').forEach((btn) => {
    btn.addEventListener('click', () => {
      const monthData = data.months.find((item) => item.month === btn.dataset.month);
      if (!monthData) return;
      selectedInvoiceMonth = monthData.month;
      renderInvoiceHistory();
    });
  });

  renderInvoiceChart(data);

  renderCategoryContent(activeMonth);
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

  registerDrilldownTxs([...monthData.entradas_txs, ...monthData.saidas_txs]);
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
          ${txClassificationFooter(tx)}
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
  ['cards', 'invoices', 'cashflow-tab', 'planning-tab'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.classList.add('hidden');
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
    ['invoices', fetchJson('/credit-card-invoices/monthly?months=12')],
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
    if (key === 'invoices') invoiceHistory = result.value;
    if (key === 'cashflow') cashflowData = result.value;
    if (key === 'cashflowRules') cashflowRules = result.value;
  });

  if (!cashflowRules) cashflowRules = [];
  if (!invoiceHistory && !cashflowData) {
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
