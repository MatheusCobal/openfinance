'use strict';

// 10D-D — User-defined classification rules UI.
// Lists, creates, edits, enables/disables, deletes and previews rules.
// Targets are restricted to the 10D-B taxonomy (INTERNAL_CATEGORIES /
// CASHFLOW_TYPES) served by /transactions/classification-options.

const RULES_URL = '/transactions/classification-rules';

const $ = (id) => document.getElementById(id);

const ERROR_MESSAGES = [
  {
    match: 'at least one match criterion is required',
    message:
      'Informe ao menos um critério de match: categoria/subcategoria/tipo Pluggy, merchant ou descrição.',
  },
  {
    match: 'name must not be empty',
    message: 'Informe um nome para a regra.',
  },
  {
    match: 'account_type_scope must be CREDIT, BANK or ALL',
    message: 'Use CREDIT, BANK ou ALL no escopo da conta.',
  },
  {
    match: 'match_amount_sign must be positive, negative or any',
    message: 'Use positivo, negativo ou qualquer no sinal do valor.',
  },
  {
    match: 'target_internal_category is not in the 10D-B taxonomy',
    message: 'Escolha uma categoria interna da taxonomia atual.',
  },
  {
    match: 'target_cashflow_type is not a supported cashflow type',
    message: 'Escolha um tipo de fluxo válido.',
  },
  {
    match: 'not found',
    message: 'Regra não encontrada. Atualize a lista e tente novamente.',
  },
];

function toast(message, ok = true) {
  const el = $('toast');
  el.textContent = message;
  el.className =
    'fixed top-4 right-4 z-50 max-w-sm rounded-md text-white text-sm px-4 py-3 shadow-lg ' +
    (ok ? 'bg-emerald-600' : 'bg-rose-600');
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 3200);
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function friendlyErrorMessage(error) {
  const detail = String(error && error.message ? error.message : error || '');
  const lower = detail.toLowerCase();
  const found = ERROR_MESSAGES.find((item) => lower.includes(item.match.toLowerCase()));
  if (found) return found.message;
  if (error && error.status === 404) return 'Regra não encontrada. Atualize a lista e tente novamente.';
  if (error && error.status === 400) return detail || 'Confira os campos da regra.';
  if (error && error.status >= 500) return 'A API encontrou um erro ao processar a regra.';
  return detail || 'Não foi possível concluir a operação.';
}

function setFormFeedback(message, ok = false) {
  const el = $('form-feedback');
  if (!message) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  el.textContent = message;
  el.className =
    'rounded-md border px-3 py-2 text-sm ' +
    (ok
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : 'border-rose-200 bg-rose-50 text-rose-800');
}

function fmtAmount(value) {
  return Number(value).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) {
      /* ignore */
    }
    const err = new Error(Array.isArray(detail) ? detail.map((item) => item.msg || item).join('; ') : detail);
    err.status = response.status;
    throw err;
  }
  if (response.status === 204) return null;
  return response.json();
}

// --- Form helpers ---------------------------------------------------------

function readForm() {
  const ignoredRaw = $('f-ignored').value;
  return {
    name: $('f-name').value.trim(),
    account_type_scope: $('f-scope').value,
    priority: Number($('f-priority').value || 100),
    match_pluggy_category: $('f-pcat').value.trim() || null,
    match_pluggy_subcategory: $('f-psub').value.trim() || null,
    match_pluggy_type: $('f-ptype').value.trim() || null,
    match_merchant: $('f-merchant').value.trim() || null,
    match_description: $('f-desc').value.trim() || null,
    match_amount_sign: $('f-sign').value,
    target_internal_category: $('f-target-cat').value,
    target_cashflow_type: $('f-target-flow').value,
    ignored_from_totals: ignoredRaw === '' ? null : ignoredRaw === 'true',
  };
}

function resetForm() {
  $('rule-id').value = '';
  $('rule-form').reset();
  $('f-priority').value = '100';
  $('form-title').textContent = 'Nova regra de classificação';
  $('btn-save').textContent = 'Salvar regra';
  $('btn-cancel').classList.add('hidden');
  $('preview').classList.add('hidden');
  setFormFeedback('');
}

function fillForm(rule) {
  $('rule-id').value = rule.id;
  $('f-name').value = rule.name || '';
  $('f-scope').value = rule.account_type_scope || 'ALL';
  $('f-priority').value = rule.priority != null ? rule.priority : 100;
  $('f-pcat').value = rule.match_pluggy_category || '';
  $('f-psub').value = rule.match_pluggy_subcategory || '';
  $('f-ptype').value = rule.match_pluggy_type || '';
  $('f-merchant').value = rule.match_merchant || '';
  $('f-desc').value = rule.match_description || '';
  $('f-sign').value = rule.match_amount_sign || 'any';
  $('f-target-cat').value = rule.target_internal_category;
  $('f-target-flow').value = rule.target_cashflow_type;
  $('f-ignored').value =
    rule.ignored_from_totals == null ? '' : String(rule.ignored_from_totals);
  $('form-title').textContent = `Editando regra #${rule.id}`;
  $('btn-save').textContent = 'Atualizar regra';
  $('btn-cancel').classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- Rendering ------------------------------------------------------------

function matchSummary(rule) {
  const parts = [];
  if (rule.match_pluggy_category) parts.push(`cat=${rule.match_pluggy_category}`);
  if (rule.match_pluggy_subcategory) parts.push(`sub=${rule.match_pluggy_subcategory}`);
  if (rule.match_pluggy_type) parts.push(`tipo=${rule.match_pluggy_type}`);
  if (rule.match_merchant) parts.push(`merchant~${rule.match_merchant}`);
  if (rule.match_description) parts.push(`desc~${rule.match_description}`);
  if (rule.match_amount_sign && rule.match_amount_sign !== 'any') {
    parts.push(`sinal=${rule.match_amount_sign}`);
  }
  if (rule.account_type_scope && rule.account_type_scope !== 'ALL') {
    parts.push(`[${rule.account_type_scope}]`);
  }
  return parts.join(', ') || '—';
}

function scopeLabel(scope) {
  if (scope === 'CREDIT') return 'CREDIT - cartão';
  if (scope === 'BANK') return 'BANK - banco/PIX';
  return 'ALL - todos';
}

function ignoredLabel(rule) {
  if (rule.ignored_from_totals == null) return 'ignorar: automático';
  return rule.ignored_from_totals ? 'ignora totais' : 'entra nos totais';
}

function rawPluggySummary(ex) {
  const parts = [
    ex.pluggy_raw_category ? `Categoria: ${ex.pluggy_raw_category}` : null,
    ex.pluggy_raw_subcategory ? `Subcategoria: ${ex.pluggy_raw_subcategory}` : null,
    ex.pluggy_raw_type ? `Tipo: ${ex.pluggy_raw_type}` : null,
    ex.pluggy_merchant ? `Merchant: ${ex.pluggy_merchant}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'Sem raw Pluggy informado';
}

function renderRules(rules) {
  const tbody = $('rules-rows');
  $('rules-count').textContent = `${rules.length} regra(s)`;
  $('rules-empty').classList.toggle('hidden', rules.length > 0);
  tbody.innerHTML = rules
    .map((rule) => {
      const enabledBadge = rule.enabled
        ? '<span class="text-emerald-700 bg-emerald-50 rounded px-1.5 py-0.5 text-xs">ativa</span>'
        : '<span class="text-slate-500 bg-slate-100 rounded px-1.5 py-0.5 text-xs">inativa</span>';
      return `
        <tr class="border-b border-slate-100 align-top">
          <td class="py-2 pr-3 tabular text-slate-500">${rule.priority}</td>
          <td class="py-2 pr-3">
            <div class="font-medium text-slate-800">${escapeHtml(rule.name)}</div>
            <div class="mt-0.5">${enabledBadge}</div>
          </td>
          <td class="py-2 pr-3 text-slate-600">${escapeHtml(scopeLabel(rule.account_type_scope))}</td>
          <td class="py-2 pr-3 text-slate-600">${escapeHtml(matchSummary(rule))}</td>
          <td class="py-2 pr-3 text-slate-700">
            <div>${escapeHtml(rule.target_internal_category)} / ${escapeHtml(rule.target_cashflow_type)}</div>
            <div class="mt-0.5 text-xs text-slate-400">${escapeHtml(ignoredLabel(rule))}</div>
          </td>
          <td class="py-2 pr-3 text-right tabular text-slate-600">${rule.affected_count ?? 0}</td>
          <td class="py-2 text-right whitespace-nowrap">
            <button data-act="preview" data-id="${rule.id}" class="text-xs text-slate-600 hover:text-slate-900 underline">Preview</button>
            <button data-act="toggle" data-id="${rule.id}" class="ml-2 text-xs text-slate-600 hover:text-slate-900 underline">${rule.enabled ? 'Desativar' : 'Ativar'}</button>
            <button data-act="edit" data-id="${rule.id}" class="ml-2 text-xs text-blue-600 hover:text-blue-800 underline">Editar</button>
            <button data-act="delete" data-id="${rule.id}" class="ml-2 text-xs text-rose-600 hover:text-rose-800 underline">Excluir</button>
          </td>
        </tr>`;
    })
    .join('');
}

function renderPreview(result, label = '') {
  const count = Number(result.matched_count || 0);
  $('preview-count').textContent =
    count === 1 ? '1 transação' : `${count.toLocaleString('pt-BR')} transações`;
  $('preview-description').textContent = label
    ? `Amostra calculada para "${label}". Nada foi gravado no banco.`
    : 'Amostra calculada com os campos atuais do formulário. Nada foi gravado no banco.';
  $('preview-empty').classList.toggle('hidden', count !== 0);
  $('preview-empty').textContent =
    count === 0
      ? 'Nenhuma transação seria afetada por esta regra agora. Isso não é erro; ajuste os matchers se esperava impactos.'
      : '';
  $('preview-rows').innerHTML = (result.examples || [])
    .map((ex) => {
      const current = `${ex.current_internal_category || '—'} / ${ex.current_cashflow_type || '—'}`;
      const next = `${ex.new_internal_category || '—'} / ${ex.new_cashflow_type || '—'}`;
      return `
        <div class="rounded-md border border-slate-200 bg-white px-4 py-3">
          <div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
            <div class="min-w-0">
              <p class="text-sm font-medium text-slate-900 break-words">${escapeHtml(ex.description || 'Sem descrição')}</p>
              <p class="mt-1 text-xs text-slate-500">
                ${escapeHtml(ex.date || '—')} · ${escapeHtml(ex.account_type || 'conta desconhecida')} · ${escapeHtml(fmtAmount(ex.amount || 0))}
              </p>
            </div>
            <span class="shrink-0 rounded bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">${escapeHtml(ex.account_type || 'ALL')}</span>
          </div>
          <div class="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div class="rounded-md bg-slate-50 px-3 py-2">
              <p class="font-semibold text-slate-700">Pluggy bruto</p>
              <p class="mt-1 leading-relaxed text-slate-500">${escapeHtml(rawPluggySummary(ex))}</p>
            </div>
            <div class="rounded-md bg-slate-50 px-3 py-2">
              <p class="font-semibold text-slate-700">Classificação atual</p>
              <p class="mt-1 text-slate-500">${escapeHtml(current)}</p>
            </div>
            <div class="rounded-md bg-blue-50 px-3 py-2">
              <p class="font-semibold text-blue-900">Nova classificação</p>
              <p class="mt-1 text-blue-800">${escapeHtml(next)}</p>
            </div>
          </div>
        </div>`;
    })
    .join('');
  $('preview').classList.remove('hidden');
  $('preview').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// --- Data flow ------------------------------------------------------------

let rulesCache = [];

async function loadOptions() {
  const options = await fetchJson('/transactions/classification-options');
  $('f-target-cat').innerHTML = options.internal_categories
    .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
    .join('');
  $('f-target-flow').innerHTML = options.cashflow_types
    .map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`)
    .join('');
}

async function loadRules() {
  rulesCache = await fetchJson(RULES_URL);
  renderRules(rulesCache);
}

async function onSubmit(event) {
  event.preventDefault();
  const id = $('rule-id').value;
  const payload = readForm();
  try {
    if (id) {
      await fetchJson(`${RULES_URL}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      toast('Regra atualizada.');
    } else {
      await fetchJson(RULES_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      toast('Regra criada.');
    }
    resetForm();
    setFormFeedback(id ? 'Regra atualizada com sucesso.' : 'Regra criada com sucesso.', true);
    await loadRules();
  } catch (err) {
    const message = friendlyErrorMessage(err);
    setFormFeedback(message, false);
    toast(message, false);
  }
}

async function onPreview() {
  const id = $('rule-id').value;
  const payload = readForm();
  const url = id ? `${RULES_URL}/${id}/preview` : `${RULES_URL}/preview`;
  try {
    const result = await fetchJson(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderPreview(result, payload.name);
  } catch (err) {
    const message = friendlyErrorMessage(err);
    setFormFeedback(message, false);
    toast(message, false);
  }
}

async function previewExistingRule(rule) {
  if (!rule) return;
  try {
    const result = await fetchJson(`${RULES_URL}/${rule.id}/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    renderPreview(result, rule.name);
    toast('Preview calculado. Nenhum dado foi alterado.');
  } catch (err) {
    const message = friendlyErrorMessage(err);
    toast(message, false);
  }
}

async function onRulesClick(event) {
  const button = event.target.closest('button[data-act]');
  if (!button) return;
  const id = Number(button.dataset.id);
  const rule = rulesCache.find((r) => r.id === id);
  const act = button.dataset.act;
  try {
    if (act === 'edit') {
      if (rule) fillForm(rule);
    } else if (act === 'preview') {
      await previewExistingRule(rule);
    } else if (act === 'toggle') {
      await fetchJson(`${RULES_URL}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      toast(rule.enabled ? 'Regra desativada.' : 'Regra ativada.');
      await loadRules();
    } else if (act === 'delete') {
      if (!window.confirm(`Excluir a regra "${rule.name}"?`)) return;
      await fetchJson(`${RULES_URL}/${id}`, { method: 'DELETE' });
      toast('Regra excluída.');
      await loadRules();
    }
  } catch (err) {
    const message = friendlyErrorMessage(err);
    toast(message, false);
  }
}

async function init() {
  $('subtitle').textContent = 'Regras personalizadas de classificação (10D-E).';
  $('rule-form').addEventListener('submit', onSubmit);
  $('btn-preview').addEventListener('click', onPreview);
  $('btn-cancel').addEventListener('click', resetForm);
  $('rules-rows').addEventListener('click', onRulesClick);
  try {
    await loadOptions();
    await loadRules();
  } catch (err) {
    toast(friendlyErrorMessage(err), false);
  }
}

init();
