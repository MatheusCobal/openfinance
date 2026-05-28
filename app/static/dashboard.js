// Dashboard / Overview — financial snapshot only.
// Reads Pluggy-native snapshot totals (/dashboard/snapshot), the current-month
// planning headline (/spending-capacity) and sync health. All transaction /
// category management lives in /transacoes, not here.

const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function currentYearMonth() {
  // Local date (not UTC) so the "current month" matches the user's calendar.
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${now.getFullYear()}-${month}`;
}

// Monotonic version so a slow fetch from a previous refresh can't overwrite a
// newer one.
let loadVersion = 0;

function showToast(message, variant = 'info') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.classList.remove('hidden', 'bg-slate-900', 'bg-red-600', 'bg-emerald-600');
  el.classList.add(
    variant === 'error' ? 'bg-red-600' : variant === 'success' ? 'bg-emerald-600' : 'bg-slate-900',
  );
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => el.classList.add('hidden'), 4000);
}

async function loadData() {
  const myVersion = ++loadVersion;
  document.getElementById('subtitle').textContent = 'Atualizando…';
  await Promise.all([
    loadSnapshot(myVersion),
    loadPlanning(myVersion),
    loadSyncHealth(myVersion),
  ]);
  if (myVersion !== loadVersion) return;
  updateEmptyState();
  document.getElementById('subtitle').textContent =
    new Date().toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });
}

function updateEmptyState() {
  const snapshotVisible = !document
    .getElementById('snapshot-section')
    .classList.contains('hidden');
  const planningVisible = !document
    .getElementById('planning-card')
    .classList.contains('hidden');
  const empty = document.getElementById('empty');
  if (snapshotVisible || planningVisible) {
    empty.classList.add('hidden');
  } else {
    empty.classList.remove('hidden');
  }
}

// ── Snapshot (Pluggy balances / limits / investments) ──────────────────
async function loadSnapshot(expectedVersion) {
  const section = document.getElementById('snapshot-section');
  if (!section) return;
  try {
    const response = await fetch('/dashboard/snapshot');
    if (expectedVersion !== loadVersion) return;
    if (!response.ok) {
      section.classList.add('hidden');
      return;
    }
    const data = await response.json();
    if (expectedVersion !== loadVersion) return;
    renderSnapshot(section, data);
  } catch (err) {
    console.error('snapshot load failed', err);
    section.classList.add('hidden');
  }
}

function renderSnapshot(section, data) {
  const bank = data.bank || {};
  const credit = data.credit || {};
  const investments = data.investments || {};

  const anything =
    bank.has_balance || credit.has_balance || investments.has_investments;
  if (!anything) {
    section.classList.add('hidden');
    section.innerHTML = '';
    return;
  }

  const card = (label, value, sub, valueClass = 'text-slate-900') => `
    <div class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
      <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">${label}</p>
      <p class="mt-2 text-2xl font-bold tabular ${valueClass}">${value}</p>
      <p class="text-xs text-slate-500 mt-1">${sub}</p>
    </div>`;

  const cards = [];
  cards.push(
    card(
      'Saldo em conta',
      bank.has_balance ? currency.format(bank.total) : '—',
      `${bank.account_count || 0} conta${(bank.account_count || 0) === 1 ? '' : 's'}`,
      'text-emerald-700',
    ),
  );
  const creditSub = credit.limit
    ? `limite ${currency.format(credit.limit)} · livre ${currency.format(credit.available)}`
    : `${credit.account_count || 0} cartã${(credit.account_count || 0) === 1 ? 'o' : 'os'}`;
  cards.push(
    card(
      'Cartão em uso',
      credit.has_balance ? currency.format(credit.used) : '—',
      creditSub,
      'text-slate-900',
    ),
  );
  cards.push(
    card(
      'Investimentos',
      investments.has_investments ? currency.format(investments.total) : '—',
      `${investments.investment_count || 0} posiç${(investments.investment_count || 0) === 1 ? 'ão' : 'ões'}`,
      'text-indigo-700',
    ),
  );
  cards.push(
    card(
      'Reserva',
      investments.has_investments ? currency.format(investments.reserve_total) : '—',
      `${investments.reserve_investment_count || 0} elegíve${(investments.reserve_investment_count || 0) === 1 ? 'l' : 'is'}`,
      'text-indigo-700',
    ),
  );

  document.getElementById('snapshot-cards').innerHTML = cards.join('');
  section.classList.remove('hidden');
}

// ── Planning headline (current-month available to spend) ───────────────
const PLAN_STATUS = {
  healthy: { label: 'Saudável', cls: 'bg-emerald-50 text-emerald-700' },
  tight: { label: 'Apertado', cls: 'bg-amber-50 text-amber-700' },
  over: { label: 'Estourado', cls: 'bg-rose-50 text-rose-700' },
  unknown: { label: 'Sem receita', cls: 'bg-slate-100 text-slate-600' },
};

async function loadPlanning(expectedVersion) {
  const section = document.getElementById('planning-card');
  if (!section) return;
  try {
    const month = currentYearMonth();
    const response = await fetch(`/spending-capacity?year_month=${month}`);
    if (expectedVersion !== loadVersion) return;
    if (!response.ok) {
      section.classList.add('hidden');
      return;
    }
    const data = await response.json();
    if (expectedVersion !== loadVersion) return;
    renderPlanning(section, data, month);
    renderMonthSummary(data);
    renderInvoiceCard(data, month);
  } catch (err) {
    console.error('planning load failed', err);
    section.classList.add('hidden');
    document.getElementById('month-summary-section')?.classList.add('hidden');
    document.getElementById('invoice-card')?.classList.add('hidden');
  }
}

// ── Resumo do mês (cash-flow snapshot for the current month) ───────────
function renderMonthSummary(data) {
  const section = document.getElementById('month-summary-section');
  if (!section) return;
  const cards = [
    {
      label: 'Entradas',
      value: data.bank_inflows_total || 0,
      sub: 'Tudo que caiu na conta (inclui resgates)',
      cls: 'text-emerald-700',
    },
    {
      label: 'Saídas',
      value: data.bank_outflows_total || 0,
      sub: 'PIX / débito (exclui fatura)',
      cls: 'text-rose-700',
    },
    {
      label: 'A receber',
      value: data.income_to_receive || 0,
      sub: `Receita esperada ${currency.format(data.expected_income_total || 0)}`,
      cls: 'text-slate-900',
    },
  ];
  document.getElementById('month-summary-cards').innerHTML = cards
    .map(
      (c) => `
      <div class="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">${c.label}</p>
        <p class="mt-2 text-2xl font-bold tabular ${c.cls}">${currency.format(c.value)}</p>
        <p class="text-xs text-slate-500 mt-1">${escapeHtml(c.sub)}</p>
      </div>`,
    )
    .join('');
  section.classList.remove('hidden');
}

// ── Fatura do cartão (cash-flow timing, prefers the official Pluggy bill) ──
function renderInvoiceCard(data, month) {
  const section = document.getElementById('invoice-card');
  if (!section) return;
  const official = data.card_invoice_official_total ?? data.card_invoice_gross_total ?? 0;
  const fromBill = data.card_invoice_source === 'bill';
  const sourceLabel = fromBill ? 'Fatura oficial (Pluggy)' : 'Reconstruída por transações';
  const sourceCls = fromBill
    ? 'bg-emerald-50 text-emerald-700'
    : 'bg-slate-100 text-slate-600';
  const monthLabel = new Date(`${month}-01T00:00:00`).toLocaleDateString('pt-BR', {
    month: 'long',
    year: 'numeric',
  });
  section.innerHTML = `
    <div class="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
      <div class="flex items-center gap-2 mb-3">
        <p class="text-xs uppercase tracking-wider text-slate-500 font-medium">Fatura do cartão</p>
        <span class="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 font-medium">Cash-flow</span>
        <span class="text-[10px] px-2 py-0.5 rounded-full ${sourceCls}">${escapeHtml(sourceLabel)}</span>
      </div>
      <p class="text-3xl font-bold tabular text-slate-900">${currency.format(official)}</p>
      <div class="flex flex-wrap items-center gap-x-5 gap-y-1 mt-3 text-sm text-slate-500">
        <span class="capitalize">${escapeHtml(monthLabel)}</span>
        <span class="text-slate-300 text-xs">·</span>
        <span>discricionária ${currency.format(data.card_invoice_discretionary_total || 0)}</span>
        <span class="text-slate-300 text-xs">·</span>
        <span>custos fixos ${currency.format(data.card_invoice_fixed_cost_total || 0)}</span>
      </div>
    </div>`;
  section.classList.remove('hidden');
}

function renderPlanning(section, data, month) {
  const available =
    data.budget_available_to_spend ?? data.discretionary_available ?? 0;
  const sign = available >= 0 ? '+' : '−';
  const valueClass = available >= 0 ? 'text-emerald-700' : 'text-rose-700';
  const status = PLAN_STATUS[data.plan_status] || PLAN_STATUS.unknown;

  const daysRemaining = data.days_remaining_in_month;
  const daily = data.daily_discretionary_remaining;
  const bits = [];
  if (Number.isFinite(daysRemaining) && daysRemaining > 0) {
    bits.push(`${daysRemaining} dia${daysRemaining === 1 ? '' : 's'} restante${daysRemaining === 1 ? '' : 's'}`);
    if (Number.isFinite(daily) && daily > 0) {
      bits.push(`${currency.format(daily)}/dia`);
    }
  }
  const monthLabel = new Date(`${month}-01T00:00:00`).toLocaleDateString('pt-BR', {
    month: 'long',
    year: 'numeric',
  });

  section.innerHTML = `
    <div class="rounded-2xl overflow-hidden shadow-md">
      <div class="bg-gradient-to-br from-indigo-600 to-indigo-700 px-8 pt-6 pb-8">
        <div class="flex items-center gap-3 mb-1">
          <p class="text-xs font-semibold text-indigo-300 uppercase tracking-widest">Disponível para gastar</p>
          <span class="text-[11px] font-medium px-2 py-0.5 rounded-full ${status.cls}">${status.label}</span>
        </div>
        <p class="text-5xl font-bold tabular text-white tracking-tight">${sign}${currency.format(Math.abs(available))}</p>
        <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 mt-4 text-sm text-indigo-200">
          <span class="capitalize">${escapeHtml(monthLabel)}</span>
          ${bits.length ? `<span class="text-indigo-400 text-xs">·</span><span>${escapeHtml(bits.join(' · '))}</span>` : ''}
          <span class="text-indigo-400 text-xs">·</span>
          <span>plano em <a href="/custos-fixos" class="text-white font-semibold hover:underline">Planejamento</a></span>
        </div>
      </div>
    </div>`;
  section.classList.remove('hidden');
}

// ── Sync health (only shown when something is wrong / running) ─────────
async function loadSyncHealth(expectedVersion) {
  const section = document.getElementById('sync-health');
  if (!section) return;
  try {
    const response = await fetch('/sync/health');
    if (expectedVersion !== loadVersion) return;
    if (!response.ok) return;
    const items = await response.json();
    renderSyncHealth(section, items);
  } catch (err) {
    console.error('sync health failed', err);
  }
}

function renderSyncHealth(section, items) {
  const noteworthy = (items || []).filter(
    (it) => it.is_running || it.last_sync_error || (it.failed_accounts || []).length > 0,
  );
  if (noteworthy.length === 0) {
    section.classList.add('hidden');
    section.innerHTML = '';
    return;
  }

  const cards = noteworthy.map((it) => {
    const running = it.is_running;
    const itemError = it.last_sync_error;
    const accountErrors = it.failed_accounts || [];
    const variant = running
      ? { bg: 'bg-indigo-50', border: 'border-indigo-200', text: 'text-indigo-900', tag: 'Sincronizando' }
      : { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-900', tag: 'Atenção' };
    const name = escapeHtml(it.connector_name || it.item_id);
    const accountList = accountErrors.length
      ? `<ul class="mt-2 space-y-1 text-xs ${variant.text}/80">${accountErrors
          .map(
            (a) =>
              `<li><span class="font-medium">${escapeHtml(a.account_id)}:</span> ${escapeHtml(a.error || '')}</li>`,
          )
          .join('')}</ul>`
      : '';
    const itemErrorLine = itemError
      ? `<p class="mt-1 text-xs ${variant.text}/80">${escapeHtml(itemError)}</p>`
      : '';
    return `
      <div class="rounded-2xl ${variant.bg} border ${variant.border} px-5 py-4">
        <div class="flex items-center gap-3">
          <span class="text-xs font-semibold uppercase tracking-wider ${variant.text}">${variant.tag}</span>
          <span class="font-medium ${variant.text}">${name}</span>
        </div>
        ${itemErrorLine}
        ${accountList}
      </div>`;
  });

  section.innerHTML = `<div class="space-y-3">${cards.join('')}</div>`;
  section.classList.remove('hidden');
}

// ── Connect bank (Pluggy Connect widget) ───────────────────────────────
async function openConnectWidget() {
  const button = document.getElementById('connect');
  button.disabled = true;
  try {
    const tokenResponse = await fetch('/connect-token', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!tokenResponse.ok) {
      throw new Error(`Falha ao obter token (HTTP ${tokenResponse.status}). Verifique suas credenciais Pluggy no .env.`);
    }
    const { accessToken } = await tokenResponse.json();

    if (typeof PluggyConnect === 'undefined') {
      throw new Error('Script do Pluggy Connect não carregou. Verifique sua conexão.');
    }

    const widget = new PluggyConnect({
      connectToken: accessToken,
      includeSandbox: false,
      language: 'pt',
      countries: ['BR'],
      connectorIds: [200],
      onSuccess: async (data) => {
        const itemId = data?.item?.id;
        if (!itemId) {
          showToast('Conexão completa mas itemId ausente.', 'error');
          return;
        }
        showToast('Conectado! Sincronizando…');
        try {
          await fetch(`/items/${itemId}`, { method: 'POST' });
          const sync = await fetch(`/items/${itemId}/sync`, { method: 'POST' });
          if (sync.status === 409) {
            showToast('Sincronização já em andamento para este item.', 'info');
            return;
          }
          const result = await sync.json();
          await loadData();
          const failed = (result.failed_accounts || []).length;
          showToast(
            failed > 0 ? `Sincronizado (${failed} conta(s) com erro).` : 'Sincronizado com sucesso.',
            failed > 0 ? 'info' : 'success',
          );
        } catch (err) {
          console.error(err);
          showToast('Erro ao sincronizar.', 'error');
        }
      },
      onError: (error) => {
        console.error('Pluggy onError:', error);
        showToast(`Erro: ${error?.message || 'desconhecido'}`, 'error');
      },
    });
    widget.init();
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  } finally {
    button.disabled = false;
  }
}

document.getElementById('refresh').addEventListener('click', () => {
  loadData().catch((err) => {
    console.error(err);
    document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
  });
});

document.getElementById('connect').addEventListener('click', openConnectWidget);

loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
