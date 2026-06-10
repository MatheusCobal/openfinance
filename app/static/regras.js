'use strict';

// 10D-D — User-defined classification rules UI.
// Lists, creates, edits, enables/disables, deletes and previews rules.
// Targets are restricted to the 10D-B taxonomy (INTERNAL_CATEGORIES /
// CASHFLOW_TYPES) served by /transactions/classification-options.

const RULES_URL = '/transactions/classification-rules';

const $ = (id) => document.getElementById(id);

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
    throw new Error(detail);
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

function renderRules(rules) {
  const tbody = $('rules-rows');
  $('rules-count').textContent = `${rules.length} regra(s)`;
  $('rules-empty').classList.toggle('hidden', rules.length > 0);
  tbody.innerHTML = rules
    .map((rule) => {
      const enabledBadge = rule.enabled
        ? '<span class="text-emerald-700 bg-emerald-50 rounded px-1.5 py-0.5 text-xs">ativa</span>'
        : '<span class="text-slate-500 bg-slate-100 rounded px-1.5 py-0.5 text-xs">inativa</span>';
      const ignored =
        rule.ignored_from_totals == null
          ? ''
          : rule.ignored_from_totals
            ? ' · ignora totais'
            : '';
      return `
        <tr class="border-b border-slate-100 align-top">
          <td class="py-2 pr-3 tabular text-slate-500">${rule.priority}</td>
          <td class="py-2 pr-3">
            <div class="font-medium text-slate-800">${escapeHtml(rule.name)}</div>
            <div class="mt-0.5">${enabledBadge}</div>
          </td>
          <td class="py-2 pr-3 text-slate-600">${escapeHtml(rule.account_type_scope)}</td>
          <td class="py-2 pr-3 text-slate-600">${escapeHtml(matchSummary(rule))}</td>
          <td class="py-2 pr-3 text-slate-700">${escapeHtml(rule.target_internal_category)} / ${escapeHtml(rule.target_cashflow_type)}${ignored}</td>
          <td class="py-2 pr-3 text-right tabular text-slate-600">${rule.affected_count}</td>
          <td class="py-2 text-right whitespace-nowrap">
            <button data-act="toggle" data-id="${rule.id}" class="text-xs text-slate-600 hover:text-slate-900 underline">${rule.enabled ? 'Desativar' : 'Ativar'}</button>
            <button data-act="edit" data-id="${rule.id}" class="ml-2 text-xs text-blue-600 hover:text-blue-800 underline">Editar</button>
            <button data-act="delete" data-id="${rule.id}" class="ml-2 text-xs text-rose-600 hover:text-rose-800 underline">Excluir</button>
          </td>
        </tr>`;
    })
    .join('');
}

function renderPreview(result) {
  $('preview-count').textContent = result.matched_count;
  $('preview-rows').innerHTML = result.examples
    .map(
      (ex) => `
      <tr class="border-b border-slate-100">
        <td class="py-1.5 pr-3 text-slate-500 tabular">${escapeHtml(ex.date)}</td>
        <td class="py-1.5 pr-3 text-slate-700">${escapeHtml(ex.description)}</td>
        <td class="py-1.5 pr-3 text-right tabular text-slate-600">${fmtAmount(ex.amount)}</td>
        <td class="py-1.5 pr-3 text-slate-500">${escapeHtml(ex.account_type || '—')}</td>
        <td class="py-1.5 pr-3 text-slate-500">${escapeHtml(ex.current_internal_category)} / ${escapeHtml(ex.current_cashflow_type)}</td>
        <td class="py-1.5 text-slate-900 font-medium">${escapeHtml(ex.new_internal_category)} / ${escapeHtml(ex.new_cashflow_type)}</td>
      </tr>`,
    )
    .join('');
  $('preview').classList.remove('hidden');
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
    await loadRules();
  } catch (err) {
    toast(err.message, false);
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
    renderPreview(result);
  } catch (err) {
    toast(err.message, false);
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
    toast(err.message, false);
  }
}

async function init() {
  $('subtitle').textContent = 'Regras personalizadas de classificação (10D-D).';
  $('rule-form').addEventListener('submit', onSubmit);
  $('btn-preview').addEventListener('click', onPreview);
  $('btn-cancel').addEventListener('click', resetForm);
  $('rules-rows').addEventListener('click', onRulesClick);
  try {
    await loadOptions();
    await loadRules();
  } catch (err) {
    toast(err.message, false);
  }
}

init();
