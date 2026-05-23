const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

const monthLongFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'long',
  year: 'numeric',
});

const FALLBACK_COLOR = '#64748b';

let progressData = null;
let editingCategory = null;
let selectedMonth = currentYearMonth();
let deleteArmed = false;
let deleteResetTimer = null;

function currentYearMonth() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${now.getFullYear()}-${month}`;
}

function shiftYearMonth(yyyymm, delta) {
  const [year, month] = yyyymm.split('-').map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  const nextMonth = String(date.getMonth() + 1).padStart(2, '0');
  return `${date.getFullYear()}-${nextMonth}`;
}

function formatMonthLong(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  const label = monthLongFormatter.format(new Date(year, month - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function statusStyles(status) {
  if (status === 'over') return { bar: 'bg-red-500', text: 'text-red-600' };
  if (status === 'warning') return { bar: 'bg-amber-500', text: 'text-amber-600' };
  if (status === 'ok') return { bar: 'bg-emerald-500', text: 'text-emerald-600' };
  return { bar: 'bg-slate-300', text: 'text-slate-500' };
}

function pluralCompras(n) {
  return n === 1 ? '1 compra' : `${n.toLocaleString('pt-BR')} compras`;
}

function scopeText(scope) {
  if (scope === 'month') return 'Meta deste mês';
  if (scope === 'default') return 'Meta padrão';
  return '';
}

function formatInputValue(value) {
  return Number(value).toFixed(2).replace('.', ',');
}

function parseTargetValue(raw) {
  const cleaned = String(raw)
    .trim()
    .replace(/[R$\s]/g, '');
  if (cleaned.length === 0) return NaN;
  const normalized = cleaned.includes(',')
    ? cleaned.replace(/\./g, '').replace(',', '.')
    : cleaned;
  return Number.parseFloat(normalized);
}

function showToast(message, variant = 'info') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.classList.remove('hidden', 'bg-slate-900', 'bg-red-600', 'bg-emerald-600');
  el.classList.add(
    variant === 'error'
      ? 'bg-red-600'
      : variant === 'success'
      ? 'bg-emerald-600'
      : 'bg-slate-900',
  );
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => el.classList.add('hidden'), 4000);
}

function renderMonthControls() {
  document.getElementById('month-pill').textContent = formatMonthLong(selectedMonth);
}

function renderCard(item) {
  const color = item.category_color || FALLBACK_COLOR;
  const hasBudget = item.target !== null;
  const pct = hasBudget && item.progress_pct !== null
    ? Math.min(item.progress_pct, 100)
    : 0;
  const overshoot = hasBudget && item.progress_pct > 100;
  const styles = statusStyles(item.status);
  const txText = pluralCompras(item.count);
  const details = [
    `Realizado ${currency.format(item.actual_spent)}`,
    item.future_spent > 0 ? `futuro ${currency.format(item.future_spent)}` : null,
  ].filter(Boolean).join(' · ');

  const right = hasBudget
    ? `
      <div class="text-right shrink-0 ml-3">
        <p class="text-sm font-semibold tabular text-slate-900">
          ${currency.format(item.projected_spent)} / ${currency.format(item.target)}
        </p>
        <p class="text-xs ${styles.text} font-medium tabular mt-0.5">
          ${item.progress_pct.toFixed(0)}%${overshoot ? ' · ultrapassou' : ''}
        </p>
      </div>
    `
    : `
      <button
        class="set-budget shrink-0 ml-3 text-sm font-medium text-indigo-600 hover:text-indigo-700"
        data-category-id="${item.category_id}"
      >
        Definir meta
      </button>
    `;

  return `
    <div
      class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm category-row"
      data-category-id="${item.category_id}"
    >
      <div class="flex items-center gap-3 mb-3">
        <span class="inline-block size-3 rounded-full shrink-0" style="background:${color}"></span>
        <div class="min-w-0 flex-1">
          <h3 class="font-medium text-slate-900 truncate">${escapeHtml(item.category_name)}</h3>
          <p class="text-xs text-slate-500 tabular mt-0.5">
            ${txText}${hasBudget ? ` · ${escapeHtml(scopeText(item.target_scope))}` : ''} · ${escapeHtml(details)}
          </p>
        </div>
        ${right}
      </div>
      ${hasBudget ? `
        <div class="h-2 rounded-full bg-slate-100 overflow-hidden">
          <div class="bar h-full ${styles.bar}" style="width:${pct}%"></div>
        </div>
      ` : ''}
    </div>
  `;
}

function renderSummary() {
  const summary = document.getElementById('summary');
  const data = progressData.summary;
  if (!data || data.target <= 0) {
    summary.classList.add('hidden');
    return;
  }
  summary.classList.remove('hidden');
  const pct = data.progress_pct || 0;
  document.getElementById('summary-text').textContent =
    `${currency.format(data.projected_spent)} / ${currency.format(data.target)}`;
  document.getElementById('summary-pct').textContent = `${pct.toFixed(0)}%`;
  document.getElementById('summary-detail').textContent =
    `Realizado: ${currency.format(data.actual_spent)} · Futuro no mês: ${currency.format(data.future_spent)}`;

  const bar = document.getElementById('summary-bar');
  bar.style.width = `${Math.min(pct, 100)}%`;
  bar.classList.remove('bg-indigo-600', 'bg-emerald-500', 'bg-amber-500', 'bg-red-500');
  if (pct >= 100) bar.classList.add('bg-red-500');
  else if (pct >= 80) bar.classList.add('bg-amber-500');
  else bar.classList.add('bg-emerald-500');
}

async function loadData() {
  renderMonthControls();
  const params = new URLSearchParams({ year_month: selectedMonth });
  const response = await fetch(`/budgets/progress?${params}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  progressData = await response.json();
  selectedMonth = progressData.year_month;
  renderMonthControls();

  const subtitle = document.getElementById('subtitle');
  const empty = document.getElementById('empty');
  const cards = document.getElementById('cards');

  if (!progressData.items || progressData.items.length === 0) {
    empty.classList.remove('hidden');
    cards.innerHTML = '';
    subtitle.textContent = formatMonthLong(progressData.year_month);
    return;
  }
  empty.classList.add('hidden');
  subtitle.textContent =
    `${formatMonthLong(progressData.year_month)} · realizado e projetado`;

  renderSummary();
  cards.innerHTML = progressData.items.map(renderCard).join('');

  cards.querySelectorAll('.category-row').forEach((row) => {
    const id = parseInt(row.dataset.categoryId, 10);
    const item = progressData.items.find((i) => i.category_id === id);
    if (!item) return;
    if (item.target !== null) {
      row.style.cursor = 'pointer';
      row.addEventListener('click', () => openEdit(item));
    }
  });
  cards.querySelectorAll('button.set-budget').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.categoryId, 10);
      const item = progressData.items.find((i) => i.category_id === id);
      if (item) openEdit(item);
    });
  });
}

function setScope(scope) {
  const input = document.querySelector(`input[name="target-scope"][value="${scope}"]`);
  if (input) input.checked = true;
}

function selectedScope() {
  return document.querySelector('input[name="target-scope"]:checked')?.value || 'month';
}

function resetDeleteState() {
  deleteArmed = false;
  clearTimeout(deleteResetTimer);
  const button = document.getElementById('modal-delete');
  if (editingCategory?.target_scope === 'month') {
    button.textContent = 'Remover meta deste mês';
  } else {
    button.textContent = 'Remover meta padrão';
  }
}

function openEdit(item) {
  editingCategory = item;
  document.getElementById('modal-title').textContent = item.category_name;
  document.getElementById('modal-color').style.background =
    item.category_color || FALLBACK_COLOR;
  document.getElementById('modal-target').value =
    item.target !== null ? formatInputValue(item.target) : '';
  document.getElementById('modal-delete').classList.toggle('hidden', item.target === null);
  document.getElementById('scope-month-label').textContent =
    `Apenas em ${formatMonthLong(selectedMonth)}`;
  setScope(item.target_scope === 'default' ? 'default' : 'month');
  resetDeleteState();
  document.getElementById('edit-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('modal-target').focus(), 50);
}

function closeEdit() {
  editingCategory = null;
  resetDeleteState();
  document.getElementById('edit-modal').classList.add('hidden');
}

async function saveTarget(event) {
  event.preventDefault();
  if (!editingCategory) return;
  const value = parseTargetValue(document.getElementById('modal-target').value);
  if (!Number.isFinite(value) || value <= 0) {
    showToast('Informe uma meta maior que zero.', 'error');
    return;
  }
  const id = editingCategory.category_id;
  const scope = selectedScope();
  const previousScope = editingCategory.target_scope;
  const path = scope === 'month'
    ? `/budgets/${id}/months/${selectedMonth}`
    : `/budgets/${id}`;
  closeEdit();
  try {
    const response = await fetch(path, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ monthly_target: value }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (scope === 'default' && previousScope === 'month') {
      const cleanup = await fetch(`/budgets/${id}/months/${selectedMonth}`, {
        method: 'DELETE',
      });
      if (!cleanup.ok) throw new Error(`HTTP ${cleanup.status}`);
    }
    await loadData();
    showToast('Meta salva.', 'success');
  } catch (err) {
    console.error(err);
    showToast('Erro ao salvar meta.', 'error');
  }
}

async function deleteTarget() {
  if (!editingCategory || editingCategory.target_scope === null) return;
  if (!deleteArmed) {
    deleteArmed = true;
    const button = document.getElementById('modal-delete');
    button.textContent = 'Confirmar remoção';
    showToast('Clique novamente para confirmar a remoção.');
    deleteResetTimer = setTimeout(resetDeleteState, 3500);
    return;
  }

  const id = editingCategory.category_id;
  const path = editingCategory.target_scope === 'month'
    ? `/budgets/${id}/months/${selectedMonth}`
    : `/budgets/${id}`;
  closeEdit();
  try {
    const response = await fetch(path, { method: 'DELETE' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await loadData();
    showToast('Meta removida.', 'success');
  } catch (err) {
    console.error(err);
    showToast('Erro ao remover meta.', 'error');
  }
}

document.getElementById('prev-month').addEventListener('click', () => {
  selectedMonth = shiftYearMonth(selectedMonth, -1);
  loadData().catch((err) => {
    console.error(err);
    showToast('Erro ao carregar orçamento.', 'error');
  });
});

document.getElementById('next-month').addEventListener('click', () => {
  selectedMonth = shiftYearMonth(selectedMonth, 1);
  loadData().catch((err) => {
    console.error(err);
    showToast('Erro ao carregar orçamento.', 'error');
  });
});

document.getElementById('current-month').addEventListener('click', () => {
  selectedMonth = currentYearMonth();
  loadData().catch((err) => {
    console.error(err);
    showToast('Erro ao carregar orçamento.', 'error');
  });
});

document.getElementById('modal-close').addEventListener('click', closeEdit);
document.getElementById('modal-cancel').addEventListener('click', closeEdit);
document.getElementById('modal-form').addEventListener('submit', saveTarget);
document.getElementById('modal-delete').addEventListener('click', deleteTarget);
document.getElementById('edit-modal').addEventListener('click', (e) => {
  if (e.target.id === 'edit-modal') closeEdit();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeEdit();
});

loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
  showToast('Erro ao carregar orçamento.', 'error');
});
