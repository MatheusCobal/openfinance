'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const MONTH_WINDOW = 6;
const MAX_CUSTOM_CATEGORIES = 5;
const TRANSACTION_SUGGESTIONS_INITIAL = 5;
const TRANSACTION_SUGGESTIONS_MAX = 50;
const MONTH_LABELS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

const TEMPLATE_EMOJIS = {
  'Aluguel': '🏠', 'Condomínio': '🏢', 'Internet': '🌐',
  'Energia': '⚡', 'Água': '💧', 'Escola': '📚',
  'Plano de saúde': '🏥', 'Streaming': '📺', 'Seguro': '🛡️', 'Pet': '🐾',
};

let selectedMonth = null;
let monthStrip = [];
let categories = [];
let fixedCosts = [];

const STATUS_CFG = {
  paid:        { label: 'Pago',           icon: '✓', bg: 'bg-emerald-100', text: 'text-emerald-700' },
  due_soon:    { label: 'Vence em breve', icon: '⏰', bg: 'bg-amber-100',   text: 'text-amber-700'   },
  overdue:     { label: 'Vencido',        icon: '⚠', bg: 'bg-red-100',     text: 'text-red-700'     },
  scheduled:   { label: 'Previsto',       icon: '·',  bg: 'bg-slate-100',  text: 'text-slate-500'   },
  unconfirmed: { label: 'Não confirmado', icon: '?',  bg: 'bg-slate-100',  text: 'text-slate-500'   },
};

// ── Utilities ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function showToast(message, variant = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className =
    'fixed top-4 right-4 z-50 max-w-sm rounded-xl text-white text-sm px-4 py-3 shadow-lg ' +
    (variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-800');
  toast.classList.remove('hidden');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add('hidden'), 3500);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json())?.detail || ''; } catch {}
    throw new Error(detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function currentYearMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function shiftYearMonth(ym, offset) {
  const [year, month] = ym.split('-').map(Number);
  const zeroBased = year * 12 + (month - 1) + offset;
  return `${String(Math.floor(zeroBased / 12)).padStart(4, '0')}-${String((zeroBased % 12) + 1).padStart(2, '0')}`;
}

function formatMonthShort(ym) {
  const [year, month] = ym.split('-').map(Number);
  return `${MONTH_LABELS[month - 1]}/${String(year).slice(2)}`;
}

function formatDate(iso) {
  const [year, month, day] = String(iso).split('-');
  if (!year || !month || !day) return iso;
  return `${day}/${month}`;
}

// ── Month strip ────────────────────────────────────────────────────────────

function renderMonthStrip() {
  const strip = document.getElementById('month-strip');
  strip.innerHTML = '';
  for (const ym of monthStrip) {
    const button = document.createElement('button');
    const active = ym === selectedMonth;
    button.type = 'button';
    button.className =
      'shrink-0 text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ' +
      (active ? 'bg-indigo-600 text-white shadow-sm' : 'bg-slate-100 text-slate-700 hover:bg-slate-200');
    button.textContent = formatMonthShort(ym);
    button.addEventListener('click', () => {
      if (ym === selectedMonth) return;
      selectedMonth = ym;
      renderMonthStrip();
      loadMonthData();
    });
    strip.appendChild(button);
  }
}

// ── Capacity flow ──────────────────────────────────────────────────────────

function renderCapacityFlow(capacity) {
  const container = document.getElementById('capacity-summary');
  const sobra = capacity.remaining_after_invoice;
  const sobraPositive = sobra >= 0;

  const steps = [
    {
      icon: '💰',
      label: 'Receita esperada',
      value: capacity.expected_income_total,
      prefix: '',
      border: 'border-emerald-200',
      bg: 'bg-emerald-50',
      text: 'text-emerald-900',
      amount: 'text-emerald-700',
    },
    {
      icon: '🏠',
      label: 'Custos fixos',
      value: capacity.fixed_cost_total,
      prefix: '−',
      border: 'border-red-200',
      bg: 'bg-red-50',
      text: 'text-red-900',
      amount: 'text-red-700',
    },
    {
      icon: '💳',
      label: 'Fatura cartão',
      value: capacity.card_invoice_total,
      prefix: '−',
      border: 'border-orange-200',
      bg: 'bg-orange-50',
      text: 'text-orange-900',
      amount: 'text-orange-700',
    },
    {
      icon: '✨',
      label: 'Sobra estimada',
      value: sobra,
      prefix: '=',
      border: sobraPositive ? 'border-emerald-200' : 'border-red-200',
      bg: sobraPositive ? 'bg-emerald-50' : 'bg-red-50',
      text: sobraPositive ? 'text-emerald-900' : 'text-red-900',
      amount: sobraPositive ? 'text-emerald-700' : 'text-red-700',
    },
  ];

  container.innerHTML = `
    <div class="flex flex-wrap items-stretch gap-1">
      ${steps.map((step, i) => `
        <div class="flex items-center gap-1 flex-1 min-w-[160px]">
          <div class="flex-1 rounded-xl border ${step.border} ${step.bg} px-4 py-3">
            <div class="flex items-center gap-1.5 mb-2">
              <span class="text-base leading-none">${step.icon}</span>
              <p class="text-[11px] uppercase tracking-wider font-semibold ${step.text} opacity-75 leading-tight">${step.label}</p>
            </div>
            <p class="text-[11px] font-medium ${step.text} opacity-60 mb-0.5">${step.prefix || ' '}</p>
            <p class="text-lg font-bold tabular ${step.amount} leading-tight">${currency.format(step.value || 0)}</p>
          </div>
          ${i < steps.length - 1 ? '<span class="text-slate-300 text-xl font-light shrink-0">›</span>' : ''}
        </div>
      `).join('')}
    </div>
  `;
}

// ── Category stacked bar ────────────────────────────────────────────────────

function renderCategoryBar(fixed) {
  const container = document.getElementById('category-bar');
  if (!container || fixed.total <= 0 || !fixed.categories?.length) {
    if (container) container.innerHTML = '';
    return;
  }
  const bars = fixed.categories
    .filter((cat) => cat.total > 0)
    .map((cat) => {
      const pct = (cat.total / fixed.total) * 100;
      return `
        <div
          class="h-full rounded-sm first:rounded-l-full last:rounded-r-full transition-all"
          style="width:${pct.toFixed(1)}%;background:${escapeHtml(cat.category_color)}"
          title="${escapeHtml(cat.category_name)}: ${currency.format(cat.total)}"
        ></div>
      `;
    }).join('');

  const legend = fixed.categories
    .filter((cat) => cat.total > 0)
    .map((cat) => `
      <span class="inline-flex items-center gap-1 text-xs text-slate-600">
        <span class="size-2 rounded-full shrink-0 inline-block" style="background:${escapeHtml(cat.category_color)}"></span>
        ${escapeHtml(cat.category_name)}
        <span class="text-slate-400">${currency.format(cat.total)}</span>
      </span>
    `).join('');

  container.innerHTML = `
    <div class="flex h-2.5 w-full rounded-full overflow-hidden gap-px mb-2">${bars}</div>
    <div class="flex flex-wrap gap-x-4 gap-y-1">${legend}</div>
  `;
}

// ── Status badge ────────────────────────────────────────────────────────────

function statusBadge(status) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.scheduled;
  return `
    <span class="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.text}">
      <span>${cfg.icon}</span>${cfg.label}
    </span>
  `;
}

// ── Month breakdown ─────────────────────────────────────────────────────────

async function loadMonthData() {
  if (!selectedMonth) return;
  try {
    const [fixed, capacity] = await Promise.all([
      fetchJson(`/fixed-costs/by-month?year_month=${selectedMonth}`),
      fetchJson(`/spending-capacity?year_month=${selectedMonth}`),
    ]);
    document.getElementById('month-total').textContent = currency.format(fixed.total);
    document.getElementById('capacity-total').textContent = currency.format(capacity.remaining_after_invoice);
    renderCapacityFlow(capacity);
    renderCategoryBar(fixed);
    renderMonthBreakdown(fixed);
  } catch (err) {
    showToast(`Erro ao carregar mês: ${err.message}`, 'error');
  }
}

function renderMonthBreakdown(fixed) {
  const list = document.getElementById('month-breakdown');
  list.innerHTML = '';
  if (fixed.entries.length === 0) {
    list.innerHTML = '<li class="py-8 text-sm text-slate-500 text-center">Nenhum custo fixo ativo. Cadastre um custo base abaixo.</li>';
    return;
  }

  // Group by category preserving order
  const groups = new Map();
  for (const item of fixed.entries) {
    if (!groups.has(item.category_id)) {
      groups.set(item.category_id, {
        category_name: item.category_name,
        category_color: item.category_color,
        items: [],
        total: 0,
      });
    }
    const group = groups.get(item.category_id);
    group.items.push(item);
    group.total += Number(item.amount || 0);
  }

  for (const group of groups.values()) {
    const groupLi = document.createElement('li');
    groupLi.className = 'py-2';

    // Category header
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between gap-3 px-3 py-2 rounded-lg mb-1';
    header.style.borderLeft = `3px solid ${group.category_color}`;
    header.style.backgroundColor = hexToFaint(group.category_color);
    header.innerHTML = `
      <div class="flex items-center gap-2 min-w-0">
        <p class="font-semibold text-slate-900 text-sm truncate">${escapeHtml(group.category_name)}</p>
        <span class="text-xs text-slate-500">${group.items.length} item${group.items.length !== 1 ? 's' : ''}</span>
      </div>
      <p class="font-bold tabular text-slate-900 text-sm shrink-0">${currency.format(group.total)}</p>
    `;
    groupLi.appendChild(header);

    // Items
    const inner = document.createElement('ul');
    inner.className = 'divide-y divide-slate-100 rounded-xl border border-slate-100 overflow-hidden ml-1';
    for (const item of group.items) inner.appendChild(buildMonthRow(item));
    groupLi.appendChild(inner);
    list.appendChild(groupLi);
  }
}

// Turn a hex color into a very faint tint for backgrounds
function hexToFaint(hex) {
  try {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},0.05)`;
  } catch {
    return 'transparent';
  }
}

function buildMonthRow(item) {
  const li = document.createElement('li');
  li.className = 'py-3 px-3 flex items-start gap-3 bg-white hover:bg-slate-50 transition-colors';

  const overrideBadge = item.is_override
    ? `<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded-full">ajustado</span>`
    : '';
  const matchedInfo = item.matched_transaction
    ? `<span class="text-[10px] text-emerald-600">↳ conciliado: ${escapeHtml(item.matched_transaction.description.slice(0, 30))}</span>`
    : '';
  const baseHint = item.is_override
    ? `<button type="button" data-action="revert" class="text-[10px] text-indigo-500 hover:text-indigo-700 underline">↩ reverter (${currency.format(item.base_amount)})</button>`
    : '';

  li.innerHTML = `
    <div class="flex flex-col items-center shrink-0 pt-0.5">
      <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-bold text-sm tabular">${item.due_day}</span>
      <span class="text-[9px] text-slate-400 mt-0.5">dia</span>
    </div>
    <div class="flex-1 min-w-0">
      <div class="flex flex-wrap items-center gap-1.5 mb-0.5">
        <p class="font-medium text-slate-900 text-sm">${escapeHtml(item.description)}</p>
        ${overrideBadge}
        ${statusBadge(item.status)}
      </div>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
        <span>vence ${formatDate(item.due_date)}</span>
        ${matchedInfo}
        ${baseHint}
      </div>
    </div>
    <input
      type="number" step="0.01" min="0" data-action="edit"
      class="w-28 text-right text-sm font-semibold tabular rounded-lg border border-slate-200 px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 shrink-0"
      value="${Number(item.amount).toFixed(2)}"
    />
  `;

  const input = li.querySelector('input[data-action="edit"]');
  const commit = async () => {
    const newAmount = Number(input.value);
    if (Number.isNaN(newAmount) || newAmount < 0) { input.value = Number(item.amount).toFixed(2); return; }
    if (Math.abs(newAmount - Number(item.amount)) < 0.005) return;
    if (Math.abs(newAmount - Number(item.base_amount)) < 0.005 && item.is_override) {
      try {
        await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, { method: 'DELETE' });
        await loadMonthData();
        showToast('Ajuste removido, voltou ao base.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    try {
      await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: newAmount }),
      });
      await loadMonthData();
      showToast('Valor do mês atualizado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
    if (event.key === 'Escape') { input.value = Number(item.amount).toFixed(2); input.blur(); }
  });

  const revertBtn = li.querySelector('[data-action="revert"]');
  if (revertBtn) {
    revertBtn.addEventListener('click', async () => {
      try {
        await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, { method: 'DELETE' });
        await loadMonthData();
        showToast('Ajuste removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
  return li;
}

// ── Categories & costs (base section) ──────────────────────────────────────

async function loadCategories() {
  categories = await fetchJson('/fixed-cost-categories');
  const customCount = categories.filter((cat) => !cat.is_default).length;
  const remaining = Math.max(0, MAX_CUSTOM_CATEGORIES - customCount);
  document.getElementById('custom-category-count').textContent =
    `${customCount}/${MAX_CUSTOM_CATEGORIES} personalizadas · ${remaining} restante${remaining === 1 ? '' : 's'}`;
  const addButton = document.querySelector('#category-form button[type="submit"]');
  if (addButton) {
    addButton.disabled = customCount >= MAX_CUSTOM_CATEGORIES;
    addButton.classList.toggle('opacity-50', customCount >= MAX_CUSTOM_CATEGORIES);
    addButton.classList.toggle('cursor-not-allowed', customCount >= MAX_CUSTOM_CATEGORIES);
  }
  renderCategoryCostList();
}

function buildCategoryCostGroup(category, costs) {
  const wrapper = document.createElement('section');
  wrapper.className = 'rounded-xl border border-slate-200 overflow-hidden';
  wrapper.style.borderTopColor = category.color;
  wrapper.style.borderTopWidth = '3px';

  const activeTotal = costs.filter((c) => c.active).reduce((sum, c) => sum + Number(c.amount || 0), 0);
  const activeCostCount = costs.filter((c) => c.active).length;
  const customBadge = category.is_default
    ? ''
    : '<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded-full">personalizada</span>';
  const deleteButton = category.is_default
    ? ''
    : '<button type="button" data-action="delete" class="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors">Excluir</button>';

  wrapper.innerHTML = `
    <div class="px-4 py-3 flex items-center justify-between gap-2 bg-slate-50">
      <!-- Left side: click to expand/collapse -->
      <button type="button" data-action="toggle-expand"
        class="flex items-center gap-2 min-w-0 flex-1 text-left">
        <span data-chevron class="text-slate-400 text-[10px] transition-transform duration-150">▶</span>
        <span class="size-2.5 rounded-full shrink-0" style="background:${escapeHtml(category.color)}"></span>
        <h3 class="font-semibold text-slate-900 text-sm truncate">${escapeHtml(category.name)}</h3>
        ${customBadge}
        <span class="text-xs text-slate-400 shrink-0">${activeCostCount} ${activeCostCount === 1 ? 'custo' : 'custos'}</span>
      </button>
      <!-- Right side: total + actions (never trigger expand) -->
      <div class="flex items-center gap-2 shrink-0">
        <span class="text-sm font-semibold tabular text-slate-700">${currency.format(activeTotal)}</span>
        <button type="button" data-action="toggle-add"
          class="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors">
          <span class="text-base leading-none" aria-hidden="true">＋</span> Adicionar
        </button>
        ${deleteButton}
      </div>
    </div>

    <!-- Collapsible body (hidden by default) -->
    <div data-body class="hidden">
      <div data-add-form class="hidden px-4 py-3 bg-indigo-50/40 border-b border-indigo-100">
        <form class="grid grid-cols-1 lg:grid-cols-[1fr_140px_90px_auto] gap-2" data-add-category="${category.id}">
          <input name="description" type="text" required value="${escapeHtml(category.name)}"
            placeholder="Descrição" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
          <input name="amount" type="number" step="0.01" min="0.01" required placeholder="Valor (R$)"
            class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
          <input name="due_day" type="number" min="1" max="31" required placeholder="Dia"
            class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
          <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg px-4 py-2">Salvar</button>
        </form>
      </div>
      <ul class="divide-y divide-slate-100 text-sm border-t border-slate-100"></ul>
    </div>
  `;

  const body = wrapper.querySelector('[data-body]');
  const addFormContainer = wrapper.querySelector('[data-add-form]');
  const chevron = wrapper.querySelector('[data-chevron]');

  function openBody() {
    body.classList.remove('hidden');
    chevron.style.transform = 'rotate(90deg)';
  }
  function closeBody() {
    body.classList.add('hidden');
    chevron.style.transform = '';
    addFormContainer.classList.add('hidden');
  }

  // Expand/collapse on left-side click
  wrapper.querySelector('[data-action="toggle-expand"]').addEventListener('click', () => {
    body.classList.contains('hidden') ? openBody() : closeBody();
  });

  // "＋ Adicionar" always opens body + shows form
  wrapper.querySelector('[data-action="toggle-add"]').addEventListener('click', () => {
    openBody();
    addFormContainer.classList.remove('hidden');
    const descInput = addFormContainer.querySelector('input[name="description"]');
    descInput.value = category.name;
    addFormContainer.querySelector('input[name="amount"]').focus();
  });

  // Submit add form
  const form = wrapper.querySelector('form[data-add-category]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const description = String(data.get('description') || '').trim();
    const amount = Number(data.get('amount'));
    const due_day = Number(data.get('due_day'));
    if (!description || !amount || !due_day) return;
    try {
      await fetchJson('/fixed-costs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: category.id, description, amount, due_day }),
      });
      form.reset();
      addFormContainer.classList.add('hidden');
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo fixo adicionado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  // Cost list
  const innerList = wrapper.querySelector('ul');
  if (costs.length === 0) {
    const emptyLi = document.createElement('li');
    emptyLi.className = 'py-6 mx-3 my-3 flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-200';
    emptyLi.innerHTML = `
      <span class="text-2xl opacity-25">📋</span>
      <p class="text-xs text-slate-400 text-center leading-relaxed">
        Nenhum custo cadastrado.<br>Clique em <strong class="font-semibold text-slate-500">＋ Adicionar</strong> para criar.
      </p>
    `;
    innerList.appendChild(emptyLi);
  } else {
    for (const cost of costs) innerList.appendChild(buildCostRow(cost));
  }

  // Delete category
  const deleteAction = wrapper.querySelector('[data-action="delete"]');
  if (deleteAction) {
    deleteAction.addEventListener('click', async () => {
      if (!confirm(`Excluir categoria "${category.name}"?`)) return;
      try {
        await fetchJson(`/fixed-cost-categories/${category.id}`, { method: 'DELETE' });
        await Promise.all([loadCategories(), loadCosts(), loadMonthData()]);
        showToast('Categoria excluída.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
  return wrapper;
}

function renderCategoryCostList() {
  const list = document.getElementById('category-cost-list');
  if (!list) return;
  list.innerHTML = '';
  if (categories.length === 0) {
    list.innerHTML = '<div class="py-8 text-sm text-slate-500 text-center">Nenhuma categoria ainda.</div>';
    return;
  }
  for (const category of categories) {
    const costs = fixedCosts.filter((cost) => Number(cost.category_id) === Number(category.id));
    list.appendChild(buildCategoryCostGroup(category, costs));
  }
}

async function loadTemplates() {
  const list = document.getElementById('template-list');
  if (!list) return;
  try {
    const templates = await fetchJson('/fixed-costs/templates');
    list.innerHTML = templates.map((template) => {
      const emoji = TEMPLATE_EMOJIS[template.label] || '📋';
      return `
        <button type="button" data-template="${escapeHtml(template.label)}"
          class="inline-flex items-center gap-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 px-3 py-1.5 rounded-lg transition-colors shadow-sm">
          <span>${emoji}</span>${escapeHtml(template.label)}
        </button>
      `;
    }).join('');
    list.querySelectorAll('button[data-template]').forEach((button) => {
      button.addEventListener('click', () => {
        const template = templates.find((item) => item.label === button.dataset.template);
        if (!template) return;
        // Find the category group, expand it, then open its add form
        const form = document.querySelector(`form[data-add-category="${template.category_id}"]`);
        if (!form) return;
        const body = form.closest('[data-body]');
        const addFormContainer = form.closest('[data-add-form]');
        const chevron = body?.closest('section')?.querySelector('[data-chevron]');
        if (body) body.classList.remove('hidden');
        if (chevron) chevron.style.transform = 'rotate(90deg)';
        if (addFormContainer) {
          addFormContainer.classList.remove('hidden');
          addFormContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        form.elements.description.value = template.description;
        form.elements.due_day.value = template.due_day;
        form.elements.amount.focus();
      });
    });
  } catch (err) {
    list.innerHTML = '<span class="text-xs text-slate-500">Templates indisponíveis.</span>';
  }
}

async function loadCosts() {
  const showInactive = document.getElementById('show-inactive').checked;
  const costs = await fetchJson('/fixed-costs' + (showInactive ? '?include_inactive=true' : ''));
  fixedCosts = costs;
  document.getElementById('cost-count').textContent =
    costs.length === 1 ? '1 custo' : `${costs.length} custos`;
  const activeTotal = costs.filter((c) => c.active).reduce((sum, c) => sum + Number(c.amount || 0), 0);
  document.getElementById('active-total').textContent = currency.format(activeTotal);
  renderCategoryCostList();
}

function buildCostRow(cost) {
  const li = document.createElement('li');
  li.className = 'py-3 px-4 flex items-center gap-3 hover:bg-slate-50 transition-colors';
  li.innerHTML = `
    <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-bold text-sm shrink-0 tabular">${cost.due_day}</span>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-sm break-words ${cost.active ? 'text-slate-900' : 'text-slate-400 line-through'}">${escapeHtml(cost.description)}</p>
      <p class="text-xs text-slate-400 mt-0.5">dia ${cost.due_day} de cada mês</p>
    </div>
    <p class="font-semibold tabular text-sm shrink-0 ${cost.active ? 'text-slate-900' : 'text-slate-400'}">${currency.format(cost.amount)}</p>
    <div class="flex items-center gap-1 shrink-0">
      <button type="button" data-action="edit"
        class="text-xs text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors">Editar</button>
      <button type="button" data-action="toggle"
        class="text-xs text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-2 py-1 rounded-lg transition-colors">${cost.active ? 'Desativar' : 'Reativar'}</button>
      <button type="button" data-action="delete"
        class="text-xs text-red-500 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors">Excluir</button>
    </div>
  `;

  li.querySelector('[data-action="edit"]').addEventListener('click', () => renderCostEditRow(li, cost));
  li.querySelector('[data-action="toggle"]').addEventListener('click', async () => {
    try {
      await fetchJson(`/fixed-costs/${cost.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !cost.active }),
      });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast(cost.active ? 'Custo desativado.' : 'Custo reativado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  li.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    if (!confirm(`Excluir "${cost.description}"?`)) return;
    try {
      await fetchJson(`/fixed-costs/${cost.id}`, { method: 'DELETE' });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo excluído.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  return li;
}

function categoryOptions(selectedId) {
  return categories.map((cat) => {
    const selected = Number(cat.id) === Number(selectedId) ? 'selected' : '';
    return `<option value="${cat.id}" ${selected}>${escapeHtml(cat.name)}</option>`;
  }).join('');
}

function renderCostEditRow(li, cost) {
  li.className = 'py-3 px-4 bg-indigo-50/40';
  li.innerHTML = `
    <form class="grid grid-cols-1 lg:grid-cols-[160px_1fr_140px_90px_auto_auto] gap-2 w-full">
      <select name="category_id" required
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white">
        ${categoryOptions(cost.category_id)}
      </select>
      <input name="description" type="text" required value="${escapeHtml(cost.description)}"
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <input name="amount" type="number" step="0.01" min="0.01" required value="${Number(cost.amount).toFixed(2)}"
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <input name="due_day" type="number" min="1" max="31" required value="${cost.due_day}"
        class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 bg-white" />
      <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg px-3 py-2">Salvar</button>
      <button type="button" data-action="cancel"
        class="text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg hover:bg-slate-100">Cancelar</button>
    </form>
  `;
  li.querySelector('[data-action="cancel"]').addEventListener('click', () => li.replaceWith(buildCostRow(cost)));
  li.querySelector('form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(li.querySelector('form'));
    try {
      await fetchJson(`/fixed-costs/${cost.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category_id: Number(data.get('category_id')),
          description: String(data.get('description') || '').trim(),
          amount: Number(data.get('amount')),
          due_day: Number(data.get('due_day')),
        }),
      });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo atualizado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Category form ───────────────────────────────────────────────────────────

document.getElementById('category-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.getElementById('category-name').value.trim();
  const color = document.getElementById('category-color').value;
  const sort_order = Number(document.getElementById('category-order').value || 0);
  if (!name) return;
  if (categories.filter((c) => !c.is_default).length >= MAX_CUSTOM_CATEGORIES) {
    showToast('Limite de 5 categorias personalizadas atingido.', 'error');
    return;
  }
  try {
    await fetchJson('/fixed-cost-categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, color, sort_order }),
    });
    document.getElementById('category-name').value = '';
    await loadCategories();
    showToast('Categoria adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

document.getElementById('show-inactive').addEventListener('change', loadCosts);

// ── Transaction suggestions ─────────────────────────────────────────────────

async function loadTransactionSuggestions() {
  const list = document.getElementById('transaction-suggestions');
  if (!list) return;
  try {
    const transactions = await fetchJson('/transactions?account_type=ALL&include_ignored=true');
    const rows = transactions.slice(0, TRANSACTION_SUGGESTIONS_MAX);
    if (rows.length === 0) {
      list.innerHTML = '<li class="py-8 text-sm text-slate-500 text-center">Nenhuma transação recente encontrada.</li>';
      return;
    }
    list.innerHTML = '';
    rows.forEach((tx, index) => {
      const row = buildTransactionSuggestionRow(tx);
      if (index >= TRANSACTION_SUGGESTIONS_INITIAL) row.classList.add('transaction-suggestion-extra', 'hidden');
      list.appendChild(row);
    });
    if (rows.length > TRANSACTION_SUGGESTIONS_INITIAL) {
      const more = document.createElement('li');
      more.className = 'py-3 text-center';
      more.innerHTML = `
        <button type="button" data-action="show-more"
          class="inline-flex items-center gap-2 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-3 py-2 rounded-lg transition-colors">
          <span aria-hidden="true">＋</span>
          Ver mais ${rows.length - TRANSACTION_SUGGESTIONS_INITIAL} transações
        </button>
      `;
      more.querySelector('[data-action="show-more"]').addEventListener('click', () => {
        list.querySelectorAll('.transaction-suggestion-extra').forEach((row) => row.classList.remove('hidden'));
        more.remove();
      });
      list.appendChild(more);
    }
  } catch (err) {
    list.innerHTML = `<li class="py-6 text-sm text-red-600 text-center">${escapeHtml(err.message)}</li>`;
  }
}

function buildTransactionSuggestionRow(tx) {
  const li = document.createElement('li');
  li.className = 'py-3 px-1 flex items-center gap-3 hover:bg-slate-50 rounded-lg transition-colors';

  const txDate = new Date(tx.date + 'T00:00:00');
  const day = String(txDate.getDate()).padStart(2, '0');
  const monthLabel = MONTH_LABELS[txDate.getMonth()];

  li.innerHTML = `
    <div class="flex flex-col items-center justify-center size-10 rounded-xl bg-slate-100 shrink-0">
      <span class="text-base font-bold text-slate-700 leading-none tabular">${day}</span>
      <span class="text-[9px] text-slate-400 uppercase tracking-wide leading-none mt-0.5">${monthLabel}</span>
    </div>
    <div class="flex-1 min-w-0">
      <p class="font-medium text-slate-900 text-sm truncate">${escapeHtml(tx.description)}</p>
      <p class="text-xs text-slate-400 mt-0.5">${escapeHtml(tx.custom_category_name || tx.category || 'Sem categoria')}</p>
    </div>
    <p class="font-semibold tabular text-sm text-slate-800 shrink-0">${currency.format(Math.abs(Number(tx.amount) || 0))}</p>
    <button type="button" data-action="use"
      class="shrink-0 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-lg transition-colors">
      + Criar custo
    </button>
  `;
  li.querySelector('[data-action="use"]').addEventListener('click', async () => {
    try {
      await fetchJson('/fixed-costs/from-transaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transaction_id: tx.id }),
      });
      await Promise.all([loadCosts(), loadMonthData()]);
      showToast('Custo fixo criado a partir da transação.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  return li;
}

// ── Init ───────────────────────────────────────────────────────────────────

(async () => {
  selectedMonth = currentYearMonth();
  monthStrip = Array.from({ length: MONTH_WINDOW }, (_, i) => shiftYearMonth(selectedMonth, i));
  renderMonthStrip();
  try {
    await loadCategories();
    await Promise.all([loadTemplates(), loadCosts(), loadMonthData(), loadTransactionSuggestions()]);
    document.getElementById('subtitle').textContent =
      'Cadastre compromissos recorrentes para calcular sua sobra mensal.';
  } catch (err) {
    showToast(err.message, 'error');
    document.getElementById('subtitle').textContent = 'Erro ao carregar custos fixos.';
  }
})();
