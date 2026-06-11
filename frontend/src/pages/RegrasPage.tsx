import { useEffect, useMemo, useState } from "react";
import { Eye, RefreshCw } from "lucide-react";
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
import { ErrorState } from "../components/ui/ErrorState";
import { FormField } from "../components/ui/FormField";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { Select } from "../components/ui/Select";
import { Table } from "../components/ui/Table";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
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
    message:
      "Informe ao menos um critério de match: categoria/subcategoria/tipo Pluggy, merchant ou descrição.",
  },
  { match: "name must not be empty", message: "Informe um nome para a regra." },
  {
    match: "account_type_scope must be CREDIT, BANK or ALL",
    message: "Use CREDIT, BANK ou ALL no escopo da conta.",
  },
  {
    match: "match_amount_sign must be positive, negative or any",
    message: "Use positivo, negativo ou qualquer no sinal do valor.",
  },
  {
    match: "target_internal_category is not in the 10D-B taxonomy",
    message: "Escolha uma categoria interna da taxonomia atual.",
  },
  {
    match: "target_cashflow_type is not a supported cashflow type",
    message: "Escolha um tipo de fluxo válido.",
  },
  { match: "not found", message: "Regra não encontrada. Atualize a lista e tente novamente." },
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

function matchSummary(rule: ClassificationRule | ClassificationRulePayload) {
  const parts = [];
  if (rule.match_pluggy_category) parts.push(`cat=${rule.match_pluggy_category}`);
  if (rule.match_pluggy_subcategory) parts.push(`sub=${rule.match_pluggy_subcategory}`);
  if (rule.match_pluggy_type) parts.push(`tipo=${rule.match_pluggy_type}`);
  if (rule.match_merchant) parts.push(`merchant~${rule.match_merchant}`);
  if (rule.match_description) parts.push(`desc~${rule.match_description}`);
  if (rule.match_amount_sign && rule.match_amount_sign !== "any") {
    parts.push(`sinal=${rule.match_amount_sign}`);
  }
  if (rule.account_type_scope && rule.account_type_scope !== "ALL") {
    parts.push(`[${rule.account_type_scope}]`);
  }
  return parts.join(", ") || "-";
}

function ignoredLabel(rule: ClassificationRule | ClassificationRulePayload) {
  if (rule.ignored_from_totals == null) return "ignorar: automático";
  return rule.ignored_from_totals ? "ignora totais" : "entra nos totais";
}

function rawPluggySummary(example: ClassificationPreviewExample) {
  const parts = [
    example.pluggy_raw_category ? `Categoria: ${example.pluggy_raw_category}` : null,
    example.pluggy_raw_subcategory ? `Subcategoria: ${example.pluggy_raw_subcategory}` : null,
    example.pluggy_raw_type ? `Tipo: ${example.pluggy_raw_type}` : null,
    example.pluggy_merchant ? `Merchant: ${example.pluggy_merchant}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Sem raw Pluggy informado";
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
    <Card className="p-6">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-950">
          {editing ? `Editando regra #${editing.id}` : "Nova regra de classificação"}
        </h2>
        <Badge tone="blue">Preview seguro</Badge>
      </div>
      <p className="mb-4 text-sm leading-relaxed text-slate-600">
        Regras classificam transações por merchant, descrição ou raw Pluggy sem alterar dados brutos.
        A ordem final continua: manual &gt; usuário &gt; Pluggy &gt; sistema &gt; fallback.
      </p>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <FormField label="Nome *">
          <Input value={value.name} onChange={(event) => update({ name: event.target.value })} />
        </FormField>
        <FormField label="Escopo de conta">
          <Select
            value={value.account_type_scope}
            onChange={(event) => update({ account_type_scope: event.target.value })}
          >
            <option value="ALL">Todas (ALL)</option>
            <option value="CREDIT">Cartão (CREDIT)</option>
            <option value="BANK">Banco (BANK)</option>
          </Select>
        </FormField>
        <FormField label="Prioridade">
          <Input
            type="number"
            value={value.priority}
            onChange={(event) => update({ priority: Number(event.target.value || 100) })}
          />
        </FormField>
      </div>

      <fieldset className="mt-4 rounded-lg border border-slate-200 p-4">
        <legend className="px-1 text-xs font-medium text-slate-500">Critérios de match</legend>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <FormField label="Pluggy categoria">
            <Input
              value={value.match_pluggy_category || ""}
              onChange={(event) => update({ match_pluggy_category: event.target.value || null })}
            />
          </FormField>
          <FormField label="Pluggy subcategoria">
            <Input
              value={value.match_pluggy_subcategory || ""}
              onChange={(event) => update({ match_pluggy_subcategory: event.target.value || null })}
            />
          </FormField>
          <FormField label="Pluggy tipo">
            <Input
              value={value.match_pluggy_type || ""}
              onChange={(event) => update({ match_pluggy_type: event.target.value || null })}
            />
          </FormField>
          <FormField label="Merchant contém">
            <Input
              value={value.match_merchant || ""}
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
              <option value="any">Qualquer</option>
              <option value="negative">Negativo</option>
              <option value="positive">Positivo</option>
            </Select>
          </FormField>
        </div>
      </fieldset>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <FormField label="Categoria interna *">
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
        <FormField label="Tipo de fluxo *">
          <Select
            value={value.target_cashflow_type}
            onChange={(event) => update({ target_cashflow_type: event.target.value })}
          >
            {options.cashflow_types.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Ignorar dos totais">
          <Select
            value={value.ignored_from_totals == null ? "" : String(value.ignored_from_totals)}
            onChange={(event) =>
              update({
                ignored_from_totals:
                  event.target.value === "" ? null : event.target.value === "true",
              })
            }
          >
            <option value="">Automático</option>
            <option value="true">Sim</option>
            <option value="false">Não</option>
          </Select>
        </FormField>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button type="button" variant="primary" onClick={() => void onSubmit()}>
          {editing ? "Atualizar regra" : "Salvar regra"}
        </Button>
        <Button type="button" onClick={() => void onPreview()}>
          <Eye className="size-4" aria-hidden="true" />
          Pré-visualizar impacto
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
    <Card className="p-5">
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-medium text-slate-800">
            Impacto: {count === 1 ? "1 transação" : `${count.toLocaleString("pt-BR")} transações`}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            Amostra calculada para {label ? `"${label}"` : "os campos atuais"}. Nada foi gravado.
          </p>
        </div>
        <Badge tone="amber">Preview seguro</Badge>
      </div>
      {count === 0 ? (
        <EmptyState title="Nenhuma transação seria afetada por esta regra agora." />
      ) : (
        <div className="space-y-3">
          {(preview.examples || []).map((example, index) => {
            const current = `${example.current_internal_category || "-"} / ${
              example.current_cashflow_type || "-"
            }`;
            const next = `${example.new_internal_category || "-"} / ${
              example.new_cashflow_type || "-"
            }`;
            return (
              <div key={`${example.description}-${index}`} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="break-words text-sm font-medium text-slate-950">
                      {example.description || "Sem descrição"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {example.date || "-"} · {example.account_type || "conta desconhecida"} ·{" "}
                      {formatMoney(example.amount || 0)}
                    </p>
                  </div>
                  <Badge>{example.account_type || "ALL"}</Badge>
                </div>
                <div className="mt-3 grid grid-cols-1 gap-3 text-xs md:grid-cols-3">
                  <div className="rounded-md bg-slate-50 px-3 py-2">
                    <p className="font-semibold text-slate-700">Pluggy bruto</p>
                    <p className="mt-1 leading-relaxed text-slate-500">{rawPluggySummary(example)}</p>
                  </div>
                  <div className="rounded-md bg-slate-50 px-3 py-2">
                    <p className="font-semibold text-slate-700">Classificação atual</p>
                    <p className="mt-1 text-slate-500">{current}</p>
                  </div>
                  <div className="rounded-md bg-blue-50 px-3 py-2">
                    <p className="font-semibold text-blue-900">Nova classificação</p>
                    <p className="mt-1 text-blue-800">{next}</p>
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
        showToast("Regra atualizada.", "success");
      } else {
        await createClassificationRule(form);
        showToast("Regra criada.", "success");
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
      showToast("Preview calculado. Nenhum dado foi alterado.", "success");
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
        current ? { ...current, rules: current.rules.map((item) => (item.id === rule.id ? updated : item)) } : current,
      );
      showToast(rule.enabled ? "Regra desativada." : "Regra ativada.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  const removeRule = async (rule: ClassificationRule) => {
    if (!window.confirm(`Excluir a regra "${rule.name}"?`)) return;
    try {
      await deleteClassificationRule(rule.id);
      await run();
      showToast("Regra excluída.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  const previewRule = async (rule: ClassificationRule) => {
    try {
      const result = await previewExistingRule(rule.id);
      setPreview(result);
      setEditing(null);
      showToast("Preview calculado. Nenhum dado foi alterado.", "success");
    } catch (err) {
      showToast(friendlyErrorMessage(err), "error");
    }
  };

  return (
    <>
      <Topbar
        subtitle="Regras personalizadas de classificação"
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer narrow>
        {loading && !data ? <LoadingState label="Carregando regras..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
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
            <Card className="overflow-hidden p-0">
              <div className="flex items-start justify-between gap-4 px-6 py-5">
                <div>
                  <h2 className="text-base font-semibold text-slate-950">Regras existentes</h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Status, prioridade, escopo, matchers e impacto estimado.
                  </p>
                </div>
                <Badge>{sortedRules.length} regras</Badge>
              </div>
              {sortedRules.length ? (
                <Table>
                  <thead className="border-y border-slate-100 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-5 py-2 text-left font-medium">Prioridade</th>
                      <th className="px-5 py-2 text-left font-medium">Nome</th>
                      <th className="px-5 py-2 text-left font-medium">Escopo</th>
                      <th className="px-5 py-2 text-left font-medium">Match</th>
                      <th className="px-5 py-2 text-left font-medium">Destino</th>
                      <th className="px-5 py-2 text-right font-medium">Afeta</th>
                      <th className="px-5 py-2 text-right font-medium">Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRules.map((rule) => (
                      <tr key={rule.id} className="border-b border-slate-100 align-top">
                        <td className="px-5 py-3 text-sm tabular text-slate-500">{rule.priority}</td>
                        <td className="px-5 py-3">
                          <p className="font-medium text-slate-900">{rule.name}</p>
                          <Badge tone={rule.enabled ? "emerald" : "slate"} className="mt-1">
                            {rule.enabled ? "ativa" : "inativa"}
                          </Badge>
                        </td>
                        <td className="px-5 py-3 text-sm text-slate-600">{rule.account_type_scope}</td>
                        <td className="px-5 py-3 text-sm text-slate-600">{matchSummary(rule)}</td>
                        <td className="px-5 py-3 text-sm text-slate-700">
                          <p>
                            {rule.target_internal_category} / {rule.target_cashflow_type}
                          </p>
                          <p className="mt-0.5 text-xs text-slate-400">{ignoredLabel(rule)}</p>
                        </td>
                        <td className="px-5 py-3 text-right text-sm tabular text-slate-600">
                          {rule.affected_count ?? 0}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <div className="flex flex-wrap justify-end gap-2">
                            <Button type="button" variant="ghost" onClick={() => void previewRule(rule)}>
                              Preview
                            </Button>
                            <Button type="button" variant="ghost" onClick={() => void toggleRule(rule)}>
                              {rule.enabled ? "Desativar" : "Ativar"}
                            </Button>
                            <Button type="button" variant="ghost" onClick={() => editRule(rule)}>
                              Editar
                            </Button>
                            <Button type="button" variant="ghost" onClick={() => void removeRule(rule)}>
                              Excluir
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <div className="p-6">
                  <EmptyState
                    title="Nenhuma regra criada ainda."
                    detail="Comece por um matcher específico e use o preview antes de salvar."
                  />
                </div>
              )}
            </Card>
          </div>
        ) : null}
      </PageContainer>
    </>
  );
}
