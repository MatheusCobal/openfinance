'use strict';

const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

function fmt(v) {
  return currency.format(v ?? 0);
}

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function showToast(message, variant = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = 'fixed top-4 right-4 z-50 max-w-sm rounded-xl text-white text-sm px-4 py-3 shadow-lg ' +
    (variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-800');
  toast.classList.remove('hidden');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add('hidden'), 4000);
}

function currentYearMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function prevYearMonth(ym) {
  const [y, m] = ym.split('-').map(Number);
  if (m === 1) return `${y - 1}-12`;
  return `${y}-${String(m - 1).padStart(2, '0')}`;
}

function monthLabel(ym) {
  const [y, m] = ym.split('-').map(Number);
  const label = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' }).format(new Date(y, m - 1, 1));
  return label.replace(/\b\w/g, c => c.toUpperCase());
}

function monthLabelCompact(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit' }).format(new Date(y, m - 1, 1));
}

function headerDateLabel(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' }).format(new Date(y, m - 1, 1));
}

function planStatusBadge(status) {
  const configs = {
    over:    { label: 'Estourado',   cls: 'bg-white/25 text-white' },
    tight:   { label: 'Apertado',    cls: 'bg-amber-100/80 text-amber-800' },
    healthy: { label: 'Saudável',    cls: 'bg-emerald-100/80 text-emerald-800' },
    unknown: { label: 'Sem receita', cls: 'bg-white/20 text-white/80' },
  };
  const cfg = configs[status] || configs.unknown;
  return `<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.cls}">${escapeHtml(cfg.label)}</span>`;
}

function deltaHtml(current, previous, invertColors) {
  if (previous == null || previous <= 0) return '';
  const diff = current - previous;
  const pct = (diff / previous) * 100;
  const sign = diff >= 0 ? '+' : '';
  // invertColors=true: spending cards where less is better (negative = green)
  const isGood = invertColors ? diff < 0 : diff > 0;
  const color = diff === 0 ? 'text-slate-400' : isGood ? 'text-emerald-600' : 'text-red-500';
  return `<span class="${color} font-medium">${sign}${pct.toFixed(0)}% vs mês anterior</span>`;
}

function categoryIcon(name) {
  const key = String(name).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const icons = {
    mercado: '🛒', restaurantes: '🍽️', transporte: '🚗',
    saude: '🩺', pets: '🐾', casa: '🏠', lazer: '🎮',
    assinaturas: '📺', educacao: '📚', transferencias: '🔁', outros: '📦',
  };
  return icons[key] ?? '💳';
}

let currentData = null;
let prevData = null;
let statsData = null;
let currentYM = null;

async function fetchJson(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function loadData() {
  currentYM = currentYearMonth();
  const prevYM = prevYearMonth(currentYM);

  setLoading(true);
  setError(false);
  showContent(false);

  try {
    [currentData, prevData, statsData] = await Promise.all([
      fetchJson(`/planning/month/${currentYM}`),
      fetchJson(`/planning/month/${prevYM}`).catch(() => null),
      fetchJson('/stats/monthly').catch(() => null),
    ]);
    renderDashboard();
    setLoading(false);
    showContent(true);
  } catch (err) {
    setLoading(false);
    setError(true);
    console.error('Dashboard load error:', err);
  }
}

function setLoading(on) {
  document.getElementById('loading').classList.toggle('hidden', !on);
}

function setError(on) {
  document.getElementById('error-state').classList.toggle('hidden', !on);
}

function showContent(on) {
  document.getElementById('dashboard-content').classList.toggle('hidden', !on);
}

function renderDashboard() {
  const d = currentData;
  const cap = d.capacity ?? {};
  const income = d.income ?? {};
  const fixed = d.fixed_costs ?? {};
  const variable = d.variable_budgets ?? {};
  const invoice = d.credit_card_invoice ?? {};
  const raw = d.raw?.spending_capacity ?? {};

  const prevIncome = prevData?.income ?? null;
  const prevFixed = prevData?.fixed_costs ?? null;
  const prevVariable = prevData?.variable_budgets ?? null;
  const prevRaw = prevData?.raw?.spending_capacity ?? null;

  document.getElementById('header-date').textContent = headerDateLabel(currentYM);

  renderHero(cap);
  renderInvoiceCard(invoice, raw);
  document.getElementById('month-compact').textContent = monthLabelCompact(currentYM);
  renderSummaryCards({ income, fixed, variable, raw, prevIncome, prevRaw });
  renderCategories();
}

function renderHero(cap) {
  const available = cap.available_to_spend ?? 0;
  const status = cap.plan_status ?? 'unknown';
  const days = cap.days_remaining_in_month ?? 0;

  document.getElementById('hero-card').innerHTML = `
    <div class="flex items-center gap-2 mb-3">
      <p class="text-xs font-bold uppercase tracking-widest text-indigo-200">Disponível para gastar</p>
      ${planStatusBadge(status)}
    </div>
    <p class="text-5xl font-bold tabular leading-tight mb-5">${escapeHtml(fmt(available))}</p>
    <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-indigo-200">
      <span>${escapeHtml(monthLabel(currentYM))}</span>
      <span>&nbsp;·&nbsp;</span>
      <span>${days} dias restantes</span>
      <span>&nbsp;·&nbsp;</span>
      <span>plano em <a href="/planejamento" class="text-white font-semibold hover:underline">Planejamento</a></span>
    </div>
  `;
}

function renderInvoiceCard(invoice, raw) {
  const amount = invoice?.amount ?? raw?.card_invoice_official_total ?? raw?.card_invoice_total ?? 0;
  const discretionary = raw?.card_invoice_discretionary_total ?? 0;
  const fixedCost = raw?.card_invoice_fixed_cost_total ?? 0;

  document.getElementById('invoice-card-content').innerHTML = `
    <p class="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Fatura do cartão</p>
    <p class="text-4xl font-bold tabular text-slate-900 mb-3">${escapeHtml(fmt(amount))}</p>
    <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
      <span>${escapeHtml(monthLabel(currentYM))}</span>
      <span>&nbsp;·&nbsp;</span>
      <span>discricionária ${escapeHtml(fmt(discretionary))}</span>
      <span>&nbsp;·&nbsp;</span>
      <span>custos fixos ${escapeHtml(fmt(fixedCost))}</span>
    </div>
  `;
}

function renderSummaryCards({ income, fixed, variable, raw, prevIncome, prevRaw }) {
  const fixedEntries = fixed.entries ?? [];
  const fixedN = fixedEntries.length;
  const fixedActual = fixed.actual ?? 0;
  const fixedPending = fixed.pending ?? 0;
  const fixedSubtitle = `${fixedN} itens · pago ${fmt(fixedActual)} · pendente ${fmt(fixedPending)}`;

  const varPlanned = variable.planned ?? 0;
  const varSubtitle = varPlanned > 0
    ? `meta ${fmt(varPlanned)} · restante ${fmt(variable.remaining ?? 0)}`
    : 'sem meta configurada';

  const cards = [
    {
      label: 'Entradas',
      iconEmoji: '💰',
      iconBg: 'bg-emerald-100',
      amount: income.received ?? 0,
      amountCls: 'text-emerald-600',
      subtitle: 'Entradas bancárias reais',
      delta: deltaHtml(income.received ?? 0, prevIncome?.received, false),
    },
    {
      label: 'Saídas',
      iconEmoji: '↗',
      iconBg: 'bg-red-100',
      amount: raw.bank_outflows_total ?? 0,
      amountCls: 'text-red-600',
      subtitle: 'Saídas bancárias reais',
      delta: deltaHtml(raw.bank_outflows_total ?? 0, prevRaw?.bank_outflows_total, true),
    },
    {
      label: 'A receber',
      iconEmoji: '⏳',
      iconBg: 'bg-amber-100',
      amount: income.to_receive ?? 0,
      amountCls: 'text-slate-900',
      subtitle: `Receita esperada ${fmt(income.expected ?? 0)}`,
      delta: '',
    },
    {
      label: 'Custos fixos',
      iconEmoji: '📌',
      iconBg: 'bg-orange-100',
      amount: fixed.reserved_or_actual ?? 0,
      amountCls: 'text-red-600',
      subtitle: fixedSubtitle,
      delta: '',
    },
    {
      label: 'Variável usado',
      iconEmoji: '📋',
      iconBg: 'bg-purple-100',
      amount: variable.consumed ?? 0,
      amountCls: 'text-slate-900',
      subtitle: varSubtitle,
      delta: '',
    },
  ];

  document.getElementById('summary-cards').innerHTML = cards.map(card => `
    <div class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <p class="text-xs font-bold uppercase tracking-wider text-slate-500">${escapeHtml(card.label)}</p>
        <span class="size-8 rounded-full ${card.iconBg} flex items-center justify-center text-base leading-none">${card.iconEmoji}</span>
      </div>
      <p class="text-3xl font-bold tabular ${card.amountCls} mb-1">${escapeHtml(fmt(card.amount))}</p>
      <p class="text-xs text-slate-500">${escapeHtml(card.subtitle)}</p>
      ${card.delta ? `<p class="text-xs mt-1">${card.delta}</p>` : ''}
    </div>
  `).join('');
}

function renderCategories() {
  const container = document.getElementById('categories-grid');

  if (!statsData?.categories?.length || !currentYM) {
    container.innerHTML = '<p class="text-sm text-slate-500 col-span-full">Nenhuma compra categorizada neste mês.</p>';
    return;
  }

  const categories = statsData.categories
    .filter(cat => (cat.by_month?.[currentYM] ?? 0) > 0)
    .sort((a, b) => (b.by_month?.[currentYM] ?? 0) - (a.by_month?.[currentYM] ?? 0));

  if (categories.length === 0) {
    container.innerHTML = '<p class="text-sm text-slate-500 col-span-full">Nenhuma compra categorizada neste mês.</p>';
    return;
  }

  container.innerHTML = categories.map(cat => {
    const amount = cat.by_month?.[currentYM] ?? 0;
    const count = cat.counts_by_month?.[currentYM] ?? 0;
    const color = cat.color || '#64748b';
    const countLabel = count === 1 ? '1 compra' : `${count} compras`;
    return `
      <div class="bg-white rounded-2xl border border-slate-200 px-5 py-4 flex items-center gap-4 shadow-sm">
        <span class="size-10 rounded-xl flex items-center justify-center text-xl shrink-0" style="background:${escapeHtml(color)}22">${categoryIcon(cat.name)}</span>
        <div class="flex-1 min-w-0">
          <p class="font-semibold text-slate-900 text-sm truncate">${escapeHtml(cat.name)}</p>
          <p class="text-xs text-slate-500">${escapeHtml(countLabel)}</p>
        </div>
        <p class="font-bold tabular text-slate-900 text-sm shrink-0">${escapeHtml(fmt(amount))}</p>
      </div>
    `;
  }).join('');
}

async function connectBank() {
  const btn = document.getElementById('btn-connect');
  btn.disabled = true;
  try {
    const res = await fetchJson('/connect-token', { method: 'POST' });
    if (typeof PluggyConnect !== 'undefined') {
      new PluggyConnect({
        connectToken: res.accessToken,
        onSuccess: () => { showToast('Banco conectado com sucesso!', 'success'); loadData(); },
        onError: (err) => showToast(`Erro ao conectar: ${err}`, 'error'),
        onClose: () => {},
      }).init();
    } else {
      showToast('Token de conexão gerado. SDK Pluggy Connect não carregado.', 'info');
    }
  } catch {
    showToast('Não foi possível conectar ao Pluggy. Verifique as configurações.', 'error');
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('btn-refresh').addEventListener('click', () => loadData());
document.getElementById('btn-connect').addEventListener('click', () => connectBank());

loadData();
