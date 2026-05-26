'use strict';

let categories = [];

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

function ruleCountLabel(n) {
  return n === 1 ? '1 regra' : `${n} regras`;
}

function affectedLabel(n) {
  if (typeof n !== 'number') return '';
  return `${n.toLocaleString('pt-BR')} ${n === 1 ? 'transação afetada' : 'transações afetadas'}`;
}

function renderRuleItem({ summary, sub, onDelete }) {
  const li = document.createElement('li');
  li.className = 'py-3 flex items-start justify-between gap-4';
  li.innerHTML = `
    <div class="min-w-0">
      <p class="font-medium text-slate-900 break-words">${summary}</p>
      ${sub ? `<p class="text-xs text-slate-500 mt-0.5">${sub}</p>` : ''}
    </div>
    <button type="button" class="text-sm text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors shrink-0">Excluir</button>
  `;
  li.querySelector('button').addEventListener('click', onDelete);
  return li;
}

// ── Descrição → categoria ─────────────────────────────────────────
async function loadDescCategoryRules() {
  try {
    const rules = await fetchJson('/category-rules/description');
    const list = document.getElementById('desc-cat-list');
    list.innerHTML = '';
    document.getElementById('desc-cat-count').textContent = ruleCountLabel(rules.length);
    if (rules.length === 0) {
      list.innerHTML = '<li class="py-3 text-sm text-slate-500">Nenhuma regra cadastrada.</li>';
      return;
    }
    for (const rule of rules) {
      const summary = `<span class="text-slate-700">"${escapeHtml(rule.pattern)}"</span> → <span class="font-semibold" style="color:${rule.category_color || '#475569'}">${escapeHtml(rule.category_name || `#${rule.category_id}`)}</span>`;
      list.appendChild(renderRuleItem({
        summary,
        sub: affectedLabel(rule.affected_count),
        onDelete: async () => {
          if (!confirm(`Excluir regra "${rule.pattern}"?`)) return;
          try {
            await fetchJson(`/category-rules/description/${rule.id}`, { method: 'DELETE' });
            await loadDescCategoryRules();
            showToast('Regra excluída.', 'success');
          } catch (err) { showToast(err.message, 'error'); }
        },
      }));
    }
  } catch (err) { showToast(`Erro ao listar regras: ${err.message}`, 'error'); }
}

document.getElementById('desc-cat-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const pattern = document.getElementById('desc-cat-pattern').value.trim();
  const category_id = Number(document.getElementById('desc-cat-category').value);
  if (!pattern || !category_id) return;
  try {
    await fetchJson('/category-rules/description', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pattern, category_id }),
    });
    document.getElementById('desc-cat-pattern').value = '';
    await loadDescCategoryRules();
    showToast('Regra adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

// ── Ignorar descrição ─────────────────────────────────────────────
async function loadIgnoreRules() {
  try {
    const rules = await fetchJson('/transaction-ignore-rules/description');
    const list = document.getElementById('ignore-list');
    list.innerHTML = '';
    document.getElementById('ignore-count').textContent = ruleCountLabel(rules.length);
    if (rules.length === 0) {
      list.innerHTML = '<li class="py-3 text-sm text-slate-500">Nenhuma regra cadastrada.</li>';
      return;
    }
    for (const rule of rules) {
      list.appendChild(renderRuleItem({
        summary: `<span class="text-slate-700">"${escapeHtml(rule.pattern)}"</span>`,
        sub: affectedLabel(rule.affected_count),
        onDelete: async () => {
          if (!confirm(`Excluir regra "${rule.pattern}"?`)) return;
          try {
            await fetchJson(`/transaction-ignore-rules/description/${rule.id}`, { method: 'DELETE' });
            await loadIgnoreRules();
            showToast('Regra excluída.', 'success');
          } catch (err) { showToast(err.message, 'error'); }
        },
      }));
    }
  } catch (err) { showToast(`Erro ao listar regras: ${err.message}`, 'error'); }
}

document.getElementById('ignore-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const pattern = document.getElementById('ignore-pattern').value.trim();
  if (!pattern) return;
  try {
    await fetchJson('/transaction-ignore-rules/description', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pattern }),
    });
    document.getElementById('ignore-pattern').value = '';
    await loadIgnoreRules();
    showToast('Regra adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

// ── Excluir de receitas (banco) ───────────────────────────────────
async function loadBankIncomeRules() {
  try {
    const rules = await fetchJson('/bank-income/exclusion-rules');
    const list = document.getElementById('bank-income-list');
    list.innerHTML = '';
    document.getElementById('bank-income-count').textContent = ruleCountLabel(rules.length);
    if (rules.length === 0) {
      list.innerHTML = '<li class="py-3 text-sm text-slate-500">Nenhuma regra cadastrada.</li>';
      return;
    }
    for (const rule of rules) {
      const kind = rule.pluggy_category ? 'Categoria Pluggy' : 'Descrição';
      const value = rule.pluggy_category || rule.pattern || '—';
      list.appendChild(renderRuleItem({
        summary: `<span class="text-xs uppercase tracking-wider text-slate-400 mr-2">${escapeHtml(kind)}</span> <span class="text-slate-700">${escapeHtml(value)}</span>`,
        sub: affectedLabel(rule.affected_count),
        onDelete: async () => {
          if (!confirm(`Excluir regra de "${value}"?`)) return;
          try {
            await fetchJson(`/bank-income/exclusion-rules/${rule.id}`, { method: 'DELETE' });
            await loadBankIncomeRules();
            showToast('Regra excluída.', 'success');
          } catch (err) { showToast(err.message, 'error'); }
        },
      }));
    }
  } catch (err) { showToast(`Erro ao listar regras: ${err.message}`, 'error'); }
}

document.getElementById('bank-income-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const kind = document.getElementById('bank-income-kind').value;
  const value = document.getElementById('bank-income-value').value.trim();
  if (!value) return;
  const body = kind === 'pluggy_category' ? { pluggy_category: value } : { pattern: value };
  try {
    await fetchJson('/bank-income/exclusion-rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    document.getElementById('bank-income-value').value = '';
    await loadBankIncomeRules();
    showToast('Regra adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

// ── Excluir de fluxo bancário ─────────────────────────────────────
async function loadBankCashflowRules() {
  try {
    const rules = await fetchJson('/bank-cashflow/exclusion-rules');
    const list = document.getElementById('bank-cashflow-list');
    list.innerHTML = '';
    document.getElementById('bank-cashflow-count').textContent = ruleCountLabel(rules.length);
    if (rules.length === 0) {
      list.innerHTML = '<li class="py-3 text-sm text-slate-500">Nenhuma regra cadastrada.</li>';
      return;
    }
    for (const rule of rules) {
      const directionLabel = rule.direction === 'IN' ? 'Entradas' : rule.direction === 'OUT' ? 'Saídas' : 'Ambos';
      const kind = rule.pluggy_category ? 'Categoria Pluggy' : 'Descrição';
      const value = rule.pluggy_category || rule.pattern || '—';
      list.appendChild(renderRuleItem({
        summary: `<span class="text-xs uppercase tracking-wider text-slate-400 mr-2">${escapeHtml(directionLabel)} · ${escapeHtml(kind)}</span> <span class="text-slate-700">${escapeHtml(value)}</span>`,
        sub: affectedLabel(rule.affected_count),
        onDelete: async () => {
          if (!confirm(`Excluir regra de "${value}"?`)) return;
          try {
            await fetchJson(`/bank-cashflow/exclusion-rules/${rule.id}`, { method: 'DELETE' });
            await loadBankCashflowRules();
            showToast('Regra excluída.', 'success');
          } catch (err) { showToast(err.message, 'error'); }
        },
      }));
    }
  } catch (err) { showToast(`Erro ao listar regras: ${err.message}`, 'error'); }
}

document.getElementById('bank-cashflow-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const direction = document.getElementById('bank-cashflow-direction').value;
  const kind = document.getElementById('bank-cashflow-kind').value;
  const value = document.getElementById('bank-cashflow-value').value.trim();
  if (!value) return;
  const body = { direction, ...(kind === 'pluggy_category' ? { pluggy_category: value } : { pattern: value }) };
  try {
    await fetchJson('/bank-cashflow/exclusion-rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    document.getElementById('bank-cashflow-value').value = '';
    await loadBankCashflowRules();
    showToast('Regra adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

// ── Bootstrap ─────────────────────────────────────────────────────
async function loadCategories() {
  try {
    categories = await fetchJson('/categories');
    const select = document.getElementById('desc-cat-category');
    select.innerHTML = categories
      .sort((a, b) => (a.sort_order ?? 999) - (b.sort_order ?? 999))
      .map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`)
      .join('');
  } catch (err) { showToast('Erro ao carregar categorias.', 'error'); }
}

(async () => {
  await loadCategories();
  await Promise.all([
    loadDescCategoryRules(),
    loadIgnoreRules(),
    loadBankIncomeRules(),
    loadBankCashflowRules(),
  ]);
  document.getElementById('subtitle').textContent = 'Gerencie todas as regras de categorização e exclusão.';
})();
