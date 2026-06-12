import { useEffect, useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, BarChart3, Minus, RefreshCw, Tags } from "lucide-react";
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
import { CategoryBreakdown } from "../components/ui/CategoryBreakdown";
import { ChartCard } from "../components/ui/ChartCard";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
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
  if (tx.internal_category) parts.push(tx.internal_category);
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

function CategorySpendingTab({
  data,
  onOpenTransactions,
}: {
  data: InvoiceHistorySummary;
  onOpenTransactions: (title: string, subtitle: string, transactions: Transaction[]) => void;
}) {
  const monthsWithCategories = data.months.filter((month) => (month.categories || []).length > 0);
  const [selectedMonth, setSelectedMonth] = useState(() => {
    const latest = [...monthsWithCategories].pop() || data.months[data.months.length - 1];
    return latest?.month || "";
  });

  useEffect(() => {
    if (selectedMonth && data.months.some((item) => item.month === selectedMonth)) return;
    const latest = [...monthsWithCategories].pop() || data.months[data.months.length - 1];
    setSelectedMonth(latest?.month || "");
  }, [data.months, monthsWithCategories, selectedMonth]);

  const active =
    data.months.find((item) => item.month === selectedMonth) || data.months[data.months.length - 1];
  const monthsWithData = data.months.filter(hasInvoiceMonthData);
  const periodClassifiedTotal = data.months.reduce(
    (sum, item) => sum + classifiedPurchaseTotal(item),
    0,
  );

  if (!monthsWithCategories.length) {
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
          subtitle={pluralize(monthsWithData.length, "mês analisado", "meses analisados")}
        />
        <MetricCard
          label="Mês selecionado"
          value={formatMoney(classifiedPurchaseTotal(active))}
          subtitle={`${formatMonthLong(active.month)} · ${pluralCompras(active.count)}`}
          tone="primary"
        />
        <MetricCard
          label="Categorias no mês"
          value={(active.categories?.length || 0).toLocaleString("pt-BR")}
          subtitle="Categorias com compras no período"
          tone="warning"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[340px_1fr]">
        <Card className="h-fit overflow-hidden">
          <div className="border-b border-ink-100 px-5 py-4">
            <h2 className="text-sm font-semibold text-ink-900">Meses com gastos</h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Total das compras classificadas, separado do valor oficial da fatura.
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
                      <p className="mt-0.5 text-xs text-ink-500">{pluralCompras(item.count)}</p>
                    </div>
                    <span className="text-sm font-semibold tabular text-ink-900">
                      {classifiedPurchaseTotal(item) > 0
                        ? formatMoney(classifiedPurchaseTotal(item))
                        : "Sem compras"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <section>
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-ink-900">Para onde o dinheiro foi</h2>
              <p className="mt-0.5 text-xs text-ink-500">
                {formatMonthLong(active.month)} · {pluralCompras(active.count)} ·{" "}
                {formatMoney(classifiedPurchaseTotal(active))}
              </p>
            </div>
            <Button
              type="button"
              onClick={() =>
                onOpenTransactions(
                  `Compras classificadas · ${formatMonthLong(active.month)}`,
                  `${pluralCompras(active.count)} · ${formatMoney(classifiedPurchaseTotal(active))}`,
                  active.transactions || [],
                )
              }
            >
              Ver todas as compras
            </Button>
          </div>
          {active.categories?.length ? (
            <CategoryBreakdown
              items={active.categories.map((category) => {
                const diff = Number(category.difference_from_average || 0);
                const hasAverage = Boolean(category.average_months_used);
                const detail = hasAverage ? (
                  <p className="flex items-center gap-1.5 text-xs text-ink-500">
                    {Math.abs(diff) < 0.005 ? (
                      <Minus className="size-3 text-ink-400" aria-hidden="true" />
                    ) : diff > 0 ? (
                      <ArrowUpRight className="size-3 text-danger-600" aria-hidden="true" />
                    ) : (
                      <ArrowDownRight className="size-3 text-positive-600" aria-hidden="true" />
                    )}
                    <span>
                      <span
                        className={
                          Math.abs(diff) < 0.005
                            ? "font-semibold text-ink-600"
                            : diff > 0
                              ? "font-semibold text-danger-700"
                              : "font-semibold text-positive-700"
                        }
                      >
                        {diff > 0 ? "+" : diff < 0 ? "−" : ""}
                        {formatMoney(Math.abs(diff))}
                      </span>{" "}
                      vs. média de {formatMoney(category.average_12m)} (
                      {pluralize(Number(category.average_months_used), "mês", "meses")})
                    </span>
                  </p>
                ) : (
                  <p className="text-xs text-ink-400">Sem histórico anterior para comparar</p>
                );
                return {
                  id: category.id,
                  name: category.name,
                  total: Number(category.total),
                  count: category.count,
                  detail,
                };
              })}
              onSelect={(id) => {
                const category = active.categories?.find((item) => String(item.id) === String(id));
                if (!category) return;
                onOpenTransactions(
                  category.name,
                  `${formatMonthLong(active.month)} · ${pluralCompras(category.count)}`,
                  category.transactions || [],
                );
              }}
            />
          ) : (
            <EmptyState title="Sem categorias para este mês." />
          )}
        </section>
      </div>
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
