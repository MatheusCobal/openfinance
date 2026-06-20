import { useEffect, useMemo, useState } from "react";
import { CalendarClock, CalendarDays, ChevronDown, CreditCard, RefreshCw, TrendingUp } from "lucide-react";
import { getUpcoming } from "../api/proximos";
import { BarChart } from "../components/charts/BarChart";
import { PageContainer } from "../components/layout/PageContainer";
import { Topbar } from "../components/layout/Topbar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ChartCard } from "../components/ui/ChartCard";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, StaleDataWarning } from "../components/ui/ErrorState";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
import { MonthStrip } from "../components/ui/MonthStrip";
import { useAsync } from "../hooks/useAsync";
import { categoryColor } from "../lib/categories";
import { formatDayLabel, formatMonthCompact, formatMonthLong } from "../lib/dates";
import { pluralParcelas } from "../lib/labels";
import { formatMoney } from "../lib/money";
import type { UpcomingMonth } from "../types/proximos";

function monthSubtitle(month: UpcomingMonth) {
  const count = month.count || 0;
  const entries = `${count.toLocaleString("pt-BR")} ${count === 1 ? "lançamento" : "lançamentos"}`;
  return `${entries} de ${formatMonthLong(month.transaction_month)}`;
}

function transactionList(transactions: UpcomingMonth["transactions"]) {
  if (!transactions?.length) {
    return <p className="px-5 py-6 text-sm text-ink-500">Sem lançamentos detalhados.</p>;
  }
  return (
    <ul className="divide-y divide-ink-100">
      {transactions.map((tx) => (
        <li key={tx.id} className="flex items-baseline justify-between gap-4 px-5 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-ink-900">{tx.description}</p>
            <p className="mt-0.5 text-xs text-ink-500">
              {formatDayLabel(tx.date)}
              {tx.installment_number && tx.total_installments
                ? ` · parcela ${tx.installment_number} de ${tx.total_installments}`
                : ""}
            </p>
          </div>
          <p className="shrink-0 text-sm font-medium tabular text-ink-900">{formatMoney(tx.amount)}</p>
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

  const monthTotals = useMemo(() => {
    const map = new Map<string, number>();
    for (const month of data?.months || []) map.set(month.month, Number(month.total || 0));
    return map;
  }, [data]);

  const barColors = useMemo(() => {
    return (data?.months || []).map((month) => {
      if (month.month === selectedMonth) return "#1d4ed8";
      if (summary.largest && month.month === summary.largest.month) return "#f59e0b";
      return "#93c5fd";
    });
  }, [data, selectedMonth, summary.largest]);

  return (
    <>
      <Topbar
        subtitle={
          data?.months?.length
            ? `${pluralParcelas(data.total_count || summary.totalCount)} já comprometidas nos próximos ${data.months.length} meses`
            : "O que já está comprometido nos próximos meses"
        }
        actions={
          <Button type="button" onClick={() => void run()} loading={loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Atualizar
          </Button>
        }
      />
      <PageContainer>
        {loading && !data ? <LoadingState label="Carregando compromissos futuros..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {error && data ? (
          <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
        ) : null}
        {data ? (
          data.months?.length ? (
            <div className="space-y-6">
              <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <MetricCard
                  label="Próxima fatura"
                  value={formatMoney(data.next_invoice?.amount ?? summary.next?.total)}
                  subtitle={
                    data.next_invoice
                      ? `${formatMonthLong(data.next_invoice.year_month)} · gastos de ${formatMonthLong(
                          data.next_invoice.transaction_month,
                        )}`
                      : summary.next
                        ? `${formatMonthLong(summary.next.month)} · ${pluralParcelas(summary.next.count)}`
                        : "Sem parcelas"
                  }
                  tone="primary"
                  icon={<CreditCard className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Próximos 3 meses"
                  value={formatMoney(summary.quarterTotal)}
                  subtitle={
                    data.next_invoice
                      ? `Inclui a fatura vigente de ${formatMonthLong(data.next_invoice.year_month)}`
                      : pluralParcelas(summary.quarterCount)
                  }
                  icon={<CalendarDays className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Total comprometido"
                  value={formatMoney(summary.totalFuture)}
                  subtitle={
                    data.next_invoice
                      ? "Fatura vigente + parcelas futuras"
                      : `${pluralParcelas(summary.totalCount)} no horizonte`
                  }
                  tone="warning"
                  icon={<TrendingUp className="size-4" aria-hidden="true" />}
                />
              </section>

              <ChartCard
                title="Pressão dos próximos meses"
                subtitle="Clique em um mês para abrir o detalhe — o mês mais pesado fica em destaque"
              >
                <BarChart
                  labels={data.months.map((month) => formatMonthCompact(month.month))}
                  ariaLabel={`Compromissos futuros por mês. Mês mais pesado: ${
                    summary.largest ? formatMonthLong(summary.largest.month) : "nenhum"
                  }.`}
                  datasets={[
                    {
                      label: "Comprometido",
                      data: data.months.map((month) => month.total),
                      backgroundColor: "#93c5fd",
                      backgroundColors: barColors,
                    },
                  ]}
                  tooltipValueOnly
                  showValueLabels
                  onBarClick={(index) => setSelectedMonth(data.months[index]?.month || null)}
                />
              </ChartCard>

              <MonthStrip
                months={data.months.map((month) => month.month)}
                value={selectedMonth}
                onChange={setSelectedMonth}
                captionFor={(ym) => {
                  const total = monthTotals.get(ym);
                  return total ? formatMoney(total) : null;
                }}
              />

              {selected ? (
                <>
                  <Card className="p-5 sm:p-6">
                    <div className="flex flex-wrap items-baseline justify-between gap-4">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                            {formatMonthLong(selected.month)}
                          </p>
                          {selected.is_current_invoice ? (
                            <Badge tone="primary">Fatura vigente</Badge>
                          ) : null}
                          {summary.largest && selected.month === summary.largest.month ? (
                            <Badge tone="warning">Mês mais pesado</Badge>
                          ) : null}
                        </div>
                        <p className="mt-1 text-3xl font-bold tracking-tight tabular text-ink-900">
                          {formatMoney(selected.total)}
                        </p>
                      </div>
                      <p className="text-sm text-ink-500 tabular">{monthSubtitle(selected)}</p>
                    </div>
                    {selected.is_current_invoice &&
                    selected.reported_invoice_total != null &&
                    Math.abs(Number(selected.reported_difference || 0)) >= 0.005 ? (
                      <p className="mt-4 border-t border-ink-100 pt-3 text-xs text-ink-500">
                        Saldo informado pela instituição: {formatMoney(selected.reported_invoice_total)} · diferença
                        para os gastos detalhados de {formatMonthLong(selected.transaction_month)}: {" "}
                        {formatMoney(selected.reported_difference || 0)}
                      </p>
                    ) : null}
                  </Card>

                  <section className="space-y-3" aria-label="Compromissos por categoria">
                    {selected.categories?.length ? (
                      selected.categories.map((category) => {
                        const color = categoryColor(category.name);
                        const share =
                          Number(selected.total) > 0
                            ? Math.round((Number(category.total || 0) / Number(selected.total)) * 100)
                            : 0;
                        return (
                          <details
                            key={String(category.id ?? category.name)}
                            name="proximos-categoria"
                            className="group overflow-hidden rounded-card border border-ink-200/70 bg-surface shadow-card"
                          >
                            <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 transition-colors hover:bg-surface-muted [&::-webkit-details-marker]:hidden">
                              <span
                                className="size-2.5 shrink-0 rounded-[4px]"
                                style={{ background: color }}
                                aria-hidden="true"
                              />
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm font-semibold text-ink-900">
                                  {category.name || "Outros"}
                                </span>
                                <span className="block text-xs text-ink-500">
                                  {pluralParcelas(category.count || 0)} · {share}% do mês
                                </span>
                              </span>
                              <span className="ml-3 text-sm font-bold tabular text-ink-900">
                                {formatMoney(category.total || 0)}
                              </span>
                              <ChevronDown
                                className="ml-1 size-4 shrink-0 text-ink-400 transition-transform group-open:rotate-180"
                                aria-hidden="true"
                              />
                            </summary>
                            {transactionList(category.transactions)}
                          </details>
                        );
                      })
                    ) : (
                      <details
                        name="proximos-categoria"
                        className="group overflow-hidden rounded-card border border-ink-200/70 bg-surface shadow-card"
                      >
                        <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 transition-colors hover:bg-surface-muted [&::-webkit-details-marker]:hidden">
                          <span className="min-w-0 flex-1 text-sm font-semibold text-ink-900">
                            Lançamentos de {formatMonthLong(selected.transaction_month)}
                          </span>
                          <span className="text-xs text-ink-500 tabular">
                            {pluralParcelas(selected.count || 0)}
                          </span>
                          <span className="ml-3 text-sm font-bold tabular text-ink-900">
                            {formatMoney(selected.total || 0)}
                          </span>
                          <ChevronDown
                            className="ml-1 size-4 shrink-0 text-ink-400 transition-transform group-open:rotate-180"
                            aria-hidden="true"
                          />
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
              icon={<CalendarClock className="size-5" aria-hidden="true" />}
              title="Nenhuma parcela futura encontrada."
              detail="Você está em dia — ou ainda não conectou contas com compras parceladas."
            />
          )
        ) : null}
      </PageContainer>
    </>
  );
}
