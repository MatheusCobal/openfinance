'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const MONTH_WINDOW = 6;
const MAX_CUSTOM_CATEGORIES = 5;
const TRANSACTION_SUGGESTIONS_INITIAL = 5;
const TRANSACTION_SUGGESTIONS_MAX = 50;
const MONTH_LABELS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
let selectedMonth = null;
let monthStrip = [];
let categories = [];

const STATUS_META = {
  paid: { label: 'pago provável', cls: 'bg-emerald-50 text-emerald-700' },
  due_soon: { label: 'vencendo', cls: 'bg-amber-50 text-amber-700' },
  overdue: { label: 'vencido', cls: 'bg-red-50 text-red-700' },
  scheduled: { label: 'previsto', cls: 'bg-slate-100 text-slate-600' },
  unconfirmed: { label: 'não confirmado', cls: 'bg-slate-100 text-slate-600' },
};

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
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

function renderMonthStrip() {
  const strip = document.getElementById('month-strip');
  strip.innerHTML = '';
  for (const ym of monthStrip) {
    const button = document.createElement('button');
    const active = ym === selectedMonth;
    button.type = 'button';
    button.className =
      'shrink-0 text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ' +
      (active ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200');
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

function capacityCard(label, value, tint = 'slate') {
  const tones = {
    emerald: 'bg-emerald-50 text-emerald-900 border-emerald-100',
    red: 'bg-red-50 text-red-900 border-red-100',
    orange: 'bg-orange-50 text-orange-900 border-orange-100',
    slate: 'bg-slate-50 text-slate-900 border-slate-100',
  };
  return `
    <div class="rounded-xl border ${tones[tint]} px-4 py-3">
      <p class="text-[11px] uppercase tracking-wider font-semibold opacity-70">${label}</p>
      <p class="mt-1 text-xl font-bold tabular">${currency.format(value || 0)}</p>
    </div>
  `;
}

function statusBadge(status) {
  const meta = STATUS_META[status] || STATUS_META.scheduled;
  return `<span class="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${meta.cls}">${meta.label}</span>`;
}

async function loadMonthData() {
  if (!selectedMonth) return;
  try {
    const [fixed, capacity] = await Promise.all([
      fetchJson(`/fixed-costs/by-month?year_month=${selectedMonth}`),
      fetchJson(`/spending-capacity?year_month=${selectedMonth}`),
    ]);
    document.getElementById('month-total').textContent = currency.format(fixed.total);
    document.getElementById('capacity-total').textContent = currency.format(capacity.remaining_after_invoice);
    document.getElementById('capacity-summary').innerHTML = [
      capacityCard('Receita esperada', capacity.expected_income_total, 'emerald'),
      capacityCard('Custos fixos', capacity.fixed_cost_total, 'red'),
      capacityCard('Fatura', capacity.card_invoice_total, 'orange'),
      capacityCard('Sobra estimada', capacity.remaining_after_invoice, capacity.remaining_after_invoice >= 0 ? 'emerald' : 'red'),
    ].join('');

    renderMonthBreakdown(fixed);
  } catch (err) {
    showToast(`Erro ao carregar mês: ${err.message}`, 'error');
  }
}

function renderMonthBreakdown(fixed) {
  const list = document.getElementById('month-breakdown');
  list.innerHTML = '';
  if (fixed.entries.length === 0) {
    list.innerHTML = '<li class="py-6 text-sm text-slate-500 text-center">Nenhum custo fixo ativo. Cadastre um custo base abaixo.</li>';
    return;
  }
  const groups = new Map();
  for (const item of fixed.entries) {
    const key = item.category_id;
    if (!groups.has(key)) {
      groups.set(key, {
        category_name: item.category_name,
        category_color: item.category_color,
        items: [],
        total: 0,
      });
    }
    const group = groups.get(key);
    group.items.push(item);
    group.total += Number(item.amount || 0);
  }
  for (const group of groups.values()) {
    const groupLi = document.createElement('li');
    groupLi.className = 'py-4';
    groupLi.innerHTML = `
      <div class="flex items-center justify-between gap-3 mb-2">
        <div class="flex items-center gap-2 min-w-0">
          <span class="size-3 rounded-full shrink-0" style="background:${escapeHtml(group.category_color)}"></span>
          <p class="font-semibold text-slate-900 truncate">${escapeHtml(group.category_name)}</p>
        </div>
        <p class="font-bold tabular text-slate-900">${currency.format(group.total)}</p>
      </div>
      <ul class="divide-y divide-slate-100 rounded-xl border border-slate-100 overflow-hidden"></ul>
    `;
    const inner = groupLi.querySelector('ul');
    for (const item of group.items) inner.appendChild(buildMonthRow(item));
    list.appendChild(groupLi);
  }
}

function buildMonthRow(item) {
  const li = document.createElement('li');
  li.className = 'py-3 flex items-center gap-3';
  const overrideBadge = item.is_override
    ? '<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">override</span>'
    : '';
  const baseHint = item.is_override
    ? `<button type="button" data-action="revert" class="text-xs text-slate-500 hover:text-slate-900 underline">reverter para base (${currency.format(item.base_amount)})</button>`
    : `<span class="text-xs text-slate-400">base ${currency.format(item.base_amount)}</span>`;
  li.innerHTML = `
    <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-semibold text-sm shrink-0 tabular">${item.due_day}</span>
    <span class="size-3 rounded-full shrink-0" style="background:${escapeHtml(item.category_color)}"></span>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <p class="font-medium text-slate-900 truncate">${escapeHtml(item.description)}</p>
        ${overrideBadge}
        ${statusBadge(item.status)}
      </div>
      <div class="mt-0.5 text-xs text-slate-500">
        vence em ${formatDate(item.due_date)} · ${baseHint}
        ${item.matched_transaction ? ` · conciliado com ${escapeHtml(item.matched_transaction.description)}` : ''}
      </div>
    </div>
    <input
      type="number"
      step="0.01"
      min="0"
      data-action="edit"
      class="w-32 text-right text-sm font-semibold tabular rounded-lg border border-slate-300 px-2 py-1 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
      value="${Number(item.amount).toFixed(2)}"
    />
  `;
  const input = li.querySelector('input[data-action="edit"]');
  const commit = async () => {
    const newAmount = Number(input.value);
    if (Number.isNaN(newAmount) || newAmount < 0) {
      input.value = Number(item.amount).toFixed(2);
      return;
    }
    if (Math.abs(newAmount - Number(item.amount)) < 0.005) return;
    if (Math.abs(newAmount - Number(item.base_amount)) < 0.005 && item.is_override) {
      try {
        await fetchJson(`/fixed-costs/${item.fixed_cost_id}/overrides/${selectedMonth}`, { method: 'DELETE' });
        await loadMonthData();
        showToast('Override removido.', 'success');
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
        showToast('Override removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
  return li;
}

function formatDate(iso) {
  const [year, month, day] = String(iso).split('-');
  if (!year || !month || !day) return iso;
  return `${day}/${month}/${year}`;
}

async function loadCategories() {
  categories = await fetchJson('/fixed-cost-categories');
  const list = document.getElementById('category-list');
  const select = document.getElementById('cost-category');
  list.innerHTML = '';
  select.innerHTML = '';
  document.getElementById('category-count').textContent =
    categories.length === 1 ? '1 categoria' : `${categories.length} categorias`;
  const customCount = categories.filter((category) => !category.is_default).length;
  const remaining = Math.max(0, MAX_CUSTOM_CATEGORIES - customCount);
  document.getElementById('custom-category-count').textContent =
    `${customCount}/${MAX_CUSTOM_CATEGORIES} categorias personalizadas usadas · ${remaining} restante${remaining === 1 ? '' : 's'}`;
  const addButton = document.querySelector('#category-form button[type="submit"]');
  if (addButton) {
    addButton.disabled = customCount >= MAX_CUSTOM_CATEGORIES;
    addButton.classList.toggle('opacity-50', customCount >= MAX_CUSTOM_CATEGORIES);
    addButton.classList.toggle('cursor-not-allowed', customCount >= MAX_CUSTOM_CATEGORIES);
  }
  if (categories.length === 0) {
    list.innerHTML = '<li class="py-6 text-sm text-slate-500 text-center">Nenhuma categoria cadastrada ainda.</li>';
    select.innerHTML = '<option value="">Cadastre uma categoria primeiro</option>';
    return;
  }
  for (const category of categories) {
    const option = document.createElement('option');
    option.value = category.id;
    option.textContent = category.name;
    select.appendChild(option);
    list.appendChild(buildCategoryRow(category));
  }
}

function buildCategoryRow(category) {
  const li = document.createElement('li');
  li.className = 'py-3 flex items-center gap-3';
  const badge = category.is_default
    ? '<span class="text-[10px] font-semibold uppercase tracking-wider text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">padrão</span>'
    : '<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">personalizada</span>';
  const deleteButton = category.is_default
    ? ''
    : '<button type="button" data-action="delete" class="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors shrink-0">Excluir</button>';
  li.innerHTML = `
    <span class="size-4 rounded-full shrink-0" style="background:${escapeHtml(category.color)}"></span>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <p class="font-medium text-slate-900 truncate">${escapeHtml(category.name)}</p>
        ${badge}
      </div>
      <p class="text-xs text-slate-500">ordem ${category.sort_order}</p>
    </div>
    ${deleteButton}
  `;
  const deleteAction = li.querySelector('[data-action="delete"]');
  if (!deleteAction) return li;
  deleteAction.addEventListener('click', async () => {
    if (!confirm(`Excluir categoria "${category.name}"?`)) return;
    try {
      await fetchJson(`/fixed-cost-categories/${category.id}`, { method: 'DELETE' });
      await Promise.all([loadCategories(), loadCosts(), loadMonthData()]);
      showToast('Categoria excluída.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });
  return li;
}

async function loadTemplates() {
  const list = document.getElementById('template-list');
  if (!list) return;
  try {
    const templates = await fetchJson('/fixed-costs/templates');
    list.innerHTML = templates.map((template) => `
      <button
        type="button"
        data-template="${escapeHtml(template.label)}"
        class="text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded-lg transition-colors"
      >
        ${escapeHtml(template.label)}
      </button>
    `).join('');
    list.querySelectorAll('button[data-template]').forEach((button) => {
      button.addEventListener('click', () => {
        const template = templates.find((item) => item.label === button.dataset.template);
        if (!template) return;
        if (template.category_id) document.getElementById('cost-category').value = template.category_id;
        document.getElementById('cost-description').value = template.description;
        document.getElementById('cost-day').value = template.due_day;
        document.getElementById('cost-amount').focus();
      });
    });
  } catch (err) {
    list.innerHTML = '<span class="text-xs text-slate-500">Templates indisponíveis.</span>';
  }
}

async function loadCosts() {
  const showInactive = document.getElementById('show-inactive').checked;
  const costs = await fetchJson('/fixed-costs' + (showInactive ? '?include_inactive=true' : ''));
  const list = document.getElementById('cost-list');
  list.innerHTML = '';
  document.getElementById('cost-count').textContent =
    costs.length === 1 ? '1 custo' : `${costs.length} custos`;
  const activeTotal = costs
    .filter((cost) => cost.active)
    .reduce((sum, cost) => sum + Number(cost.amount || 0), 0);
  document.getElementById('active-total').textContent = currency.format(activeTotal);
  if (costs.length === 0) {
    list.innerHTML = '<li class="py-6 text-sm text-slate-500 text-center">Nenhum custo fixo cadastrado ainda.</li>';
    return;
  }
  for (const cost of costs) list.appendChild(buildCostRow(cost));
}

function buildCostRow(cost) {
  const li = document.createElement('li');
  li.className = 'py-3 flex items-center gap-3';
  const activeLabel = cost.active ? 'Desativar' : 'Reativar';
  li.innerHTML = `
    <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-semibold text-sm shrink-0 tabular">${cost.due_day}</span>
    <span class="size-3 rounded-full shrink-0" style="background:${escapeHtml(cost.category_color)}"></span>
    <div class="flex-1 min-w-0">
      <p class="font-medium break-words ${cost.active ? 'text-slate-900' : 'text-slate-400 line-through'}">${escapeHtml(cost.description)}</p>
      <p class="text-xs text-slate-500 mt-0.5">${escapeHtml(cost.category_name)} · dia ${cost.due_day} de cada mês</p>
    </div>
    <p class="font-semibold tabular ${cost.active ? 'text-slate-900' : 'text-slate-400'}">${currency.format(cost.amount)}</p>
    <button type="button" data-action="edit" class="text-xs text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors shrink-0">Editar</button>
    <button type="button" data-action="toggle" class="text-xs text-slate-600 hover:text-slate-900 hover:bg-slate-100 px-2 py-1 rounded-lg transition-colors shrink-0">${activeLabel}</button>
    <button type="button" data-action="delete" class="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors shrink-0">Excluir</button>
  `;
  li.querySelector('[data-action="edit"]').addEventListener('click', () => {
    renderCostEditRow(li, cost);
  });
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
  return categories.map((category) => {
    const selected = Number(category.id) === Number(selectedId) ? 'selected' : '';
    return `<option value="${category.id}" ${selected}>${escapeHtml(category.name)}</option>`;
  }).join('');
}

function renderCostEditRow(li, cost) {
  li.className = 'py-3';
  li.innerHTML = `
    <form class="grid grid-cols-1 lg:grid-cols-[160px_1fr_140px_100px_auto_auto] gap-2">
      <select name="category_id" required class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100">${categoryOptions(cost.category_id)}</select>
      <input name="description" type="text" required value="${escapeHtml(cost.description)}" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
      <input name="amount" type="number" step="0.01" min="0.01" required value="${Number(cost.amount).toFixed(2)}" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
      <input name="due_day" type="number" min="1" max="31" required value="${cost.due_day}" class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
      <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg px-3 py-2">Salvar</button>
      <button type="button" data-action="cancel" class="text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg hover:bg-slate-100">Cancelar</button>
    </form>
  `;
  const form = li.querySelector('form');
  li.querySelector('[data-action="cancel"]').addEventListener('click', () => {
    li.replaceWith(buildCostRow(cost));
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(form);
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

document.getElementById('category-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.getElementById('category-name').value.trim();
  const color = document.getElementById('category-color').value;
  const sort_order = Number(document.getElementById('category-order').value || 0);
  if (!name) return;
  const customCount = categories.filter((category) => !category.is_default).length;
  if (customCount >= MAX_CUSTOM_CATEGORIES) {
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

document.getElementById('cost-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const category_id = Number(document.getElementById('cost-category').value);
  const description = document.getElementById('cost-description').value.trim();
  const amount = Number(document.getElementById('cost-amount').value);
  const due_day = Number(document.getElementById('cost-day').value);
  if (!category_id || !description || !amount || !due_day) return;
  try {
    await fetchJson('/fixed-costs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category_id, description, amount, due_day }),
    });
    document.getElementById('cost-description').value = '';
    document.getElementById('cost-amount').value = '';
    document.getElementById('cost-day').value = '';
    document.getElementById('cost-description').focus();
    await Promise.all([loadCosts(), loadMonthData()]);
    showToast('Custo fixo adicionado.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

document.getElementById('show-inactive').addEventListener('change', loadCosts);

async function loadTransactionSuggestions() {
  const list = document.getElementById('transaction-suggestions');
  if (!list) return;
  try {
    const transactions = await fetchJson('/transactions?account_type=ALL&include_ignored=true');
    const rows = transactions.slice(0, TRANSACTION_SUGGESTIONS_MAX);
    if (rows.length === 0) {
      list.innerHTML = '<li class="py-6 text-sm text-slate-500 text-center">Nenhuma transação recente encontrada.</li>';
      return;
    }
    list.innerHTML = '';
    rows.forEach((tx, index) => {
      const row = buildTransactionSuggestionRow(tx);
      if (index >= TRANSACTION_SUGGESTIONS_INITIAL) {
        row.classList.add('transaction-suggestion-extra', 'hidden');
      }
      list.appendChild(row);
    });
    if (rows.length > TRANSACTION_SUGGESTIONS_INITIAL) {
      const more = document.createElement('li');
      more.className = 'py-3 text-center';
      more.innerHTML = `
        <button type="button" class="inline-flex items-center gap-2 text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-3 py-2 rounded-lg transition-colors" data-action="show-more-transactions">
          <span aria-hidden="true">＋</span>
          Ver mais ${rows.length - TRANSACTION_SUGGESTIONS_INITIAL} transações
        </button>
      `;
      more.querySelector('[data-action="show-more-transactions"]').addEventListener('click', () => {
        list.querySelectorAll('.transaction-suggestion-extra').forEach((row) => {
          row.classList.remove('hidden');
        });
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
  li.className = 'py-3 flex items-center gap-3';
  li.innerHTML = `
    <div class="flex-1 min-w-0">
      <p class="font-medium text-slate-900 truncate">${escapeHtml(tx.description)}</p>
      <p class="text-xs text-slate-500 mt-0.5">${formatDate(tx.date)} · ${escapeHtml(tx.custom_category_name || tx.category || 'Sem categoria')}</p>
    </div>
    <p class="font-semibold tabular text-slate-900">${currency.format(Math.abs(Number(tx.amount) || 0))}</p>
    <button type="button" data-action="use" class="text-xs text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-2 py-1 rounded-lg transition-colors shrink-0">Criar custo</button>
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

(async () => {
  selectedMonth = currentYearMonth();
  monthStrip = Array.from({ length: MONTH_WINDOW }, (_, i) =>
    shiftYearMonth(selectedMonth, i)
  );
  renderMonthStrip();
  try {
    await loadCategories();
    await Promise.all([
      loadTemplates(),
      loadCosts(),
      loadMonthData(),
      loadTransactionSuggestions(),
    ]);
    document.getElementById('subtitle').textContent =
      'Cadastre compromissos recorrentes para calcular sua sobra mensal.';
  } catch (err) {
    showToast(err.message, 'error');
    document.getElementById('subtitle').textContent = 'Erro ao carregar custos fixos.';
  }
})();
