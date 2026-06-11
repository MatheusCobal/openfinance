import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import {
  createCashflowRule,
  deleteCashflowRule,
  getCashflow,
  getClassificationOptions,
  getInvoiceHistory,
  listCashflowRules,
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
import { ErrorState } from "../components/ui/ErrorState";
import { FormField } from "../components/ui/FormField";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
import { Modal } from "../components/ui/Modal";
import { Select } from "../components/ui/Select";
import { Table } from "../components/ui/Table";
import { Tabs } from "../components/ui/Tabs";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { CATEGORY_COLORS } from "../lib/constants";
import { formatDayLabel, formatMonthCompact, formatMonthLong } from "../lib/dates";
import { formatMoney } from "../lib/money";
import type { ClassificationOptions, Transaction } from "../types/common";
import type {
  CashflowRule,
  CashflowSummary,
  InvoiceHistoryMonth,
  InvoiceHistorySummary,
} from "../types/historico";

type HistoryTab = "invoices" | "cashflow";

async function loadHistory() {
  const [invoices, cashflow, cashflowRules] = await Promise.allSettled([
    getInvoiceHistory(12),
    getCashflow(12),
    listCashflowRules(),
  ]);
  if (invoices.status === "rejected" && cashflow.status === "rejected") {
    throw new Error("Falha ao carregar histórico");
  }
  return {
    invoices: invoices.status === "fulfilled" ? invoices.value : null,
    cashflow: cashflow.status === "fulfilled" ? cashflow.value : null,
    cashflowRules: cashflowRules.status === "fulfilled" ? cashflowRules.value : [],
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

function invoiceSourceLabel(item?: Partial<InvoiceHistoryMonth> | null) {
  const labels: Record<string, string> = {
    pluggy_official_bill: "Fatura oficial Pluggy",
    dashboard_current_invoice: "Fatura vigente calculada",
    missing_official_bill_fallback: "Sem fatura oficial",
  };
  return labels[item?.invoice_total_source || ""] || "Fatura";
}

function categoryColor(name: string) {
  return CATEGORY_COLORS[name] || "#64748b";
}

function pluralCompras(n: number) {
  return n === 1 ? "1 compra" : `${n.toLocaleString("pt-BR")} compras`;
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
        month.entradas_count > 0 ||
        month.saidas_count > 0 ||
        month.entradas > 0 ||
        month.saidas > 0,
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

function TransactionRows({
  transactions,
  onEdit,
}: {
  transactions: Transaction[];
  onEdit: (tx: Transaction) => void;
}) {
  if (!transactions.length) return <p className="px-5 py-8 text-center text-sm text-slate-500">Sem transações.</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {transactions.map((tx) => (
        <li key={tx.id} className="flex items-start justify-between gap-4 px-5 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-950">{tx.description}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {formatDayLabel(tx.date)}
              {tx.account_name ? ` · ${tx.account_name}` : ""}
              {tx.internal_category ? ` · ${tx.internal_category}` : ""}
              {tx.cashflow_type ? ` · ${tx.cashflow_type}` : ""}
              {tx.classification_source ? ` · ${tx.classification_source}` : ""}
            </p>
            <button
              type="button"
              className="mt-1 text-xs font-medium text-blue-700 hover:text-blue-800"
              onClick={() => onEdit(tx)}
            >
              Editar classificação
            </button>
          </div>
          <p className="shrink-0 text-sm font-semibold tabular text-slate-900">
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
      showToast("Classificação manual salva.", "success");
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
      showToast("Classificação manual removida.", "success");
      onSaved();
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao remover override.", "error");
    }
  };

  return (
    <Modal open={!!tx} title="Editar classificação" subtitle={tx?.description} onClose={onClose}>
      <div className="space-y-4 p-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="Categoria interna">
            <Select value={category} onChange={(event) => setCategory(event.target.value)}>
              {(options?.internal_categories || []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Tipo de fluxo">
            <Select value={cashflow} onChange={(event) => setCashflow(event.target.value)}>
              {(options?.cashflow_types || []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            className="rounded border-slate-300 text-blue-700 focus:ring-blue-500"
            checked={ignored}
            onChange={(event) => setIgnored(event.target.checked)}
          />
          Ignorar dos totais
        </label>
        <div className="flex flex-wrap justify-between gap-2">
          <Button type="button" variant="danger" onClick={reset}>
            Remover override
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

function InvoiceTab({
  data,
  onOpenTransactions,
}: {
  data: InvoiceHistorySummary;
  onOpenTransactions: (title: string, subtitle: string, transactions: Transaction[]) => void;
}) {
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

  const active = data.months.find((item) => item.month === selectedMonth) || data.months[data.months.length - 1];
  const largest = monthsWithData.reduce<InvoiceHistoryMonth | null>(
    (best, item) => (!best || invoiceDisplayTotal(item) > invoiceDisplayTotal(best) ? item : best),
    null,
  );
  const periodTotal = invoiceDisplayTotal(data);
  const periodClassifiedTotal = classifiedPurchaseTotal(data);
  const average = data.months.length > 0 ? periodTotal / data.months.length : 0;

  if (!monthsWithData.length) {
    return (
      <EmptyState
        title="Nenhuma fatura de cartão encontrada."
        detail="Faturas oficiais e compras CREDIT válidas aparecerão aqui."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MetricCard
          label="Faturas no período"
          value={formatMoney(periodTotal)}
          subtitle={`${pluralCompras(data.total_count || 0)} classificadas · ${formatMoney(periodClassifiedTotal)}`}
        />
        <MetricCard
          label="Mês selecionado"
          value={formatMoney(invoiceDisplayTotal(active))}
          subtitle={`${formatMonthLong(active.month)} · ${invoiceSourceLabel(active)}`}
          tone="blue"
        />
        <MetricCard
          label="Maior mês"
          value={largest ? formatMoney(invoiceDisplayTotal(largest)) : "-"}
          subtitle={largest ? `${formatMonthCompact(largest.month)} · média ${formatMoney(average)}` : "-"}
          tone="amber"
        />
      </div>

      <ChartCard title="Evolução das faturas de cartão">
        <BarChart
          labels={data.months.map((month) => formatMonthCompact(month.month))}
          datasets={[
            {
              label: "Fatura",
              data: data.months.map(invoiceDisplayTotal),
              backgroundColor: "#475569",
            },
          ]}
          onBarClick={(index) => setSelectedMonth(data.months[index]?.month || selectedMonth)}
        />
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_1fr]">
        <Card className="overflow-hidden">
          <div className="px-5 py-4">
            <h2 className="font-semibold text-slate-950">Histórico mensal</h2>
          </div>
          <ul className="divide-y divide-slate-100">
            {[...data.months].reverse().map((item) => {
              const activeRow = item.month === active.month;
              return (
                <li key={item.month} className={activeRow ? "bg-blue-50/60" : undefined}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-4 px-5 py-3 text-left"
                    onClick={() => setSelectedMonth(item.month)}
                  >
                    <div>
                      <p className="text-sm font-medium text-slate-950">{formatMonthLong(item.month)}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {invoiceSourceLabel(item)}
                      </p>
                    </div>
                    <span className="text-sm font-semibold tabular text-slate-950">
                      {hasInvoiceMonthData(item) ? formatMoney(invoiceDisplayTotal(item)) : "Sem fatura"}
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
              <h2 className="font-semibold text-slate-950">Gastos por classificação</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                {formatMonthLong(active.month)} · {pluralCompras(active.count)}
              </p>
            </div>
            <Button
              type="button"
              onClick={() =>
                onOpenTransactions(
                  `Fatura · ${formatMonthLong(active.month)}`,
                  `${pluralCompras(active.count)} · ${formatMoney(invoiceDisplayTotal(active))}`,
                  active.transactions || [],
                )
              }
            >
              Ver transações do mês
            </Button>
          </div>
          {active.categories?.length ? (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {active.categories.map((category) => (
                <button
                  key={category.id}
                  type="button"
                  onClick={() =>
                    onOpenTransactions(
                      category.name,
                      `${formatMonthLong(active.month)} · ${pluralCompras(category.count)}`,
                      category.transactions || [],
                    )
                  }
                  className="rounded-lg border border-slate-200 bg-white p-5 text-left transition hover:border-blue-200 hover:shadow-soft"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          className="size-2.5 shrink-0 rounded-sm"
                          style={{ background: categoryColor(category.name) }}
                        />
                        <h3 className="truncate font-semibold text-slate-950">{category.name}</h3>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{pluralCompras(category.count)}</p>
                    </div>
                    <p className="shrink-0 font-bold tabular text-slate-950">
                      {formatMoney(category.total)}
                    </p>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-4 border-t border-slate-100 pt-3 text-xs">
                    <div>
                      <p className="text-slate-500">Média 12m</p>
                      <p className="mt-0.5 font-semibold tabular text-slate-800">
                        {category.average_months_used
                          ? `${formatMoney(category.average_12m)} em ${category.average_months_used} meses`
                          : "sem histórico anterior"}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-500">Vs. média</p>
                      <p className="mt-0.5 font-semibold tabular text-slate-800">
                        {formatMoney(category.difference_from_average || 0)}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
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
  rules,
  onReload,
  onOpenTransactions,
}: {
  data: CashflowSummary;
  rules: CashflowRule[];
  onReload: () => Promise<unknown>;
  onOpenTransactions: (title: string, subtitle: string, transactions: Transaction[]) => void;
}) {
  const { showToast } = useToast();
  const summary = useMemo(() => summarizeCashflow(data), [data]);
  const [direction, setDirection] = useState("ALL");
  const [kind, setKind] = useState("pluggy_category");
  const [value, setValue] = useState("");

  const submitRule = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!value.trim()) return;
    try {
      await createCashflowRule(
        kind === "pluggy_category"
          ? { direction, pluggy_category: value.trim() }
          : { direction, pattern: value.trim() },
      );
      setValue("");
      await onReload();
      showToast("Regra criada e fluxo recalculado.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao criar regra.", "error");
    }
  };

  const removeRule = async (id: number) => {
    if (!window.confirm("Remover esta regra?")) return;
    try {
      await deleteCashflowRule(id);
      await onReload();
      showToast("Regra removida e fluxo recalculado.", "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Erro ao remover regra.", "error");
    }
  };

  if (!summary.months.length) {
    return (
      <EmptyState
        title="Sem entradas ou saídas nos últimos 12 meses."
        detail="Conecte uma conta bancária pelo Pluggy para acompanhar o fluxo de caixa."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MetricCard
          label="Total de entradas"
          value={formatMoney(summary.total_entradas)}
          subtitle={`${summary.total_entradas_count.toLocaleString("pt-BR")} créditos`}
          tone="emerald"
        />
        <MetricCard
          label="Total de saídas"
          value={formatMoney(summary.total_saidas)}
          subtitle={`${summary.total_saidas_count.toLocaleString("pt-BR")} débitos`}
          tone="rose"
        />
        <MetricCard
          label="Saldo"
          value={`${summary.net >= 0 ? "+" : "-"}${formatMoney(Math.abs(summary.net))}`}
          subtitle="Entradas menos saídas bancárias"
          tone={summary.net >= 0 ? "emerald" : "rose"}
        />
      </div>

      <ChartCard title="Entradas vs saídas por mês" subtitle="Clique numa barra para ver o mês">
        <BarChart
          labels={summary.months.map((month) => formatMonthCompact(month.month))}
          datasets={[
            {
              label: "Entradas",
              data: summary.months.map((month) => month.entradas),
              backgroundColor: "#10b981",
            },
            {
              label: "Saídas",
              data: summary.months.map((month) => month.saidas),
              backgroundColor: "#ef4444",
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
        <div className="border-b border-slate-100 px-5 py-4">
          <h2 className="font-semibold text-slate-950">Detalhamento mensal</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Apenas movimentações bancárias; cartão aparece quando a fatura é paga.
          </p>
        </div>
        <Table>
          <thead>
            <tr className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <th className="px-5 py-2 text-left font-medium">Mês</th>
              <th className="px-5 py-2 text-right font-medium">Entradas</th>
              <th className="px-5 py-2 text-right font-medium">Saídas</th>
              <th className="px-5 py-2 text-right font-medium">Saldo</th>
            </tr>
          </thead>
          <tbody>
            {[...summary.months].reverse().map((month) => (
              <tr
                key={month.month}
                className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                onClick={() =>
                  onOpenTransactions(
                    `Entradas e saídas · ${formatMonthLong(month.month)}`,
                    `Entradas ${formatMoney(month.entradas)} · Saídas ${formatMoney(month.saidas)}`,
                    [...month.entradas_txs, ...month.saidas_txs],
                  )
                }
              >
                <td className="whitespace-nowrap px-5 py-3 text-sm font-medium text-slate-950">
                  {formatMonthLong(month.month)}
                </td>
                <td className="px-5 py-3 text-right text-sm tabular text-emerald-700">
                  {formatMoney(month.entradas)}
                </td>
                <td className="px-5 py-3 text-right text-sm tabular text-rose-700">
                  {formatMoney(month.saidas)}
                </td>
                <td className="px-5 py-3 text-right text-sm font-medium tabular text-slate-950">
                  {month.net >= 0 ? "+" : "-"}
                  {formatMoney(Math.abs(month.net))}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card className="p-5">
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="font-semibold text-slate-950">Regras do fluxo de caixa</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Remove investimentos, transferências internas e ruídos bancários.
            </p>
          </div>
          <Badge>{rules.length} regras</Badge>
        </div>
        <form className="grid grid-cols-1 gap-2 lg:grid-cols-[170px_180px_1fr_auto]" onSubmit={submitRule}>
          <Select value={direction} onChange={(event) => setDirection(event.target.value)}>
            <option value="ALL">Entradas e saídas</option>
            <option value="IN">Somente entradas</option>
            <option value="OUT">Somente saídas</option>
          </Select>
          <Select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="pluggy_category">Por categoria Pluggy</option>
            <option value="pattern">Por descrição</option>
          </Select>
          <Input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Ex: Fixed income, Resgate CDB, Same person transfer"
          />
          <Button type="submit" variant="primary">
            Adicionar
          </Button>
        </form>
        <ul className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-100">
          {rules.map((rule) => (
            <li key={rule.id} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">
                  {rule.pluggy_category || rule.pattern || "-"}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {rule.direction || "ALL"} · {rule.affected_count ?? 0} transações removidas
                </p>
              </div>
              <Button type="button" variant="ghost" className="size-8 px-0" onClick={() => void removeRule(rule.id)}>
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
          {!rules.length ? <li className="px-4 py-6 text-center text-sm text-slate-500">Nenhuma regra cadastrada.</li> : null}
        </ul>
      </Card>
    </div>
  );
}

export function HistoricoPage() {
  const { showToast } = useToast();
  const { data, loading, error, run } = useAsync(loadHistory, []);
  const [activeTab, setActiveTab] = useState<HistoryTab>("invoices");
  const [modal, setModal] = useState<{ title: string; subtitle: string; transactions: Transaction[] } | null>(null);
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
        subtitle={activeTab === "invoices" ? "Faturas de cartão" : "Fluxo de caixa bancário"}
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
              { key: "invoices", label: "Faturas cartão" },
              { key: "cashflow", label: "Entradas e saídas" },
            ]}
          />
          {loading && !data ? <LoadingState label="Carregando histórico..." /> : null}
          {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
          {data && activeTab === "invoices" && data.invoices ? (
            <InvoiceTab
              data={data.invoices}
              onOpenTransactions={(title, subtitle, transactions) =>
                setModal({ title, subtitle, transactions })
              }
            />
          ) : null}
          {data && activeTab === "cashflow" && data.cashflow ? (
            <CashflowTab
              data={data.cashflow}
              rules={data.cashflowRules}
              onReload={run}
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
