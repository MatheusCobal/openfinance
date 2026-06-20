import { useEffect, useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, BarChart3, RefreshCw, Tags } from "lucide-react";
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
  classificationSourceLabel,
  invoiceSourceLabel,
  pluralCompras,
  pluralize,
} from "../lib/labels";
import { formatMoney } from "../lib/money";
import type { ClassificationOptions, Transaction } from "../types/common";
import type {
  CashflowSummary,
  InvoiceHistoryMonth,
  InvoiceHistorySummary,
} from "../types/historico";

type HistoryTab = "invoices" | "categories" | "cashflow";

async function loadHistory() {
  const [invoices, cashflow] = await Promise.allSettled([
    getInvoiceHistory(12),
    getCashflow(12),
  ]);
  if (invoices.status === "rejected" && cashflow.status === "rejected") {
    throw new Error("Falha ao carregar histórico");
  }
  return {
    invoices: invoices.status === "fulfilled" ? invoices.value : null,
    cashflow: cashflow.status === "fulfilled" ? cashflow.value : null,
    partialError: invoices.status === "rejected" || cashflow.status === "rejected",
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

function monthSourceBadge(item?: Partial<InvoiceHistoryMonth> | null) {
  const source = item?.invoice_total_source || "";
  if (source === "pluggy_official_bill") return <Badge tone="positive">Fatura fechada</Badge>;
  if (source === "credit_card_invoice_snapshot") return <Badge tone="accent">Registro histórico</Badge>;
  if (source === "dashboard_current_invoice") return <Badge tone="primary">Fatura vigente</Badge>;
  if (source === "missing_official_bill_fallback") return <Badge>Sem fatura oficial</Badge>;
  return null;
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
  const source = classificationSourceLabel(tx.classification_source);
  if (source) parts.push(source);
  return parts.join(" · ");
}

function TransactionRows({
  transactions,
  onEdit,
}: {
  transactions: Transaction[];
  onEdit: (tx: Transaction) => void;
}) {
  if (!transactions.length)
    return <p className="px-5 py-8 text-center text-sm text-ink-500">Sem transações.</p>;
  return (
    <ul className="divide-y divide-ink-100">
      {transactions.map((tx) => (
        <li key={tx.id} className="flex items-start justify-between gap-4 px-5 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink-900">{tx.description}</p>
            <p className="mt-0.5 text-xs text-ink-500">{transactionMeta(tx)}</p>
            <button
              type="button"
              className="mt-1 text-xs font-medium text-primary-700 hover:text-primary-800"
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
  );
}

function ClassificationEditor({
  tx,
  options,
  onClose,
  onSaved,
}: {
  tx: Transaction | null;
  options: ClassificationOptions | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { showToast } = useToast();
  const [category, setCategory] = useState("");
  const [cashflow, setCashflow] = useState("");
  const [ignored, setIgnored] = useState(false);

  useEffect(() => {
    setCategory(tx?.internal_category || options?.internal_categories?.[0] || "");
    setCashflow(tx?.cashflow_type || options?.cashflow_types?.[0] || "");
    setIgnored(Boolean(tx?.ignored_from_totals));
  }, [options, tx]);

  const save = async () => {
    if (!tx) return;
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
    }
  };

  const reset = async () => {
    if (!tx) return;
    try {
      await resetTransactionClassification(tx.id);
      showToast("Ajuste manual removido. A classificação automática voltou a valer.", "success");
      onSaved();
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao remover ajuste.", "error");
    }
  };

  return (
    <Modal open={!!tx} title="Editar classificação" subtitle={tx?.description} onClose={onClose}>
      <div className="space-y-4 p-5">
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
        <label className="flex items-center gap-2 text-sm text-ink-600">
          <input
            type="checkbox"
            className="rounded border-ink-300 text-primary-600 focus:ring-primary-200"
            checked={ignored}
            onChange={(event) => setIgnored(event.target.checked)}
          />
          Não contar nos totais do mês
        </label>
        <div className="flex flex-wrap justify-between gap-2">
          <Button type="button" variant="danger" onClick={reset}>
            Remover ajuste manual
          </Button>
          <div className="flex gap-2">
            <Button type="button" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="button" variant="primary" onClick={save}>
              Salvar
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function InvoiceTab({ data }: { data: InvoiceHistorySummary }) {
  const monthsWithData = data.months.filter(hasInvoiceMonthData);
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
  const largest = monthsWithData.reduce<InvoiceHistoryMonth | null>(
    (best, item) => (!best || invoiceDisplayTotal(item) > invoiceDisplayTotal(best) ? item : best),
    null,
  );
  const periodTotal = invoiceDisplayTotal(data);
  const average = monthsWithData.length > 0 ? periodTotal / monthsWithData.length : 0;

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
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MetricCard
          label="Faturas no período"
          value={formatMoney(periodTotal)}
          subtitle="Meses fechados valem a fatura oficial do banco; a vigente é calculada."
        />
        <MetricCard
          label="Mês selecionado"
          value={formatMoney(invoiceDisplayTotal(active))}
          subtitle={`${formatMonthLong(active.month)} · ${invoiceSourceLabel(active.invoice_total_source)}`}
          tone="primary"
        />
        <MetricCard
          label="Maior fatura"
          value={largest ? formatMoney(invoiceDisplayTotal(largest)) : "—"}
          subtitle={
            largest
              ? `${formatMonthCompact(largest.month)} · média do período ${formatMoney(average)}`
              : "—"
          }
          tone="warning"
        />
      </div>

      <ChartCard
        title="Evolução das faturas"
        subtitle="Clique em um mês para analisar — o selecionado fica em destaque"
      >
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

      <Card className="overflow-hidden">
        <div className="border-b border-ink-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-ink-900">Mês a mês</h2>
          <p className="mt-0.5 text-xs text-ink-500">
            Meses fechados respeitam o valor oficial do banco; a fatura vigente usa o cálculo do
            Dashboard.
          </p>
        </div>
        <ul className="divide-y divide-ink-100">
          {[...data.months].reverse().map((item) => {
            const activeRow = item.month === active.month;
            return (
              <li key={item.month} className={activeRow ? "bg-primary-50/60" : undefined}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-4 px-5 py-3 text-left transition-colors hover:bg-surface-muted"
                  onClick={() => setSelectedMonth(item.month)}
                >
                  <div>
                    <p className="text-sm font-medium text-ink-900">{formatMonthLong(item.month)}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-ink-500">
                      {monthSourceBadge(item)}
                    </div>
                  </div>
                  <span className="text-sm font-semibold tabular text-ink-900">
                    {hasInvoiceMonthData(item) ? formatMoney(invoiceDisplayTotal(item)) : "Sem fatura"}
                  </span>
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

function categoryName(category: { name?: string | null; resolved_category?: string | null }) {
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
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MetricCard
          label="Gastos classificados"
          value={formatMoney(periodClassifiedTotal)}
          subtitle={pluralize(periodMonths.length, "mês analisado", "meses analisados")}
        />
        <MetricCard
          label="Média mensal"
          value={formatMoney(periodMonths.length ? periodClassifiedTotal / periodMonths.length : 0)}
          subtitle={`${pluralCompras(periodCount)} nos últimos 12 meses`}
          tone="primary"
        />
        <MetricCard
          label="Categorias"
          value={categories.length.toLocaleString("pt-BR")}
          subtitle="Agrupadas pela regra central do cartão"
          tone="warning"
        />
      </div>

      <section>
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Para onde o dinheiro foi</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Últimos 12 meses · {pluralCompras(periodCount)} · {formatMoney(periodClassifiedTotal)}
            </p>
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
            Ver todas as compras
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {categories.map((category) => {
            const color = categoryColor(category.name);
            const largestMonth = Math.max(...category.months.map((month) => month.total), 0);
            return (
              <Card key={category.id} className="p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className="size-2.5 shrink-0 rounded-[4px]"
                        style={{ background: color }}
                        aria-hidden="true"
                      />
                      <h3 className="truncate text-sm font-semibold text-ink-900">{category.name}</h3>
                    </div>
                    <p className="mt-1 text-xs text-ink-500">
                      {pluralCompras(category.count)} · média {formatMoney(category.average_monthly)}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <p className="text-right text-lg font-bold tabular text-ink-900">
                      {formatMoney(category.total)}
                    </p>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        onOpenTransactions(
                          category.name,
                          `Últimos 12 meses · ${pluralCompras(category.count)}`,
                          category.transactions,
                        )
                      }
                    >
                      Ver compras
                    </Button>
                  </div>
                </div>
                <div
                  className="mt-5 grid h-20 grid-cols-12 items-end gap-1"
                  aria-label={`Gastos mensais em ${category.name}`}
                >
                  {category.months.map((month) => {
                    const height = largestMonth > 0 ? Math.max(8, (month.total / largestMonth) * 100) : 0;
                    return (
                      <div
                        key={month.month}
                        className="group/bar relative flex h-full items-end"
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
                          className="pointer-events-none absolute -top-9 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-control bg-ink-900 px-2 py-1 text-center text-[10px] font-semibold leading-tight text-white shadow-lift group-hover/bar:block"
                        >
                          {formatMonthCompact(month.month)}
                          <br />
                          {formatMoney(month.total)}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 flex justify-between text-[11px] text-ink-400">
                  <span>{formatMonthCompact(category.months[0]?.month || "")}</span>
                  <span>{formatMonthCompact(category.months[category.months.length - 1]?.month || "")}</span>
                </div>
              </Card>
            );
          })}
        </div>
      </section>
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
          subtitle={pluralize(summary.total_entradas_count, "crédito no período", "créditos no período")}
          tone="positive"
          icon={<ArrowDownRight className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="Total de saídas"
          value={formatMoney(summary.total_saidas)}
          subtitle={pluralize(summary.total_saidas_count, "débito no período", "débitos no período")}
          tone="danger"
          icon={<ArrowUpRight className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="Resultado"
          value={`${summary.net >= 0 ? "+" : "−"}${formatMoney(Math.abs(summary.net))}`}
          subtitle="Entradas menos saídas bancárias"
          tone={summary.net >= 0 ? "positive" : "danger"}
        />
      </div>

      <ChartCard
        title="Entradas e saídas por mês"
        subtitle="Movimentações da conta: PIX, boleto, transferências e pagamentos. Clique para abrir o mês."
      >
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
          onBarClick={(index) => {
            const month = summary.months[index];
            if (!month) return;
            onOpenTransactions(
              `Entradas e saídas · ${formatMonthLong(month.month)}`,
              `Entradas ${formatMoney(month.entradas)} · Saídas ${formatMoney(month.saidas)}`,
              [...month.entradas_txs, ...month.saidas_txs],
            );
          }}
        />
      </ChartCard>

      <Card className="overflow-hidden">
        <div className="border-b border-ink-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-ink-900">Mês a mês</h2>
          <p className="mt-0.5 text-xs text-ink-500">
            Somente movimentações bancárias; o cartão entra quando a fatura é paga.
          </p>
        </div>
        <Table>
          <thead>
            <tr className="bg-surface-muted text-xs uppercase tracking-wide text-ink-500">
              <th className="px-5 py-2.5 text-left font-medium">Mês</th>
              <th className="px-5 py-2.5 text-right font-medium">Entradas</th>
              <th className="px-5 py-2.5 text-right font-medium">Saídas</th>
              <th className="px-5 py-2.5 text-right font-medium">Resultado</th>
            </tr>
          </thead>
          <tbody>
            {[...summary.months].reverse().map((month) => (
              <tr
                key={month.month}
                className="cursor-pointer border-t border-ink-100 transition-colors hover:bg-surface-muted"
                onClick={() =>
                  onOpenTransactions(
                    `Entradas e saídas · ${formatMonthLong(month.month)}`,
                    `Entradas ${formatMoney(month.entradas)} · Saídas ${formatMoney(month.saidas)}`,
                    [...month.entradas_txs, ...month.saidas_txs],
                  )
                }
              >
                <td className="whitespace-nowrap px-5 py-3 text-sm font-medium text-ink-900">
                  {formatMonthLong(month.month)}
                </td>
                <td className="px-5 py-3 text-right text-sm tabular text-positive-700">
                  {formatMoney(month.entradas)}
                </td>
                <td className="px-5 py-3 text-right text-sm tabular text-danger-700">
                  {formatMoney(month.saidas)}
                </td>
                <td
                  className={`px-5 py-3 text-right text-sm font-semibold tabular ${
                    month.net >= 0 ? "text-positive-700" : "text-danger-700"
                  }`}
                >
                  {month.net >= 0 ? "+" : "−"}
                  {formatMoney(Math.abs(month.net))}
                </td>
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
  const { data, loading, error, run } = useAsync(loadHistory, []);
  const [activeTab, setActiveTab] = useState<HistoryTab>("invoices");
  const [modal, setModal] = useState<{
    title: string;
    subtitle: string;
    transactions: Transaction[];
  } | null>(null);
  const [editingTx, setEditingTx] = useState<Transaction | null>(null);
  const [options, setOptions] = useState<ClassificationOptions | null>(null);

  useEffect(() => {
    if (data?.partialError) showToast("Alguns dados do histórico não carregaram.", "error");
  }, [data?.partialError, showToast]);

  const openEditor = async (tx: Transaction) => {
    setEditingTx(tx);
    if (!options) {
      const loaded = await getClassificationOptions();
      setOptions(loaded);
    }
  };

  return (
    <>
      <Topbar
        subtitle={
          activeTab === "invoices"
            ? "Como as faturas evoluíram mês a mês."
            : activeTab === "categories"
              ? "Para onde o dinheiro foi, por categoria."
              : "Entradas e saídas bancárias dos últimos meses."
        }
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer>
        <div className="space-y-6">
          <Tabs<HistoryTab>
            value={activeTab}
            onChange={setActiveTab}
            items={[
              { key: "invoices", label: "Faturas do cartão" },
              { key: "categories", label: "Gastos por categoria" },
              { key: "cashflow", label: "Entradas e saídas" },
            ]}
          />
          {loading && !data ? <LoadingState label="Carregando histórico..." /> : null}
          {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
          {error && data ? (
            <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
          ) : null}
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
        open={!!modal}
        title={modal?.title || ""}
        subtitle={modal?.subtitle}
        onClose={() => setModal(null)}
      >
        <TransactionRows transactions={modal?.transactions || []} onEdit={(tx) => void openEditor(tx)} />
      </Modal>
      <ClassificationEditor
        tx={editingTx}
        options={options}
        onClose={() => setEditingTx(null)}
        onSaved={() => void run()}
      />
    </>
  );
}
