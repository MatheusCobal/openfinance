import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, ArrowDownLeft, ArrowUpRight, Calendar, CalendarClock, ChevronDown, Copy, CreditCard, Link2, MoreVertical, Pencil, Plus, RefreshCw, SlidersHorizontal, Wallet, X } from "lucide-react";
import {
  createExpectedIncome,
  createFixedCost,
  createFixedCostCategory,
  createFixedCostMatch,
  deleteExpectedIncome,
  deleteFixedCost,
  deleteFixedCostMatch,
  deleteFixedCostOverride,
  deleteVariableBudget,
  getExpectedIncomeByMonth,
  getFixedCostsByMonth,
  getPlanningMonth,
  listExpectedIncome,
  listFixedCostCategories,
  listFixedCosts,
  listFixedCostTemplates,
  listFixedCostMatchCandidates,
  setFixedCostOverride,
  replicateVariableBudgets,
  setVariableBudget,
  updateExpectedIncome,
  updateFixedCost,
} from "../api/planejamento";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { CatAvatar } from "../components/ui/CatAvatar";
import { DayBadge } from "../components/ui/DayBadge";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, StaleDataWarning } from "../components/ui/ErrorState";
import { FinancialFlow } from "../components/ui/FinancialFlow";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { MonthStrip } from "../components/ui/MonthStrip";
import { Select } from "../components/ui/Select";
import { StatusPill } from "../components/ui/StatusPill";
import { Tabs } from "../components/ui/Tabs";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { MAX_CUSTOM_CATEGORIES } from "../lib/constants";
import {
  currentYearMonth,
  formatDayLabel,
  formatMonthLong,
  formatMonthShort,
  getDefaultPlanningMonth,
  monthWindow,
} from "../lib/dates";
import {
  invoiceIncludedAmount,
  isFuturePlanningMonth,
  normalizePlanningOverview,
  tokenSet,
} from "../lib/planning";
import { categoryColor } from "../lib/categories";
import { pluralize } from "../lib/labels";
import { classNames } from "../lib/classNames";
import { asMoneyNumber, formatMoney, percent } from "../lib/money";
import type { Transaction } from "../types/common";
import type {
  ExpectedIncomeEntry,
  ExpectedIncomeMonth,
  FixedCost,
  FixedCostCategory,
  FixedCostMonthEntry,
  FixedCostsMonth,
  FixedCostTemplate,
  PlanningOverview,
  VariableBudgetItem,
} from "../types/planejamento";

type PlanningTab = "overview" | "custos" | "variaveis" | "receita";

const PLANNING_MONTH_WINDOW_SIZE = 12;

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

function entryStatusPill(status?: string) {
  const cfg: Record<string, { label: string; tone: "positive" | "warning" | "danger" | "neutral" }> = {
    paid: { label: "Pago", tone: "positive" },
    due_soon: { label: "Vence em breve", tone: "warning" },
    overdue: { label: "Vencido", tone: "danger" },
    scheduled: { label: "Previsto", tone: "neutral" },
    unconfirmed: { label: "Aguardando confirmação", tone: "neutral" },
  };
  const item = cfg[status || ""] || cfg.scheduled;
  return <StatusPill label={item.label} tone={item.tone} />;
}

async function loadPlanningData(selectedMonth: string): Promise<PlanningData> {
  const [planning, categories, costs, templates, incomeEntries, incomeMonth] = await Promise.all([
    getPlanningMonth(selectedMonth),
    listFixedCostCategories(),
    listFixedCosts(true),
    listFixedCostTemplates().catch(() => []),
    listExpectedIncome(true),
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

function FormField({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={classNames("block min-w-0 space-y-1.5 text-xs font-medium text-ink-600", className)}>
      <span>{label}</span>
      {children}
    </label>
  );
}

/** "Plano do mês" — the decision panel at the top of the page. */
function MonthPlanPanel({ capacity, onOpenTab }: { capacity: PlanningOverview; onOpenTab: (tab: PlanningTab) => void }) {
  const isFuture = isFuturePlanningMonth(capacity);
  const free = asMoneyNumber(
    capacity.budget_available_to_spend ?? capacity.available_to_spend,
  );
  const income = capacity.expected_income_total || 0;
  const fixed = isFuture
    ? capacity.fixed_cost_planned_total || 0
    : capacity.fixed_cost_reserved_total || 0;
  const card = invoiceIncludedAmount(capacity);
  const hasPlanData = [income, fixed, card].some((value) => Math.abs(value) > 0.009);

  if (!hasPlanData) {
    return (
      <Card className="p-6 sm:p-10">
        <EmptyState
          icon={<Wallet className="size-5" aria-hidden="true" />}
          title="Vamos montar seu mês"
          detail="Comece pela receita esperada e pelos compromissos recorrentes."
          action={<Button variant="primary" onClick={() => onOpenTab("receita")}><Plus className="size-4" aria-hidden="true" />Planejar receita</Button>}
        />
      </Card>
    );
  }

  const status =
    income <= 0
      ? { label: "Sem receita prevista", tone: "neutral" as const }
      : free < 0
        ? { label: "Estourado", tone: "danger" as const }
        : free <= 1000
          ? { label: "No limite", tone: "warning" as const }
          : { label: "Saudável", tone: "positive" as const };

  return (
    <section aria-label="Resumo do plano" className="grid overflow-hidden rounded-card border border-ink-200/70 bg-surface shadow-card lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <div className="cockpit-surface flex min-w-0 flex-col justify-between p-5 text-white sm:p-7">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-white/65">Seu plano do mês</span>
            <StatusPill label={status.label} tone={status.tone} inverse />
          </div>
          <p className="mt-8 text-sm text-white/75">{isFuture ? "Sobra planejada" : "Disponível para gastar"}</p>
          <p className={classNames("mt-2 break-words text-4xl font-semibold leading-tight tracking-tight tabular sm:text-5xl", free < 0 ? "text-danger-300" : "text-white")}>{formatMoney(free)}</p>
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-white/65">{isFuture ? "A margem prevista para o mês que você está planejando." : "Acompanhe a margem do mês conforme os pagamentos acontecem."}</p>
            {capacity.days_remaining_in_month && capacity.daily_discretionary_remaining ? (
              <div className="mt-5 flex flex-wrap items-center justify-between gap-2 rounded-control border border-white/15 bg-white/[0.06] px-4 py-3">
                <p className="text-xl font-semibold tabular text-white">
                  {formatMoney(capacity.daily_discretionary_remaining)}
                  <span className="text-xs font-normal text-white/65"> /dia</span>
                </p>
                <p className="text-xs text-white/65">
                  {pluralize(capacity.days_remaining_in_month, "dia restante", "dias restantes")}
                </p>
              </div>
            ) : null}
        </div>
          {income > 0 ? (
              <FinancialFlow
                inverse
                className="mt-7 border-t border-white/15 pt-5"
                total={income}
                segments={[
                  { key: "fixed", label: "Custos fixos", value: fixed, color: "#fbbf24" },
                  {
                    key: "invoice",
                    label: isFuture ? "Fatura prevista" : "Fatura em aberto",
                    value: card,
                    color: "#fda4af",
                  },
                ]}
                remainder={{ label: isFuture ? "Sobra planejada" : "Disponível", value: free }}
              />
          ) : null}
      </div>
      <div className="min-w-0 divide-y divide-ink-100 px-5 sm:px-7">
        <div className="py-5 sm:py-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-ink-600"><ArrowDownLeft className="size-4 text-positive-700" aria-hidden="true" />Receita esperada</div>
            <button className="text-xs font-semibold text-primary-700 hover:underline" onClick={() => onOpenTab("receita")}>Gerenciar</button>
          </div>
          <p className="mt-2 text-2xl font-semibold tracking-tight tabular text-ink-900">{formatMoney(income)}</p>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
            <div><dt className="text-ink-500">Já recebido</dt><dd className="mt-1 font-medium tabular text-positive-700">{formatMoney(capacity.received_income_total || 0)}</dd></div>
            <div><dt className="text-ink-500">A receber</dt><dd className="mt-1 font-medium tabular text-ink-700">{formatMoney(capacity.income_to_receive || 0)}</dd></div>
          </dl>
        </div>
        <div className="py-5 sm:py-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-ink-600"><Wallet className="size-4" aria-hidden="true" />Custos fixos</div>
            <button className="text-xs font-semibold text-primary-700 hover:underline" onClick={() => onOpenTab("custos")}>Ver compromissos</button>
          </div>
          <p className="mt-2 text-2xl font-semibold tracking-tight tabular text-ink-900">{formatMoney(fixed)}</p>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
            <div><dt className="text-ink-500">Pagos</dt><dd className="mt-1 font-medium tabular text-positive-700">{formatMoney(capacity.fixed_cost_actual_total || 0)}</dd></div>
            <div><dt className="text-ink-500">Pendentes</dt><dd className="mt-1 font-medium tabular text-ink-700">{formatMoney(capacity.fixed_cost_pending_total || 0)}</dd></div>
          </dl>
        </div>
        <div className="py-5 sm:py-6">
          <div className="flex items-center gap-2 text-sm font-medium text-ink-600"><CreditCard className="size-4 text-primary-700" aria-hidden="true" />{isFuture ? "Fatura prevista" : "Fatura em aberto"}</div>
          <p className="mt-2 text-2xl font-semibold tracking-tight tabular text-ink-900">{formatMoney(card)}</p>
          <p className="mt-2 text-xs leading-relaxed text-ink-500">Valor do cartão considerado no plano deste mês.</p>
        </div>
      </div>
    </section>
  );
}

function variableStatusTone(status: VariableBudgetItem["status"]): "positive" | "warning" | "danger" | "neutral" {
  if (status === "over") return "danger";
  if (status === "warning") return "warning";
  if (status === "no_target") return "neutral";
  return "positive";
}

function VariableBudgetRow({
  item,
  isEditing,
  onStartEdit,
  onEndEdit,
  onSave,
  onRemove,
}: {
  item: VariableBudgetItem;
  isEditing: boolean;
  onStartEdit: () => void;
  onEndEdit: () => void;
  onSave: (category: string, amount: number) => Promise<void>;
  onRemove: (category: string) => Promise<void>;
}) {
  const progress = Math.min(item.progress_percent ?? 0, 100);
  const tone = variableStatusTone(item.status);
  const color = categoryColor(item.category);
  const barColor = tone === "danger" ? "#e11d48" : tone === "warning" ? "#f59e0b" : color;
  const over = item.spent > item.target && item.has_target;

  return (
    <div className="group grid grid-cols-3 gap-x-3 gap-y-4 border-b border-ink-100 px-4 py-4 transition-colors last:border-0 hover:bg-surface-muted/40 sm:px-5 xl:grid-cols-[minmax(0,1fr)_minmax(70px,.6fr)_100px_105px_100px_112px] xl:items-center xl:gap-4">
      <div className="col-span-2 flex min-w-0 items-center gap-2.5 xl:col-span-1">
        <span className="size-2.5 shrink-0 rounded-[4px]" style={{ backgroundColor: color }} aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink-900">{item.category}</p>
          <p className="text-xs text-ink-400">
            {item.transaction_count > 0
              ? pluralize(item.transaction_count, "compra", "compras") + " no mês"
              : "sem gastos no mês"}
          </p>
        </div>
      </div>
      <div className="order-last col-span-3 xl:order-none xl:col-span-1">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-100" role="img" aria-label={`Progresso de ${item.category}: ${item.progress_percent ?? 0}% da meta`}>
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${progress}%`, backgroundColor: barColor }}
          />
        </div>
      </div>
      <p className={classNames("min-w-0 text-sm font-semibold tabular xl:text-right", over ? "text-danger-700" : "text-ink-900")}>
        <span className="mb-1 block text-[11px] font-normal text-ink-500 xl:hidden">Consumido</span>
        {formatMoney(item.spent)}
      </p>
      <div className="min-w-0 text-right">
        <span className="mb-1 block text-[11px] text-ink-500 xl:hidden">Meta</span>
        {isEditing ? (
          <Input
            type="number"
            step="0.01"
            min="0"
            aria-label={`Meta de ${item.category}`}
            defaultValue={item.target.toFixed(2)}
            className="w-full text-right text-sm font-semibold tabular"
            autoFocus
            onBlur={async (e) => {
              const v = Number(e.currentTarget.value);
              if (!Number.isNaN(v) && v >= 0) await onSave(item.category, v);
              onEndEdit();
            }}
          />
        ) : (
          <button
            type="button"
            aria-label={`Editar meta de ${item.category}: ${formatMoney(item.target)}`}
            className="inline-flex min-h-6 items-center gap-1.5 text-sm font-medium tabular text-primary-700 hover:underline"
            onClick={onStartEdit}
          >
            {formatMoney(item.target)}
            <Pencil className="size-3 shrink-0" aria-hidden="true" />
          </button>
        )}
      </div>
      <p className={classNames(
        "min-w-0 text-right text-sm font-semibold tabular",
        over ? "text-danger-700" : "text-positive-700",
      )}>
        <span className="mb-1 block text-[11px] font-normal text-ink-500 xl:hidden">{over ? "Excedido" : "Sobra"}</span>
        {over ? `+${formatMoney(item.spent - item.target)}` : formatMoney(Math.max(item.remaining, 0))}
      </p>
      <div className="col-start-3 row-start-1 flex items-center justify-end gap-1 xl:col-auto xl:row-auto">
        {over ? (
          <span className="rounded-full bg-danger-50 px-2 py-0.5 text-[10px] font-semibold text-danger-700">Excedeu</span>
        ) : tone === "warning" ? (
          <span className="rounded-full bg-warning-50 px-2 py-0.5 text-[10px] font-semibold text-warning-800">Atenção</span>
        ) : (
          <span className="rounded-full bg-positive-50 px-2 py-0.5 text-[10px] font-semibold text-positive-700">OK</span>
        )}
        <button
          type="button"
          aria-label={`Remover meta de ${item.category}`}
          title={`Remover meta de ${item.category}`}
          className="ml-0.5 flex size-8 shrink-0 items-center justify-center rounded-control text-ink-400 transition-colors hover:bg-danger-50 hover:text-danger-600 focus-visible:text-danger-600"
          onClick={() => void onRemove(item.category)}
        >
          <X className="size-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function VariableBudgetsPanel({
  capacity,
  selectedMonth,
  onReload,
}: {
  capacity: PlanningOverview;
  selectedMonth: string;
  onReload: () => Promise<unknown>;
}) {
  const { showToast } = useToast();
  const items = (capacity.variable_budgets?.items || []) as VariableBudgetItem[];
  const eligible = capacity.variable_budgets?.eligible_categories || [];
  const budgeted = items.filter((item) => item.has_target);
  const suggestions = items.filter((item) => !item.has_target && item.spent > 0);

  const target = asMoneyNumber(capacity.variable_budget_total);

  const budgetedCategories = new Set(budgeted.map((item) => item.category));
  const availableToAdd = eligible.filter((category) => !budgetedCategories.has(category));

  const [newCategory, setNewCategory] = useState("");
  const [newAmount, setNewAmount] = useState("");
  const [statusFilter, setStatusFilter] = useState<"Todas" | "OK" | "Atenção" | "Excedido">("Todas");
  const [editingGoal, setEditingGoal] = useState<string | null>(null);
  const [replicating, setReplicating] = useState(false);
  const [replicateConfirm, setReplicateConfirm] = useState(false);
  const [showAddGoal, setShowAddGoal] = useState(false);

  const handleReplicate = async () => {
    setReplicating(true);
    try {
      const result = await replicateVariableBudgets(selectedMonth);
      await onReload();
      const msg = result.skipped > 0
        ? `Metas copiadas para ${result.replicated} ${result.replicated === 1 ? "mês" : "meses"} (${result.skipped} ignorados — já tinham metas).`
        : `Metas copiadas para ${result.replicated} ${result.replicated === 1 ? "mês" : "meses"}.`;
      showToast(msg, "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao replicar metas.", "error");
    } finally {
      setReplicating(false);
      setReplicateConfirm(false);
    }
  };

  const saveGoal = async (category: string, amount: number) => {
    try {
      await setVariableBudget(selectedMonth, category, amount);
      await onReload();
      showToast("Meta atualizada.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao salvar meta.", "error");
    }
  };

  const removeGoal = async (category: string) => {
    try {
      await deleteVariableBudget(selectedMonth, category);
      await onReload();
      showToast("Meta removida.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao remover meta.", "error");
    }
  };

  const addGoal = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newCategory) {
      showToast("Selecione uma categoria.", "error");
      return;
    }
    const amount = Number(newAmount);
    if (Number.isNaN(amount) || amount < 0) {
      showToast("Informe um valor maior ou igual a zero.", "error");
      return;
    }
    await saveGoal(newCategory, amount);
    setNewCategory("");
    setNewAmount("");
    setShowAddGoal(false);
  };

  const statusMap: Record<string, VariableBudgetItem["status"]> = {
    "OK": "ok",
    "Atenção": "warning",
    "Excedido": "over",
  };
  const shownBudgets = statusFilter === "Todas"
    ? budgeted
    : budgeted.filter((item) => item.status === statusMap[statusFilter]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold tracking-tight text-ink-900">Metas de gastos variáveis</h2>
          <p className="mt-1 text-sm leading-relaxed text-ink-500">Limites por categoria para acompanhar suas escolhas ao longo do mês.</p>
          {budgeted.length > 0 ? (
            <p className="mt-1 text-sm text-ink-500">
              {budgeted.length} categorias com limite ·{" "}
              <span className="tabular font-semibold text-ink-700">{formatMoney(target)}</span> / mês
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          {availableToAdd.length > 0 ? (
            <Button type="button" variant="primary" size="sm" onClick={() => setShowAddGoal(true)}>
              <Plus className="size-3.5" aria-hidden="true" />
              Nova meta
            </Button>
          ) : null}
          {budgeted.length > 0 ? (
            <>
            {replicateConfirm ? (
              <>
                <p className="text-xs text-ink-500">
                  Copiar {budgeted.length} {budgeted.length === 1 ? "meta" : "metas"} para os próximos 11 meses?
                </p>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={() => void handleReplicate()}
                  loading={replicating}
                >
                  Confirmar
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => setReplicateConfirm(false)}
                  disabled={replicating}
                >
                  Cancelar
                </Button>
              </>
            ) : (
              <Button
                type="button"
                size="sm"
                onClick={() => setReplicateConfirm(true)}
              >
                <Copy className="size-3.5" aria-hidden="true" />
                Replicar para próximos meses
              </Button>
            )}
            </>
          ) : null}
        </div>
      </div>

      {/* Status filter chips */}
      {budgeted.length >= 4 ? <div className="flex flex-wrap gap-2" aria-label="Filtrar metas por status">
        {(["Todas", "OK", "Atenção", "Excedido"] as const).map((f) => {
          const active = statusFilter === f;
          const dotCls = f === "OK" ? "bg-positive-500" : f === "Atenção" ? "bg-warning-500" : f === "Excedido" ? "bg-danger-500" : "bg-ink-400";
          return (
            <button
              key={f}
              type="button"
              aria-pressed={active}
              onClick={() => setStatusFilter(f)}
              className={classNames(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                active ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-surface text-ink-600 hover:border-ink-300",
              )}
            >
              {f !== "Todas" && <span className={classNames("size-1.5 rounded-full", active ? "bg-white" : dotCls)} />}
              {f}
            </button>
          );
        })}
      </div> : null}

      {/* Add goal form */}
      {showAddGoal && availableToAdd.length > 0 ? <Card className="border-primary-200 bg-primary-50/30 p-5 sm:p-6">
        <h3 className="mb-4 text-sm font-semibold text-ink-900">Nova meta mensal</h3>
        <form
          onSubmit={addGoal}
          className="flex flex-col gap-3 lg:flex-row lg:items-end"
        >
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-ink-600">Categoria</span>
            <Select
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value)}
            >
              <option value="">Selecione uma categoria</option>
              {availableToAdd.map((category) => (
                <option key={category} value={category}>{category}</option>
              ))}
            </Select>
          </label>
          <label className="lg:w-40">
            <span className="mb-1 block text-xs font-medium text-ink-600">Meta (R$)</span>
            <Input
              type="number"
              step="0.01"
              min="0"
              placeholder="0,00"
              value={newAmount}
              onChange={(event) => setNewAmount(event.target.value)}
            />
          </label>
          <Button type="submit" variant="primary">
            <Plus className="size-4" aria-hidden="true" />
            Adicionar meta
          </Button>
          <Button type="button" onClick={() => setShowAddGoal(false)}>
            Cancelar
          </Button>
        </form>
      </Card> : null}

      {/* Budget list */}
      {shownBudgets.length > 0 ? (
        <div className="overflow-hidden rounded-card border border-ink-200/70 bg-surface shadow-card">
          <div className="hidden grid-cols-[minmax(0,1fr)_minmax(70px,.6fr)_100px_105px_100px_112px] items-center gap-4 border-b border-ink-100 bg-surface-muted/60 px-5 py-3 xl:grid">
            <span className="min-w-0 text-[11px] font-semibold uppercase tracking-wider text-ink-400">Categoria</span>
            <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">Progresso</span>
            <span className="text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Consumido</span>
            <span className="text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Meta</span>
            <span className="text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Sobra</span>
            <span className="text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Status</span>
          </div>
          {shownBudgets.map((item) => (
            <VariableBudgetRow
              key={item.category}
              item={item}
              isEditing={editingGoal === item.category}
              onStartEdit={() => setEditingGoal(item.category)}
              onEndEdit={() => setEditingGoal(null)}
              onSave={saveGoal}
              onRemove={removeGoal}
            />
          ))}
        </div>
      ) : budgeted.length === 0 ? (
        <Card className="p-5 sm:p-6">
          <EmptyState
            icon={<CalendarClock className="size-5" aria-hidden="true" />}
            title="Nenhuma meta configurada"
            detail="Defina limites para as categorias que deseja acompanhar."
            action={
              availableToAdd.length ? (
                <Button type="button" variant="primary" onClick={() => setShowAddGoal(true)}>
                  Criar primeira meta
                </Button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <Card className="p-5 sm:p-6">
          <EmptyState title="Nenhuma categoria neste filtro." />
        </Card>
      )}

      {/* Suggestions */}
      {suggestions.length > 0 ? (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-400">Gastos sem meta</p>
            <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] font-semibold text-ink-500">
              {suggestions.length}
            </span>
          </div>
          <div className="overflow-hidden rounded-card border border-ink-200/70 bg-surface shadow-card">
            {suggestions.map((item, idx) => (
              <div
                key={item.category}
                className={classNames(
                  "flex flex-wrap items-center gap-3 px-4 py-4 sm:px-5",
                  idx < suggestions.length - 1 ? "border-b border-ink-100" : "",
                )}
              >
                <span className="size-2.5 shrink-0 rounded-[4px]" style={{ backgroundColor: categoryColor(item.category) }} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-ink-900">{item.category}</p>
                  <p className="text-xs text-ink-400">
                    {formatMoney(item.spent)} · {pluralize(item.transaction_count, "compra", "compras")} · sem limite definido
                  </p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setNewCategory(item.category);
                    setNewAmount(item.spent.toFixed(2));
                    setShowAddGoal(true);
                  }}
                >
                  <Plus className="size-3" aria-hidden="true" />
                  Definir meta
                </Button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const FIXED_STATUS_RANK: Record<string, number> = {
  overdue: 4,
  due_soon: 3,
  scheduled: 2,
  unconfirmed: 2,
  paid: 1,
};

const CALENDAR_DOT_COLOR: Record<number, string> = {
  4: "#fb7185",
  3: "#fbbf24",
  2: "#94a3b8",
  1: "#34d399",
};

const WEEK_LABELS = ["D", "S", "T", "Q", "Q", "S", "S"];

function dayBadgeTone(status: string): "positive" | "danger" | "warning" | "neutral" {
  if (status === "paid") return "positive";
  if (status === "overdue") return "danger";
  if (status === "due_soon") return "warning";
  return "neutral";
}

function FixedCostsAgenda({
  fixed,
  expectedIncome,
  selectedMonth,
  onReload,
}: {
  fixed: FixedCostsMonth;
  expectedIncome: number;
  selectedMonth: string;
  onReload: () => Promise<unknown>;
}) {
  const { showToast } = useToast();
  const [mounted, setMounted] = useState(false);
  const [expandedFor, setExpandedFor] = useState<number | null>(null);
  const [allCandidates, setAllCandidates] = useState<Transaction[]>([]);
  const [pickerFilter, setPickerFilter] = useState<"CREDIT" | "BANK">("CREDIT");
  const [pickerVisible, setPickerVisible] = useState(10);
  const [loadingPicker, setLoadingPicker] = useState(false);
  const [pickerAttempted, setPickerAttempted] = useState(false);

  const filteredCandidates = allCandidates.filter(
    (tx) => (tx.account_type ?? "").toUpperCase() === pickerFilter,
  );
  const transactions = filteredCandidates.slice(0, pickerVisible);

  useEffect(() => {
    const timer = window.setTimeout(() => setMounted(true), 120);
    return () => window.clearTimeout(timer);
  }, []);

  const effStatus = (entry: FixedCostMonthEntry): string => entry.status || "scheduled";

  const entries = useMemo(() => fixed.entries || [], [fixed.entries]);
  const total = Number(fixed.total || 0);
  const paidSum = entries
    .filter((e) => e.status === "paid")
    .reduce((sum, e) => sum + Number(e.amount || 0), 0);
  const paidCount = entries.filter((e) => e.status === "paid").length;
  const pendingSum = Math.max(total - paidSum, 0);
  const incomeShare = expectedIncome > 0 ? (total / expectedIncome) * 100 : 0;

  const ordered = useMemo(
    () => [...entries].sort((a, b) => a.due_day - b.due_day),
    [entries],
  );

  // Calendar geometry for the selected month.
  const [year, month] = selectedMonth.split("-").map(Number);
  const daysInMonth = new Date(year, month, 0).getDate();
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const isCurrentMonth = selectedMonth === currentYearMonth();
  const today = new Date().getDate();

  const byDay = useMemo(() => {
    const map = new Map<number, FixedCostMonthEntry[]>();
    for (const entry of entries) {
      const list = map.get(entry.due_day) || [];
      list.push(entry);
      map.set(entry.due_day, list);
    }
    return map;
  }, [entries]);

  const dividerIndex = isCurrentMonth ? ordered.findIndex((e) => e.due_day >= today) : -1;

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
    setLoadingPicker(true);
    setPickerFilter("CREDIT");
    setPickerVisible(10);
    try {
      const data = await listFixedCostMatchCandidates(selectedMonth);
      const costTokens = tokenSet(item.description);
      const tolerance = Math.max(Number(item.amount) * 0.15, 10);
      const scored = data
        .filter((tx) => {
          const ct = (tx.cashflow_type ?? "").toLowerCase();
          return ct !== "income" && ct !== "refund" && Number(tx.amount) !== 0;
        })
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
        .map((scoredItem) => scoredItem.tx);
      setAllCandidates(scored);
      setPickerAttempted(true);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao carregar transações.", "error");
      setPickerAttempted(true);
    } finally {
      setLoadingPicker(false);
    }
  };

  const linkTransaction = async (item: FixedCostMonthEntry, tx: Transaction) => {
    try {
      await createFixedCostMatch(item.fixed_cost_id, tx.id, selectedMonth);
      setExpandedFor(null);
      setAllCandidates([]);
      setPickerFilter("CREDIT");
      setPickerVisible(10);
      await onReload();
      showToast(`"${item.description}" vinculado ao pagamento.`, "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao vincular pagamento.", "error");
    }
  };

  const toggleExpand = (item: FixedCostMonthEntry) => {
    setExpandedFor((current) => (current === item.fixed_cost_id ? null : item.fixed_cost_id));
    setAllCandidates([]);
    setPickerFilter("CREDIT");
    setPickerVisible(10);
    setPickerAttempted(false);
  };

  if (!entries.length) {
    return <Card className="p-5"><EmptyState icon={<CalendarClock className="size-5" aria-hidden="true" />} title="Nenhum compromisso previsto" detail="Cadastre um custo recorrente para organizar os vencimentos deste mês." /></Card>;
  }

  return (
    <div className="space-y-6">
      {/* Hero — total, live paid bar and month calendar */}
      <section className="relative overflow-hidden rounded-card border border-ink-200/70 bg-surface p-5 shadow-card sm:p-6">
        <div className="relative grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_220px]">
          <div className="flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2.5">
                <span className="inline-flex size-8 items-center justify-center rounded-control bg-primary-50 ring-1 ring-inset ring-primary-100">
                  <CalendarClock className="size-4 text-primary-700" aria-hidden="true" />
                </span>
                <p className="text-sm font-medium text-ink-600">
                  Total previsto · {formatMonthLong(selectedMonth)}
                </p>
              </div>
              <p className="mt-4 text-4xl font-semibold leading-tight tracking-tight tabular text-ink-900">
                {formatMoney(total)}
              </p>
              {expectedIncome > 0 ? (
                <p className="mt-3 text-sm text-ink-500">
                  {percent(incomeShare)} da receita esperada
                </p>
              ) : null}
            </div>
            <div className="mt-5">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="inline-flex items-center gap-1.5 font-medium text-ink-600">
                  <span className="size-2 rounded-[3px] bg-positive-400" /> Pago {formatMoney(paidSum)}
                </span>
                <span className="inline-flex items-center gap-1.5 font-medium text-ink-600">
                  <span className="size-2 rounded-[3px] bg-ink-200" /> A pagar {formatMoney(pendingSum)}
                </span>
              </div>
              <div className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-ink-100">
                <div
                  className="bar-fill h-full rounded-l-full"
                  style={{
                    width: mounted && total > 0 ? `${(paidSum / total) * 100}%` : 0,
                    background: "rgba(52,211,153,0.95)",
                  }}
                />
              </div>
              <p className="mt-2 text-[11px] text-ink-500">
                {paidCount} de {entries.length} contas quitadas
              </p>
            </div>
          </div>

          {/* Mini calendar */}
          <div className="mx-auto w-full max-w-[280px] rounded-control bg-surface-muted p-3 lg:max-w-none">
            <div className="mb-2 grid grid-cols-7 gap-1 text-center text-[10px] font-semibold uppercase text-ink-500">
              {WEEK_LABELS.map((label, i) => (
                <div key={i}>{label}</div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {Array.from({ length: firstWeekday }).map((_, i) => (
                <div key={`blank-${i}`} />
              ))}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const day = i + 1;
                const items = byDay.get(day) || [];
                const isToday = isCurrentMonth && day === today;
                const worst = items.reduce(
                  (rank, entry) => Math.max(rank, FIXED_STATUS_RANK[effStatus(entry)] || 0),
                  0,
                );
                const dotColor = CALENDAR_DOT_COLOR[worst];
                return (
                  <div
                    key={day}
                    className={classNames(
                      "relative flex aspect-square flex-col items-center justify-center rounded-md text-[11px] tabular",
                      isToday
                        ? "bg-primary-700 font-bold text-white"
                        : items.length
                          ? "bg-primary-50 font-medium text-primary-800"
                          : "text-ink-500",
                    )}
                  >
                    {day}
                    {dotColor && !isToday ? (
                      <span
                        className="absolute bottom-1 size-1 rounded-full"
                        style={{ background: dotColor }}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-ink-200 pt-2.5 text-[10px] text-ink-500">
              <span className="inline-flex items-center gap-1">
                <span className="size-1.5 rounded-full bg-positive-400" />pago
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="size-1.5 rounded-full bg-warning-400" />em breve
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="size-1.5 rounded-full bg-danger-400" />vencido
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Timeline */}
      <div className="ofx-rise" style={{ animationDelay: "120ms" }}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink-900">Vencimentos do mês</h3>
          <p className="text-xs text-ink-500">Abra um compromisso para ajustar o valor ou vincular um pagamento.</p>
        </div>
        <div className="rounded-card border border-ink-200/70 bg-surface p-2 shadow-card">
          <ul>
            {ordered.map((item, idx) => {
              const status = effStatus(item);
              const isPaid = status === "paid";
              const color = categoryColor(item.category_name, item.category_color);
              const expanded = expandedFor === item.fixed_cost_id;
              return (
                <li key={`${item.fixed_cost_id}-${item.due_date}`}>
                  {idx === dividerIndex ? (
                    <div className="flex items-center gap-3 px-3 py-2">
                      <span className="rounded-full bg-primary-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                        Hoje · {today} {formatMonthShort(selectedMonth).split("/")[0]}
                      </span>
                      <span className="h-px flex-1 bg-primary-200" />
                    </div>
                  ) : null}
                  <div className="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 rounded-control px-2 py-4 transition-colors hover:bg-surface-muted sm:flex sm:items-center sm:px-3">
                    <DayBadge day={item.due_day} tone={dayBadgeTone(status)} />
                    <span className="hidden lg:block"><CatAvatar category={item.category_name} color={color} size={38} /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <p
                          className={classNames(
                            "min-w-0 break-words text-sm font-semibold",
                            isPaid ? "text-ink-500" : "text-ink-900",
                          )}
                        >
                          {item.description}
                        </p>
                        <span className="hidden text-xs text-ink-400 sm:inline">·</span>
                        <span className="text-xs font-medium" style={{ color }}>
                          {item.category_name}
                        </span>
                        {item.is_override ? <Badge tone="primary">Ajustado</Badge> : null}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-ink-500">
                        {item.matched_transaction ? (
                          <span className="inline-flex items-center gap-1 text-positive-700">
                            <Link2 className="size-3" aria-hidden="true" />
                            {item.matched_transaction.description?.slice(0, 40)} ·{" "}
                            {formatMoney(
                              item.matched_transaction.amount_abs ??
                                Math.abs(Number(item.matched_transaction.amount)),
                            )}
                          </span>
                        ) : (
                          <span className="text-ink-400">sem pagamento vinculado</span>
                        )}
                      </p>
                      <div className="mt-2 sm:hidden">{entryStatusPill(status)}</div>
                    </div>
                    <p
                      className={classNames(
                        "col-start-2 text-sm font-semibold tabular sm:shrink-0",
                        isPaid ? "text-ink-400" : "text-ink-900",
                      )}
                    >
                      {formatMoney(item.amount)}
                    </p>
                    <div className="hidden w-28 shrink-0 justify-end sm:flex">{entryStatusPill(status)}</div>
                    <button
                      type="button"
                      onClick={() => toggleExpand(item)}
                      aria-label={`Ajustes de ${item.description}`}
                      aria-expanded={expanded}
                      className="col-start-3 row-start-1 flex size-8 shrink-0 items-center justify-center rounded-control border border-ink-200 text-ink-500 transition-colors hover:bg-surface-muted hover:text-ink-800"
                    >
                      <ChevronDown
                        className={classNames("size-4 transition-transform", expanded && "rotate-180")}
                        aria-hidden="true"
                      />
                    </button>
                  </div>

                  {expanded ? (
                    <div className="mb-1 ml-3 mr-1 rounded-control border border-ink-100 bg-surface-muted/60 p-3">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                        <label className="text-xs font-medium text-ink-600">
                          Valor neste mês
                          <Input
                            type="number"
                            step="0.01"
                            min="0"
                            aria-label={`Valor de ${item.description} neste mês`}
                            defaultValue={Number(item.amount).toFixed(2)}
                            className="mt-1 w-full text-right font-semibold tabular sm:w-40"
                            onBlur={(event) => {
                              const amount = Number(event.target.value);
                              if (
                                !Number.isNaN(amount) &&
                                Math.abs(amount - Number(item.amount)) >= 0.005
                              ) {
                                void updateOverride(item, amount);
                              }
                            }}
                          />
                        </label>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                          <span className="text-ink-500">vence {formatDayLabel(item.due_date)}</span>
                          {item.is_override ? (
                            <button
                              type="button"
                              className="font-medium text-ink-600 hover:text-ink-800"
                              onClick={async () => {
                                await deleteFixedCostOverride(item.fixed_cost_id, selectedMonth);
                                await onReload();
                              }}
                            >
                              Voltar ao valor base ({formatMoney(item.base_amount)})
                            </button>
                          ) : null}
                          {item.matched_transaction ? (
                            item.match_source === "manual" && item.fixed_cost_transaction_match_id ? (
                              <button
                                type="button"
                                className="font-medium text-danger-600 hover:text-danger-700"
                                onClick={async () => {
                                  await deleteFixedCostMatch(
                                    item.fixed_cost_transaction_match_id as number,
                                  );
                                  await onReload();
                                }}
                              >
                                Desvincular pagamento
                              </button>
                            ) : null
                          ) : (
                            <button
                              type="button"
                              className="font-medium text-primary-700 hover:text-primary-800"
                              onClick={() => void openPicker(item)}
                            >
                              Vincular pagamento
                            </button>
                          )}
                        </div>
                      </div>

                      {!loadingPicker && pickerAttempted && (
                        <div className="mt-3 flex gap-1.5">
                          {(["CREDIT", "BANK"] as const).map((f) => (
                            <button
                              key={f}
                              type="button"
                              onClick={() => { setPickerFilter(f); setPickerVisible(10); }}
                              className={classNames(
                                "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors",
                                pickerFilter === f
                                  ? "bg-primary-600 text-white"
                                  : "bg-ink-100 text-ink-600 hover:bg-ink-200",
                              )}
                            >
                              {f === "CREDIT" ? "Crédito" : "Débito"}
                            </button>
                          ))}
                        </div>
                      )}

                      {loadingPicker ? (
                        <p className="py-3 text-center text-xs text-ink-500">Buscando saídas do mês...</p>
                      ) : transactions.length ? (
                        <>
                          <div className="mt-2 max-h-64 space-y-1 overflow-y-auto">
                            {transactions.map((tx) => (
                              <div
                                key={tx.id}
                                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-control bg-surface p-3 sm:flex"
                              >
                                <span className="col-span-2 shrink-0 text-xs text-ink-500 sm:w-14">
                                  {formatDayLabel(tx.date)}
                                </span>
                                <div className="min-w-0 flex-1">
                                  <p className="truncate text-xs text-ink-800">{tx.description}</p>
                                  <p className="text-[11px] text-ink-400">
                                    {[tx.account_type, tx.account_name, tx.pluggy_category || tx.category]
                                      .filter(Boolean)
                                      .join(" · ")}
                                  </p>
                                </div>
                                <span className="shrink-0 text-xs font-semibold tabular text-ink-800">
                                  {formatMoney(Math.abs(Number(tx.amount)))}
                                </span>
                                <Button
                                  type="button"
                                  variant="primary"
                                  size="sm"
                                  onClick={() => void linkTransaction(item, tx)}
                                >
                                  Vincular
                                </Button>
                              </div>
                            ))}
                          </div>
                          {filteredCandidates.length > pickerVisible && (
                            <button
                              type="button"
                              onClick={() => setPickerVisible((v) => v + 10)}
                                  className="mt-2 min-h-9 w-full text-center text-xs font-medium text-primary-700 hover:text-primary-800"
                            >
                              Ver mais ({filteredCandidates.length - pickerVisible} restantes)
                            </button>
                          )}
                        </>
                      ) : pickerAttempted ? (
                        <p className="py-3 text-center text-xs text-ink-400">
                          {`Nenhuma transação de ${pickerFilter === "CREDIT" ? "crédito" : "débito"} encontrada.`}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}

function CostsBase({
  data,
  showInactive,
  setShowInactive,
  showAddCostForm,
  setShowAddCostForm,
  onReload,
}: {
  data: PlanningData;
  showInactive: boolean;
  setShowInactive: (value: boolean) => void;
  showAddCostForm: boolean;
  setShowAddCostForm: (value: boolean) => void;
  onReload: () => Promise<unknown>;
}) {
  const { showToast } = useToast();
  const [categoryForm, setCategoryForm] = useState({ name: "", color: "#64748b", sort_order: 0 });
  const [quickCost, setQuickCost] = useState({ category_id: 0, description: "", amount: "", due_day: "" });
  const [editingCost, setEditingCost] = useState<number | null>(null);
  const [costDraft, setCostDraft] = useState<Partial<FixedCost>>({});
  const [menuOpen, setMenuOpen] = useState<number | null>(null);
  const [catFilter, setCatFilter] = useState<string>("Todas");
  const customCount = data.categories.filter((cat) => !cat.is_default).length;
  const catMap = useMemo(
    () => new Map(data.categories.map((c) => [c.id, c])),
    [data.categories],
  );
  const getCostCategory = (cost: FixedCost) => catMap.get(Number(cost.category_id));
  const activeCosts = data.costs.filter((cost) => cost.active);
  const inactiveCosts = data.costs.filter((cost) => !cost.active);
  const activeTotal = activeCosts.reduce((sum, cost) => sum + Number(cost.amount || 0), 0);
  const catNames = ["Todas", ...Array.from(new Set(
    activeCosts.map((c) => catMap.get(Number(c.category_id))?.name).filter((n): n is string => Boolean(n)),
  ))];
  const filteredCosts = catFilter === "Todas"
    ? activeCosts
    : activeCosts.filter((c) => catMap.get(Number(c.category_id))?.name === catFilter);

  useEffect(() => {
    if (!quickCost.category_id && data.categories[0]) {
      setQuickCost((current) => ({ ...current, category_id: data.categories[0].id }));
    }
  }, [data.categories, quickCost.category_id]);

  useEffect(() => {
    if (showAddCostForm) {
      const form = document.getElementById("add-cost-form");
      form?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      form?.querySelector<HTMLSelectElement>("select")?.focus({ preventScroll: true });
    }
  }, [showAddCostForm]);

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
      setShowAddCostForm(false);
      await onReload();
      showToast("Custo fixo adicionado.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao adicionar custo.", "error");
    }
  };

  const costEditForm = (cost: FixedCost) => (
    <form
      className="grid grid-cols-1 gap-3 rounded-card bg-primary-50/40 px-5 py-5 sm:grid-cols-2 xl:grid-cols-[minmax(120px,.8fr)_minmax(160px,1.4fr)_minmax(100px,.7fr)_90px]"
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
      <FormField label="Categoria"><Select
        aria-label="Categoria"
        value={Number(costDraft.category_id ?? cost.category_id)}
        onChange={(event) => setCostDraft((c) => ({ ...c, category_id: Number(event.target.value) }))}
      >
        {data.categories.map((cat) => (
          <option key={cat.id} value={cat.id}>{cat.name}</option>
        ))}
      </Select></FormField>
      <FormField label="Descrição"><Input
        aria-label="Descrição"
        value={String(costDraft.description ?? cost.description)}
        onChange={(event) => setCostDraft((c) => ({ ...c, description: event.target.value }))}
      /></FormField>
      <FormField label="Valor (R$)"><Input
        aria-label="Valor"
        type="number"
        step="0.01"
        min="0.01"
        value={Number(costDraft.amount ?? cost.amount)}
        onChange={(event) => setCostDraft((c) => ({ ...c, amount: Number(event.target.value) }))}
      /></FormField>
      <FormField label="Dia de vencimento"><Input
        aria-label="Dia de vencimento"
        type="number"
        min="1"
        max="31"
        value={Number(costDraft.due_day ?? cost.due_day)}
        onChange={(event) => setCostDraft((c) => ({ ...c, due_day: Number(event.target.value) }))}
      /></FormField>
      <div className="flex flex-wrap gap-2 pt-1 sm:col-span-2 xl:col-span-4"><Button type="submit" variant="primary">Salvar alterações</Button><Button type="button" onClick={() => setEditingCost(null)}>Cancelar</Button></div>
    </form>
  );

  return (
    <section id="recurring-costs" className="scroll-mt-28 space-y-5 border-t border-ink-200 pt-7" onClick={() => setMenuOpen(null)} onKeyDown={(event) => { if (event.key === "Escape") setMenuOpen(null); }}>
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-primary-700">Base recorrente</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink-900">Compromissos recorrentes</h2>
          <p className="mt-1 text-sm text-ink-500">Valores e vencimentos que se repetem todos os meses.</p>
          {activeCosts.length > 0 ? (
            <p className="mt-1 text-sm text-ink-500">
              {activeCosts.length} custos ativos ·{" "}
              <span className="tabular font-semibold text-ink-700">{formatMoney(activeTotal)}</span> / mês
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          variant="primary"
          aria-expanded={showAddCostForm}
          aria-controls="add-cost-form"
          onClick={(e) => { e.stopPropagation(); setShowAddCostForm(!showAddCostForm); }}
        >
          <Plus className="size-4" aria-hidden="true" />
          Novo custo
        </Button>
      </div>

      {catNames.length > 1 || inactiveCosts.length > 0 ? (
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        {catNames.length > 1 ? (
        <div className="flex flex-wrap gap-1.5">
          {catNames.map((cat) => {
            const isActive = catFilter === cat;
            const catObj = cat === "Todas" ? undefined : data.categories.find((c) => c.name === cat);
            const color = catObj?.color || "#475569";
            return (
              <button
                key={cat}
                type="button"
                aria-pressed={isActive}
                onClick={(e) => { e.stopPropagation(); setCatFilter(cat); }}
                className={classNames(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                  isActive ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-surface text-ink-600 hover:border-ink-300",
                )}
              >
                {cat !== "Todas" && (
                  <span className="size-1.5 rounded-full" style={{ background: isActive ? "#fff" : color }} />
                )}
                {cat}
              </button>
            );
          })}
        </div>
        ) : <span />}
        {inactiveCosts.length > 0 ? (
        <button
          type="button"
          aria-pressed={showInactive}
          onClick={(e) => { e.stopPropagation(); setShowInactive(!showInactive); }}
          className={classNames(
            "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
            showInactive ? "border-ink-400 bg-ink-100 text-ink-700" : "border-ink-200 bg-surface text-ink-500 hover:border-ink-300",
          )}
        >
          <span className={classNames("size-1.5 rounded-full", showInactive ? "bg-ink-600" : "bg-ink-300")} />
          Mostrar inativos
        </button>
        ) : null}
      </div>
      ) : null}

      {showAddCostForm ? (
      <Card id="add-cost-form" className="scroll-mt-28 border-primary-200 bg-primary-50/30 p-5 sm:p-6">
        <h2 className="text-sm font-semibold text-ink-900">Adicionar custo fixo</h2>
        <p className="mt-0.5 text-xs text-ink-500">
          O valor se repete todos os meses. Ajustes pontuais ficam na agenda mensal.
        </p>
        {data.templates.length ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {data.templates.map((template) => (
              <Button
                key={template.label}
                type="button"
                size="sm"
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
        <form className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(120px,.8fr)_minmax(160px,1.4fr)_minmax(100px,.7fr)_90px]" onSubmit={addCost}>
          <FormField label="Categoria"><Select
            aria-label="Categoria"
            value={quickCost.category_id}
            onChange={(event) =>
              setQuickCost((current) => ({ ...current, category_id: Number(event.target.value) }))
            }
            required
          >
            {data.categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select></FormField>
          <FormField label="Descrição"><Input
            required
            placeholder="Descrição (ex.: Aluguel)"
            value={quickCost.description}
            onChange={(event) => setQuickCost((current) => ({ ...current, description: event.target.value }))}
          /></FormField>
          <FormField label="Valor (R$)"><Input
            required
            type="number"
            step="0.01"
            min="0.01"
            placeholder="Valor"
            value={quickCost.amount}
            onChange={(event) => setQuickCost((current) => ({ ...current, amount: event.target.value }))}
          /></FormField>
          <FormField label="Dia de vencimento"><Input
            required
            type="number"
            min="1"
            max="31"
            placeholder="Dia"
            aria-label="Dia de vencimento"
            value={quickCost.due_day}
            onChange={(event) => setQuickCost((current) => ({ ...current, due_day: event.target.value }))}
          /></FormField>
          <div className="flex flex-wrap gap-2 pt-1 sm:col-span-2 xl:col-span-4"><Button type="submit" variant="primary">
            <Plus className="size-4" aria-hidden="true" />
            Adicionar
          </Button>
          <Button type="button" onClick={() => setShowAddCostForm(false)}>
            Cancelar
          </Button></div>
        </form>

        <details className="mt-6 border-t border-ink-100 pt-5">
          <summary className="cursor-pointer text-sm font-semibold text-ink-700">
            Criar categoria personalizada
          </summary>
        <form className="mt-4" onSubmit={addCategory}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-ink-900">Nova categoria personalizada</h3>
              <p className="mt-0.5 text-xs text-ink-500">Para agrupar custos do seu jeito.</p>
            </div>
            <span className="text-xs text-ink-500">
              {customCount}/{MAX_CUSTOM_CATEGORIES} criadas
            </span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_120px_auto]">
            <FormField label="Nome da categoria"><Input
              required
              placeholder="Nome da categoria"
              value={categoryForm.name}
              onChange={(event) => setCategoryForm((current) => ({ ...current, name: event.target.value }))}
            /></FormField>
            <FormField label="Cor da categoria"><Input
              type="color"
              aria-label="Cor da categoria"
              className="h-10 cursor-pointer p-1"
              value={categoryForm.color}
              onChange={(event) => setCategoryForm((current) => ({ ...current, color: event.target.value }))}
            /></FormField>
            <Button type="submit" className="self-end" disabled={customCount >= MAX_CUSTOM_CATEGORIES}>
              Criar
            </Button>
          </div>
        </form>
        </details>
      </Card>
      ) : null}

      {!filteredCosts.length ? <Card className="p-5"><EmptyState title={activeCosts.length ? "Nenhum compromisso nesta categoria" : "Sua base recorrente está vazia"} detail={activeCosts.length ? "Selecione outra categoria para ver os compromissos." : "Adicione aluguel, assinaturas e outros custos que se repetem."} /></Card> : null}

      {/* Active flat list */}
      {filteredCosts.length > 0 ? (
        <div className="rounded-card border border-ink-200/70 bg-surface shadow-card">
          <div className="hidden items-center gap-4 border-b border-ink-100 bg-surface-muted/60 px-5 py-2.5 md:flex">
            <span className="flex-1 text-[11px] font-semibold uppercase tracking-wider text-ink-400">Compromisso</span>
            <span className="w-28 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Valor / mês</span>
            <span className="w-36 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Recorrência</span>
            <span className="w-24 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Ações</span>
          </div>
          {filteredCosts.map((cost) => {
            const cat = getCostCategory(cost);
            const color = categoryColor(cat?.name, cat?.color);
            if (editingCost === cost.id) return <div key={cost.id}>{costEditForm(cost)}</div>;
            return (
              <div
                key={cost.id}
                className="group relative grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 border-b border-ink-100 px-4 py-3.5 transition-colors last:border-0 hover:bg-surface-muted/40 md:flex md:items-center md:gap-4 md:px-5"
              >
                <CatAvatar category={cat?.name} color={color} size={42} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 break-words text-sm font-semibold text-ink-900">{cost.description}</p>
                    <span
                      className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold leading-none"
                      style={{ background: color + "1A", color }}
                    >
                      {cat?.name}
                    </span>
                  </div>
                </div>
                <p className="col-start-2 w-auto shrink-0 text-left text-sm font-bold tabular text-ink-900 md:w-28 md:text-right">
                  {formatMoney(cost.amount)}
                </p>
                <div className="col-start-2 flex w-auto shrink-0 justify-start md:w-36 md:justify-end">
                  {cost.due_day ? (
                    <span className="inline-flex items-center gap-1 rounded-control bg-surface-muted px-2.5 py-1 text-xs font-medium text-ink-600">
                      <Calendar className="size-3 text-ink-400" aria-hidden="true" />
                      Dia {cost.due_day}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-700">
                      <SlidersHorizontal className="size-3" aria-hidden="true" />
                      Personalizada
                    </span>
                  )}
                </div>
                <div className="col-start-2 flex w-auto shrink-0 items-center justify-start gap-1 md:w-24 md:justify-end md:gap-0.5">
                  <div className="relative">
                    <button
                      type="button"
                      title="Mais opções"
                      aria-label={`Opções de ${cost.description}`}
                      aria-expanded={menuOpen === cost.id}
                      className="flex size-9 items-center justify-center rounded-control text-ink-400 transition-all hover:bg-surface-muted hover:text-ink-600 md:size-7 md:text-ink-300 md:group-hover:text-ink-500"
                      onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === cost.id ? null : cost.id); }}
                    >
                      <MoreVertical className="size-4" aria-hidden="true" />
                    </button>
                    {menuOpen === cost.id && (
                      <div className="absolute left-0 top-10 z-30 min-w-[168px] md:left-auto md:right-0 md:top-8 overflow-hidden rounded-control border border-ink-200 bg-surface shadow-lift">
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-ink-700 hover:bg-surface-muted"
                          onClick={(e) => { e.stopPropagation(); setEditingCost(cost.id); setCostDraft(cost); setMenuOpen(null); }}
                        >
                          <Pencil className="size-3.5 text-ink-400" aria-hidden="true" />Editar
                        </button>
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-ink-700 hover:bg-surface-muted"
                          onClick={async (e) => { e.stopPropagation(); await updateFixedCost(cost.id, { active: false }); setMenuOpen(null); await onReload(); }}
                        >
                          <X className="size-3.5 text-ink-400" aria-hidden="true" />Desativar
                        </button>
                        <div className="my-0.5 border-t border-ink-100" />
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-danger-600 hover:bg-danger-50"
                          onClick={async (e) => {
                            e.stopPropagation();
                            if (!window.confirm(`Excluir "${cost.description}"?`)) return;
                            await deleteFixedCost(cost.id);
                            setMenuOpen(null);
                            await onReload();
                          }}
                        >
                          <AlertCircle className="size-3.5" aria-hidden="true" />Excluir
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Inactive section */}
      {showInactive && inactiveCosts.length > 0 && (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-400">Inativos</p>
            <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] font-semibold text-ink-500">
              {inactiveCosts.length}
            </span>
          </div>
          <div className="rounded-card border border-ink-200/70 bg-surface shadow-card">
            {inactiveCosts.map((cost, idx) => {
              const cat = getCostCategory(cost);
              const color = categoryColor(cat?.name, cat?.color);
              if (editingCost === cost.id) return <div key={cost.id}>{costEditForm(cost)}</div>;
              return (
                <div
                  key={cost.id}
                  className={classNames(
                    "grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-4 py-3.5 md:flex md:items-center md:gap-4 md:px-5",
                    idx < inactiveCosts.length - 1 ? "border-b border-ink-100" : "",
                  )}
                >
                  <div className="opacity-40">
                    <CatAvatar category={cat?.name} color={color} size={38} />
                  </div>
                  <div className="min-w-0 flex-1 opacity-50">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-ink-500 line-through">{cost.description}</p>
                      <span
                        className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold leading-none"
                        style={{ background: color + "1A", color }}
                      >
                        {cat?.name}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-ink-400">{cost.due_day ? `Dia ${cost.due_day}` : "Personalizada"}</p>
                  </div>
                  <p className="col-start-2 w-auto shrink-0 text-left text-sm font-semibold tabular text-ink-400 line-through opacity-50 md:w-28 md:text-right">
                    {formatMoney(cost.amount)}
                  </p>
                  <div className="col-start-2 flex w-auto shrink-0 justify-start md:w-36 md:justify-end">
                    <span className="rounded-full bg-ink-100 px-2.5 py-1 text-xs font-medium text-ink-500">Inativo</span>
                  </div>
                  <div className="col-start-2 flex w-auto shrink-0 justify-start md:w-24 md:justify-end">
                    <button
                      type="button"
                      className="rounded-control border border-ink-200 bg-surface px-2.5 py-1.5 text-xs font-semibold text-ink-600 transition-colors hover:bg-surface-muted"
                      onClick={async () => { await updateFixedCost(cost.id, { active: true }); await onReload(); }}
                    >
                      Reativar
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}


    </section>
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
  const [menuOpen, setMenuOpen] = useState<number | null>(null);
  const [showAddIncomeForm, setShowAddIncomeForm] = useState(false);

  useEffect(() => {
    if (!showAddIncomeForm) return;
    const form = document.getElementById("add-income-form");
    form?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "start",
    });
    form?.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
  }, [showAddIncomeForm]);

  const addEntry = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await createExpectedIncome({
        description: entryForm.description.trim(),
        amount: Number(entryForm.amount),
        expected_day: Number(entryForm.expected_day),
      });
      setEntryForm({ description: "", amount: "", expected_day: "" });
      setShowAddIncomeForm(false);
      await onReload();
      showToast("Entrada adicionada.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao adicionar entrada.", "error");
    }
  };

  const total = data.incomeMonth.total;
  const activeEntries = data.incomeEntries.filter((e) => e.active);
  const inactiveEntries = data.incomeEntries.filter((e) => !e.active);
  const shownEntries = showInactive ? data.incomeEntries : activeEntries;

  return (
    <div className="space-y-6" onClick={() => setMenuOpen(null)} onKeyDown={(event) => { if (event.key === "Escape") setMenuOpen(null); }}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-ink-900">Receitas do mês</h2>
          <p className="mt-1 text-sm text-ink-500">Sua base de entradas para {formatMonthLong(selectedMonth).toLowerCase()}.</p>
        </div>
        <Button
          type="button"
          variant="primary"
          aria-expanded={showAddIncomeForm}
          aria-controls="add-income-form"
          onClick={(e) => { e.stopPropagation(); setShowAddIncomeForm((current) => !current); }}
        >
          <Plus className="size-4" aria-hidden="true" />Nova entrada
        </Button>
      </div>
      <Card className="grid divide-y divide-ink-100 sm:grid-cols-[1.2fr_1fr_1fr] sm:divide-x sm:divide-y-0">
        <div className="p-5 sm:p-6">
          <p className="flex items-center gap-2 text-xs font-medium text-ink-500"><ArrowDownLeft className="size-4 text-primary-700" aria-hidden="true" />Receita prevista</p>
          <p className="mt-2 text-3xl font-semibold tabular tracking-tight text-ink-900">{formatMoney(total)}</p>
          <p className="mt-2 text-xs text-ink-500">Total esperado para o mês</p>
        </div>
        <div className="p-5 sm:p-6">
          <p className="text-xs font-medium text-ink-500">Já recebido</p>
          <p className="mt-2 text-2xl font-semibold tabular tracking-tight text-positive-700">{formatMoney(data.capacity.received_income_total || 0)}</p>
          <p className="mt-2 text-xs text-ink-500">Entradas realizadas no mês</p>
        </div>
        <div className="p-5 sm:p-6">
          <p className="text-xs font-medium text-ink-500">A receber</p>
          <p className="mt-2 text-2xl font-semibold tabular tracking-tight text-ink-900">{formatMoney(data.capacity.income_to_receive || 0)}</p>
          <p className="mt-2 text-xs text-ink-500">Receita ainda prevista</p>
        </div>
      </Card>

      {/* List header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink-900">
          Entradas recorrentes
          {data.incomeEntries.length > 0 ? (
            <span className="ml-2 text-xs font-normal text-ink-400">
              {pluralize(data.incomeEntries.length, "entrada", "entradas")}
            </span>
          ) : null}
        </h3>
        {inactiveEntries.length > 0 ? (
        <button
          type="button"
          aria-pressed={showInactive}
          onClick={(e) => { e.stopPropagation(); setShowInactive(!showInactive); }}
          className={classNames(
            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
            showInactive ? "border-ink-400 bg-ink-100 text-ink-700" : "border-ink-200 bg-surface text-ink-500 hover:border-ink-300",
          )}
        >
          <span className={classNames("size-1.5 rounded-full", showInactive ? "bg-ink-600" : "bg-ink-300")} />
          Mostrar inativas
        </button>
        ) : null}
      </div>

      {showAddIncomeForm ? (
      <Card id="add-income-form" className="border-primary-200 bg-primary-50/30 p-5 sm:p-6">
        <h2 className="text-sm font-semibold text-ink-900">Nova entrada recorrente</h2>
        <p className="mt-0.5 text-xs text-ink-500">A base que se repete todos os meses.</p>
        <form
          className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_160px_130px]"
          onSubmit={addEntry}
        >
          <FormField label="Descrição"><Input
            required
            placeholder="Descrição (ex.: Salário)"
            value={entryForm.description}
            onChange={(event) => setEntryForm((current) => ({ ...current, description: event.target.value }))}
          /></FormField>
          <FormField label="Valor (R$)"><Input
            required
            type="number"
            step="0.01"
            min="0.01"
            placeholder="Valor"
            value={entryForm.amount}
            onChange={(event) => setEntryForm((current) => ({ ...current, amount: event.target.value }))}
          /></FormField>
          <FormField label="Dia esperado"><Input
            required
            type="number"
            min="1"
            max="31"
            placeholder="Dia"
            aria-label="Dia esperado"
            value={entryForm.expected_day}
            onChange={(event) => setEntryForm((current) => ({ ...current, expected_day: event.target.value }))}
          /></FormField>
          <div className="flex flex-wrap gap-2 pt-1 sm:col-span-2 lg:col-span-3"><Button type="submit" variant="primary">
            Adicionar
          </Button>
          <Button type="button" onClick={() => setShowAddIncomeForm(false)}>
            Cancelar
          </Button></div>
        </form>
      </Card>
      ) : null}

      {/* Entries list */}
      {shownEntries.length > 0 ? (
        <div className="rounded-card border border-ink-200/70 bg-surface shadow-card">
          <div className="hidden items-center gap-4 border-b border-ink-100 bg-surface-muted/60 px-5 py-2.5 md:flex">
            <span className="flex-1 text-[11px] font-semibold uppercase tracking-wider text-ink-400">Entrada</span>
            <span className="w-28 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Valor</span>
            <span className="w-36 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Status</span>
            <span className="w-16 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-400">Ações</span>
          </div>
          {shownEntries.map((entry, idx) => {
            const inactive = !entry.active;
            const isLast = idx === shownEntries.length - 1;
            if (editingEntry === entry.id) {
              return (
                <div key={entry.id} className={classNames("px-5 py-3", !isLast ? "border-b border-ink-100" : "")}>
                  <form
                    className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_160px_130px]"
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
                    <FormField label="Descrição"><Input
                      aria-label="Descrição"
                      value={String(entryDraft.description ?? entry.description)}
                      onChange={(event) => setEntryDraft((c) => ({ ...c, description: event.target.value }))}
                    /></FormField>
                    <FormField label="Valor (R$)"><Input
                      aria-label="Valor"
                      type="number"
                      step="0.01"
                      value={Number(entryDraft.amount ?? entry.amount)}
                      onChange={(event) => setEntryDraft((c) => ({ ...c, amount: Number(event.target.value) }))}
                    /></FormField>
                    <FormField label="Dia esperado"><Input
                      aria-label="Dia esperado"
                      type="number"
                      value={Number(entryDraft.expected_day ?? entry.expected_day)}
                      onChange={(event) => setEntryDraft((c) => ({ ...c, expected_day: Number(event.target.value) }))}
                    /></FormField>
                    <div className="flex flex-wrap gap-2 pt-1 sm:col-span-2 lg:col-span-3"><Button type="submit" variant="primary">Salvar alterações</Button><Button type="button" onClick={() => setEditingEntry(null)}>Cancelar</Button></div>
                  </form>
                </div>
              );
            }
            return (
              <div
                key={entry.id}
                className={classNames(
                  "group grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-4 py-3.5 transition-colors hover:bg-surface-muted/40 md:flex md:items-center md:gap-4 md:px-5",
                  !isLast ? "border-b border-ink-100" : "",
                  inactive ? "opacity-60" : "",
                )}
              >
                <DayBadge day={entry.expected_day} tone="neutral" size={38} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className={classNames("min-w-0 break-words text-sm font-semibold", inactive ? "text-ink-400 line-through" : "text-ink-900")}>
                      {entry.description}
                    </p>
                    {inactive && (
                      <span className="rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold text-ink-500">Inativo</span>
                    )}
                  </div>
                </div>
                <p className={classNames("col-start-2 w-auto shrink-0 text-left text-sm font-bold tabular md:w-28 md:text-right", inactive ? "text-ink-400" : "text-positive-700")}>
                  {formatMoney(entry.amount)}
                </p>
                <div className="col-start-2 flex w-auto shrink-0 justify-start md:w-36 md:justify-end">
                  {inactive ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-ink-100 px-2.5 py-1 text-xs font-semibold text-ink-500 ring-1 ring-inset ring-ink-200">Inativo</span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-50 px-2.5 py-1 text-xs font-semibold text-warning-800 ring-1 ring-inset ring-warning-200">
                      <span className="size-1.5 rounded-full bg-warning-500" />
                      Aguardando
                    </span>
                  )}
                </div>
                <div className="col-start-2 flex w-auto shrink-0 items-center justify-start gap-1 md:w-16 md:justify-end md:gap-0.5">
                  <div className="relative">
                    <button
                      type="button"
                      title="Mais opções"
                      aria-label={`Opções de ${entry.description}`}
                      aria-expanded={menuOpen === entry.id}
                      className="flex size-9 items-center justify-center rounded-control text-ink-400 transition-all hover:bg-surface-muted hover:text-ink-600 md:size-7 md:text-ink-300 md:group-hover:text-ink-500"
                      onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === entry.id ? null : entry.id); }}
                    >
                      <MoreVertical className="size-4" aria-hidden="true" />
                    </button>
                    {menuOpen === entry.id && (
                      <div className="absolute left-0 top-10 z-30 min-w-[168px] md:left-auto md:right-0 md:top-8 overflow-hidden rounded-control border border-ink-200 bg-surface shadow-lift">
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-ink-700 hover:bg-surface-muted"
                          onClick={(e) => { e.stopPropagation(); setEditingEntry(entry.id); setEntryDraft(entry); setMenuOpen(null); }}
                        >
                          <Pencil className="size-3.5 text-ink-400" aria-hidden="true" />Editar
                        </button>
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-ink-700 hover:bg-surface-muted"
                          onClick={async (e) => { e.stopPropagation(); await updateExpectedIncome(entry.id, { active: !entry.active }); setMenuOpen(null); await onReload(); }}
                        >
                          <X className="size-3.5 text-ink-400" aria-hidden="true" />{entry.active ? "Desativar" : "Reativar"}
                        </button>
                        <div className="my-0.5 border-t border-ink-100" />
                        <button
                          type="button"
                          className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-danger-600 hover:bg-danger-50"
                          onClick={async (e) => {
                            e.stopPropagation();
                            if (!window.confirm(`Excluir "${entry.description}"?`)) return;
                            await deleteExpectedIncome(entry.id);
                            setMenuOpen(null);
                            await onReload();
                          }}
                        >
                          <AlertCircle className="size-3.5" aria-hidden="true" />Excluir
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <Card className="p-5 sm:p-6">
          <EmptyState
            title="Nenhuma entrada cadastrada."
            detail="Cadastre salário e outras receitas previstas."
          />
        </Card>
      )}


    </div>
  );
}

export function PlanejamentoPage() {
  const [selectedMonth, setSelectedMonth] = useState(getDefaultPlanningMonth());
  const [activeTab, setActiveTab] = useState<PlanningTab>(() => selectedTabFromLocation());
  const [showInactiveCosts, setShowInactiveCosts] = useState(false);
  const [showInactiveIncome, setShowInactiveIncome] = useState(false);
  const [showAddCostForm, setShowAddCostForm] = useState(false);
  const months = useMemo(() => monthWindow(getDefaultPlanningMonth(), PLANNING_MONTH_WINDOW_SIZE + 1), []);
  const planningLoader = useCallback(
    () => loadPlanningData(selectedMonth),
    [selectedMonth],
  );
  const { data, loading, error, run } = useAsync(planningLoader);
  const currentData = data?.selectedMonth === selectedMonth ? data : null;

  useEffect(() => {
    const url = new URL(window.location.href);
    if (activeTab === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", activeTab);
    window.history.replaceState({}, "", url);
  }, [activeTab]);

  return (
    <>
      <Topbar
        subtitle={`${formatMonthLong(selectedMonth)} · planejamento mensal`}
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Atualizar planejamento"
            title="Atualizar"
            onClick={() => void run()}
            loading={loading}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer>
        <div className="space-y-6" aria-busy={loading}>
          <div className="min-w-0 space-y-4">
            <div>
              <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                <h2 className="text-lg font-semibold tracking-tight text-ink-900">{formatMonthLong(selectedMonth)}</h2>
                <p className="text-xs text-ink-500">Selecione o mês que você quer planejar</p>
              </div>
              <MonthStrip months={months} value={selectedMonth} onChange={setSelectedMonth} />
            </div>
            <Tabs<PlanningTab>
              value={activeTab}
              onChange={setActiveTab}
              items={[
                { key: "overview", label: "Plano do mês" },
                { key: "custos", label: "Custos fixos" },
                { key: "variaveis", label: "Gastos variáveis" },
                { key: "receita", label: "Receita" },
              ]}
            />
          </div>

          {loading && !currentData ? <LoadingState label={`Carregando ${formatMonthLong(selectedMonth).toLowerCase()}...`} /> : null}
          {error && !currentData ? <ErrorState message={error} onRetry={() => void run()} /> : null}
          {error && currentData ? (
            <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
          ) : null}
          {currentData ? (
            <>
              {activeTab === "overview" ? <MonthPlanPanel capacity={currentData.capacity} onOpenTab={setActiveTab} /> : null}

              {activeTab === "custos" ? (
                <div className="space-y-6">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-primary-700">Neste mês</p>
                      <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink-900">Agenda de pagamentos</h2>
                      <p className="mt-1 text-sm text-ink-500">Acompanhe vencimentos e ajuste os valores deste mês.</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => document.getElementById("recurring-costs")?.scrollIntoView({ behavior: "smooth", block: "start" })}>Base recorrente<ArrowUpRight className="size-3.5" aria-hidden="true" /></Button>
                      <Button variant="primary" onClick={() => { setShowAddCostForm(true); document.getElementById("add-cost-form")?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }}><Plus className="size-4" aria-hidden="true" />Novo custo</Button>
                    </div>
                  </div>
                  <FixedCostsAgenda
                    fixed={currentData.fixedMonth}
                    expectedIncome={currentData.capacity.expected_income_total || 0}
                    selectedMonth={selectedMonth}
                    onReload={run}
                  />

                  <CostsBase
                    data={currentData}
                    showInactive={showInactiveCosts}
                    setShowInactive={setShowInactiveCosts}
                    showAddCostForm={showAddCostForm}
                    setShowAddCostForm={setShowAddCostForm}
                    onReload={run}
                  />
                </div>
              ) : null}

              {activeTab === "variaveis" ? (
                <VariableBudgetsPanel
                  capacity={currentData.capacity}
                  selectedMonth={selectedMonth}
                  onReload={run}
                />
              ) : null}

              {activeTab === "receita" ? (
                <IncomePlanning
                  data={currentData}
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
