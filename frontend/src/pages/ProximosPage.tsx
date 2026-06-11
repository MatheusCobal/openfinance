import { useEffect, useMemo, useState } from "react";
import { CalendarDays, ListChecks, RefreshCw, TrendingUp, WalletCards } from "lucide-react";
import { getUpcoming } from "../api/proximos";
import { BarChart } from "../components/charts/BarChart";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ChartCard } from "../components/ui/ChartCard";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
import { useAsync } from "../hooks/useAsync";
import { classNames } from "../lib/classNames";
import { formatDayLabel, formatMonthCompact, formatMonthLong } from "../lib/dates";
import { formatMoney } from "../lib/money";
import type { UpcomingMonth } from "../types/proximos";

function pluralParcelas(n: number) {
  return n === 1 ? "1 parcela" : `${n.toLocaleString("pt-BR")} parcelas`;
}

function monthSubtitle(month: UpcomingMonth) {
  if (month.is_current_invoice) {
    const label = month.invoice_source_label || "Fatura vigente";
    const scheduledCount = month.scheduled_count ?? month.count ?? 0;
    return `${label} · ${pluralParcelas(scheduledCount)}`;
  }
  return pluralParcelas(month.count || 0);
}

function transactionList(transactions: UpcomingMonth["transactions"]) {
  if (!transactions?.length) {
    return <p className="px-5 py-6 text-sm text-slate-500">Sem parcelas detalhadas.</p>;
  }
  return (
    <ul className="divide-y divide-slate-100">
      {transactions.map((tx) => (
        <li key={tx.id} className="flex items-baseline justify-between gap-4 px-5 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-slate-950">{tx.description}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {formatDayLabel(tx.date)}
              {tx.internal_category ? ` · ${tx.internal_category}` : ""}
              {tx.cashflow_type ? ` · ${tx.cashflow_type}` : ""}
              {tx.pluggy_category ? ` · ${tx.pluggy_category}` : ""}
            </p>
          </div>
          <p className="shrink-0 text-sm font-medium tabular text-slate-900">{formatMoney(tx.amount)}</p>
        </li>
      ))}
    </ul>
  );
}

export function ProximosPage() {
  const { data, loading, error, run } = useAsync(getUpcoming, []);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);

  useEffect(() => {
    if (!data?.months?.length) return;
    if (!selectedMonth || !data.months.some((month) => month.month === selectedMonth)) {
      setSelectedMonth(data.months[0].month);
    }
  }, [data, selectedMonth]);

  const selected = data?.months?.find((month) => month.month === selectedMonth) || null;
  const summary = useMemo(() => {
    const months = data?.months || [];
    const next = months[0] || null;
    const firstThree = months.slice(0, 3);
    const totalFuture = months.reduce((sum, month) => sum + Number(month.total || 0), 0);
    const totalCount = months.reduce((sum, month) => sum + Number(month.count || 0), 0);
    const quarterTotal = firstThree.reduce((sum, month) => sum + Number(month.total || 0), 0);
    const quarterCount = firstThree.reduce((sum, month) => sum + Number(month.count || 0), 0);
    const largest = months.reduce<UpcomingMonth | null>(
      (best, month) => (!best || Number(month.total) > Number(best.total) ? month : best),
      null,
    );
    return { next, totalFuture, totalCount, quarterTotal, quarterCount, largest };
  }, [data]);

  return (
    <>
      <Topbar
        subtitle={
          data?.months?.length
            ? `${pluralParcelas(data.total_count || summary.totalCount)} em ${data.months.length} meses`
            : "Parcelas e faturas futuras"
        }
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer>
        {loading && !data ? <LoadingState label="Carregando próximos gastos..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {data ? (
          data.months?.length ? (
            <div className="space-y-6">
              <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard
                  label="Próxima fatura"
                  value={formatMoney(data.next_invoice?.amount ?? summary.next?.total)}
                  subtitle={
                    data.next_invoice
                      ? `${formatMonthLong(data.next_invoice.year_month)} · ${
                          data.next_invoice.source_label || "Fatura estimada"
                        }`
                      : summary.next
                        ? `${formatMonthLong(summary.next.month)} · ${pluralParcelas(summary.next.count)}`
                        : "Sem parcelas"
                  }
                  tone="blue"
                  icon={<WalletCards className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="3 meses"
                  value={formatMoney(summary.quarterTotal)}
                  subtitle={
                    data.next_invoice
                      ? `Inclui ${formatMonthLong(data.next_invoice.year_month)} vigente`
                      : pluralParcelas(summary.quarterCount)
                  }
                  icon={<CalendarDays className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Total futuro"
                  value={formatMoney(summary.totalFuture)}
                  subtitle={
                    data.next_invoice
                      ? "Fatura vigente + parcelas futuras"
                      : pluralParcelas(summary.totalCount)
                  }
                  tone="amber"
                  icon={<TrendingUp className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Mês com mais parcelas"
                  value={summary.largest ? formatMoney(summary.largest.total) : "-"}
                  subtitle={
                    summary.largest
                      ? `${formatMonthLong(summary.largest.month)} · ${pluralParcelas(summary.largest.count)}`
                      : "Sem parcelas"
                  }
                  icon={<ListChecks className="size-4" aria-hidden="true" />}
                />
              </section>

              <ChartCard title="Próximos meses">
                <BarChart
                  labels={data.months.map((month) => formatMonthCompact(month.month))}
                  datasets={[
                    {
                      label: "Parcelas",
                      data: data.months.map((month) => month.total),
                      backgroundColor: "#1d4ed8",
                    },
                  ]}
                  onBarClick={(index) => setSelectedMonth(data.months[index]?.month || null)}
                />
              </ChartCard>

              <div className="chip-strip flex gap-2 overflow-x-auto pb-2">
                {data.months.map((month) => {
                  const active = month.month === selectedMonth;
                  return (
                    <button
                      key={month.month}
                      type="button"
                      onClick={() => setSelectedMonth(month.month)}
                      className={classNames(
                        "shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors",
                        active
                          ? "bg-blue-700 text-white"
                          : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
                      )}
                    >
                      {formatMonthCompact(month.month)}
                    </button>
                  );
                })}
              </div>

              {selected ? (
                <>
                  <Card className="p-6">
                    <div className="flex items-baseline justify-between gap-4">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                          {formatMonthLong(selected.month)}
                        </p>
                        <p className="mt-1 text-3xl font-bold tabular text-slate-950">
                          {formatMoney(selected.total)}
                        </p>
                      </div>
                      <p className="text-sm text-slate-500 tabular">{monthSubtitle(selected)}</p>
                    </div>
                  </Card>

                  <section className="space-y-3">
                    {selected.categories?.length ? (
                      selected.categories.map((category) => (
                        <details
                          key={String(category.id ?? category.name)}
                          className="overflow-hidden rounded-lg border border-slate-200 bg-white"
                          open
                        >
                          <summary className="flex cursor-pointer items-center gap-3 px-5 py-4 hover:bg-slate-50">
                            <span className="flex-1 font-medium text-slate-950">
                              {category.name || "Outros"}
                            </span>
                            <span className="text-xs text-slate-500 tabular">
                              {pluralParcelas(category.count || 0)}
                            </span>
                            <span className="ml-3 font-semibold tabular text-slate-950">
                              {formatMoney(category.total || 0)}
                            </span>
                          </summary>
                          {transactionList(category.transactions)}
                        </details>
                      ))
                    ) : (
                      <details className="overflow-hidden rounded-lg border border-slate-200 bg-white" open>
                        <summary className="flex cursor-pointer items-center gap-3 px-5 py-4 hover:bg-slate-50">
                          <span className="flex-1 font-medium text-slate-950">Classificação Pluggy-based</span>
                          <span className="text-xs text-slate-500 tabular">
                            {pluralParcelas(selected.count || 0)}
                          </span>
                          <span className="ml-3 font-semibold tabular text-slate-950">
                            {formatMoney(selected.total || 0)}
                          </span>
                        </summary>
                        {transactionList(selected.transactions)}
                      </details>
                    )}
                  </section>
                </>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title="Nenhuma parcela futura encontrada."
              detail="Você está em dia ou ainda não conectou contas com parcelamento."
            />
          )
        ) : null}
      </PageContainer>
    </>
  );
}
