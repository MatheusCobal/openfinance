const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

const monthLongFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'long',
  year: 'numeric',
});

const FALLBACK_COLOR = '#64748b';
const MIN_YEAR = 2000;
const MAX_FUTURE_MONTHS = 24;
const MAX_PAST_MONTHS = 120;

let progressData = null;
let editingCategory = null;
let selectedMonth = currentYearMonth();
let deleteArmed = false;
let deleteResetTimer = null;
let loadToken = 0;

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

function monthDelta(from, to) {
  const [fy, fm] = from.split('-').map(Number);
  const [ty, tm] = to.split('-').map(Number);
  return (ty - fy) * 12 + (tm - fm);
}

function canShiftMonth(delta) {
  const target = shiftYearMonth(selectedMonth, delta);
  const [year] = target.split('-').map(Number);
  if (year < MIN_YEAR) return false;
  const ahead = monthDelta(currentYearMonth(), target);
  if (ahead > MAX_FUTURE_MONTHS) return false;
  if (ahead < -MAX_PAST_MONTHS) return false;
  return true;
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

function hexWithAlpha(hex, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
}

function categoryIcon(name) {
  const key = String(name).toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '');
  const icons = {
    mercado:        '🛒',
    restaurantes:   '🍽️',
    transporte:     '🚗',
    saude:          '🩺',
    pets:           '🐾',
    casa:           '🏠',
    lazer:          '🎮',
    assinaturas:    '📺',
    educacao:       '📚',
    transferencias: '🔁',
    outros:         '📦',
  };
  return icons[key] ?? '💳';
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
  document.getElementById('prev-month').disabled = !canShiftMonth(-1);
  document.getElementById('next-month').disabled = !canShiftMonth(1);
}

function renderCard(item) {
  const color = item.category_color || FALLBACK_COLOR;
  const hasBudget = item.target !== null;

  // ── No budget: dashed placeholder card ───────────────────────
  if (!hasBudget) {
    return `
      <div class="rounded-2xl border-2 border-dashed border-slate-200 p-5 flex items-center gap-4 category-row cursor-pointer hover:border-slate-300 hover:bg-slate-50 transition-all" data-category-id="${item.category_id}">
        <div class="size-10 rounded-xl flex items-center justify-center shrink-0 text-xl leading-none" style="background:${hexWithAlpha(color, 0.15)}">
          ${categoryIcon(item.category_name)}
        </div>
        <div class="flex-1 min-w-0">
          <p class="font-bold text-slate-900">${escapeHtml(item.category_name)}</p>
          <p class="text-xs text-slate-500 mt-0.5 tabular">${currency.format(item.actual_spent)} gastos · ${pluralCompras(item.count)}</p>
        </div>
        <button class="set-budget shrink-0 text-sm font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors" data-category-id="${item.category_id}">
          + Meta
        </button>
      </div>
    `;
  }

  // ── Has budget: rich card with tinted header ──────────────────
  const pct = item.progress_pct !== null ? Math.min(item.progress_pct, 100) : 0;
  const overshoot = item.progress_pct > 100;
  const styles = statusStyles(item.status);
  const headerBg = `linear-gradient(135deg,${hexWithAlpha(color, 0.12)} 0%,${hexWithAlpha(color, 0.05)} 100%)`;

  return `
    <div class="rounded-2xl border border-slate-200 shadow-sm overflow-hidden cursor-pointer category-row" data-category-id="${item.category_id}">
      <div class="px-5 py-4" style="background:${headerBg}">
        <div class="flex items-start gap-3 mb-3">
          <div class="size-10 rounded-xl flex items-center justify-center shrink-0 mt-0.5 text-xl leading-none" style="background:${hexWithAlpha(color, 0.20)}">
            ${categoryIcon(item.category_name)}
          </div>
          <div class="flex-1 min-w-0">
            <p class="font-bold text-slate-900 leading-tight">${escapeHtml(item.category_name)}</p>
            <p class="text-xs text-slate-500 mt-0.5">${pluralCompras(item.count)} · ${escapeHtml(scopeText(item.target_scope))}</p>
          </div>
          <div class="text-right shrink-0 ml-2">
            <p class="text-2xl font-bold tabular ${styles.text}">${item.progress_pct.toFixed(0)}%</p>
            <p class="text-xs text-slate-500 tabular mt-0.5">
              ${currency.format(item.projected_spent)}<span class="text-slate-300"> / </span>${currency.format(item.target)}
            </p>
          </div>
        </div>
        <div class="h-3 rounded-full overflow-hidden" style="background:${hexWithAlpha(color, 0.18)}">
          <div class="bar h-full rounded-full ${styles.bar}" style="width:${pct}%"></div>
        </div>
      </div>
      <div class="px-5 py-3 bg-white flex items-center flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 border-t border-slate-100">
        <span class="tabular">Realizado <span class="font-semibold text-slate-700">${currency.format(item.actual_spent)}</span></span>
        ${item.future_spent > 0 ? `<span class="text-slate-300">·</span><span class="tabular">Futuro <span class="font-semibold text-slate-700">${currency.format(item.future_spent)}</span></span>` : ''}
        ${overshoot ? `<span class="text-slate-300">·</span><span class="font-semibold text-red-600">Ultrapassou ${currency.format(item.projected_spent - item.target)}</span>` : ''}
      </div>
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
  const detailParts = [
    `Realizado: ${currency.format(data.actual_spent)}`,
    `Futuro no mês: ${currency.format(data.future_spent)}`,
  ];
  if (data.unbudgeted_projected_spent > 0) {
    detailParts.push(
      `Fora do orçamento: ${currency.format(data.unbudgeted_projected_spent)}`,
    );
  }
  document.getElementById('summary-detail').textContent = detailParts.join(' · ');

  const bar = document.getElementById('summary-bar');
  bar.style.width = `${Math.min(pct, 100)}%`;
  // Use inline color so the bar stays legible on the dark gradient hero.
  if (pct >= 100) bar.style.background = '#f87171';      // red-400
  else if (pct >= 80) bar.style.background = '#fbbf24';  // amber-400
  else bar.style.background = '#34d399';                 // emerald-400
}

async function loadData() {
  const myToken = ++loadToken;
  renderMonthControls();
  const params = new URLSearchParams({ year_month: selectedMonth });
  const response = await fetch(`/budgets/progress?${params}`);
  if (myToken !== loadToken) return;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  if (myToken !== loadToken) return;
  progressData = data;
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
    row.addEventListener('click', () => openEdit(item));
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
  } catch (err) {
    console.error(err);
    showToast('Erro ao salvar meta.', 'error');
    return;
  }
  closeEdit();
  showToast('Meta salva.', 'success');
  try {
    await loadData();
  } catch (err) {
    console.error(err);
    showToast('Meta salva, mas falhou ao atualizar a tela.', 'error');
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
  try {
    const response = await fetch(path, { method: 'DELETE' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } catch (err) {
    console.error(err);
    showToast('Erro ao remover meta.', 'error');
    return;
  }
  closeEdit();
  showToast('Meta removida.', 'success');
  try {
    await loadData();
  } catch (err) {
    console.error(err);
    showToast('Meta removida, mas falhou ao atualizar a tela.', 'error');
  }
}

document.getElementById('prev-month').addEventListener('click', () => {
  if (!canShiftMonth(-1)) return;
  selectedMonth = shiftYearMonth(selectedMonth, -1);
  loadData().catch((err) => {
    console.error(err);
    showToast('Erro ao carregar orçamento.', 'error');
  });
});

document.getElementById('next-month').addEventListener('click', () => {
  if (!canShiftMonth(1)) return;
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
