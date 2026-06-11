import { useEffect, useMemo, useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import {
  createExpectedIncome,
  createFixedCost,
  createFixedCostCategory,
  createFixedCostMatch,
  deleteExpectedIncome,
  deleteExpectedIncomeOverride,
  deleteFixedCost,
  deleteFixedCostCategory,
  deleteFixedCostMatch,
  deleteFixedCostOverride,
  getExpectedIncomeByMonth,
  getFixedCostsByMonth,
  getPlanningMonth,
  listExpectedIncome,
  listFixedCostCategories,
  listFixedCosts,
  listFixedCostTemplates,
  listTransactionsForMonth,
  setExpectedIncomeOverride,
  setFixedCostOverride,
  updateExpectedIncome,
  updateFixedCost,
} from "../api/planejamento";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
import { Select } from "../components/ui/Select";
import { Tabs } from "../components/ui/Tabs";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { MAX_CUSTOM_CATEGORIES } from "../lib/constants";
import {
  formatDayLabel,
  formatMonthShort,
  getDefaultPlanningMonth,
  monthDateRange,
  monthWindow,
} from "../lib/dates";
import { invoiceIncludedAmount, isFuturePlanningMonth, normalizePlanningOverview, tokenSet } from "../lib/planning";
import { classNames } from "../lib/classNames";
import { asMoneyNumber, formatMoney, percent } from "../lib/money";
import type { Transaction } from "../types/common";
import type {
  ExpectedIncomeEntry,
  ExpectedIncomeMonth,
  ExpectedIncomeMonthEntry,
  FixedCost,
  FixedCostCategory,
  FixedCostMonthEntry,
  FixedCostsMonth,
  FixedCostTemplate,
  PlanningOverview,
} from "../types/planejamento";

type PlanningTab = "overview" | "custos" | "variaveis" | "receita";

interface PlanningData {
  selectedMonth: string;
  capacity: PlanningOverview;
  fixedMonth: FixedCostsMonth;
  categories: FixedCostCategory[];
  costs: FixedCost[];
  templates: FixedCostTemplate[];
  incomeEntries: ExpectedIncomeEntry[];
  incomeMonth: ExpectedIncomeMonth;
}

function selectedTabFromLocation(): PlanningTab {
  const tab = new URLSearchParams(window.location.search).get("tab");
  if (tab === "custos" || tab === "variaveis" || tab === "receita") return tab;
  return "overview";
}

function statusBadge(status?: string) {
  const cfg: Record<string, { label: string; tone: "emerald" | "amber" | "rose" | "slate" }> = {
    paid: { label: "Pago", tone: "emerald" },
    due_soon: { label: "Vence em breve", tone: "amber" },
    overdue: { label: "Vencido", tone: "rose" },
    scheduled: { label: "Previsto", tone: "slate" },
    unconfirmed: { label: "Não confirmado", tone: "slate" },
  };
  const item = cfg[status || ""] || cfg.scheduled;
  return <Badge tone={item.tone}>{item.label}</Badge>;
}

async function loadPlanningData(
  selectedMonth: string,
  showInactiveCosts: boolean,
  showInactiveIncome: boolean,
): Promise<PlanningData> {
  const [planning, categories, costs, templates, incomeEntries, incomeMonth] = await Promise.all([
    getPlanningMonth(selectedMonth),
    listFixedCostCategories(),
    listFixedCosts(showInactiveCosts),
    listFixedCostTemplates().catch(() => []),
    listExpectedIncome(showInactiveIncome),
    getExpectedIncomeByMonth(selectedMonth),
  ]);
  const capacity = normalizePlanningOverview(planning);
  const fixedMonth = capacity.fixed_costs || (await getFixedCostsByMonth(selectedMonth));
  return {
    selectedMonth,
    capacity,
    fixedMonth,
    categories,
    costs,
    templates,
    incomeEntries,
    incomeMonth,
  };
}

function CapacityFlow({ capacity }: { capacity: PlanningOverview }) {
  const isFuture = isFuturePlanningMonth(capacity);
  const free = asMoneyNumber(
    capacity.budget_available_to_spend ??
      capacity.discretionary_available ??
      capacity.available_to_spend ??
      capacity.remaining_after_plan ??
      capacity.remaining_after_invoice,
  );
  const income = capacity.expected_income_total || 0;
  const fixed = isFuture ? capacity.fixed_cost_planned_total || 0 : capacity.fixed_cost_reserved_total || 0;
  const variable = isFuture
    ? capacity.variable_budget_total || 0
    : (capacity.variable_budget_consumed || 0) + (capacity.variable_budget_overage || 0);
  const card = invoiceIncludedAmount(capacity);
  const fixedPct = income > 0 ? Math.min(100, (fixed / income) * 100) : 0;
  const variablePct = income > 0 ? Math.min(100, (variable / income) * 100) : 0;
  const cardPct = income > 0 ? Math.min(100, (card / income) * 100) : 0;
  const freePct = Math.max(0, 100 - fixedPct - variablePct - cardPct);
  const positive = free >= 0;
  const status =
    income <= 0
      ? { label: "Sem receita", tone: "slate" as const }
      : free < 0
        ? { label: "Estourado", tone: "rose" as const }
        : free <= 1000
          ? { label: "Apertado", tone: "amber" as const }
          : { label: "Saudável", tone: "emerald" as const };

  return (
    <Card className="p-5">
      <div className={classNames("rounded-lg border px-5 py-4", positive ? "border-emerald-200 bg-emerald-50" : "border-rose-200 bg-rose-50")}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {isFuture ? "Projeção: livre para gastar" : "Disponível para gastar"}
              </p>
              <Badge tone={status.tone}>{status.label}</Badge>
              {isFuture ? <Badge>Plano projetado</Badge> : null}
            </div>
            <p className={classNames("text-3xl font-bold tabular", positive ? "text-emerald-700" : "text-rose-700")}>
              {formatMoney(free)}
            </p>
          </div>
          {capacity.days_remaining_in_month && capacity.daily_discretionary_remaining ? (
            <div className="text-right text-xs text-slate-500">
              <p>{formatMoney(capacity.daily_discretionary_remaining)}/dia disponível</p>
              <p>{capacity.days_remaining_in_month} dias restantes</p>
            </div>
          ) : null}
        </div>
      </div>
      {income > 0 ? (
        <>
          <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="bg-slate-400" style={{ width: `${fixedPct}%` }} />
            <div className="bg-amber-400" style={{ width: `${variablePct}%` }} />
            <div className="bg-yellow-500" style={{ width: `${cardPct}%` }} />
            <div className={positive ? "bg-emerald-300" : "bg-rose-300"} style={{ width: `${freePct}%` }} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>Fixos {percent(fixedPct)}</span>
            <span>Variável {percent(variablePct)}</span>
            <span>Fatura {percent(cardPct)}</span>
            <span>Livre {percent(freePct)}</span>
          </div>
        </>
      ) : null}
      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Receita esperada" value={formatMoney(income)} subtitle={`Recebido ${formatMoney(capacity.received_income_total)}`} tone="emerald" />
        <MetricCard label="Custos fixos" value={formatMoney(fixed)} subtitle={isFuture ? "planejados" : "reservados/pagos"} />
        <MetricCard label="Variável" value={formatMoney(variable)} subtitle={`Meta ${formatMoney(capacity.variable_budget_total)}`} tone="amber" />
        <MetricCard label="Fatura no cálculo" value={formatMoney(card)} subtitle={capacity.credit_card_invoice?.source_label || "regra consolidada"} tone="blue" />
      </div>
    </Card>
  );
}

function MonthStrip({ months, value, onChange }: { months: string[]; value: string; onChange: (ym: string) => void }) {
  return (
    <div className="chip-strip flex gap-2 overflow-x-auto pb-2">
      {months.map((ym) => (
        <button
          key={ym}
          type="button"
          onClick={() => onChange(ym)}
          className={classNames(
            "shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
            ym === value ? "bg-blue-700 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200",
          )}
        >
          {formatMonthShort(ym)}
        </button>
      ))}
    </div>
  );
}

function FixedMonthBreakdown({
  fixed,
  selectedMonth,
  onReload,
}: {
  fixed: FixedCostsMonth;
  selectedMonth: string;
  onReload: () => Promise<unknown>;
}) {
  const { showToast } = useToast();
  const [pickerFor, setPickerFor] = useState<FixedCostMonthEntry | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loadingPicker, setLoadingPicker] = useState(false);

  const groups = useMemo(() => {
    const grouped = new Map<number, { name: string; color: string; total: number; items: FixedCostMonthEntry[] }>();
    for (const item of fixed.entries || []) {
      const group = grouped.get(item.category_id) || {
        name: item.category_name,
        color: item.category_color,
        total: 0,
        items: [],
      };
      group.total += Number(item.amount || 0);
      group.items.push(item);
      grouped.set(item.category_id, group);
    }
    return [...grouped.entries()];
  }, [fixed.entries]);

  const updateOverride = async (item: FixedCostMonthEntry, amount: number) => {
    try {
      if (item.is_override && Math.abs(amount - Number(item.base_amount)) < 0.005) {
        await deleteFixedCostOverride(item.fixed_cost_id, selectedMonth);
      } else {
        await setFixedCostOverride(item.fixed_cost_id, selectedMonth, amount);
      }
      await onReload();
      showToast("Valor do mês atualizado.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao atualizar valor.", "error");
    }
  };

  const openPicker = async (item: FixedCostMonthEntry) => {
    setPickerFor(item);
    setLoadingPicker(true);
    try {
      const { fromDate, toDate } = monthDateRange(selectedMonth);
      const data = await listTransactionsForMonth(fromDate, toDate);
      const costTokens = tokenSet(item.description);
      const tolerance = Math.max(Number(item.amount) * 0.15, 10);
      const scored = data
        .filter((tx) => Number(tx.amount) < 0)
        .map((tx) => {
          const txAbs = Math.abs(Number(tx.amount));
          const amountDelta = Math.abs(txAbs - Number(item.amount));
          const txTokens = tokenSet(tx.description || "");
          const overlap = [...costTokens].filter((token) => txTokens.has(token)).length;
          return { tx, closeAmount: amountDelta <= tolerance, overlap, amountDelta };
        })
        .sort((a, b) => {
          if (a.closeAmount !== b.closeAmount) return a.closeAmount ? -1 : 1;
          if (b.overlap !== a.overlap) return b.overlap - a.overlap;
          return a.amountDelta - b.amountDelta;
        })
        .slice(0, 20)
        .map((item) => item.tx);
      setTransactions(scored);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao carregar transações.", "error");
    } finally {
      setLoadingPicker(false);
    }
  };

  const linkTransaction = async (item: FixedCostMonthEntry, tx: Transaction) => {
    try {
      await createFixedCostMatch(item.fixed_cost_id, tx.id, selectedMonth);
      setPickerFor(null);
      await onReload();
      showToast(`"${item.description}" vinculado ao pagamento.`, "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao vincular pagamento.", "error");
    }
  };

  if (!fixed.entries?.length) {
    return <EmptyState title="Nenhum custo fixo ativo." detail="Cadastre um custo base abaixo." />;
  }

  return (
    <div className="space-y-3">
      {groups.map(([categoryId, group]) => (
        <Card key={categoryId} className="overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3" style={{ borderLeft: `3px solid ${group.color}` }}>
            <div>
              <p className="font-semibold text-slate-950">{group.name}</p>
              <p className="text-xs text-slate-500">{group.items.length} itens</p>
            </div>
            <p className="font-bold tabular text-slate-950">{formatMoney(group.total)}</p>
          </div>
          <ul className="divide-y divide-slate-100">
            {group.items.map((item) => (
              <li key={`${item.fixed_cost_id}-${item.due_date}`} className="px-4 py-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-sm font-bold tabular text-slate-700">
                    {item.due_day}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium text-slate-950">{item.description}</p>
                      {item.is_override ? <Badge tone="blue">ajustado</Badge> : null}
                      {statusBadge(item.status)}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                      <span>vence {formatDayLabel(item.due_date)}</span>
                      {item.matched_transaction ? (
                        <>
                          <span className="text-emerald-700">
                            vinculado · {item.matched_transaction.description?.slice(0, 44)} ·{" "}
                            {formatMoney(item.matched_transaction.amount_abs ?? Math.abs(Number(item.matched_transaction.amount)))}
                          </span>
                          {item.match_source === "manual" && item.fixed_cost_transaction_match_id ? (
                            <button
                              type="button"
                              className="font-medium text-rose-600 hover:text-rose-700"
                              onClick={async () => {
                                await deleteFixedCostMatch(item.fixed_cost_transaction_match_id as number);
                                await onReload();
                              }}
                            >
                              Desvincular
                            </button>
                          ) : null}
                        </>
                      ) : (
                        <button type="button" className="font-medium text-blue-700" onClick={() => void openPicker(item)}>
                          Vincular pagamento
                        </button>
                      )}
                      {item.is_override ? (
                        <button
                          type="button"
                          className="font-medium text-slate-600"
                          onClick={async () => {
                            await deleteFixedCostOverride(item.fixed_cost_id, selectedMonth);
                            await onReload();
                          }}
                        >
                          reverter ({formatMoney(item.base_amount)})
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    defaultValue={Number(item.amount).toFixed(2)}
                    className="w-full text-right font-semibold tabular sm:w-32"
                    onBlur={(event) => {
                      const amount = Number(event.target.value);
                      if (!Number.isNaN(amount) && Math.abs(amount - Number(item.amount)) >= 0.005) {
                        void updateOverride(item, amount);
                      }
                    }}
                  />
                </div>
                {pickerFor?.fixed_cost_id === item.fixed_cost_id ? (
                  <div className="mt-3 rounded-lg border border-blue-100 bg-blue-50/40 p-3 sm:ml-12">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold text-slate-700">
                        Vincular {item.description} a qual transação?
                      </p>
                      <Button type="button" variant="ghost" onClick={() => setPickerFor(null)}>
                        Fechar
                      </Button>
                    </div>
                    {loadingPicker ? (
                      <p className="py-3 text-center text-xs text-slate-500">Carregando transações...</p>
                    ) : transactions.length ? (
                      <div className="max-h-64 space-y-1 overflow-y-auto">
                        {transactions.map((tx) => (
                          <div key={tx.id} className="flex items-center gap-2 rounded-md bg-white/70 px-2 py-1.5">
                            <span className="w-14 shrink-0 text-xs text-slate-500">{formatDayLabel(tx.date)}</span>
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-xs text-slate-800">{tx.description}</p>
                              <p className="text-[11px] text-slate-400">{tx.pluggy_category || tx.category || ""}</p>
                            </div>
                            <span className="shrink-0 text-xs font-semibold tabular text-slate-800">
                              {formatMoney(Math.abs(Number(tx.amount)))}
                            </span>
                            <Button type="button" variant="primary" onClick={() => void linkTransaction(item, tx)}>
                              Vincular
                            </Button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="py-3 text-center text-xs text-slate-500">Nenhuma saída encontrada neste mês.</p>
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function CostsBase({
  data,
  showInactive,
  setShowInactive,
  onReload,
}: {
  data: PlanningData;
  showInactive: boolean;
  setShowInactive: (value: boolean) => void;
  onReload: () => Promise<unknown>;
}) {
  const { showToast } = useToast();
  const [categoryForm, setCategoryForm] = useState({ name: "", color: "#64748b", sort_order: 0 });
  const [quickCost, setQuickCost] = useState({ category_id: 0, description: "", amount: "", due_day: "" });
  const [editingCost, setEditingCost] = useState<number | null>(null);
  const [costDraft, setCostDraft] = useState<Partial<FixedCost>>({});
  const customCount = data.categories.filter((cat) => !cat.is_default).length;
  const activeTotal = data.costs.filter((cost) => cost.active).reduce((sum, cost) => sum + Number(cost.amount || 0), 0);

  useEffect(() => {
    if (!quickCost.category_id && data.categories[0]) {
      setQuickCost((current) => ({ ...current, category_id: data.categories[0].id }));
    }
  }, [data.categories, quickCost.category_id]);

  const addCategory = async (event: React.FormEvent) => {
    event.preventDefault();
    if (customCount >= MAX_CUSTOM_CATEGORIES) {
      showToast("Limite de 5 categorias personalizadas atingido.", "error");
      return;
    }
    try {
      await createFixedCostCategory(categoryForm);
      setCategoryForm({ name: "", color: "#64748b", sort_order: 0 });
      await onReload();
      showToast("Categoria adicionada.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao adicionar categoria.", "error");
    }
  };

  const addCost = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await createFixedCost({
        category_id: Number(quickCost.category_id),
        description: quickCost.description.trim(),
        amount: Number(quickCost.amount),
        due_day: Number(quickCost.due_day),
      });
      setQuickCost((current) => ({ ...current, description: "", amount: "", due_day: "" }));
      await onReload();
      showToast("Custo fixo adicionado.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao adicionar custo.", "error");
    }
  };

  const grouped = data.categories
    .map((category) => ({
      category,
      costs: data.costs.filter((cost) => Number(cost.category_id) === Number(category.id)),
    }))
    .filter((entry) => entry.costs.length > 0);

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-950">Custos base</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {data.costs.length} custos · ativo {formatMoney(activeTotal)}
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              className="rounded border-slate-300 text-blue-700"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            Mostrar inativos
          </label>
        </div>

        {grouped.length ? (
          <div className="space-y-3">
            {grouped.map(({ category, costs }) => (
              <Card key={category.id} className="overflow-hidden">
                <div className="flex items-center justify-between gap-3 bg-slate-50 px-4 py-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="size-2.5 shrink-0 rounded-full" style={{ background: category.color }} />
                    <h3 className="truncate text-sm font-semibold text-slate-950">{category.name}</h3>
                    {!category.is_default ? <Badge tone="blue">personalizada</Badge> : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold tabular text-slate-700">
                      {formatMoney(costs.filter((cost) => cost.active).reduce((sum, cost) => sum + Number(cost.amount || 0), 0))}
                    </span>
                    {!category.is_default ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="size-8 px-0"
                        onClick={async () => {
                          if (!window.confirm(`Excluir categoria "${category.name}"?`)) return;
                          await deleteFixedCostCategory(category.id);
                          await onReload();
                        }}
                      >
                        <Trash2 className="size-4" aria-hidden="true" />
                      </Button>
                    ) : null}
                  </div>
                </div>
                <ul className="divide-y divide-slate-100">
                  {costs.map((cost) => (
                    <li key={cost.id} className="px-4 py-3">
                      {editingCost === cost.id ? (
                        <form
                          className="grid grid-cols-1 gap-2 lg:grid-cols-[160px_1fr_130px_90px_auto_auto]"
                          onSubmit={async (event) => {
                            event.preventDefault();
                            await updateFixedCost(cost.id, {
                              category_id: Number(costDraft.category_id ?? cost.category_id),
                              description: String(costDraft.description ?? cost.description).trim(),
                              amount: Number(costDraft.amount ?? cost.amount),
                              due_day: Number(costDraft.due_day ?? cost.due_day),
                            });
                            setEditingCost(null);
                            await onReload();
                            showToast("Custo atualizado.", "success");
                          }}
                        >
                          <Select
                            value={Number(costDraft.category_id ?? cost.category_id)}
                            onChange={(event) => setCostDraft((current) => ({ ...current, category_id: Number(event.target.value) }))}
                          >
                            {data.categories.map((cat) => (
                              <option key={cat.id} value={cat.id}>
                                {cat.name}
                              </option>
                            ))}
                          </Select>
                          <Input
                            value={String(costDraft.description ?? cost.description)}
                            onChange={(event) => setCostDraft((current) => ({ ...current, description: event.target.value }))}
                          />
                          <Input
                            type="number"
                            step="0.01"
                            min="0.01"
                            value={Number(costDraft.amount ?? cost.amount)}
                            onChange={(event) => setCostDraft((current) => ({ ...current, amount: Number(event.target.value) }))}
                          />
                          <Input
                            type="number"
                            min="1"
                            max="31"
                            value={Number(costDraft.due_day ?? cost.due_day)}
                            onChange={(event) => setCostDraft((current) => ({ ...current, due_day: Number(event.target.value) }))}
                          />
                          <Button type="submit" variant="primary">
                            Salvar
                          </Button>
                          <Button type="button" onClick={() => setEditingCost(null)}>
                            Cancelar
                          </Button>
                        </form>
                      ) : (
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-sm font-bold tabular text-slate-700">
                            {cost.due_day}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className={classNames("text-sm font-medium", cost.active ? "text-slate-950" : "text-slate-400 line-through")}>
                              {cost.description}
                            </p>
                            <p className="text-xs text-slate-400">dia {cost.due_day} de cada mês</p>
                          </div>
                          <p className={classNames("font-semibold tabular", cost.active ? "text-slate-950" : "text-slate-400")}>
                            {formatMoney(cost.amount)}
                          </p>
                          <div className="flex flex-wrap gap-1">
                            <Button type="button" variant="ghost" onClick={() => {
                              setEditingCost(cost.id);
                              setCostDraft(cost);
                            }}>
                              Editar
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              onClick={async () => {
                                await updateFixedCost(cost.id, { active: !cost.active });
                                await onReload();
                              }}
                            >
                              {cost.active ? "Desativar" : "Reativar"}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              onClick={async () => {
                                if (!window.confirm(`Excluir "${cost.description}"?`)) return;
                                await deleteFixedCost(cost.id);
                                await onReload();
                              }}
                            >
                              Excluir
                            </Button>
                          </div>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState title="Nenhum custo fixo cadastrado ainda." />
        )}
      </Card>

      <Card className="p-6">
        <h2 className="mb-3 font-semibold text-slate-950">Adicionar custo fixo</h2>
        {data.templates.length ? (
          <div className="mb-4 flex flex-wrap gap-2">
            {data.templates.map((template) => (
              <Button
                key={template.label}
                type="button"
                onClick={() =>
                  setQuickCost({
                    category_id: template.category_id,
                    description: template.description,
                    amount: quickCost.amount,
                    due_day: String(template.due_day),
                  })
                }
              >
                {template.label}
              </Button>
            ))}
          </div>
        ) : null}
        <form className="grid grid-cols-1 gap-2 lg:grid-cols-[170px_1fr_140px_90px_auto]" onSubmit={addCost}>
          <Select
            value={quickCost.category_id}
            onChange={(event) => setQuickCost((current) => ({ ...current, category_id: Number(event.target.value) }))}
            required
          >
            {data.categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
          <Input
            required
            placeholder="Descrição"
            value={quickCost.description}
            onChange={(event) => setQuickCost((current) => ({ ...current, description: event.target.value }))}
          />
          <Input
            required
            type="number"
            step="0.01"
            min="0.01"
            placeholder="Valor"
            value={quickCost.amount}
            onChange={(event) => setQuickCost((current) => ({ ...current, amount: event.target.value }))}
          />
          <Input
            required
            type="number"
            min="1"
            max="31"
            placeholder="Dia"
            value={quickCost.due_day}
            onChange={(event) => setQuickCost((current) => ({ ...current, due_day: event.target.value }))}
          />
          <Button type="submit" variant="primary">
            <Plus className="size-4" aria-hidden="true" />
            Adicionar
          </Button>
        </form>

        <form className="mt-5 border-t border-slate-100 pt-5" onSubmit={addCategory}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-slate-950">Nova categoria personalizada</h3>
            <span className="text-xs text-slate-500">
              {customCount}/{MAX_CUSTOM_CATEGORIES} personalizadas
            </span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_120px_100px_auto]">
            <Input
              required
              placeholder="Nome da categoria"
              value={categoryForm.name}
              onChange={(event) => setCategoryForm((current) => ({ ...current, name: event.target.value }))}
            />
            <Input
              type="color"
              value={categoryForm.color}
              onChange={(event) => setCategoryForm((current) => ({ ...current, color: event.target.value }))}
            />
            <Input
              type="number"
              value={categoryForm.sort_order}
              onChange={(event) => setCategoryForm((current) => ({ ...current, sort_order: Number(event.target.value) }))}
            />
            <Button type="submit" disabled={customCount >= MAX_CUSTOM_CATEGORIES}>
              Criar
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

function IncomePlanning({
  data,
  selectedMonth,
  showInactive,
  setShowInactive,
  onReload,
}: {
  data: PlanningData;
  selectedMonth: string;
  showInactive: boolean;
  setShowInactive: (value: boolean) => void;
  onReload: () => Promise<unknown>;
}) {
  const { showToast } = useToast();
  const [entryForm, setEntryForm] = useState({ description: "", amount: "", expected_day: "" });
  const [editingEntry, setEditingEntry] = useState<number | null>(null);
  const [entryDraft, setEntryDraft] = useState<Partial<ExpectedIncomeEntry>>({});

  const addEntry = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await createExpectedIncome({
        description: entryForm.description.trim(),
        amount: Number(entryForm.amount),
        expected_day: Number(entryForm.expected_day),
      });
      setEntryForm({ description: "", amount: "", expected_day: "" });
      await onReload();
      showToast("Entrada adicionada.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao adicionar entrada.", "error");
    }
  };

  const setIncomeOverride = async (item: ExpectedIncomeMonthEntry, amount: number) => {
    try {
      if (item.is_override && Math.abs(amount - Number(item.base_amount)) < 0.005) {
        await deleteExpectedIncomeOverride(item.expected_income_id, selectedMonth);
      } else {
        await setExpectedIncomeOverride(item.expected_income_id, selectedMonth, amount);
      }
      await onReload();
      showToast("Valor do mês atualizado.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao atualizar valor.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <Card className="border-emerald-200 bg-emerald-50 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Receita mensal esperada</p>
            <p className="mt-1 text-3xl font-bold tabular text-emerald-700">{formatMoney(data.incomeMonth.total)}</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              className="rounded border-slate-300 text-emerald-700"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            Mostrar inativas
          </label>
        </div>
      </Card>

      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold text-slate-950">Visão do mês</h2>
          <span className="text-xs text-slate-500">{formatMonthShort(selectedMonth)}</span>
        </div>
        {data.incomeMonth.entries.length ? (
          <ul className="divide-y divide-slate-100">
            {data.incomeMonth.entries.map((item) => (
              <li key={item.expected_income_id} className="flex flex-col gap-3 px-2 py-3 sm:flex-row sm:items-center">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-sm font-bold tabular text-emerald-700">
                  {item.expected_day}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-slate-950">{item.description}</p>
                    {item.is_override ? <Badge tone="blue">ajustado</Badge> : null}
                  </div>
                  {item.is_override ? (
                    <button
                      type="button"
                      className="mt-1 text-xs font-medium text-slate-600"
                      onClick={async () => {
                        await deleteExpectedIncomeOverride(item.expected_income_id, selectedMonth);
                        await onReload();
                      }}
                    >
                      reverter ({formatMoney(item.base_amount)})
                    </button>
                  ) : null}
                </div>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  defaultValue={Number(item.amount).toFixed(2)}
                  className="w-full text-right font-bold tabular text-emerald-700 sm:w-32"
                  onBlur={(event) => {
                    const amount = Number(event.target.value);
                    if (!Number.isNaN(amount) && Math.abs(amount - Number(item.amount)) >= 0.005) {
                      void setIncomeOverride(item, amount);
                    }
                  }}
                />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="Nenhuma entrada ativa para este mês." />
        )}
      </Card>

      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold text-slate-950">Entradas base</h2>
          <span className="text-xs text-slate-500">{data.incomeEntries.length} entradas</span>
        </div>
        {data.incomeEntries.length ? (
          <ul className="mb-5 space-y-2">
            {data.incomeEntries.map((entry) => (
              <li key={entry.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
                {editingEntry === entry.id ? (
                  <form
                    className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_140px_100px_auto_auto]"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      await updateExpectedIncome(entry.id, {
                        description: String(entryDraft.description ?? entry.description).trim(),
                        amount: Number(entryDraft.amount ?? entry.amount),
                        expected_day: Number(entryDraft.expected_day ?? entry.expected_day),
                      });
                      setEditingEntry(null);
                      await onReload();
                    }}
                  >
                    <Input
                      value={String(entryDraft.description ?? entry.description)}
                      onChange={(event) => setEntryDraft((current) => ({ ...current, description: event.target.value }))}
                    />
                    <Input
                      type="number"
                      step="0.01"
                      value={Number(entryDraft.amount ?? entry.amount)}
                      onChange={(event) => setEntryDraft((current) => ({ ...current, amount: Number(event.target.value) }))}
                    />
                    <Input
                      type="number"
                      value={Number(entryDraft.expected_day ?? entry.expected_day)}
                      onChange={(event) => setEntryDraft((current) => ({ ...current, expected_day: Number(event.target.value) }))}
                    />
                    <Button type="submit" variant="primary">Salvar</Button>
                    <Button type="button" onClick={() => setEditingEntry(null)}>Cancelar</Button>
                  </form>
                ) : (
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                    <span className={classNames("flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-bold tabular", entry.active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400")}>
                      {entry.expected_day}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className={classNames("text-sm font-medium", entry.active ? "text-slate-950" : "text-slate-400 line-through")}>{entry.description}</p>
                      <p className="text-xs text-slate-400">recorrente · todo mês</p>
                    </div>
                    <p className={classNames("font-bold tabular", entry.active ? "text-emerald-700" : "text-slate-400")}>{formatMoney(entry.amount)}</p>
                    <div className="flex flex-wrap gap-1">
                      <Button type="button" variant="ghost" onClick={() => {
                        setEditingEntry(entry.id);
                        setEntryDraft(entry);
                      }}>Editar</Button>
                      <Button type="button" variant="ghost" onClick={async () => {
                        await updateExpectedIncome(entry.id, { active: !entry.active });
                        await onReload();
                      }}>{entry.active ? "Desativar" : "Reativar"}</Button>
                      <Button type="button" variant="ghost" onClick={async () => {
                        if (!window.confirm(`Excluir "${entry.description}"?`)) return;
                        await deleteExpectedIncome(entry.id);
                        await onReload();
                      }}>Excluir</Button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="Nenhuma entrada cadastrada." />
        )}
        <form className="grid grid-cols-1 gap-2 border-t border-slate-100 pt-5 sm:grid-cols-[1fr_140px_100px_auto]" onSubmit={addEntry}>
          <Input required placeholder="Descrição" value={entryForm.description} onChange={(event) => setEntryForm((current) => ({ ...current, description: event.target.value }))} />
          <Input required type="number" step="0.01" min="0.01" placeholder="Valor" value={entryForm.amount} onChange={(event) => setEntryForm((current) => ({ ...current, amount: event.target.value }))} />
          <Input required type="number" min="1" max="31" placeholder="Dia" value={entryForm.expected_day} onChange={(event) => setEntryForm((current) => ({ ...current, expected_day: event.target.value }))} />
          <Button type="submit" variant="primary">Adicionar</Button>
        </form>
      </Card>
    </div>
  );
}

export function PlanejamentoPage() {
  const [selectedMonth, setSelectedMonth] = useState(getDefaultPlanningMonth());
  const [activeTab, setActiveTab] = useState<PlanningTab>(() => selectedTabFromLocation());
  const [showInactiveCosts, setShowInactiveCosts] = useState(false);
  const [showInactiveIncome, setShowInactiveIncome] = useState(false);
  const months = useMemo(() => monthWindow(getDefaultPlanningMonth(), 6), []);
  const { data, loading, error, run } = useAsync(
    () => loadPlanningData(selectedMonth, showInactiveCosts, showInactiveIncome),
    [selectedMonth, showInactiveCosts, showInactiveIncome],
  );

  useEffect(() => {
    const url = new URL(window.location.href);
    if (activeTab === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", activeTab);
    window.history.replaceState({}, "", url);
  }, [activeTab]);

  const free = data
    ? asMoneyNumber(
        data.capacity.budget_available_to_spend ??
          data.capacity.discretionary_available ??
          data.capacity.available_to_spend ??
          data.capacity.remaining_after_plan ??
          data.capacity.remaining_after_invoice,
      )
    : 0;

  return (
    <>
      <Topbar
        subtitle={
          activeTab === "overview"
            ? "Veja os principais números do planejamento mensal."
            : activeTab === "custos"
              ? "Cadastre e edite compromissos recorrentes."
              : activeTab === "variaveis"
                ? "Metas variáveis sobre a classificação Pluggy-based."
                : "Cadastre o que você espera receber em cada mês."
        }
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer narrow>
        <div className="space-y-6">
          <Tabs<PlanningTab>
            value={activeTab}
            onChange={setActiveTab}
            items={[
              { key: "overview", label: "Visão geral" },
              { key: "custos", label: "Custos fixos" },
              { key: "variaveis", label: "Metas variáveis" },
              { key: "receita", label: "Receita futura" },
            ]}
          />
          <MonthStrip months={months} value={selectedMonth} onChange={setSelectedMonth} />

          {loading && !data ? <LoadingState label="Carregando planejamento..." /> : null}
          {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
          {data ? (
            <>
              {activeTab === "overview" ? (
                <div className="space-y-6">
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                    <span>
                      Total fixo: <span className="font-semibold tabular text-slate-950">{formatMoney(data.fixedMonth.total)}</span>
                    </span>
                    <span>
                      Pode gastar: <span className="font-semibold tabular text-slate-950">{formatMoney(free)}</span>
                    </span>
                  </div>
                  <CapacityFlow capacity={data.capacity} />
                </div>
              ) : null}

              {activeTab === "custos" ? (
                <div className="space-y-6">
                  <Card className="p-6">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div>
                        <h2 className="font-semibold text-slate-950">Custos do mês</h2>
                        <p className="mt-0.5 text-xs text-slate-500">
                          Ajustes valem apenas para {formatMonthShort(selectedMonth)}.
                        </p>
                      </div>
                      <span className="text-sm font-semibold tabular text-slate-950">
                        {formatMoney(data.fixedMonth.total)}
                      </span>
                    </div>
                    <FixedMonthBreakdown fixed={data.fixedMonth} selectedMonth={selectedMonth} onReload={run} />
                  </Card>
                  <CostsBase
                    data={data}
                    showInactive={showInactiveCosts}
                    setShowInactive={setShowInactiveCosts}
                    onReload={run}
                  />
                </div>
              ) : null}

              {activeTab === "variaveis" ? (
                <Card className="p-6">
                  <h2 className="font-semibold text-slate-950">Metas de gastos variáveis</h2>
                  <div className="mt-5">
                    <EmptyState
                      title="Metas variáveis por categoria foram removidas na 10D-A."
                      detail="A recriação fica vinculada à classificação Pluggy-based em uma próxima etapa."
                    />
                  </div>
                </Card>
              ) : null}

              {activeTab === "receita" ? (
                <IncomePlanning
                  data={data}
                  selectedMonth={selectedMonth}
                  showInactive={showInactiveIncome}
                  setShowInactive={setShowInactiveIncome}
                  onReload={run}
                />
              ) : null}
            </>
          ) : null}
        </div>
      </PageContainer>
    </>
  );
}
