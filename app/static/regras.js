'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

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

function categoryOptions(selectedId) {
  return categories
    .map((c) => {
      const selected = Number(c.id) === Number(selectedId) ? 'selected' : '';
      return `<option value="${c.id}" ${selected}>${escapeHtml(c.name)}</option>`;
    })
    .join('');
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
            await Promise.all([loadDescCategoryRules(), loadDescCategorySuggestions()]);
            showToast('Regra excluída.', 'success');
          } catch (err) { showToast(err.message, 'error'); }
        },
      }));
    }
  } catch (err) { showToast(`Erro ao listar regras: ${err.message}`, 'error'); }
}

async function loadDescCategorySuggestions() {
  const list = document.getElementById('desc-cat-suggestions');
  if (!list) return;
  list.innerHTML = '<li class="text-xs text-slate-500 py-2">Carregando sugestões…</li>';
  try {
    const payload = await fetchJson('/category-rules/description/suggestions?months=12&min_count=2&limit=10');
    const suggestions = payload.suggestions || [];
    if (suggestions.length === 0) {
      list.innerHTML = '<li class="text-xs text-slate-500 py-2">Nenhuma sugestão recorrente encontrada.</li>';
      return;
    }
    list.innerHTML = '';
    for (const suggestion of suggestions) {
      const li = document.createElement('li');
      li.className = 'rounded-xl border border-slate-200 bg-white p-3 flex flex-col lg:flex-row lg:items-center gap-3';
      li.innerHTML = `
        <div class="flex-1 min-w-0">
          <p class="font-medium text-slate-900 break-words">${escapeHtml(suggestion.sample_description)}</p>
          <p class="text-xs text-slate-500 mt-0.5">
            ${suggestion.transaction_count.toLocaleString('pt-BR')} ocorrências · ${currency.format(suggestion.total || 0)}
            ${suggestion.current_category_name ? ` · hoje em ${escapeHtml(suggestion.current_category_name)}` : ''}
          </p>
        </div>
        <div class="flex flex-col sm:flex-row gap-2 shrink-0">
          <select data-category
            class="text-sm rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-50 bg-white">
            ${categoryOptions(suggestion.current_category_id)}
          </select>
          <button type="button" data-action="create"
            class="bg-blue-700 hover:bg-blue-800 text-white text-sm font-medium rounded-lg px-4 py-2">
            Criar regra
          </button>
        </div>
      `;
      li.querySelector('[data-action="create"]').addEventListener('click', async () => {
        const category_id = Number(li.querySelector('[data-category]').value);
        try {
          await fetchJson('/category-rules/description', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              pattern: suggestion.sample_description,
              category_id,
            }),
          });
          await Promise.all([loadDescCategoryRules(), loadDescCategorySuggestions()]);
          showToast('Regra criada a partir da sugestão.', 'success');
        } catch (err) { showToast(err.message, 'error'); }
      });
      list.appendChild(li);
    }
  } catch (err) {
    list.innerHTML = `<li class="text-xs text-red-600 py-2">${escapeHtml(err.message)}</li>`;
  }
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
    await Promise.all([loadDescCategoryRules(), loadDescCategorySuggestions()]);
    showToast('Regra adicionada.', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

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
  await Promise.all([loadDescCategoryRules(), loadDescCategorySuggestions()]);
  document.getElementById('subtitle').textContent = 'Gerencie as regras de categorização por descrição.';
})();

document.getElementById('desc-cat-suggestions-refresh')?.addEventListener('click', () => {
  loadDescCategorySuggestions();
});
