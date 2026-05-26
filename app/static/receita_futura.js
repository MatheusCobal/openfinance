'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

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
      await loadEntries();
      showToast(entry.active ? 'Entrada desativada.' : 'Entrada reativada.', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  li.querySelector('[data-action="delete"]').addEventListener('click', async () => {
    if (!confirm(`Excluir "${entry.description}"?`)) return;
    try {
      await fetchJson(`/expected-income/${entry.id}`, { method: 'DELETE' });
      await loadEntries();
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

(async () => {
  await loadEntries();
  document.getElementById('subtitle').textContent = 'Cadastre o que você espera receber em cada mês.';
})();
