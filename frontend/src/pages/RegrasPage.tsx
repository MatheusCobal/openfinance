import { useEffect, useMemo, useState } from "react";
import { ArrowRight, FlaskConical, RefreshCw, Sparkles, Zap } from "lucide-react";
import {
  createClassificationRule,
  deleteClassificationRule,
  getClassificationOptions,
  listClassificationRules,
  previewExistingRule,
  previewNewRule,
  updateClassificationRule,
} from "../api/regras";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, StaleDataWarning } from "../components/ui/ErrorState";
import { FormField } from "../components/ui/FormField";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { Select } from "../components/ui/Select";
import { StatusPill } from "../components/ui/StatusPill";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { accountScopeLabel, cashflowTypeLabel, pluralize } from "../lib/labels";
import { formatMoney } from "../lib/money";
import type { ClassificationOptions } from "../types/common";
import type {
  ClassificationPreview,
  ClassificationPreviewExample,
  ClassificationRule,
  ClassificationRulePayload,
} from "../types/regras";

const EMPTY_RULE: ClassificationRulePayload = {
  name: "",
  enabled: true,
  priority: 100,
  account_type_scope: "ALL",
  match_pluggy_category: null,
  match_pluggy_subcategory: null,
  match_pluggy_type: null,
  match_merchant: null,
  match_description: null,
  match_amount_sign: "any",
  target_internal_category: "",
  target_cashflow_type: "",
  ignored_from_totals: null,
};

const ERROR_MESSAGES = [
  {
    match: "at least one match criterion is required",
    message: "Preencha ao menos uma condição: categoria do banco, estabelecimento ou descrição.",
  },
  { match: "name must not be empty", message: "Dê um nome para a automação." },
  {
    match: "account_type_scope must be CREDIT, BANK or ALL",
    message: "Escolha um alcance válido: cartão, conta ou todas.",
  },
  {
    match: "match_amount_sign must be positive, negative or any",
    message: "Escolha um sinal de valor válido: entradas, saídas ou qualquer.",
  },
  {
    match: "target_internal_category is not in the 10D-B taxonomy",
    message: "Escolha uma categoria da lista.",
  },
  {
    match: "target_cashflow_type is not a supported cashflow type",
    message: "Escolha um tipo de movimentação válido.",
  },
  { match: "not found", message: "Automação não encontrada. Atualize a lista e tente novamente." },
];

function friendlyErrorMessage(error: unknown) {
  const detail = error instanceof Error ? error.message : String(error || "");
  const lower = detail.toLowerCase();
  const found = ERROR_MESSAGES.find((item) => lower.includes(item.match.toLowerCase()));
  return found?.message || detail || "Não foi possível concluir a operação.";
}

async function loadRulesPage() {
  const [options, rules] = await Promise.all([getClassificationOptions(), listClassificationRules()]);
  return { options, rules };
}

/** Human sentence describing when a rule fires. */
function matchSentence(rule: ClassificationRule | ClassificationRulePayload): string {
  const conditions: string[] = [];
  if (rule.match_pluggy_category) conditions.push(`a categoria do banco é “${rule.match_pluggy_category}”`);
  if (rule.match_pluggy_subcategory) conditions.push(`a subcategoria é “${rule.match_pluggy_subcategory}”`);
  if (rule.match_pluggy_type) conditions.push(`o tipo é “${rule.match_pluggy_type}”`);
  if (rule.match_merchant) conditions.push(`o estabelecimento contém “${rule.match_merchant}”`);
  if (rule.match_description) conditions.push(`a descrição contém “${rule.match_description}”`);
  if (rule.match_amount_sign === "negative") conditions.push("o valor é uma saída");
  if (rule.match_amount_sign === "positive") conditions.push("o valor é uma entrada");
  if (!conditions.length) return "Sem condições definidas";
  return `Quando ${conditions.join(" e ")}`;
}

function totalsLabel(rule: ClassificationRule | ClassificationRulePayload) {
  if (rule.ignored_from_totals == null) return null;
  return rule.ignored_from_totals ? "Fora dos totais" : "Conta nos totais";
}

function RuleForm({
  options,
  editing,
  value,
  setValue,
  onSubmit,
  onCancel,
  onPreview,
}: {
  options: ClassificationOptions;
  editing: ClassificationRule | null;
  value: ClassificationRulePayload;
  setValue: (value: ClassificationRulePayload) => void;
  onSubmit: () => Promise<void>;
  onCancel: () => void;
  onPreview: () => Promise<void>;
}) {
  const update = (patch: Partial<ClassificationRulePayload>) => setValue({ ...value, ...patch });
  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold tracking-tight text-ink-900">
          {editing ? `Editando “${editing.name}”` : "Nova automação"}
        </h2>
        <Badge tone="primary">
          <FlaskConical className="size-3" aria-hidden="true" />
          Simulação sem risco
        </Badge>
      </div>
      <p className="mb-5 max-w-2xl text-sm leading-relaxed text-ink-500">
        Automações classificam suas transações sozinhas, sem alterar os dados originais. Ajustes
        manuais sempre têm a palavra final.
      </p>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <FormField label="Nome da automação">
          <Input
            value={value.name}
            placeholder="Ex.: iFood é Alimentação"
            onChange={(event) => update({ name: event.target.value })}
          />
        </FormField>
        <FormField label="Alcance">
          <Select
            value={value.account_type_scope}
            onChange={(event) => update({ account_type_scope: event.target.value })}
          >
            <option value="ALL">Todas as contas</option>
            <option value="CREDIT">Cartão de crédito</option>
            <option value="BANK">Conta bancária</option>
          </Select>
        </FormField>
        <FormField label="Prioridade" hint="Número menor decide primeiro em caso de empate.">
          <Input
            type="number"
            value={value.priority}
            onChange={(event) => update({ priority: Number(event.target.value || 100) })}
          />
        </FormField>
      </div>

      <fieldset className="mt-5 rounded-card border border-ink-200 p-4">
        <legend className="px-1.5 text-xs font-semibold text-ink-600">
          Quando a transação combinar com...
        </legend>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <FormField label="Categoria do banco">
            <Input
              value={value.match_pluggy_category || ""}
              placeholder="Ex.: Food delivery"
              onChange={(event) => update({ match_pluggy_category: event.target.value || null })}
            />
          </FormField>
          <FormField label="Subcategoria do banco">
            <Input
              value={value.match_pluggy_subcategory || ""}
              onChange={(event) => update({ match_pluggy_subcategory: event.target.value || null })}
            />
          </FormField>
          <FormField label="Tipo informado pelo banco">
            <Input
              value={value.match_pluggy_type || ""}
              onChange={(event) => update({ match_pluggy_type: event.target.value || null })}
            />
          </FormField>
          <FormField label="Estabelecimento contém">
            <Input
              value={value.match_merchant || ""}
              placeholder="Ex.: IFOOD"
              onChange={(event) => update({ match_merchant: event.target.value || null })}
            />
          </FormField>
          <FormField label="Descrição contém">
            <Input
              value={value.match_description || ""}
              onChange={(event) => update({ match_description: event.target.value || null })}
            />
          </FormField>
          <FormField label="Sinal do valor">
            <Select
              value={value.match_amount_sign}
              onChange={(event) => update({ match_amount_sign: event.target.value })}
            >
              <option value="any">Qualquer valor</option>
              <option value="negative">Somente saídas</option>
              <option value="positive">Somente entradas</option>
            </Select>
          </FormField>
        </div>
      </fieldset>

      <fieldset className="mt-4 rounded-card border border-primary-200 bg-primary-50/40 p-4">
        <legend className="px-1.5 text-xs font-semibold text-primary-700">...classificar como</legend>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <FormField label="Categoria">
            <Select
              value={value.target_internal_category}
              onChange={(event) => update({ target_internal_category: event.target.value })}
            >
              {options.internal_categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Tipo de movimentação">
            <Select
              value={value.target_cashflow_type}
              onChange={(event) => update({ target_cashflow_type: event.target.value })}
            >
              {options.cashflow_types.map((item) => (
                <option key={item} value={item}>
                  {cashflowTypeLabel(item) || item}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Contar nos totais?" hint="Automático segue o padrão do tipo escolhido.">
            <Select
              value={value.ignored_from_totals == null ? "" : String(value.ignored_from_totals)}
              onChange={(event) =>
                update({
                  ignored_from_totals: event.target.value === "" ? null : event.target.value === "true",
                })
              }
            >
              <option value="">Automático</option>
              <option value="true">Não contar</option>
              <option value="false">Contar</option>
            </Select>
          </FormField>
        </div>
      </fieldset>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button type="button" onClick={() => void onPreview()}>
          <FlaskConical className="size-4" aria-hidden="true" />
          Simular impacto
        </Button>
        <Button type="button" variant="primary" onClick={() => void onSubmit()}>
          {editing ? "Salvar alterações" : "Criar automação"}
        </Button>
        {editing ? (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancelar edição
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

function PreviewPanel({ preview, label }: { preview: ClassificationPreview | null; label: string }) {
  if (!preview) return null;
  const count = Number(preview.matched_count || 0);
  return (
    <Card className="border-warning-200 p-5">
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-ink-900">
            Simulação:{" "}
            {pluralize(count, "transação seria reclassificada", "transações seriam reclassificadas")}
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            Cálculo para {label ? `“${label}”` : "os campos atuais"}. Nada foi gravado ainda.
          </p>
        </div>
        <Badge tone="warning">
          <FlaskConical className="size-3" aria-hidden="true" />
          Simulação
        </Badge>
      </div>
      {count === 0 ? (
        <EmptyState title="Nenhuma transação combina com essas condições hoje." />
      ) : (
        <div className="space-y-3">
          {(preview.examples || []).map((example: ClassificationPreviewExample, index) => {
            const current = `${example.current_internal_category || "Sem categoria"} · ${
              cashflowTypeLabel(example.current_cashflow_type) || "sem tipo"
            }`;
            const next = `${example.new_internal_category || "Sem categoria"} · ${
              cashflowTypeLabel(example.new_cashflow_type) || "sem tipo"
            }`;
            return (
              <div
                key={`${example.description}-${index}`}
                className="rounded-control border border-ink-200 bg-surface p-4"
              >
                <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="break-words text-sm font-medium text-ink-900">
                      {example.description || "Sem descrição"}
                    </p>
                    <p className="mt-1 text-xs text-ink-500">
                      {example.date || "—"} · {accountScopeLabel(example.account_type)} ·{" "}
                      {formatMoney(example.amount || 0)}
                    </p>
                  </div>
                </div>
                <div className="mt-3 flex flex-col gap-2 text-xs sm:flex-row sm:items-stretch">
                  <div className="flex-1 rounded-control bg-surface-muted px-3 py-2">
                    <p className="font-semibold text-ink-500">Antes</p>
                    <p className="mt-1 text-ink-700">{current}</p>
                  </div>
                  <span className="flex items-center justify-center text-ink-400">
                    <ArrowRight className="size-4 rotate-90 sm:rotate-0" aria-hidden="true" />
                  </span>
                  <div className="flex-1 rounded-control bg-primary-50 px-3 py-2">
                    <p className="font-semibold text-primary-700">Depois</p>
                    <p className="mt-1 text-primary-900">{next}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export function RegrasPage() {
  const { showToast } = useToast();
  const { data, loading, error, run, setData } = useAsync(loadRulesPage, []);
  const [editing, setEditing] = useState<ClassificationRule | null>(null);
  const [form, setForm] = useState<ClassificationRulePayload>(EMPTY_RULE);
  const [preview, setPreview] = useState<ClassificationPreview | null>(null);

  useEffect(() => {
    if (!data?.options) return;
    setForm((current) => ({
      ...current,
      target_internal_category:
        current.target_internal_category || data.options.internal_categories[0] || "",
      target_cashflow_type: current.target_cashflow_type || data.options.cashflow_types[0] || "",
    }));
  }, [data?.options]);

  const sortedRules = useMemo(
    () => [...(data?.rules || [])].sort((a, b) => a.priority - b.priority || a.id - b.id),
    [data?.rules],
  );

  const resetForm = () => {
    setEditing(null);
    setPreview(null);
    setForm({
      ...EMPTY_RULE,
      target_internal_category: data?.options.internal_categories[0] || "",
      target_cashflow_type: data?.options.cashflow_types[0] || "",
    });
  };

  const save = async () => {
    try {
      if (editing) {
        await updateClassificationRule(editing.id, form);
        showToast("Automação atualizada.", "success");
      } else {
        await createClassificationRule(form);
        showToast("Automação criada.", "success");
      }
      resetForm();
      await run();
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  const previewCurrent = async () => {
    try {
      const result = editing ? await previewExistingRule(editing.id, form) : await previewNewRule(form);
      setPreview(result);
      showToast("Simulação pronta. Nenhum dado foi alterado.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  const editRule = (rule: ClassificationRule) => {
    setEditing(rule);
    setPreview(null);
    setForm({
      name: rule.name,
      enabled: rule.enabled,
      priority: rule.priority,
      account_type_scope: rule.account_type_scope,
      match_pluggy_category: rule.match_pluggy_category || null,
      match_pluggy_subcategory: rule.match_pluggy_subcategory || null,
      match_pluggy_type: rule.match_pluggy_type || null,
      match_merchant: rule.match_merchant || null,
      match_description: rule.match_description || null,
      match_amount_sign: rule.match_amount_sign || "any",
      target_internal_category: rule.target_internal_category,
      target_cashflow_type: rule.target_cashflow_type,
      ignored_from_totals: rule.ignored_from_totals ?? null,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const toggleRule = async (rule: ClassificationRule) => {
    try {
      const updated = await updateClassificationRule(rule.id, { enabled: !rule.enabled });
      setData((current) =>
        current
          ? { ...current, rules: current.rules.map((item) => (item.id === rule.id ? updated : item)) }
          : current,
      );
      showToast(rule.enabled ? "Automação pausada." : "Automação ativada.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  const removeRule = async (rule: ClassificationRule) => {
    if (!window.confirm(`Excluir a automação "${rule.name}"?`)) return;
    try {
      await deleteClassificationRule(rule.id);
      await run();
      showToast("Automação excluída.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  const previewRule = async (rule: ClassificationRule) => {
    try {
      const result = await previewExistingRule(rule.id);
      setPreview(result);
      setEditing(null);
      showToast("Simulação pronta. Nenhum dado foi alterado.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  return (
    <>
      <Topbar
        subtitle="Automações que classificam suas transações por você."
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer narrow>
        {loading && !data ? <LoadingState label="Carregando automações..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {error && data ? (
          <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
        ) : null}
        {data ? (
          <div className="space-y-6">
            <RuleForm
              options={data.options}
              editing={editing}
              value={form}
              setValue={setForm}
              onSubmit={save}
              onCancel={resetForm}
              onPreview={previewCurrent}
            />
            <PreviewPanel preview={preview} label={editing?.name || form.name} />

            <section aria-label="Automações existentes">
              <div className="mb-4 flex items-end justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold tracking-tight text-ink-900">Suas automações</h2>
                  <p className="mt-0.5 text-xs text-ink-500">
                    Aplicadas na ordem de prioridade. Ajustes manuais sempre vencem.
                  </p>
                </div>
                <Badge>{pluralize(sortedRules.length, "automação", "automações")}</Badge>
              </div>
              {sortedRules.length ? (
                <div className="space-y-3">
                  {sortedRules.map((rule) => (
                    <Card key={rule.id} className="p-4 sm:p-5">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={`inline-flex size-7 items-center justify-center rounded-control ${
                                rule.enabled ? "bg-primary-50 text-primary-600" : "bg-ink-100 text-ink-400"
                              }`}
                              aria-hidden="true"
                            >
                              <Zap className="size-3.5" />
                            </span>
                            <h3 className="text-sm font-semibold text-ink-900">{rule.name}</h3>
                            <StatusPill
                              label={rule.enabled ? "Automação ativa" : "Pausada"}
                              tone={rule.enabled ? "positive" : "neutral"}
                            />
                          </div>
                          <p className="mt-2 text-sm leading-relaxed text-ink-600">
                            {matchSentence(rule)}{" "}
                            <ArrowRight className="inline size-3.5 text-ink-400" aria-hidden="true" />{" "}
                            <span className="font-medium text-ink-900">{rule.target_internal_category}</span>
                            {cashflowTypeLabel(rule.target_cashflow_type) ? (
                              <span className="text-ink-500">
                                {" "}
                                · {cashflowTypeLabel(rule.target_cashflow_type)}
                              </span>
                            ) : null}
                          </p>
                          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-xs">
                            <Badge>{accountScopeLabel(rule.account_type_scope)}</Badge>
                            <Badge>Prioridade {rule.priority}</Badge>
                            {totalsLabel(rule) ? <Badge>{totalsLabel(rule)}</Badge> : null}
                            <span className="text-ink-500">
                              · alcança {pluralize(rule.affected_count ?? 0, "transação", "transações")}
                            </span>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5 lg:shrink-0">
                          <Button type="button" variant="ghost" size="sm" onClick={() => void previewRule(rule)}>
                            <FlaskConical className="size-3.5" aria-hidden="true" />
                            Simular
                          </Button>
                          <Button type="button" variant="ghost" size="sm" onClick={() => void toggleRule(rule)}>
                            {rule.enabled ? "Pausar" : "Ativar"}
                          </Button>
                          <Button type="button" variant="ghost" size="sm" onClick={() => editRule(rule)}>
                            Editar
                          </Button>
                          <Button type="button" variant="ghost" size="sm" onClick={() => void removeRule(rule)}>
                            Excluir
                          </Button>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              ) : (
                <EmptyState
                  icon={<Sparkles className="size-5" aria-hidden="true" />}
                  title="Nenhuma automação ainda."
                  detail="Crie a primeira: por exemplo, “toda compra com IFOOD vira Alimentação”. Use a simulação para ver o impacto antes de salvar — nada é alterado sem você confirmar."
                />
              )}
            </section>
          </div>
        ) : null}
      </PageContainer>
    </>
  );
}
