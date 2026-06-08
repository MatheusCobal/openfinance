'use strict';

// Version marker — change this whenever dashboard.js is modified so the
// DevTools console confirms the new file is actually executing.
const DASHBOARD_JS_VERSION = 'current-card-invoice-v11';
window.DASHBOARD_JS_VERSION = DASHBOARD_JS_VERSION;
console.log('[Dashboard] JS carregado:', DASHBOARD_JS_VERSION);

// The Dashboard is a READ-ONLY presentation of the Planejamento "Visão do mês"
// numbers, except for the card invoice tile, which uses the dedicated
// /credit-card/current-invoice source for the adjusted current balance.

function fmt(v) {
  return currency.format(asMoneyNumber(v));
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

// Long month label, e.g. "Julho de 2026".
function monthLabelLong(ym) {
  const [y, m] = ym.split('-').map(Number);
  const label = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' }).format(new Date(y, m - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function planStatusBadge(status) {
  // Label comes from the shared mapping; colours are tuned for the purple hero.
  const cls = {
    over: 'bg-white/25 text-white',
    tight: 'bg-amber-100/90 text-amber-800',
    healthy: 'bg-emerald-100/90 text-emerald-800',
    unknown: 'bg-white/20 text-white/80',
  }[status] || 'bg-white/20 text-white/80';
  return `<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}">${escapeHtml(planStatusLabel(status))}</span>`;
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

// Selected month follows the SAME default logic as Planejamento.
let planningYM = getDefaultPlanningMonth();
let capacity = null;       // normalized planning overview (source of truth)
let currentCardInvoice = null; // Dashboard-only current card balance
let statsData = null;      // category stats (secondary, informational only)

async function fetchJson(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) {
    let detail = '';
    try {
      const body = await r.json();
      detail = body?.detail ?? body?.message ?? JSON.stringify(body);
    } catch {
      try { detail = await r.text(); } catch { /* ignore */ }
    }
    throw new Error(`HTTP ${r.status}${detail ? ': ' + detail : ''}`);
  }
  return r.json();
}

async function loadData() {
  planningYM = getDefaultPlanningMonth();

  setLoading(true);
  setError(false);
  showContent(false);

  try {
    const [planning, invoice, stats] = await Promise.all([
      fetchJson(`/planning/month/${planningYM}`),
      fetchJson('/credit-card/current-invoice'),
      fetchJson('/stats/monthly').catch(() => null),
    ]);
    capacity = normalizePlanningOverview(planning);
    currentCardInvoice = invoice;
    statsData = stats;
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
  document.getElementById('header-date').textContent = `Planejamento de ${monthLabelLong(planningYM)}`;
  document.getElementById('month-compact').textContent = formatMonthShort(planningYM);

  renderHero();
  renderInvoiceCard();
  renderSummaryCards();
  renderCategories();
}

function renderHero() {
  // Exact same "sobra" resolution as Planejamento renderCapacityFlow().
  const sobra = capacity.budget_available_to_spend ?? capacity.discretionary_available ?? capacity.available_to_spend ?? 0;
  const status = capacity.plan_status ?? 'unknown';
  const days = capacity.days_remaining_in_month ?? 0;

  document.getElementById('hero-card').innerHTML = `
    <div class="flex items-center gap-2 mb-3">
      <p class="text-xs font-bold uppercase tracking-widest text-indigo-200">Disponível para gastar</p>
      ${planStatusBadge(status)}
    </div>
    <p class="text-5xl font-bold tabular leading-tight mb-5">${escapeHtml(fmt(sobra))}</p>
    <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-indigo-200">
      <span>${escapeHtml(monthLabelLong(planningYM))}</span>
      <span>&nbsp;·&nbsp;</span>
      <span>${days} dias restantes</span>
      <span>&nbsp;·&nbsp;</span>
      <span>plano em <a href="/planejamento" class="text-white font-semibold hover:underline">Planejamento</a></span>
    </div>
  `;
}

function renderInvoiceCard() {
  const invoice = currentCardInvoice || {};
  const invoiceAmount = invoice.amount ?? 0;
  // Amount actually subtracted in the available-to-spend calculation.
  const includedAmount = invoiceIncludedAmount(capacity);
  const adjustedCard = (invoice.cards || []).find(card => (card.adjustments || []).length > 0);
  const subtitle = adjustedCard
    ? `saldo Pluggy ${fmt(adjustedCard.raw_balance)} - fatura anterior ${fmt(adjustedCard.latest_bill_amount)}`
    : 'saldo Pluggy sem ajuste aplicado';

  document.getElementById('invoice-card-content').innerHTML = `
    <p class="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Fatura do cartão</p>
    <p class="text-4xl font-bold tabular text-slate-900 mb-3">${escapeHtml(fmt(invoiceAmount))}</p>
    <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
      <span>${escapeHtml(invoice.source_label || 'Fatura vigente ajustada')}</span>
      <span>&nbsp;·&nbsp;</span>
      <span>${escapeHtml(subtitle)}</span>
      <span>&nbsp;·&nbsp;</span>
      <span>no cálculo ${escapeHtml(fmt(includedAmount))}</span>
    </div>
  `;
}

function renderSummaryCards() {
  const isFuture = (capacity.planning_mode || (capacity.is_future_month ? 'future_month' : 'current_month')) === 'future_month';

  // ── Custos fixos: planned for future months, reserved for current/past
  //    (mirrors fixedBarAmt in Planejamento renderCapacityFlow). ──
  const fixedEntries = capacity.fixed_costs?.entries ?? [];
  const fixedMain = isFuture
    ? (capacity.fixed_cost_planned_total ?? 0)
    : (capacity.fixed_cost_reserved_total ?? 0);
  const fixedActual = capacity.fixed_cost_actual_total ?? 0;
  const fixedPending = capacity.fixed_cost_pending_total ?? 0;
  const fixedSubtitle = `${fixedEntries.length} itens · pago ${fmt(fixedActual)} · pendente ${fmt(fixedPending)}`;

  // ── Variável usado ──
  const varPlanned = capacity.variable_budget_total ?? 0;
  const varConsumed = capacity.variable_budget_consumed ?? 0;
  const varRemaining = capacity.variable_budget_remaining ?? 0;
  const varSubtitle = varPlanned > 0
    ? `meta ${fmt(varPlanned)} · restante ${fmt(varRemaining)}`
    : 'sem meta configurada';

  const cards = [
    {
      label: 'Entradas',
      iconEmoji: '💰',
      iconBg: 'bg-emerald-100',
      amount: capacity.received_income_total ?? 0,
      amountCls: 'text-emerald-600',
      subtitle: 'Entradas bancárias reais',
    },
    {
      label: 'Saídas',
      iconEmoji: '↗',
      iconBg: 'bg-red-100',
      amount: capacity.bank_outflows_total ?? 0,
      amountCls: 'text-red-600',
      subtitle: 'Saídas bancárias reais',
    },
    {
      label: 'A receber',
      iconEmoji: '⏳',
      iconBg: 'bg-amber-100',
      amount: capacity.income_to_receive ?? 0,
      amountCls: 'text-slate-900',
      subtitle: `Receita esperada ${fmt(capacity.expected_income_total ?? 0)}`,
    },
    {
      label: 'Custos fixos',
      iconEmoji: '📌',
      iconBg: 'bg-orange-100',
      amount: fixedMain,
      amountCls: 'text-red-600',
      subtitle: fixedSubtitle,
    },
    {
      label: 'Variável usado',
      iconEmoji: '📋',
      iconBg: 'bg-purple-100',
      amount: varConsumed,
      amountCls: 'text-slate-900',
      subtitle: varSubtitle,
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
    </div>
  `).join('');
}

function renderCategories() {
  const container = document.getElementById('categories-grid');
  const emptyState = '<p class="text-sm text-slate-500 col-span-full">Nenhuma compra categorizada neste mês.</p>';

  if (!statsData?.categories?.length) {
    container.innerHTML = emptyState;
    return;
  }

  // Informational only — filtered to the selected planning month. Never used
  // to override the financial cards above.
  const categories = statsData.categories
    .filter(cat => (cat.by_month?.[planningYM] ?? 0) > 0)
    .sort((a, b) => (b.by_month?.[planningYM] ?? 0) - (a.by_month?.[planningYM] ?? 0));

  if (categories.length === 0) {
    container.innerHTML = emptyState;
    return;
  }

  container.innerHTML = categories.map(cat => {
    const amount = cat.by_month?.[planningYM] ?? 0;
    const count = cat.counts_by_month?.[planningYM] ?? 0;
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

const PLUGGY_CONNECT_SDK_URL = 'https://cdn.pluggy.ai/pluggy-connect/latest/pluggy-connect.js';

function waitForPluggyConnectSdk(timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function poll() {
      if (window.PluggyConnect) return resolve();
      if (Date.now() - start > timeoutMs) {
        return reject(new Error('Timeout aguardando window.PluggyConnect.'));
      }
      setTimeout(poll, 100);
    })();
  });
}

async function ensurePluggyConnectSdkLoaded() {
  if (window.PluggyConnect) return;

  // Match both the static <script> tag added in dashboard.html (which has no
  // data-pluggy-connect-sdk attribute but contains "pluggy-connect" in its src)
  // and any previously injected dynamic script.
  const existingScript = document.querySelector(
    'script[data-pluggy-connect-sdk], script[src*="pluggy-connect"]',
  );
  if (existingScript) {
    await waitForPluggyConnectSdk();
    return;
  }

  const script = document.createElement('script');
  script.src = PLUGGY_CONNECT_SDK_URL;
  script.async = true;
  script.dataset.pluggyConnectSdk = 'true';

  const loadPromise = new Promise((resolve, reject) => {
    script.onload = () => {
      if (window.PluggyConnect) resolve();
      else reject(new Error('SDK Pluggy Connect carregou, mas window.PluggyConnect não ficou disponível.'));
    };
    script.onerror = () => {
      reject(new Error('Não foi possível carregar o Pluggy Connect no navegador. Verifique bloqueador de anúncios, conexão ou CSP.'));
    };
  });

  document.head.appendChild(script);
  await loadPromise;
}

async function connectBank() {
  const btn = document.getElementById('btn-connect');
  btn.disabled = true;
  console.log('[Pluggy] connectBank: botão clicado');
  try {
    // ── 1. Garantir que o SDK está carregado ANTES de chamar o backend ──
    console.log('[Pluggy] connectBank: carregando SDK…');
    await ensurePluggyConnectSdkLoaded();
    console.log('[Pluggy] connectBank: SDK pronto, typeof window.PluggyConnect =', typeof window.PluggyConnect);

    // ── 2. Gerar connect token no backend ──
    console.log('[Pluggy] connectBank: solicitando connect token…');
    const res = await fetchJson('/connect-token', { method: 'POST' });
    console.log('[Pluggy] connectBank: token recebido, tem accessToken =', !!res.accessToken);
    if (!res.accessToken) throw new Error('connect-token não retornou accessToken.');

    // ── 3. Abrir o widget Pluggy Connect ──
    console.log('[Pluggy] connectBank: abrindo widget Pluggy Connect…');
    new window.PluggyConnect({
      connectToken: res.accessToken,
      includeSandbox: false,
      language: 'pt',
      countries: ['BR'],
      connectorIds: [200],
      onSuccess: async (data) => {
        // Pluggy SDK pode retornar { itemId }, { item: { id } } ou { id } — suportamos todos.
        const itemId = data?.itemId || data?.item?.id || data?.id;
        console.log('[Pluggy] onSuccess payload:', JSON.stringify(data), '→ itemId:', itemId);
        if (!itemId) {
          console.error('[Pluggy] onSuccess: payload sem itemId', data);
          showToast('Banco conectado, mas o widget não retornou o ID do item. Verifique o console.', 'error');
          return;
        }
        try {
          await fetchJson(`/items/${itemId}`, { method: 'POST' });
          console.log('[Pluggy] item registrado localmente:', itemId);
          try {
            await fetchJson(`/items/${itemId}/sync`, { method: 'POST' });
            console.log('[Pluggy] sync disparado para:', itemId);
          } catch (syncErr) {
            // 409 = sync já em andamento (não é erro crítico)
            if (syncErr.message?.includes('409')) {
              console.warn('[Pluggy] sync já em andamento para:', itemId);
            } else {
              throw syncErr;
            }
          }
          showToast('Banco conectado! Sincronizando dados…', 'success');
          loadData();
        } catch (err) {
          console.error('[Pluggy] erro ao registrar/sincronizar item:', err);
          showToast(`Erro ao sincronizar banco: ${err.message}`, 'error');
        }
      },
      onError: (err) => {
        console.error('[Pluggy] widget error:', err);
        showToast(`Erro ao conectar banco: ${err?.message ?? JSON.stringify(err)}`, 'error');
      },
      onClose: () => {
        console.log('[Pluggy] widget fechado pelo usuário');
      },
    }).init();
  } catch (err) {
    console.error('[Pluggy] connectBank erro:', err);
    showToast(err?.message ?? 'Não foi possível conectar ao Pluggy. Verifique as configurações.', 'error');
  } finally {
    btn.disabled = false;
  }
}

// Expose helpers on window so:
//   1. DevTools can confirm the new version is actually executing.
//   2. The event listener below references window.connectBank directly
//      (avoids stale-closure issues from a cached older version of the file).
window.ensurePluggyConnectSdkLoaded = ensurePluggyConnectSdkLoaded;
window.connectBank = connectBank;

document.getElementById('btn-refresh').addEventListener('click', () => loadData());
document.getElementById('btn-connect')?.addEventListener('click', window.connectBank);

loadData();
