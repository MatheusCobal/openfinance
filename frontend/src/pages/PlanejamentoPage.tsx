import { useEffect, useMemo, useState } from "react";
import { CalendarClock, ChevronDown, CreditCard, Link2, Plus, RefreshCw, Trash2, Wallet } from "lucide-react";
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
  deleteVariableBudget,
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
import { CheckToggle } from "../components/ui/CheckToggle";
import { DayBadge } from "../components/ui/DayBadge";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { FinancialFlow } from "../components/ui/FinancialFlow";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
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
  monthDateRange,
  monthWindow,
} from "../lib/dates";
import {
  invoiceIncludedAmount,
  isFuturePlanningMonth,
  normalizePlanningOverview,
  tokenSet,
} from "../lib/planning";
import { categoryColor } from "../lib/categories";
import { invoiceSourceLabel, pluralize } from "../lib/labels";
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

/** "Plano do mês" — the decision panel at the top of the page. */
function MonthPlanPanel({ capacity }: { capacity: PlanningOverview }) {
  const isFuture = isFuturePlanningMonth(capacity);
  const free = asMoneyNumber(
    capacity.budget_available_to_spend ??
      capacity.discretionary_available ??
      capacity.available_to_spend ??
      capacity.remaining_after_plan ??
      capacity.remaining_after_invoice,
  );
  const income = capacity.expected_income_total || 0;
  const fixed = isFuture
    ? capacity.fixed_cost_planned_total || 0
    : capacity.fixed_cost_reserved_total || 0;
  const variable = isFuture
    ? capacity.variable_budget_total || 0
    : (capacity.variable_budget_consumed || 0) + (capacity.variable_budget_overage || 0);
  const card = invoiceIncludedAmount(capacity);
  const status =
    income <= 0
      ? { label: "Sem receita prevista", tone: "neutral" as const }
      : free < 0
        ? { label: "Estourado", tone: "danger" as const }
        : free <= 1000
          ? { label: "No limite", tone: "warning" as const }
          : { label: "Saudável", tone: "positive" as const };

  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <p className="text-sm font-medium text-ink-500">
              {isFuture ? "Sobra planejada" : "Disponível para gastar"}
            </p>
            <StatusPill label={status.label} tone={status.tone} />
            {isFuture ? <Badge tone="primary">Projeção</Badge> : null}
          </div>
          <p
            className={classNames(
              "mt-2 text-4xl font-bold tracking-tight tabular",
              free < 0 ? "text-danger-600" : "text-ink-900",
            )}
          >
            {formatMoney(free)}
          </p>
        </div>
        {capacity.days_remaining_in_month && capacity.daily_discretionary_remaining ? (
          <div className="rounded-control bg-surface-muted px-4 py-3 text-right">
            <p className="text-lg font-bold tabular text-ink-900">
              {formatMoney(capacity.daily_discretionary_remaining)}
              <span className="text-xs font-medium text-ink-500"> /dia</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-500">
              {pluralize(capacity.days_remaining_in_month, "dia restante", "dias restantes")}
            </p>
          </div>
        ) : null}
      </div>

      {income > 0 ? (
        <FinancialFlow
          className="mt-6"
          total={income}
          segments={[
            { key: "fixed", label: "Custos fixos", value: fixed, color: "#64748b" },
            { key: "invoice", label: "Fatura no cálculo", value: card, color: "#0ea5e9" },
            {
              key: "variable",
              label: isFuture ? "Meta variável" : "Variáveis usados",
              value: variable,
              color: "#a78bfa",
            },
          ]}
          remainder={{ label: isFuture ? "Sobra planejada" : "Disponível", value: free }}
        />
      ) : null}

      <div className="mt-6 grid grid-cols-1 gap-4 border-t border-ink-100 pt-5 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Receita esperada"
          value={formatMoney(income)}
          subtitle={`Já recebido ${formatMoney(capacity.received_income_total)}`}
          tone="positive"
        />
        <MetricCard
          label="Custos fixos"
          value={formatMoney(fixed)}
          subtitle={isFuture ? "Planejados para o mês" : "Reservados ou já pagos"}
        />
        <MetricCard
          label="Gastos variáveis"
          value={formatMoney(variable)}
          subtitle={`Meta de ${formatMoney(capacity.variable_budget_total)}`}
          tone="warning"
        />
        <MetricCard
          label="Fatura no cálculo"
          value={formatMoney(card)}
          subtitle={invoiceSourceLabel(
            capacity.credit_card_invoice?.source,
            capacity.credit_card_invoice?.source_label || "Regra consolidada do mês",
          )}
          tone="primary"
        />
      </div>
    </Card>
  );
}

function variableStatusTone(status: VariableBudgetItem["status"]): "positive" | "warning" | "danger" | "neutral" {
  if (status === "over") return "danger";
  if (status === "warning") return "warning";
  if (status === "no_target") return "neutral";
  return "positive";
}

function VariableBudgetGoalRow({
  item,
  selectedMonth,
  onSave,
  onRemove,
}: {
  item: VariableBudgetItem;
  selectedMonth: string;
  onSave: (category: string, amount: number) => Promise<void>;
  onRemove: (category: string) => Promise<void>;
}) {
  const overage = Math.max(item.spent - item.target, 0);
  const remaining = Math.max(item.target - item.spent, 0);
  const progress = Math.min(item.progress_percent ?? 0, 100);
  const tone = variableStatusTone(item.status);
  const barColor =
    tone === "danger" ? "bg-danger-500" : tone === "warning" ? "bg-amber-500" : "bg-primary-500";

  return (
    <li className="px-2 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: categoryColor(item.category) }}
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-ink-900">{item.category}</p>
            {overage > 0 ? (
              <Badge tone="danger">Excedeu {formatMoney(overage)}</Badge>
            ) : item.target > 0 ? (
              <Badge tone="neutral">Restam {formatMoney(remaining)}</Badge>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-500">
            {formatMoney(item.spent)} de {formatMoney(item.target)}
            {item.transaction_count > 0
              ? ` · ${pluralize(item.transaction_count, "compra", "compras")}`
              : " · sem gastos no mês"}
          </p>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
            <div
              className={classNames("h-full rounded-full transition-all", barColor)}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            step="0.01"
            min="0"
            aria-label={`Meta de ${item.category} em ${formatMonthShort(selectedMonth)}`}
            defaultValue={item.target.toFixed(2)}
            className="w-full text-right font-semibold tabular sm:w-28"
            onBlur={(event) => {
              const amount = Number(event.target.value);
              if (!Number.isNaN(amount) && amount >= 0 && Math.abs(amount - item.target) >= 0.005) {
                void onSave(item.category, amount);
              }
            }}
          />
          <button
            type="button"
            aria-label={`Remover meta de ${item.category}`}
            className="rounded-control p-2 text-ink-400 hover:bg-danger-50 hover:text-danger-600"
            onClick={() => void onRemove(item.category)}
          >
            <Trash2 className="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </li>
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
  const consumed = asMoneyNumber(capacity.variable_budget_consumed);
  const overage = asMoneyNumber(capacity.variable_budget_overage);
  const remaining = Math.max(target - consumed, 0);
  const hasTarget = target > 0 || budgeted.length > 0;

  const invoiceTotal = asMoneyNumber(
    capacity.card_invoice_current_open_total ?? capacity.planning_invoice?.amount,
  );
  const invoiceLabel =
    capacity.card_invoice_current_open_label ??
    capacity.planning_invoice?.source_label ??
    invoiceSourceLabel(capacity.card_invoice_current_open_source ?? capacity.planning_invoice?.source);
  const isFuture = capacity.planning_mode === "future_month";

  const budgetedCategories = new Set(budgeted.map((item) => item.category));
  const availableToAdd = eligible.filter((category) => !budgetedCategories.has(category));

  const [newCategory, setNewCategory] = useState("");
  const [newAmount, setNewAmount] = useState("");

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
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          label="Fatura do mês"
          value={isFuture ? "—" : formatMoney(invoiceTotal)}
          subtitle={isFuture ? "Mês futuro" : invoiceLabel}
          icon={<CreditCard className="size-5" aria-hidden="true" />}
          tone="neutral"
        />
        <MetricCard
          label="Meta variável do mês"
          value={hasTarget ? formatMoney(target) : "—"}
          subtitle={hasTarget ? "Soma das metas por categoria" : "Nenhuma meta definida"}
          icon={<Wallet className="size-5" aria-hidden="true" />}
          tone="primary"
        />
        <MetricCard
          label="Consumido"
          value={formatMoney(consumed)}
          subtitle="Compras na fatura vigente com meta"
          tone={consumed > target && hasTarget ? "danger" : "warning"}
        />
        <MetricCard
          label={overage > 0 ? "Excedente" : "Restante"}
          value={hasTarget ? formatMoney(overage > 0 ? overage : remaining) : "—"}
          subtitle={overage > 0 ? "Acima da meta variável" : "Ainda disponível na meta"}
          tone={overage > 0 ? "danger" : "positive"}
        />
        <MetricCard
          label="Metas por categoria"
          value={budgeted.length}
          subtitle="Categorias com meta configurada"
          icon={<CalendarClock className="size-5" aria-hidden="true" />}
        />
      </div>

      <Card className="p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Metas de gastos variáveis</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Metas de {formatMonthShort(capacity.year_month || selectedMonth)} sobre as compras de
              cartão classificadas. Valem apenas para este mês.
            </p>
          </div>
          <Badge tone={hasTarget ? "primary" : "neutral"}>
            {hasTarget ? `${budgeted.length} ativa(s)` : "Sem meta definida"}
          </Badge>
        </div>

        {budgeted.length > 0 ? (
          <ul className="mt-4 divide-y divide-ink-100">
            {budgeted.map((item) => (
              <VariableBudgetGoalRow
                key={item.category}
                item={item}
                selectedMonth={selectedMonth}
                onSave={saveGoal}
                onRemove={removeGoal}
              />
            ))}
          </ul>
        ) : (
          <div className="mt-4">
            <EmptyState
              icon={<CalendarClock className="size-5" aria-hidden="true" />}
              title="Nenhuma meta configurada para este mês."
              detail="Defina uma meta por categoria abaixo para acompanhar os gastos variáveis do cartão."
            />
          </div>
        )}

        <form
          onSubmit={addGoal}
          className="mt-5 flex flex-col gap-2 border-t border-ink-100 pt-5 sm:flex-row sm:items-end"
        >
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-ink-600">Categoria</span>
            <Select
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value)}
              disabled={availableToAdd.length === 0}
            >
              <option value="">Selecione uma categoria</option>
              {availableToAdd.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </Select>
          </label>
          <label className="sm:w-40">
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
          <Button type="submit" variant="primary" disabled={availableToAdd.length === 0}>
            <Plus className="size-4" aria-hidden="true" />
            Adicionar meta
          </Button>
        </form>
        {availableToAdd.length === 0 && budgeted.length > 0 ? (
          <p className="mt-2 text-xs text-ink-400">
            Todas as categorias variáveis já têm meta neste mês.
          </p>
        ) : null}
      </Card>

      {suggestions.length > 0 ? (
        <Card className="p-5 sm:p-6">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Gastos sem meta</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Categorias com compras no mês que ainda não têm meta definida.
            </p>
          </div>
          <ul className="mt-4 divide-y divide-ink-100">
            {suggestions.map((item) => (
              <li
                key={item.category}
                className="flex items-center justify-between gap-3 px-2 py-3"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: categoryColor(item.category) }}
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink-900">{item.category}</p>
                    <p className="text-xs text-ink-500">
                      {formatMoney(item.spent)} ·{" "}
                      {pluralize(item.transaction_count, "compra", "compras")}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setNewCategory(item.category);
                    setNewAmount(item.spent.toFixed(2));
                  }}
                >
                  Definir meta
                </Button>
              </li>
            ))}
          </ul>
        </Card>
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

/**
 * Concept A — "Agenda do mês". Dark cockpit hero (total + live paid bar +
 * month calendar) over a payment timeline with a "hoje" divider, live paid
 * toggles, and the month's payment-linking / override editing preserved.
 */
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
  const [localPaid, setLocalPaid] = useState<Set<number>>(
    () => new Set((fixed.entries || []).filter((e) => e.status === "paid").map((e) => e.fixed_cost_id)),
  );
  const [expandedFor, setExpandedFor] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loadingPicker, setLoadingPicker] = useState(false);

  useEffect(() => {
    setLocalPaid(
      new Set((fixed.entries || []).filter((e) => e.status === "paid").map((e) => e.fixed_cost_id)),
    );
  }, [fixed.entries]);

  useEffect(() => {
    const timer = window.setTimeout(() => setMounted(true), 120);
    return () => window.clearTimeout(timer);
  }, []);

  const togglePaid = (id: number) =>
    setLocalPaid((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Effective status: the local paid toggle overrides the API status.
  const effStatus = (entry: FixedCostMonthEntry): string => {
    if (localPaid.has(entry.fixed_cost_id)) return "paid";
    if (entry.status === "paid") return "scheduled";
    return entry.status || "scheduled";
  };

  const entries = useMemo(() => fixed.entries || [], [fixed.entries]);
  const total = Number(fixed.total || 0);
  const paidSum = entries
    .filter((e) => localPaid.has(e.fixed_cost_id))
    .reduce((sum, e) => sum + Number(e.amount || 0), 0);
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
        .map((scoredItem) => scoredItem.tx);
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
      setExpandedFor(null);
      setTransactions([]);
      await onReload();
      showToast(`"${item.description}" vinculado ao pagamento.`, "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao vincular pagamento.", "error");
    }
  };

  const toggleExpand = (item: FixedCostMonthEntry) => {
    setExpandedFor((current) => (current === item.fixed_cost_id ? null : item.fixed_cost_id));
    setTransactions([]);
  };

  if (!entries.length) {
    return (
      <EmptyState
        icon={<Wallet className="size-5" aria-hidden="true" />}
        title="Nenhum custo fixo ativo neste mês."
        detail="Cadastre os compromissos recorrentes na seção abaixo para acompanhar o plano."
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Hero — total, live paid bar and month calendar */}
      <section className="cockpit-surface ofx-rise relative overflow-hidden rounded-card p-6 text-white shadow-cockpit">
        <div className="cockpit-grid pointer-events-none absolute inset-0 opacity-40" aria-hidden="true" />
        <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2.5">
                <span className="inline-flex size-8 items-center justify-center rounded-control bg-white/10 ring-1 ring-inset ring-white/15">
                  <CalendarClock className="size-4 text-white/80" aria-hidden="true" />
                </span>
                <p className="text-sm font-medium text-white/70">
                  Custos fixos · {formatMonthLong(selectedMonth)}
                </p>
              </div>
              <p className="mt-4 text-4xl font-bold leading-none tracking-tight tabular sm:text-5xl">
                {formatMoney(total)}
              </p>
              {expectedIncome > 0 ? (
                <p className="mt-3 max-w-sm text-sm leading-relaxed text-white/55">
                  Compromissos que se repetem todo mês. Ocupam{" "}
                  <span className="font-semibold text-white/80">{percent(incomeShare)}</span> da sua
                  receita esperada de {formatMoney(expectedIncome)}.
                </p>
              ) : (
                <p className="mt-3 max-w-sm text-sm leading-relaxed text-white/55">
                  Compromissos que se repetem todo mês.
                </p>
              )}
            </div>
            <div className="mt-6">
              <div className="flex items-center justify-between text-xs">
                <span className="inline-flex items-center gap-1.5 font-medium text-white/70">
                  <span className="size-2 rounded-[3px] bg-positive-400" /> Pago {formatMoney(paidSum)}
                </span>
                <span className="inline-flex items-center gap-1.5 font-medium text-white/70">
                  <span className="size-2 rounded-[3px] bg-white/30" /> A pagar {formatMoney(pendingSum)}
                </span>
              </div>
              <div className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="bar-fill h-full rounded-l-full"
                  style={{
                    width: mounted && total > 0 ? `${(paidSum / total) * 100}%` : 0,
                    background: "rgba(52,211,153,0.95)",
                  }}
                />
              </div>
              <p className="mt-2 text-[11px] text-white/45">
                {localPaid.size} de {entries.length} contas quitadas · marque conforme paga
              </p>
            </div>
          </div>

          {/* Mini calendar */}
          <div className="rounded-card border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm">
            <div className="mb-2 grid grid-cols-7 gap-1 text-center text-[10px] font-semibold uppercase text-white/40">
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
                        ? "bg-primary-500 font-bold text-white"
                        : items.length
                          ? "bg-white/[0.06] text-white/80"
                          : "text-white/30",
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
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-white/10 pt-2.5 text-[10px] text-white/50">
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
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink-900">Linha do tempo de pagamentos</h3>
          <span className="text-xs text-ink-500">ordenado por vencimento</span>
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
                  <div className="group flex items-center gap-3 rounded-control px-3 py-2.5 transition-colors hover:bg-surface-muted">
                    <DayBadge day={item.due_day} tone={dayBadgeTone(status)} />
                    <CatAvatar category={item.category_name} color={color} size={38} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p
                          className={classNames(
                            "truncate text-sm font-semibold",
                            isPaid ? "text-ink-500" : "text-ink-900",
                          )}
                        >
                          {item.description}
                        </p>
                        <span className="text-xs text-ink-400">·</span>
                        <span className="shrink-0 text-xs font-medium" style={{ color }}>
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
                    </div>
                    <p
                      className={classNames(
                        "shrink-0 text-sm font-bold tabular",
                        isPaid ? "text-ink-400" : "text-ink-900",
                      )}
                    >
                      {formatMoney(item.amount)}
                    </p>
                    <div className="hidden w-28 shrink-0 justify-end sm:flex">{entryStatusPill(status)}</div>
                    <CheckToggle paid={isPaid} onToggle={() => togglePaid(item.fixed_cost_id)} />
                    <button
                      type="button"
                      onClick={() => toggleExpand(item)}
                      aria-label={`Ajustes de ${item.description}`}
                      aria-expanded={expanded}
                      className="flex size-7 shrink-0 items-center justify-center rounded-control text-ink-400 transition-colors hover:bg-surface-muted hover:text-ink-700"
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

                      {loadingPicker ? (
                        <p className="py-3 text-center text-xs text-ink-500">Buscando saídas do mês...</p>
                      ) : transactions.length ? (
                        <div className="mt-3 max-h-64 space-y-1 overflow-y-auto">
                          {transactions.map((tx) => (
                            <div
                              key={tx.id}
                              className="flex items-center gap-2 rounded-control bg-surface px-2 py-1.5"
                            >
                              <span className="w-14 shrink-0 text-xs text-ink-500">
                                {formatDayLabel(tx.date)}
                              </span>
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-xs text-ink-800">{tx.description}</p>
                                <p className="text-[11px] text-ink-400">
                                  {tx.pluggy_category || tx.category || ""}
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
  const activeTotal = data.costs
    .filter((cost) => cost.active)
    .reduce((sum, cost) => sum + Number(cost.amount || 0), 0);

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
      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Compromissos recorrentes</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              {pluralize(data.costs.length, "custo cadastrado", "custos cadastrados")} ·{" "}
              {formatMoney(activeTotal)} ativos por mês
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-ink-600">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-primary-600 focus:ring-primary-200"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            Mostrar inativos
          </label>
        </div>

        {grouped.length ? (
          <div className="space-y-3">
            {grouped.map(({ category, costs }) => (
              <Card key={category.id} elevation="flat" className="overflow-hidden">
                <div className="flex items-center justify-between gap-3 bg-surface-muted px-4 py-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: category.color }}
                      aria-hidden="true"
                    />
                    <h3 className="truncate text-sm font-semibold text-ink-900">{category.name}</h3>
                    {!category.is_default ? <Badge tone="primary">Personalizada</Badge> : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold tabular text-ink-700">
                      {formatMoney(
                        costs
                          .filter((cost) => cost.active)
                          .reduce((sum, cost) => sum + Number(cost.amount || 0), 0),
                      )}
                    </span>
                    {!category.is_default ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="size-8 px-0"
                        aria-label={`Excluir categoria ${category.name}`}
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
                <ul className="divide-y divide-ink-100">
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
                            aria-label="Categoria"
                            value={Number(costDraft.category_id ?? cost.category_id)}
                            onChange={(event) =>
                              setCostDraft((current) => ({
                                ...current,
                                category_id: Number(event.target.value),
                              }))
                            }
                          >
                            {data.categories.map((cat) => (
                              <option key={cat.id} value={cat.id}>
                                {cat.name}
                              </option>
                            ))}
                          </Select>
                          <Input
                            aria-label="Descrição"
                            value={String(costDraft.description ?? cost.description)}
                            onChange={(event) =>
                              setCostDraft((current) => ({ ...current, description: event.target.value }))
                            }
                          />
                          <Input
                            aria-label="Valor"
                            type="number"
                            step="0.01"
                            min="0.01"
                            value={Number(costDraft.amount ?? cost.amount)}
                            onChange={(event) =>
                              setCostDraft((current) => ({ ...current, amount: Number(event.target.value) }))
                            }
                          />
                          <Input
                            aria-label="Dia de vencimento"
                            type="number"
                            min="1"
                            max="31"
                            value={Number(costDraft.due_day ?? cost.due_day)}
                            onChange={(event) =>
                              setCostDraft((current) => ({ ...current, due_day: Number(event.target.value) }))
                            }
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
                          <span className="flex size-9 shrink-0 flex-col items-center justify-center rounded-control bg-surface-muted text-ink-700">
                            <span className="text-sm font-bold tabular leading-none">{cost.due_day}</span>
                            <span className="text-[9px] font-medium uppercase text-ink-400">dia</span>
                          </span>
                          <div className="min-w-0 flex-1">
                            <p
                              className={classNames(
                                "text-sm font-medium",
                                cost.active ? "text-ink-900" : "text-ink-400 line-through",
                              )}
                            >
                              {cost.description}
                            </p>
                            <p className="text-xs text-ink-400">todo dia {cost.due_day}</p>
                          </div>
                          <p
                            className={classNames(
                              "font-semibold tabular",
                              cost.active ? "text-ink-900" : "text-ink-400",
                            )}
                          >
                            {formatMoney(cost.amount)}
                          </p>
                          <div className="flex flex-wrap gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setEditingCost(cost.id);
                                setCostDraft(cost);
                              }}
                            >
                              Editar
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
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
                              size="sm"
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
          <EmptyState
            icon={<Wallet className="size-5" aria-hidden="true" />}
            title="Nenhum custo fixo cadastrado ainda."
            detail="Comece pelos compromissos que se repetem todo mês: aluguel, internet, assinaturas."
          />
        )}
      </Card>

      <Card className="p-5 sm:p-6">
        <h2 className="text-sm font-semibold text-ink-900">Adicionar custo fixo</h2>
        <p className="mt-0.5 text-xs text-ink-500">
          O valor vira a base de todos os meses; ajustes pontuais ficam na lista acima.
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
        <form className="mt-4 grid grid-cols-1 gap-2 lg:grid-cols-[170px_1fr_140px_90px_auto]" onSubmit={addCost}>
          <Select
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
          </Select>
          <Input
            required
            placeholder="Descrição (ex.: Aluguel)"
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
            aria-label="Dia de vencimento"
            value={quickCost.due_day}
            onChange={(event) => setQuickCost((current) => ({ ...current, due_day: event.target.value }))}
          />
          <Button type="submit" variant="primary">
            <Plus className="size-4" aria-hidden="true" />
            Adicionar
          </Button>
        </form>

        <form className="mt-6 border-t border-ink-100 pt-5" onSubmit={addCategory}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-ink-900">Nova categoria personalizada</h3>
              <p className="mt-0.5 text-xs text-ink-500">Para agrupar custos do seu jeito.</p>
            </div>
            <span className="text-xs text-ink-500">
              {customCount}/{MAX_CUSTOM_CATEGORIES} criadas
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
              aria-label="Cor da categoria"
              className="h-10 cursor-pointer p-1"
              value={categoryForm.color}
              onChange={(event) => setCategoryForm((current) => ({ ...current, color: event.target.value }))}
            />
            <Input
              type="number"
              aria-label="Ordem de exibição"
              value={categoryForm.sort_order}
              onChange={(event) =>
                setCategoryForm((current) => ({ ...current, sort_order: Number(event.target.value) }))
              }
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
      <Card className="border-positive-200 bg-positive-50/70 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-positive-700">
              Receita esperada em {formatMonthShort(selectedMonth)}
            </p>
            <p className="mt-1 text-3xl font-bold tracking-tight tabular text-positive-700">
              {formatMoney(data.incomeMonth.total)}
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-ink-600">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-positive-600 focus:ring-positive-200"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            Mostrar inativas
          </label>
        </div>
      </Card>

      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Entradas deste mês</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Ajustes aqui valem apenas para {formatMonthShort(selectedMonth)}.
            </p>
          </div>
        </div>
        {data.incomeMonth.entries.length ? (
          <ul className="divide-y divide-ink-100">
            {data.incomeMonth.entries.map((item) => (
              <li
                key={item.expected_income_id}
                className="flex flex-col gap-3 px-2 py-3 sm:flex-row sm:items-center"
              >
                <span className="flex size-9 shrink-0 flex-col items-center justify-center rounded-control bg-positive-100 text-positive-700">
                  <span className="text-sm font-bold tabular leading-none">{item.expected_day}</span>
                  <span className="text-[9px] font-medium uppercase text-positive-600/70">dia</span>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink-900">{item.description}</p>
                    {item.is_override ? <Badge tone="primary">Ajustado no mês</Badge> : null}
                  </div>
                  {item.is_override ? (
                    <button
                      type="button"
                      className="mt-1 text-xs font-medium text-ink-600 hover:text-ink-800"
                      onClick={async () => {
                        await deleteExpectedIncomeOverride(item.expected_income_id, selectedMonth);
                        await onReload();
                      }}
                    >
                      Voltar ao valor base ({formatMoney(item.base_amount)})
                    </button>
                  ) : null}
                </div>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  aria-label={`Valor de ${item.description} neste mês`}
                  defaultValue={Number(item.amount).toFixed(2)}
                  className="w-full text-right font-bold tabular text-positive-700 sm:w-32"
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

      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Entradas recorrentes</h2>
            <p className="mt-0.5 text-xs text-ink-500">A base que se repete todos os meses.</p>
          </div>
          <span className="text-xs text-ink-500">
            {pluralize(data.incomeEntries.length, "entrada", "entradas")}
          </span>
        </div>
        {data.incomeEntries.length ? (
          <ul className="mb-5 space-y-2">
            {data.incomeEntries.map((entry) => (
              <li key={entry.id} className="rounded-control border border-ink-200 bg-surface px-4 py-3">
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
                      aria-label="Descrição"
                      value={String(entryDraft.description ?? entry.description)}
                      onChange={(event) =>
                        setEntryDraft((current) => ({ ...current, description: event.target.value }))
                      }
                    />
                    <Input
                      aria-label="Valor"
                      type="number"
                      step="0.01"
                      value={Number(entryDraft.amount ?? entry.amount)}
                      onChange={(event) =>
                        setEntryDraft((current) => ({ ...current, amount: Number(event.target.value) }))
                      }
                    />
                    <Input
                      aria-label="Dia esperado"
                      type="number"
                      value={Number(entryDraft.expected_day ?? entry.expected_day)}
                      onChange={(event) =>
                        setEntryDraft((current) => ({ ...current, expected_day: Number(event.target.value) }))
                      }
                    />
                    <Button type="submit" variant="primary">
                      Salvar
                    </Button>
                    <Button type="button" onClick={() => setEditingEntry(null)}>
                      Cancelar
                    </Button>
                  </form>
                ) : (
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                    <span
                      className={classNames(
                        "flex size-9 shrink-0 flex-col items-center justify-center rounded-control",
                        entry.active ? "bg-positive-100 text-positive-700" : "bg-surface-muted text-ink-400",
                      )}
                    >
                      <span className="text-sm font-bold tabular leading-none">{entry.expected_day}</span>
                      <span className="text-[9px] font-medium uppercase opacity-70">dia</span>
                    </span>
                    <div className="min-w-0 flex-1">
                      <p
                        className={classNames(
                          "text-sm font-medium",
                          entry.active ? "text-ink-900" : "text-ink-400 line-through",
                        )}
                      >
                        {entry.description}
                      </p>
                      <p className="text-xs text-ink-400">recorrente · todo mês</p>
                    </div>
                    <p
                      className={classNames(
                        "font-bold tabular",
                        entry.active ? "text-positive-700" : "text-ink-400",
                      )}
                    >
                      {formatMoney(entry.amount)}
                    </p>
                    <div className="flex flex-wrap gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditingEntry(entry.id);
                          setEntryDraft(entry);
                        }}
                      >
                        Editar
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={async () => {
                          await updateExpectedIncome(entry.id, { active: !entry.active });
                          await onReload();
                        }}
                      >
                        {entry.active ? "Desativar" : "Reativar"}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={async () => {
                          if (!window.confirm(`Excluir "${entry.description}"?`)) return;
                          await deleteExpectedIncome(entry.id);
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
        ) : (
          <EmptyState
            title="Nenhuma entrada cadastrada."
            detail="Cadastre salário e outras receitas previstas."
          />
        )}
        <form
          className="grid grid-cols-1 gap-2 border-t border-ink-100 pt-5 sm:grid-cols-[1fr_140px_100px_auto]"
          onSubmit={addEntry}
        >
          <Input
            required
            placeholder="Descrição (ex.: Salário)"
            value={entryForm.description}
            onChange={(event) => setEntryForm((current) => ({ ...current, description: event.target.value }))}
          />
          <Input
            required
            type="number"
            step="0.01"
            min="0.01"
            placeholder="Valor"
            value={entryForm.amount}
            onChange={(event) => setEntryForm((current) => ({ ...current, amount: event.target.value }))}
          />
          <Input
            required
            type="number"
            min="1"
            max="31"
            placeholder="Dia"
            aria-label="Dia esperado"
            value={entryForm.expected_day}
            onChange={(event) => setEntryForm((current) => ({ ...current, expected_day: event.target.value }))}
          />
          <Button type="submit" variant="primary">
            Adicionar
          </Button>
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
  const months = useMemo(() => monthWindow(getDefaultPlanningMonth(), PLANNING_MONTH_WINDOW_SIZE), []);
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

  return (
    <>
      <Topbar
        subtitle={
          activeTab === "overview"
            ? `O plano de ${formatMonthLong(selectedMonth).toLowerCase()} em uma tela.`
            : activeTab === "custos"
              ? "Compromissos recorrentes e ajustes do mês."
              : activeTab === "variaveis"
                ? "Metas para os gastos do dia a dia."
                : "O que você espera receber em cada mês."
        }
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer narrow>
        <div className="space-y-5">
          <div className="flex flex-col gap-3">
            <Tabs<PlanningTab>
              value={activeTab}
              onChange={setActiveTab}
              items={[
                { key: "overview", label: "Plano do mês" },
                { key: "custos", label: "Custos fixos" },
                { key: "variaveis", label: "Metas variáveis" },
                { key: "receita", label: "Receita prevista" },
              ]}
            />
            <MonthStrip months={months} value={selectedMonth} onChange={setSelectedMonth} />
          </div>

          {loading && !data ? <LoadingState label="Carregando planejamento..." /> : null}
          {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
          {data ? (
            <>
              {activeTab === "overview" ? <MonthPlanPanel capacity={data.capacity} /> : null}

              {activeTab === "custos" ? (
                <div className="space-y-6">
                  <FixedCostsAgenda
                    fixed={data.fixedMonth}
                    expectedIncome={data.capacity.expected_income_total || 0}
                    selectedMonth={selectedMonth}
                    onReload={run}
                  />
                  <CostsBase
                    data={data}
                    showInactive={showInactiveCosts}
                    setShowInactive={setShowInactiveCosts}
                    onReload={run}
                  />
                </div>
              ) : null}

              {activeTab === "variaveis" ? (
                <VariableBudgetsPanel
                  capacity={data.capacity}
                  selectedMonth={selectedMonth}
                  onReload={run}
                />
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
