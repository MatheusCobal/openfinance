import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  CreditCard,
  Search,
  RefreshCw,
  Tags,
} from "lucide-react";
import {
  getCashflow,
  getClassificationOptions,
  getInvoiceHistory,
  resetTransactionClassification,
  updateTransactionClassification,
} from "../api/historico";
import { BarChart } from "../components/charts/BarChart";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ChartCard } from "../components/ui/ChartCard";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, StaleDataWarning } from "../components/ui/ErrorState";
import { FormField } from "../components/ui/FormField";
import { LoadingState } from "../components/ui/LoadingState";
import { Input } from "../components/ui/Input";
import { MetricCard } from "../components/ui/MetricCard";
import { Modal } from "../components/ui/Modal";
import { Select } from "../components/ui/Select";
import { Table } from "../components/ui/Table";
import { Tabs } from "../components/ui/Tabs";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { CHART_COLORS } from "../lib/chartTheme";
import { categoryColor } from "../lib/categories";
import { formatDayLabel, formatMonthCompact, formatMonthLong } from "../lib/dates";
import {
  cashflowTypeLabel,
  pluralCompras,
} from "../lib/labels";
import { formatMoney } from "../lib/money";
import type { ClassificationOptions, Transaction } from "../types/common";
import type {
  CashflowSummary,
  InvoiceHistoryCard,
  InvoiceHistoryMonth,
  InvoiceHistorySummary,
} from "../types/historico";

type HistoryTab = "invoices" | "categories" | "cashflow";

async function loadHistory() {
  const [invoices, cashflow] = await Promise.allSettled([
    getInvoiceHistory(12),
    getCashflow(12),
  ]);
  const failureMessage = (reason: unknown, fallback: string) => reason instanceof Error ? reason.message : fallback;
  if (invoices.status === "rejected" && cashflow.status === "rejected") {
    throw new Error(`Faturas: ${failureMessage(invoices.reason, "Falha ao carregar")} Entradas e saídas: ${failureMessage(cashflow.reason, "Falha ao carregar")}`);
  }
  return {
    invoices: invoices.status === "fulfilled" ? invoices.value : null,
    cashflow: cashflow.status === "fulfilled" ? cashflow.value : null,
    partialError: invoices.status === "rejected" || cashflow.status === "rejected",
    invoicesError: invoices.status === "rejected" ? failureMessage(invoices.reason, "Falha ao carregar faturas e categorias.") : null,
    cashflowError: cashflow.status === "rejected" ? failureMessage(cashflow.reason, "Falha ao carregar entradas e saídas.") : null,
  };
}

function invoiceDisplayTotal(item?: Partial<InvoiceHistoryMonth | InvoiceHistorySummary> | null) {
  return Number(item?.invoice_display_total ?? item?.total ?? 0);
}

function classifiedPurchaseTotal(item?: Partial<InvoiceHistoryMonth | InvoiceHistorySummary> | null) {
  return Number(item?.classified_purchase_total ?? item?.total ?? 0);
}

function hasInvoiceMonthData(item: InvoiceHistoryMonth) {
  return invoiceDisplayTotal(item) > 0 || Number(item.count || 0) > 0;
}

function invoiceCardLabel(card: InvoiceHistoryCard) {
  const candidates = [card.institution_name, card.account_name].filter(Boolean) as string[];
  const normalized = candidates
    .join(" ")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase();
  if (normalized.includes("ITAU")) return "ITAÚ";
  if (normalized.includes("CAIXA")) return "CAIXA";
  return (candidates[0] || "Cartão").toLocaleUpperCase("pt-BR");
}

function InvoiceCardDetails({ month }: { month: InvoiceHistoryMonth; }) {
  const cards = month.cards || [];
  return (
    <Card className="h-full overflow-hidden" elevation="flat">
      <div className="flex items-center gap-3 border-b border-ink-100 px-5 py-5">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-control bg-primary-50 text-primary-700">
          <CreditCard className="size-5" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-ink-900">Cartões no mês</h2>
          <p className="mt-1 text-xs text-ink-500">{formatMonthLong(month.month)}</p>
        </div>
      </div>
      {cards.length ? (
        <div className="divide-y divide-ink-100 px-5">
          {cards.map((card) => {
            const cardMeta = [
              card.card_brand,
              card.card_last_four ? `final ${card.card_last_four}` : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <div
                key={card.account_id}
                className="flex flex-wrap items-center justify-between gap-3 py-5"
              >
                <div className="min-w-0">
                  <p className="text-xs font-bold tracking-wide text-ink-900">{invoiceCardLabel(card)}</p>
                  {cardMeta ? <p className="mt-0.5 text-xs text-ink-500">{cardMeta}</p> : null}
                </div>
                <p className="shrink-0 text-base font-bold tabular text-ink-900">
                  {formatMoney(card.total)}
                </p>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="px-5 py-4 text-sm text-ink-500">
          Não há dados suficientes para separar esta fatura por cartão.
        </p>
      )}
    </Card>
  );
}

function summarizeCashflow(data: CashflowSummary | null) {
  const months = (data?.months || [])
    .map((month) => {
      const transactions = month.transactions || [];
      return {
        month: month.month,
        entradas: month.income || 0,
        saidas: month.outflow || 0,
        net: month.net || 0,
        entradas_count: month.income_count || 0,
        saidas_count: month.outflow_count || 0,
        entradas_txs: transactions.filter((tx) => Number(tx.amount) > 0),
        saidas_txs: transactions.filter((tx) => Number(tx.amount) < 0),
      };
    })
    .filter(
      (month) =>
        month.entradas_count > 0 || month.saidas_count > 0 || month.entradas > 0 || month.saidas > 0,
    );
  return {
    months,
    total_entradas: data?.summary?.income || 0,
    total_saidas: data?.summary?.outflow || 0,
    total_entradas_count: months.reduce((sum, month) => sum + month.entradas_count, 0),
    total_saidas_count: months.reduce((sum, month) => sum + month.saidas_count, 0),
    net: data?.summary?.net || 0,
  };
}

function transactionMeta(tx: Transaction): string {
  const parts = [formatDayLabel(tx.date)];
  if (tx.account_name) parts.push(tx.account_name);
  const displayCategory =
    tx.effective_category || tx.resolved_category || tx.credit_category || tx.internal_category;
  if (displayCategory) parts.push(displayCategory);
  const flow = cashflowTypeLabel(tx.cashflow_type);
  if (flow) parts.push(flow);
  return parts.join(" · ");
}

function TransactionRows({
  transactions,
  onEdit,
}: {
  transactions: Transaction[];
  onEdit: (tx: Transaction) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = transactions.filter((tx) =>
    `${tx.description} ${transactionMeta(tx)}`.toLocaleLowerCase("pt-BR").includes(search.toLocaleLowerCase("pt-BR")),
  );
  if (!transactions.length)
    return <p className="px-5 py-8 text-center text-sm text-ink-500">Não há transações detalhadas disponíveis para esta seleção.</p>;
  return (
    <>
      <div className="sticky top-0 z-10 border-b border-ink-100 bg-surface px-5 py-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3 size-4 text-ink-400" aria-hidden="true" />
          <Input className="pl-10" type="search" aria-label="Buscar transações" placeholder="Buscar descrição, conta ou categoria" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>
      <ul className="divide-y divide-ink-100">
        {filtered.map((tx) => (
          <li key={tx.id} className="flex items-start justify-between gap-4 px-5 py-4 transition-colors hover:bg-surface-muted">
            <div className="min-w-0 flex-1">
              <p className="break-words text-sm font-semibold text-ink-900">{tx.description}</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-500">{transactionMeta(tx)}</p>
              <button
                type="button"
                className="mt-1.5 min-h-8 rounded-control text-xs font-semibold text-primary-700 hover:text-primary-800"
                onClick={() => onEdit(tx)}
              >
                Editar classificação
              </button>
            </div>
            <p className="shrink-0 text-sm font-semibold tabular text-ink-900">
              {formatMoney(Math.abs(Number(tx.amount)))}
            </p>
          </li>
        ))}
      </ul>
      {!filtered.length ? <p className="px-5 py-10 text-center text-sm text-ink-500">Nenhuma transação corresponde à busca.</p> : null}
    </>
  );
}

function ClassificationEditor({
  tx,
  options,
  optionsLoading,
  optionsError,
  onRetryOptions,
  onClose,
  onSaved,
}: {
  tx: Transaction | null;
  options: ClassificationOptions | null;
  optionsLoading: boolean;
  optionsError: string | null;
  onRetryOptions: () => void;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { showToast } = useToast();
  const [category, setCategory] = useState("");
  const [cashflow, setCashflow] = useState("");
  const [ignored, setIgnored] = useState(false);
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);

  useEffect(() => {
    setCategory(tx?.internal_category || options?.internal_categories?.[0] || "");
    setCashflow(tx?.cashflow_type || options?.cashflow_types?.[0] || "");
    setIgnored(Boolean(tx?.ignored_from_totals));
  }, [options, tx]);

  const save = async () => {
    if (!tx || busy || !options || !category || !cashflow) return;
    setBusy("save");
    try {
      await updateTransactionClassification(tx.id, {
        internal_category: category,
        cashflow_type: cashflow,
        ignored_from_totals: ignored,
      });
      showToast("Classificação salva.", "success");
      onSaved();
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao salvar classificação.", "error");
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    if (!tx || busy) return;
    setBusy("reset");
    try {
      await resetTransactionClassification(tx.id);
      showToast("Ajuste manual removido. A classificação automática voltou a valer.", "success");
      onSaved();
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao remover ajuste.", "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open={!!tx} title="Editar classificação" subtitle={tx?.description} onClose={() => { if (!busy) onClose(); }}>
      <div className="space-y-5 p-5 sm:p-6">
        {tx ? <div className="flex flex-wrap justify-between gap-2 rounded-control bg-surface-muted px-4 py-3 text-sm"><span className="text-ink-500">{formatDayLabel(tx.date)} · {tx.account_name || "Transação"}</span><strong className="tabular text-ink-900">{formatMoney(Math.abs(Number(tx.amount)))}</strong></div> : null}
        {optionsLoading ? <LoadingState label="Carregando opções de classificação..." /> : null}
        {optionsError ? <ErrorState message={optionsError} onRetry={onRetryOptions} /> : null}
        <fieldset disabled={!!busy || !options} className="space-y-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="Categoria">
              <Select value={category} onChange={(event) => setCategory(event.target.value)}>
                {(options?.internal_categories || []).map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="Tipo de movimentação">
              <Select value={cashflow} onChange={(event) => setCashflow(event.target.value)}>
                {(options?.cashflow_types || []).map((item) => (
                  <option key={item} value={item}>
                    {cashflowTypeLabel(item) || item}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
          <label className="flex cursor-pointer items-center gap-3 rounded-control border border-ink-200 p-4 text-sm text-ink-600">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-primary-600 focus:ring-primary-200"
              checked={ignored}
              onChange={(event) => setIgnored(event.target.checked)}
            />
            Não contar nos totais do mês
          </label>
        </fieldset>
        <div className="flex flex-wrap justify-between gap-3 border-t border-ink-100 pt-5">
          <Button type="button" variant="ghost" className="text-danger-700" onClick={reset} disabled={!!busy} loading={busy === "reset"}>
            Remover ajuste manual
          </Button>
          <div className="flex gap-2">
            <Button type="button" onClick={onClose} disabled={!!busy}>
              Cancelar
            </Button>
            <Button type="button" variant="primary" onClick={save} loading={busy === "save"} disabled={!!busy || !options || !category || !cashflow}>
              Salvar
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function InvoiceTab({ data }: { data: InvoiceHistorySummary; }) {
  const monthsWithData = useMemo(() => data.months.filter(hasInvoiceMonthData), [data.months]);
  const [selectedMonth, setSelectedMonth] = useState(() => {
    const latest = [...monthsWithData].pop() || data.months[data.months.length - 1];
    return latest?.month || "";
  });

  useEffect(() => {
    if (selectedMonth && data.months.some((item) => item.month === selectedMonth)) return;
    const latest = [...monthsWithData].pop() || data.months[data.months.length - 1];
    setSelectedMonth(latest?.month || "");
  }, [data.months, monthsWithData, selectedMonth]);

  const active =
    data.months.find((item) => item.month === selectedMonth) || data.months[data.months.length - 1];
  const periodTotal = invoiceDisplayTotal(data);

  const barColors = data.months.map((item) =>
    item.month === active?.month ? CHART_COLORS.primarySelected : CHART_COLORS.primarySoft,
  );

  if (!monthsWithData.length) {
    return (
      <EmptyState
        icon={<BarChart3 className="size-5" aria-hidden="true" />}
        title="Nenhuma fatura de cartão encontrada."
        detail="Quando houver faturas fechadas ou compras de cartão classificadas, a análise aparece aqui."
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="cockpit-surface overflow-hidden rounded-card p-6 text-white sm:p-7" aria-label="Resumo das faturas históricas">
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-white/70">Faturas · últimos 12 meses</p>
            <p className="mt-3 text-3xl font-bold tracking-tight tabular sm:text-4xl">{formatMoney(periodTotal)}</p>
            <p className="mt-2 text-sm text-white/70">Total no período</p>
          </div>
          <div className="border-t border-white/15 pt-5 sm:border-l sm:border-t-0 sm:pl-7 sm:pt-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-white/70">Mês selecionado</p>
            <p className="mt-3 text-2xl font-semibold tracking-tight tabular sm:text-3xl">{formatMoney(invoiceDisplayTotal(active))}</p>
            <p className="mt-2 text-sm text-white/80">{formatMonthLong(active.month)}</p>
          </div>
        </div>
      </section>

      <div className="grid items-stretch gap-5 xl:grid-cols-[minmax(0,1.8fr)_minmax(280px,1fr)]">
        <ChartCard title="Evolução das faturas" subtitle="Selecione uma barra ou um mês para ver os cartões."
          aside={<Badge tone="primary">{formatMonthCompact(active.month)}</Badge>}>
          <BarChart
            labels={data.months.map((month) => formatMonthCompact(month.month))}
            ariaLabel="Evolução mensal das faturas de cartão"
            datasets={[
              {
                label: "Fatura",
                data: data.months.map(invoiceDisplayTotal),
                backgroundColor: CHART_COLORS.primarySoft,
                backgroundColors: barColors,
              },
            ]}
            showValueLabels
            onBarClick={(index) => setSelectedMonth(data.months[index]?.month || selectedMonth)}
          />
        </ChartCard>
        <InvoiceCardDetails month={active} />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-5 py-5">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Mês a mês</h2>
            <p className="mt-1 text-xs text-ink-500">Compare os valores e explore cada fatura.</p>
          </div>
          <CalendarDays className="size-5 text-primary-600" aria-hidden="true" />
        </div>
        <ul className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[...data.months].reverse().map((item) => {
            const activeRow = item.month === active.month;
            return (
              <li key={item.month}>
                <button
                  type="button"
                  aria-pressed={activeRow}
                  className={`flex h-full w-full items-center justify-between gap-3 rounded-control border px-4 py-4 text-left transition-colors ${activeRow ? "border-primary-300 bg-primary-50 ring-1 ring-primary-200" : "border-ink-200/80 hover:border-primary-200 hover:bg-surface-muted"}`}
                  onClick={() => setSelectedMonth(item.month)}
                >
                  <span className="min-w-0">
                    <span className="block text-xs font-medium text-ink-500">{formatMonthLong(item.month)}</span>
                    <span className="mt-2 block text-base font-semibold tabular text-ink-900">
                      {hasInvoiceMonthData(item) ? formatMoney(invoiceDisplayTotal(item)) : "Sem fatura"}
                    </span>
                  </span>
                  <ArrowRight className={`size-4 shrink-0 ${activeRow ? "text-primary-700" : "text-ink-300"}`} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}

type CategoryMonthPoint = {
  month: string;
  total: number;
  count: number;
  transactions: Transaction[];
};

type CategoryPeriodSummary = {
  id: string;
  name: string;
  total: number;
  count: number;
  average_monthly: number;
  months: CategoryMonthPoint[];
  transactions: Transaction[];
};

function categoryName(category: { name?: string | null; resolved_category?: string | null; }) {
  return category.resolved_category || category.name || "Outros";
}

function summarizeCreditCategories(data: InvoiceHistorySummary): CategoryPeriodSummary[] {
  const months = data.months.slice(-12);
  const byCategory = new Map<string, CategoryPeriodSummary>();

  for (const month of months) {
    for (const category of month.categories || []) {
      const name = categoryName(category);
      const bucket =
        byCategory.get(name) ||
        {
          id: name,
          name,
          total: 0,
          count: 0,
          average_monthly: 0,
          months: months.map((item) => ({
            month: item.month,
            total: 0,
            count: 0,
            transactions: [],
          })),
          transactions: [],
        };
      const monthPoint = bucket.months.find((item) => item.month === month.month);
      const total = Number(category.total || 0);
      const count = Number(category.count || 0);
      const transactions = category.transactions || [];

      if (monthPoint) {
        monthPoint.total += total;
        monthPoint.count += count;
        monthPoint.transactions.push(...transactions);
      }
      bucket.total += total;
      bucket.count += count;
      bucket.transactions.push(...transactions);
      byCategory.set(name, bucket);
    }
  }

  return [...byCategory.values()]
    .map((category) => ({
      ...category,
      average_monthly: months.length ? category.total / months.length : 0,
      transactions: [...category.transactions].sort((a, b) => {
        const dateOrder = new Date(b.date).getTime() - new Date(a.date).getTime();
        if (dateOrder !== 0) return dateOrder;
        return String(a.description || "").localeCompare(String(b.description || ""), "pt-BR");
      }),
    }))
    .sort((a, b) => b.total - a.total || b.count - a.count || a.name.localeCompare(b.name, "pt-BR"));
}

function CategorySpendingTab({
  data,
  onOpenTransactions,
}: {
  data: InvoiceHistorySummary;
  onOpenTransactions: (title: string, subtitle: string, transactions: Transaction[]) => void;
}) {
  const categories = useMemo(() => summarizeCreditCategories(data), [data]);
  const periodMonths = data.months.slice(-12);
  const periodClassifiedTotal = data.months.reduce(
    (sum, item) => sum + classifiedPurchaseTotal(item),
    0,
  );
  const periodCount = categories.reduce((sum, category) => sum + category.count, 0);
  const allTransactions = categories.flatMap((category) => category.transactions);

  if (!categories.length) {
    return (
      <EmptyState
        icon={<Tags className="size-5" aria-hidden="true" />}
        title="Sem gastos por categoria ainda."
        detail="Quando houver compras de cartão classificadas, a leitura por categoria aparece aqui."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <MetricCard
          label="Gastos classificados"
          value={formatMoney(periodClassifiedTotal)}
          subtitle={`${pluralCompras(periodCount)} nos últimos 12 meses`}
          icon={<Tags className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="Média mensal"
          value={formatMoney(periodMonths.length ? periodClassifiedTotal / periodMonths.length : 0)}
          tone="primary"
          subtitle="Compras classificadas no período disponível"
        />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-ink-100 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Para onde o dinheiro foi</h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">Categorias ordenadas por gasto. Selecione uma barra para explorar o mês.</p>
          </div>
          <Button
            type="button"
            onClick={() =>
              onOpenTransactions(
                "Compras classificadas · últimos 12 meses",
                `${pluralCompras(periodCount)} · ${formatMoney(periodClassifiedTotal)}`,
                allTransactions,
              )
            }
          >
            Ver todas as compras <ArrowRight className="size-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="hidden grid-cols-[minmax(160px,1fr)_minmax(180px,1.1fr)_minmax(175px,.8fr)] gap-8 bg-surface-muted px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink-500 lg:grid">
          <span>Categoria e média mensal</span><span>Evolução no período</span><span className="text-right">Total e detalhes</span>
        </div>
        <div className="divide-y divide-ink-100">
          {categories.map((category) => {
            const color = categoryColor(category.name);
            const largestMonth = Math.max(...category.months.map((month) => month.total), 0);
            return (
              <article key={category.id} className="grid gap-4 p-5 transition-colors hover:bg-surface-muted/50 lg:grid-cols-[minmax(160px,1fr)_minmax(180px,1.1fr)_minmax(175px,.8fr)] lg:items-center lg:gap-8">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className="size-2.5 shrink-0 rounded-[4px]"
                      style={{ background: color }}
                      aria-hidden="true"
                    />
                    <h3 className="text-sm font-semibold text-ink-900">{category.name}</h3>
                  </div>
                  <p className="mt-2 text-xs text-ink-500">{pluralCompras(category.count)}</p>
                  <p className="mt-1 text-xs text-ink-500">Média mensal <span className="font-medium tabular text-ink-700">{formatMoney(category.average_monthly)}</span></p>
                </div>
                <div className="min-w-0">
                  <div
                    className="grid h-16 grid-cols-12 items-end gap-1.5"
                    aria-label={`Gastos mensais em ${category.name}`}
                  >
                    {category.months.map((month) => {
                      const height = largestMonth > 0 ? Math.max(8, (month.total / largestMonth) * 100) : 0;
                      return (
                        <button
                          key={month.month}
                          type="button"
                          className="group/bar relative flex h-full items-end rounded-sm"
                          aria-label={`${category.name}, ${formatMonthLong(month.month)}, ${formatMoney(month.total)}. Ver compras.`}
                          onClick={() => onOpenTransactions(`${category.name} · ${formatMonthLong(month.month)}`, `${pluralCompras(month.count)} · ${formatMoney(month.total)}`, month.transactions)}
                        >
                          <span
                            className="block w-full rounded-t-[4px] bg-ink-100 transition-opacity group-hover/bar:opacity-100"
                            style={{
                              height: month.total > 0 ? `${height}%` : "4px",
                              backgroundColor: month.total > 0 ? color : undefined,
                              opacity: month.total > 0 ? 0.92 : 1,
                            }}
                            aria-hidden="true"
                          />
                          <span
                            role="tooltip"
                            className="pointer-events-none absolute -top-9 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-control bg-ink-900 px-2 py-1 text-center text-[10px] font-semibold leading-tight text-white shadow-lift group-hover/bar:block group-focus-visible/bar:block"
                          >
                            {formatMonthCompact(month.month)}
                            <br />
                            {formatMoney(month.total)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-2 flex justify-between text-[11px] text-ink-400">
                    <span>{formatMonthCompact(category.months[0]?.month || "")}</span>
                    <span>{formatMonthCompact(category.months[category.months.length - 1]?.month || "")}</span>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3 border-t border-ink-100 pt-3 lg:flex-col lg:items-end lg:border-0 lg:pt-0">
                  <p className="text-lg font-bold tabular text-ink-900">{formatMoney(category.total)}</p>
                  <Button type="button" size="sm" variant="ghost" className="text-primary-700" onClick={() => onOpenTransactions(category.name, `Últimos 12 meses · ${pluralCompras(category.count)}`, category.transactions)}>
                    Ver compras <ArrowRight className="size-3.5" aria-hidden="true" />
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

function CashflowTab({
  data,
  onOpenTransactions,
}: {
  data: CashflowSummary;
  onOpenTransactions: (title: string, subtitle: string, transactions: Transaction[]) => void;
}) {
  const summary = useMemo(() => summarizeCashflow(data), [data]);

  if (!summary.months.length) {
    return (
      <EmptyState
        title="Sem entradas ou saídas nos últimos 12 meses."
        detail="Conecte uma conta bancária para acompanhar o fluxo de caixa."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MetricCard
          label="Total de entradas"
          value={formatMoney(summary.total_entradas)}
          subtitle="Recebimentos no período"
          tone="positive"
          icon={<ArrowDownRight className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="Total de saídas"
          value={formatMoney(summary.total_saidas)}
          subtitle="Movimentações de saída no período"
          tone="danger"
          icon={<ArrowUpRight className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="Resultado"
          value={`${summary.net >= 0 ? "+" : "−"}${formatMoney(Math.abs(summary.net))}`}
          subtitle="Entradas menos saídas"
          tone={summary.net >= 0 ? "positive" : "danger"}
        />
      </div>

      <ChartCard title="Entradas e saídas por mês" subtitle="Compare o movimento das contas. Selecione uma barra para ver as transações.">
        <BarChart
          labels={summary.months.map((month) => formatMonthCompact(month.month))}
          ariaLabel="Entradas e saídas bancárias por mês"
          datasets={[
            {
              label: "Entradas",
              data: summary.months.map((month) => month.entradas),
              backgroundColor: CHART_COLORS.positive,
            },
            {
              label: "Saídas",
              data: summary.months.map((month) => month.saidas),
              backgroundColor: CHART_COLORS.negative,
            },
          ]}
          onBarClick={(index, datasetIndex) => {
            const month = summary.months[index];
            if (!month) return;
            const showingIncome = datasetIndex === 0;
            const flowLabel = showingIncome ? "Entradas" : "Saídas";
            const flowTotal = showingIncome ? month.entradas : month.saidas;
            const transactions = showingIncome ? month.entradas_txs : month.saidas_txs;
            onOpenTransactions(
              `${flowLabel} · ${formatMonthLong(month.month)}`,
              `${flowLabel} ${formatMoney(flowTotal)}`,
              transactions,
            );
          }}
        />
      </ChartCard>

      <Card className="overflow-hidden">
        <div className="border-b border-ink-100 px-5 py-5">
          <h2 className="text-sm font-semibold text-ink-900">Mês a mês</h2>
          <p className="mt-1 text-xs text-ink-500">Abra um mês ou selecione o valor de entradas ou saídas.</p>
        </div>
        <Table>
          <thead>
            <tr className="bg-surface-muted text-xs uppercase tracking-wide text-ink-500">
              <th className="px-5 py-2.5 text-left font-medium">Mês</th>
              <th className="px-5 py-2.5 text-right font-medium">Entradas</th>
              <th className="px-5 py-2.5 text-right font-medium">Saídas</th>
              <th className="px-5 py-2.5 text-right font-medium">Resultado</th>
              <th className="px-5 py-2.5"><span className="sr-only">Detalhes</span></th>
            </tr>
          </thead>
          <tbody>
            {[...summary.months].reverse().map((month) => (
              <tr
                key={month.month}
                className="border-t border-ink-100 transition-colors hover:bg-surface-muted"
              >
                <td className="whitespace-nowrap px-5 py-3 text-sm font-medium text-ink-900">
                  {formatMonthLong(month.month)}
                </td>
                <td className="px-5 py-3 text-right text-sm tabular text-positive-700">
                  <button type="button" className="min-h-9 whitespace-nowrap rounded-control font-medium underline decoration-positive-200 underline-offset-4 hover:decoration-positive-700" aria-label={`Ver entradas de ${formatMonthLong(month.month)}, ${formatMoney(month.entradas)}`} onClick={() => onOpenTransactions(`Entradas · ${formatMonthLong(month.month)}`, `Entradas ${formatMoney(month.entradas)}`, month.entradas_txs)}>{formatMoney(month.entradas)}</button>
                </td>
                <td className="px-5 py-3 text-right text-sm tabular text-danger-700">
                  <button type="button" className="min-h-9 whitespace-nowrap rounded-control font-medium underline decoration-danger-200 underline-offset-4 hover:decoration-danger-700" aria-label={`Ver saídas de ${formatMonthLong(month.month)}, ${formatMoney(month.saidas)}`} onClick={() => onOpenTransactions(`Saídas · ${formatMonthLong(month.month)}`, `Saídas ${formatMoney(month.saidas)}`, month.saidas_txs)}>{formatMoney(month.saidas)}</button>
                </td>
                <td
                  className={`whitespace-nowrap px-5 py-3 text-right text-sm font-semibold tabular ${month.net >= 0 ? "text-positive-700" : "text-danger-700"
                    }`}
                >
                  {month.net >= 0 ? "+" : "−"}
                  {formatMoney(Math.abs(month.net))}
                </td>
                <td className="px-5 py-3 text-right"><Button type="button" size="sm" variant="ghost" className="whitespace-nowrap text-primary-700" aria-label={`Ver transações de ${formatMonthLong(month.month)}`} onClick={() => onOpenTransactions(`Entradas e saídas · ${formatMonthLong(month.month)}`, `Entradas ${formatMoney(month.entradas)} · Saídas ${formatMoney(month.saidas)}`, [...month.entradas_txs, ...month.saidas_txs])}>Ver mês <ArrowRight className="size-3.5" aria-hidden="true" /></Button></td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}

export function HistoricoPage() {
  const { showToast } = useToast();
  const { data, loading, error, run } = useAsync(loadHistory);
  const [activeTab, setActiveTab] = useState<HistoryTab>("invoices");
  const [modal, setModal] = useState<{
    title: string;
    subtitle: string;
    transactions: Transaction[];
  } | null>(null);
  const [editingTx, setEditingTx] = useState<Transaction | null>(null);
  const [options, setOptions] = useState<ClassificationOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  useEffect(() => {
    if (data?.partialError) showToast("Alguns dados do histórico não carregaram.", "error");
  }, [data?.partialError, showToast]);

  const loadOptions = async () => {
    setOptionsLoading(true);
    setOptionsError(null);
    try {
      const loaded = await getClassificationOptions();
      setOptions(loaded);
    } catch (err) {
      setOptionsError(err instanceof Error ? err.message : "Não foi possível carregar as opções de classificação.");
    } finally {
      setOptionsLoading(false);
    }
  };

  const openEditor = (tx: Transaction) => {
    setEditingTx(tx);
    if (!options && !optionsLoading) void loadOptions();
  };

  return (
    <>
      <Topbar
        subtitle="Faturas, categorias e movimento das contas"
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Atualizar histórico"
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
        <div className="space-y-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <Tabs<HistoryTab>
              value={activeTab}
              onChange={setActiveTab}
              items={[
                { key: "invoices", label: "Faturas do cartão" },
                { key: "categories", label: "Gastos por categoria" },
                { key: "cashflow", label: "Entradas e saídas" },
              ]}
            />
            <span className="inline-flex shrink-0 items-center gap-2 text-xs font-medium text-ink-500"><CalendarDays className="size-4 text-primary-600" aria-hidden="true" />Últimos 12 meses</span>
          </div>
          {loading && !data ? <LoadingState label="Carregando histórico..." /> : null}
          {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
          {error && data ? (
            <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
          ) : null}
          {data && activeTab !== "cashflow" && data.invoicesError ? <ErrorState message={`Faturas e categorias: ${data.invoicesError}`} onRetry={() => void run()} /> : null}
          {data && activeTab === "cashflow" && data.cashflowError ? <ErrorState message={`Entradas e saídas: ${data.cashflowError}`} onRetry={() => void run()} /> : null}
          {data && activeTab === "invoices" && data.invoices ? <InvoiceTab data={data.invoices} /> : null}
          {data && activeTab === "categories" && data.invoices ? (
            <CategorySpendingTab
              data={data.invoices}
              onOpenTransactions={(title, subtitle, transactions) =>
                setModal({ title, subtitle, transactions })
              }
            />
          ) : null}
          {data && activeTab === "cashflow" && data.cashflow ? (
            <CashflowTab
              data={data.cashflow}
              onOpenTransactions={(title, subtitle, transactions) =>
                setModal({ title, subtitle, transactions })
              }
            />
          ) : null}
        </div>
      </PageContainer>

      <Modal
        open={!!modal && !editingTx}
        title={modal?.title || ""}
        subtitle={modal?.subtitle}
        onClose={() => setModal(null)}
      >
        <TransactionRows key={modal?.title} transactions={modal?.transactions || []} onEdit={openEditor} />
      </Modal>
      <ClassificationEditor
        tx={editingTx}
        options={options}
        optionsLoading={optionsLoading}
        optionsError={optionsError}
        onRetryOptions={() => void loadOptions()}
        onClose={() => setEditingTx(null)}
        onSaved={() => { setModal(null); void run(); }}
      />
    </>
  );
}
