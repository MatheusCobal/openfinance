'use strict';

// Version marker — change this whenever dashboard.js is modified so the
// DevTools console confirms the new file is actually executing.
const DASHBOARD_JS_VERSION = 'dashboard-hero-reorder-v16';
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
  toast.className = 'fixed top-4 right-4 z-50 max-w-sm rounded-md text-white text-sm px-4 py-3 shadow-lg ' +
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
  const cls = {
    over: 'bg-red-500/20 text-red-300',
    tight: 'bg-amber-500/20 text-amber-300',
    healthy: 'bg-emerald-500/20 text-emerald-300',
    unknown: 'bg-white/10 text-slate-400',
  }[status] || 'bg-white/10 text-slate-400';
  return `<span class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${cls}">${escapeHtml(planStatusLabel(status))}</span>`;
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
let bankBalance = null;    // Active BANK accounts balance summary

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
    const [planning, invoice] = await Promise.all([
      fetchJson(`/planning/month/${planningYM}`),
      fetchJson('/credit-card/current-invoice'),
    ]);
    capacity = normalizePlanningOverview(planning);
    currentCardInvoice = invoice;
    // Bank balance is best-effort — a failure must not break the whole dashboard.
    bankBalance = await fetchJson('/bank/balance-summary').catch(() => null);
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
  renderInvoiceReconciliation();
  renderBankBalance();
  renderSummaryCards();
  renderCategories();
}

function renderHero() {
  // Exact same "sobra" resolution as Planejamento renderCapacityFlow().
  const sobra = capacity.budget_available_to_spend ?? capacity.discretionary_available ?? capacity.available_to_spend ?? 0;
  const status = capacity.plan_status ?? 'unknown';
  const days = capacity.days_remaining_in_month ?? 0;

  document.getElementById('hero-card').innerHTML = `
    <div class="flex h-full flex-col justify-between gap-5">
      <div class="flex items-center gap-2">
        <p class="text-sm font-medium text-slate-300">Disponível para gastar</p>
        ${planStatusBadge(status)}
      </div>
      <div>
        <p class="text-3xl font-semibold tabular leading-tight">${escapeHtml(fmt(sobra))}</p>
        <div class="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-400">
          <span>${escapeHtml(monthLabelLong(planningYM))}</span>
          <span>${days} dias restantes</span>
        </div>
      </div>
      <p class="text-sm text-slate-400">Plano em <a href="/planejamento" class="text-white font-medium hover:underline">Planejamento</a></p>
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
    ? `Saldo Pluggy ajustado: ${fmt(adjustedCard.raw_balance)} - fatura anterior ${fmt(adjustedCard.latest_bill_amount)}`
    : 'Saldo Pluggy ajustado';

  document.getElementById('invoice-card-content').innerHTML = `
    <div class="flex min-h-[150px] flex-col justify-between gap-5">
      <div>
        <p class="text-sm font-medium text-slate-500">Fatura do cartão</p>
        <p class="mt-3 text-3xl font-semibold tabular text-slate-900">${escapeHtml(fmt(invoiceAmount))}</p>
      </div>
      <div class="space-y-1">
        <p class="text-sm text-slate-600">${escapeHtml(invoice.source_label || 'Fatura vigente ajustada')}</p>
        <p class="text-xs leading-relaxed text-slate-500">${escapeHtml(subtitle)}</p>
        <p class="text-xs text-slate-400">No cálculo: <span class="font-medium text-slate-600">${escapeHtml(fmt(includedAmount))}</span></p>
      </div>
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
    <div class="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <p class="text-xs font-bold uppercase tracking-wider text-slate-500">${escapeHtml(card.label)}</p>
        <span class="size-8 rounded-full ${card.iconBg} flex items-center justify-center text-base leading-none">${card.iconEmoji}</span>
      </div>
      <p class="text-2xl font-semibold tabular ${card.amountCls} mb-1">${escapeHtml(fmt(card.amount))}</p>
      <p class="text-xs text-slate-500">${escapeHtml(card.subtitle)}</p>
    </div>
  `).join('');
}

function formatDatePtBr(dateString) {
  if (!dateString) return '';
  const [y, m, d] = dateString.split('-');
  return `${d}/${m}/${y}`;
}

function formatDateTimePtBr(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function renderInvoiceReconciliation() {
  const el = document.getElementById('invoice-reconciliation');
  if (!el) return;

  const rec = currentCardInvoice?.reconciliation;
  if (!rec || rec.amount == null) {
    el.classList.add('hidden');
    el.innerHTML = '';
    return;
  }

  el.classList.remove('hidden');
  el.innerHTML = `
    <p class="text-sm font-medium text-slate-700 mb-3">Reconciliação da fatura</p>
    <div class="space-y-2 text-sm">
      <div class="flex items-center justify-between gap-4">
        <span class="text-slate-500">Fatura vigente</span>
        <span class="tabular font-medium text-slate-900">${escapeHtml(fmt(rec.amount))}</span>
      </div>
      <div class="flex items-center justify-between gap-4">
        <span class="text-slate-500">Compras detalhadas</span>
        <span class="tabular font-medium text-slate-900">${escapeHtml(fmt(rec.category_total))}</span>
      </div>
      <div class="flex items-center justify-between gap-4">
        <span class="text-slate-500">Reembolsos/estornos detectados</span>
        <span class="tabular font-medium text-emerald-600">- ${escapeHtml(fmt(rec.refund_abs_total))}</span>
      </div>
      <div class="flex items-center justify-between gap-4 pt-2 border-t border-slate-200">
        <span class="text-slate-500">Diferença contra saldo Pluggy</span>
        <span class="tabular font-medium text-slate-700">${escapeHtml(fmt(rec.amount_minus_category_total))}</span>
      </div>
    </div>
    <p class="text-xs text-slate-400 mt-3 leading-relaxed">A fatura usa o saldo Pluggy ajustado. As categorias mostram apenas compras rastreadas.</p>
  `;
}

function renderBankBalance() {
  const el = document.getElementById('bank-balance-card');
  if (!el) return;

  if (!bankBalance) {
    el.innerHTML = `
      <div class="flex h-full min-h-[142px] flex-col justify-between gap-5">
        <p class="text-sm font-medium text-slate-500">Saldo em banco</p>
        <div>
          <p class="text-2xl font-semibold tabular text-slate-900">--</p>
          <p class="mt-2 text-sm text-slate-500">Contas bancárias ativas</p>
          <p class="mt-1 text-xs text-slate-400">Indisponível no momento</p>
        </div>
      </div>
    `;
    return;
  }

  const total = bankBalance.total ?? 0;
  const accounts = bankBalance.accounts ?? [];
  const updatedAt = bankBalance.updated_at;
  const updatedLabel = updatedAt ? `Atualizado em ${formatDateTimePtBr(updatedAt)}` : '';
  const accountCountLabel = accounts.length === 1 ? '1 conta ativa' : `${accounts.length} contas ativas`;

  const accountRows = accounts.length > 1
    ? `<div class="mt-4 rounded-xl bg-slate-50 px-3 py-2 divide-y divide-slate-100">${accounts.map(a => `
        <div class="flex items-center justify-between gap-3 py-1.5">
          <span class="text-xs text-slate-500 truncate">${escapeHtml(a.name || 'Conta')}</span>
          <span class="text-xs tabular font-medium text-slate-700 ml-2 shrink-0">${escapeHtml(fmt(a.balance ?? 0))}</span>
        </div>`).join('')}</div>`
    : '';

  el.innerHTML = `
    <div class="flex h-full min-h-[142px] flex-col justify-between gap-5">
      <div>
        <p class="text-sm font-medium text-slate-500">Saldo em banco</p>
        <p class="mt-3 text-2xl font-semibold tabular text-slate-900">${escapeHtml(fmt(total))}</p>
      </div>
      <div>
        <p class="text-sm text-slate-600">Contas bancárias ativas</p>
        <p class="mt-1 text-xs text-slate-400">${escapeHtml(accountCountLabel)}${updatedLabel ? ' · ' + escapeHtml(updatedLabel) : ''}</p>
        ${accountRows}
      </div>
    </div>
  `;
}

function formatInstallment(tx) {
  if (tx.installment_number && tx.total_installments) {
    return `Parcela ${tx.installment_number}/${tx.total_installments}`;
  }
  return null;
}

function renderCategoryTransactions(category) {
  const list = document.getElementById('modal-transactions-list');
  const transactions = [...(category.transactions || [])];

  if (transactions.length === 0) {
    list.innerHTML = '<p class="text-sm text-slate-500 text-center py-6">Nenhuma transação detalhada encontrada para esta categoria.</p>';
    return;
  }

  transactions.sort((a, b) => {
    if (b.date !== a.date) return b.date.localeCompare(a.date);
    return (a.description || '').localeCompare(b.description || '');
  });

  list.innerHTML = transactions.map(tx => {
    const installment = formatInstallment(tx);
    const metaParts = [];
    if (tx.category) metaParts.push(escapeHtml(tx.category));
    if (installment) metaParts.push(escapeHtml(installment));
    if (tx.status) metaParts.push(escapeHtml(tx.status));
    const metaStr = metaParts.join(' · ');
    return `
      <div class="flex items-start justify-between gap-4 py-3 border-b border-slate-100 last:border-0">
        <div class="min-w-0">
          <p class="text-sm font-medium leading-snug text-slate-900 break-words">${escapeHtml(tx.description)}</p>
          <p class="mt-1 text-xs leading-relaxed text-slate-400">${escapeHtml(formatDatePtBr(tx.date))}${metaStr ? ' · ' + metaStr : ''}</p>
        </div>
        <p class="font-semibold tabular text-slate-900 text-sm shrink-0 text-right">${escapeHtml(fmt(tx.amount ?? 0))}</p>
      </div>
    `;
  }).join('');
}

function openCategoryModal(category) {
  document.getElementById('modal-category-name').textContent = category.name;
  const countLabel = (category.count ?? 0) === 1 ? '1 compra' : `${category.count ?? 0} compras`;
  document.getElementById('modal-category-subtitle').textContent =
    `${fmt(category.total ?? 0)} · ${countLabel}`;
  renderCategoryTransactions(category);
  document.getElementById('category-modal').classList.remove('hidden');
  document.addEventListener('keydown', _categoryModalKeyHandler);
}

function closeCategoryModal() {
  document.getElementById('category-modal').classList.add('hidden');
  document.removeEventListener('keydown', _categoryModalKeyHandler);
}

function _categoryModalKeyHandler(e) {
  if (e.key === 'Escape') closeCategoryModal();
}

function renderCategories() {
  const container = document.getElementById('categories-grid');
  const invoiceAmount = asMoneyNumber(currentCardInvoice?.amount);
  const categories = [...(currentCardInvoice?.categories || [])]
    .filter(cat => asMoneyNumber(cat.total) > 0)
    .sort((a, b) => asMoneyNumber(b.total) - asMoneyNumber(a.total));

  if (categories.length === 0) {
    const message = invoiceAmount > 0
      ? 'A fatura possui saldo, mas as compras detalhadas ainda não foram sincronizadas pela Pluggy.'
      : 'Nenhuma compra encontrada para a fatura vigente.';
    container.innerHTML = `<p class="text-sm text-slate-500 col-span-full rounded-2xl border border-dashed border-slate-200 bg-white px-5 py-6">${escapeHtml(message)}</p>`;
    return;
  }

  container.innerHTML = categories.map((cat, index) => {
    const amount = cat.total ?? 0;
    const count = cat.count ?? 0;
    const color = cat.color || '#64748b';
    const countLabel = count === 1 ? '1 compra' : `${count} compras`;
    return `
      <button type="button" data-category-index="${index}"
        class="group bg-white rounded-2xl border border-slate-200 px-4 py-4 flex items-center gap-3.5 w-full text-left cursor-pointer shadow-sm hover:bg-slate-50 hover:border-slate-300 hover:shadow transition">
        <span class="size-10 rounded-xl flex items-center justify-center text-base shrink-0 ring-1 ring-inset ring-slate-900/5" style="background:${escapeHtml(color)}22">
          <span class="size-2.5 rounded-full" style="background:${escapeHtml(color)}"></span>
        </span>
        <div class="flex-1 min-w-0">
          <p class="font-semibold text-slate-900 text-sm truncate">${escapeHtml(cat.name)}</p>
          <p class="mt-0.5 text-xs text-slate-500">${escapeHtml(countLabel)}</p>
        </div>
        <div class="flex items-center gap-2 shrink-0 text-right">
          <p class="font-semibold tabular text-slate-900 text-sm">${escapeHtml(fmt(amount))}</p>
          <span class="text-slate-300 group-hover:text-slate-500 text-lg leading-none" aria-hidden="true">›</span>
        </div>
      </button>
    `;
  }).join('');

  container.querySelectorAll('button[data-category-index]').forEach(btn => {
    btn.addEventListener('click', () => {
      const category = categories[Number(btn.dataset.categoryIndex)];
      if (category) openCategoryModal(category);
    });
  });
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
document.getElementById('modal-close-btn')?.addEventListener('click', closeCategoryModal);
document.getElementById('category-modal-backdrop')?.addEventListener('click', closeCategoryModal);

loadData();
