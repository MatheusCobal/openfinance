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
  // Returns Tailwind classes for the progress bar fill and percentage label.
  if (status === 'over') return { bar: 'bg-red-500', text: 'text-red-600' };
  if (status === 'warning') return { bar: 'bg-amber-500', text: 'text-amber-600' };
  if (status === 'ok') return { bar: 'bg-emerald-500', text: 'text-emerald-600' };
  return { bar: 'bg-slate-300', text: 'text-slate-500' };
}

function renderCard(item) {
  const color = item.category_color || FALLBACK_COLOR;
  const hasBudget = item.target !== null;
  const pct = hasBudget ? Math.min(item.progress_pct, 100) : 0;
  const overshoot = hasBudget && item.progress_pct > 100;
  const styles = statusStyles(item.status);
  const txt = item.count === 1 ? '1 compra' : `${item.count.toLocaleString('pt-BR')} compras`;

  const right = hasBudget
    ? `
      <div class="text-right shrink-0 ml-3">
        <p class="text-sm font-semibold tabular text-slate-900">
          ${currency.format(item.spent)} / ${currency.format(item.target)}
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
        <h3 class="font-medium text-slate-900 flex-1 truncate">${escapeHtml(item.category_name)}</h3>
        <span class="text-xs text-slate-500 tabular shrink-0">${txt}</span>
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

function renderSummary(items) {
  const summary = document.getElementById('summary');
  const budgeted = items.filter((i) => i.target !== null);
  if (budgeted.length === 0) {
    summary.classList.add('hidden');
    return;
  }
  summary.classList.remove('hidden');
  const totalTarget = budgeted.reduce((s, i) => s + i.target, 0);
  const totalSpent = budgeted.reduce((s, i) => s + i.spent, 0);
  const pct = totalTarget > 0 ? (totalSpent / totalTarget) * 100 : 0;
  document.getElementById('summary-text').textContent =
    `${currency.format(totalSpent)} / ${currency.format(totalTarget)}`;
  document.getElementById('summary-pct').textContent = `${pct.toFixed(0)}%`;

  const bar = document.getElementById('summary-bar');
  bar.style.width = `${Math.min(pct, 100)}%`;
  bar.classList.remove('bg-indigo-600', 'bg-emerald-500', 'bg-amber-500', 'bg-red-500');
  if (pct >= 100) bar.classList.add('bg-red-500');
  else if (pct >= 80) bar.classList.add('bg-amber-500');
  else bar.classList.add('bg-emerald-500');
}

async function loadData() {
  const response = await fetch('/budgets/progress');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  progressData = await response.json();

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
  subtitle.textContent = formatMonthLong(progressData.year_month);

  renderSummary(progressData.items);
  cards.innerHTML = progressData.items.map(renderCard).join('');

  // Whole row is clickable to edit when there's a budget; otherwise the
  // "Definir meta" button (set up below).
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

function openEdit(item) {
  editingCategory = item;
  document.getElementById('modal-title').textContent = item.category_name;
  document.getElementById('modal-color').style.background =
    item.category_color || FALLBACK_COLOR;
  document.getElementById('modal-target').value =
    item.target !== null ? item.target.toFixed(2) : '';
  document.getElementById('modal-delete').classList.toggle('hidden', item.target === null);
  document.getElementById('edit-modal').classList.remove('hidden');
  setTimeout(() => document.getElementById('modal-target').focus(), 50);
}

function closeEdit() {
  editingCategory = null;
  document.getElementById('edit-modal').classList.add('hidden');
}

async function saveTarget(event) {
  event.preventDefault();
  if (!editingCategory) return;
  const value = parseFloat(document.getElementById('modal-target').value);
  if (Number.isNaN(value) || value < 0) return;
  const id = editingCategory.category_id;
  closeEdit();
  try {
    const response = await fetch(`/budgets/${id}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ monthly_target: value }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await loadData();
  } catch (err) {
    console.error(err);
    alert('Erro ao salvar meta');
  }
}

async function deleteTarget() {
  if (!editingCategory) return;
  if (!confirm(`Remover a meta de ${editingCategory.category_name}?`)) return;
  const id = editingCategory.category_id;
  closeEdit();
  try {
    const response = await fetch(`/budgets/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await loadData();
  } catch (err) {
    console.error(err);
    alert('Erro ao remover meta');
  }
}

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
});
