'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const MONTH_WINDOW = 6;
let selectedMonth = null; // YYYY-MM
let monthStrip = []; // [YYYY-MM, ...] computed once on load

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
  const r = await fetch(url, options);
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.json())?.detail || ''; } catch {}
    throw new Error(detail || `HTTP ${r.status}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

function buildEntryRow(entry) {
  const li = document.createElement('li');
  li.className = 'py-3 flex items-center gap-3';
  const dayBadge = `<span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-semibold text-sm shrink-0 tabular">${entry.expected_day}</span>`;
  const desc = `<p class="font-medium text-slate-900 break-words ${entry.active ? '' : 'text-slate-400 line-through'}">${escapeHtml(entry.description)}</p>`;
  const amount = `<p class="font-semibold tabular ${entry.active ? 'text-slate-900' : 'text-slate-400'}">${currency.format(entry.amount)}</p>`;
  const activeLabel = entry.active ? 'Desativar' : 'Reativar';
  li.innerHTML = `
    ${dayBadge}
    <div class="flex-1 min-w-0">
      ${desc}
      <p class="text-xs text-slate-500 mt-0.5">dia ${entry.expected_day} de cada mês</p>
    </div>
    ${amount}
    <button type="button" data-action="toggle" class="text-xs text-slate-600 hover:text-slate-900 hover:bg-slate-100 px-2 py-1 rounded-lg transition-colors shrink-0">${activeLabel}</button>
    <button type="button" data-action="delete" class="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-lg transition-colors shrink-0">Excluir</button>
  `;

  li.querySelector('[data-action="toggle"]').addEventListener('click', async () => {
    try {
      await fetchJson(`/expected-income/${entry.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !entry.active }),
      });
      await Promise.all([loadEntries(), loadMonthBreakdown()]);
      showToast(entry.active ? 'Entrada desativada.' : 'Entrada reativada.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  li.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    if (!confirm(`Excluir "${entry.description}"?`)) return;
    try {
      await fetchJson(`/expected-income/${entry.id}`, { method: 'DELETE' });
      await Promise.all([loadEntries(), loadMonthBreakdown()]);
      showToast('Entrada excluída.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  return li;
}

async function loadEntries() {
  const showInactive = document.getElementById('show-inactive').checked;
  try {
    const entries = await fetchJson(
      '/expected-income' + (showInactive ? '?include_inactive=true' : '')
    );
    const list = document.getElementById('entry-list');
    list.innerHTML = '';
    document.getElementById('entry-count').textContent =
      entries.length === 1 ? '1 entrada' : `${entries.length} entradas`;

    const activeTotal = entries
      .filter((e) => e.active)
      .reduce((sum, e) => sum + Number(e.amount || 0), 0);
    document.getElementById('active-total').textContent = currency.format(activeTotal);

    if (entries.length === 0) {
      list.innerHTML = '<li class="py-6 text-sm text-slate-500 text-center">Nenhuma entrada cadastrada ainda.</li>';
      return;
    }
    for (const entry of entries) list.appendChild(buildEntryRow(entry));
  } catch (err) {
    showToast(`Erro ao carregar: ${err.message}`, 'error');
  }
}

document.getElementById('entry-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const description = document.getElementById('entry-description').value.trim();
  const amount = Number(document.getElementById('entry-amount').value);
  const expected_day = Number(document.getElementById('entry-day').value);
  if (!description || !amount || !expected_day) return;
  try {
    await fetchJson('/expected-income', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description, amount, expected_day }),
    });
    document.getElementById('entry-description').value = '';
    document.getElementById('entry-amount').value = '';
    document.getElementById('entry-day').value = '';
    document.getElementById('entry-description').focus();
    await loadEntries();
    showToast('Entrada adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

document.getElementById('show-inactive').addEventListener('change', loadEntries);

function currentYearMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function shiftYearMonth(ym, offset) {
  const [y, m] = ym.split('-').map(Number);
  const zeroBased = y * 12 + (m - 1) + offset;
  return `${String(Math.floor(zeroBased / 12)).padStart(4, '0')}-${String((zeroBased % 12) + 1).padStart(2, '0')}`;
}

const MONTH_LABELS_LONG = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
function formatMonthShort(ym) {
  const [y, m] = ym.split('-').map(Number);
  return `${MONTH_LABELS_LONG[m - 1]}/${String(y).slice(2)}`;
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
      (active
        ? 'bg-indigo-600 text-white'
        : 'bg-slate-100 text-slate-700 hover:bg-slate-200');
    button.textContent = formatMonthShort(ym);
    button.addEventListener('click', () => {
      if (ym === selectedMonth) return;
      selectedMonth = ym;
      renderMonthStrip();
      loadMonthBreakdown();
    });
    strip.appendChild(button);
  }
}

async function loadMonthBreakdown() {
  if (!selectedMonth) return;
  try {
    const data = await fetchJson(
      `/expected-income/by-month?year_month=${selectedMonth}`
    );
    document.getElementById('month-total').textContent = currency.format(data.total);
    const list = document.getElementById('month-breakdown');
    list.innerHTML = '';
    if (data.entries.length === 0) {
      list.innerHTML =
        '<li class="py-6 text-sm text-slate-500 text-center">Nenhuma entrada ativa. Cadastre uma na seção abaixo.</li>';
      return;
    }
    for (const item of data.entries) list.appendChild(buildBreakdownRow(item));
  } catch (err) {
    showToast(`Erro ao carregar o mês: ${err.message}`, 'error');
  }
}

function buildBreakdownRow(item) {
  const li = document.createElement('li');
  li.className = 'py-3 flex items-center gap-3';
  const overrideBadge = item.is_override
    ? `<span class="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">override</span>`
    : '';
  const baseHint = item.is_override
    ? `<button type="button" data-action="revert" class="text-xs text-slate-500 hover:text-slate-900 underline">reverter para base (${currency.format(item.base_amount)})</button>`
    : `<span class="text-xs text-slate-400">base ${currency.format(item.base_amount)}</span>`;
  li.innerHTML = `
    <span class="inline-flex items-center justify-center size-9 rounded-lg bg-slate-100 text-slate-700 font-semibold text-sm shrink-0 tabular">${item.expected_day}</span>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <p class="font-medium text-slate-900 truncate">${escapeHtml(item.description)}</p>
        ${overrideBadge}
      </div>
      <div class="mt-0.5">${baseHint}</div>
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
      // Editing back to base → delete override.
      try {
        await fetchJson(
          `/expected-income/${item.expected_income_id}/overrides/${selectedMonth}`,
          { method: 'DELETE' }
        );
        await loadMonthBreakdown();
        showToast('Override removido (voltou ao base).', 'success');
      } catch (err) { showToast(err.message, 'error'); }
      return;
    }
    try {
      await fetchJson(
        `/expected-income/${item.expected_income_id}/overrides/${selectedMonth}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ amount: newAmount }),
        }
      );
      await loadMonthBreakdown();
      showToast('Valor do mês atualizado.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = Number(item.amount).toFixed(2); input.blur(); }
  });

  const revertBtn = li.querySelector('[data-action="revert"]');
  if (revertBtn) {
    revertBtn.addEventListener('click', async () => {
      try {
        await fetchJson(
          `/expected-income/${item.expected_income_id}/overrides/${selectedMonth}`,
          { method: 'DELETE' }
        );
        await loadMonthBreakdown();
        showToast('Override removido.', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
  return li;
}

(async () => {
  // Build month strip starting from the current month.
  selectedMonth = currentYearMonth();
  monthStrip = Array.from({ length: MONTH_WINDOW }, (_, i) =>
    shiftYearMonth(selectedMonth, i)
  );
  renderMonthStrip();
  await Promise.all([loadEntries(), loadMonthBreakdown()]);
  document.getElementById('subtitle').textContent =
    'Cadastre o que você espera receber em cada mês.';
})();
