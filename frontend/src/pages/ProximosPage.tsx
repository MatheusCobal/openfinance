import { useEffect, useMemo, useState } from "react";
import { CalendarClock, ChevronDown, CreditCard, RefreshCw } from "lucide-react";
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

function cardLabel(card: {
  institution_name?: string | null;
  account_name?: string | null;
  card_brand?: string | null;
  card_last_four?: string | null;
}) {
  const normalizeToken = (value: string) =>
    value
      .normalize("NFD")
      .replace(/\p{Diacritic}/gu, "")
      .replace(/[^a-zA-Z0-9]/g, "")
      .toUpperCase();
  const noise = new Set([
    "BLACK",
    "GOLD",
    "INFINITE",
    "INTERNACIONAL",
    "INTERNATIONAL",
    "MASTERCARD",
    "PLATINUM",
    "VISA",
  ]);
  for (const word of card.card_brand?.split(/\s+/) || []) noise.add(normalizeToken(word));

  const usefulName = card.account_name
    ?.split(/\s+/)
    .filter((word) => !noise.has(normalizeToken(word)))
    .join(" ")
    .trim();
  const connectorName =
    normalizeToken(card.institution_name || "") === "MEUPLUGGY"
      ? ""
      : card.institution_name?.trim();
  const name = usefulName || connectorName || card.card_brand?.trim() || "Cartão";
  return card.card_last_four ? `${name} · final ${card.card_last_four}` : name;
}

function hasCommitment(month: UpcomingMonth) {
  return (
    Math.abs(Number(month.total || 0)) > 0.009 ||
    Number(month.count || 0) > 0 ||
    Boolean(month.cards?.length) ||
    Boolean(month.transactions?.length)
  );
}

function transactionList(transactions: UpcomingMonth["transactions"]) {
  if (!transactions?.length) return null;
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
              {tx.is_projected ? " · prevista" : ""}
            </p>
            <p className="mt-1 truncate text-xs font-medium text-primary-700">{cardLabel(tx)}</p>
          </div>
          <p
            className={`shrink-0 text-sm font-medium tabular ${
              Number(tx.signed_amount ?? tx.amount) < 0 ? "text-positive-700" : "text-ink-900"
            }`}
          >
            {formatMoney(tx.signed_amount ?? tx.amount)}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function ProximosPage() {
  const { data, loading, error, run } = useAsync(getUpcoming);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const months = useMemo(() => (data?.months || []).filter(hasCommitment), [data]);

  useEffect(() => {
    if (!months.length) return;
    if (!selectedMonth || !months.some((month) => month.month === selectedMonth)) {
      setSelectedMonth(months[0].month);
    }
  }, [months, selectedMonth]);

  const selected = months.find((month) => month.month === selectedMonth) || months[0] || null;
  const currentInvoice = months.find((month) => month.is_current_invoice) || null;
  const futureMonths = months.filter((month) => !month.is_current_invoice);
  const futureTotal = futureMonths.reduce((sum, month) => sum + Number(month.total || 0), 0);
  const futureCount = futureMonths.reduce((sum, month) => sum + Number(month.count || 0), 0);
  const barColors = months.map((month) =>
    month.month === selectedMonth ? "#1d4ed8" : "#93c5fd",
  );

  return (
    <>
      <Topbar
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="size-9 px-0"
            aria-label="Atualizar"
            title="Atualizar"
            onClick={() => void run()}
            loading={loading}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
          </Button>
        }
      />
      <PageContainer>
        {loading && !data ? <LoadingState label="Carregando compromissos..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {error && data ? (
          <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
        ) : null}
        {data ? (
          months.length ? (
            <div className="space-y-6">
              <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {currentInvoice ? (
                  <MetricCard
                    label="Fatura em aberto"
                    value={formatMoney(currentInvoice.total)}
                    subtitle={formatMonthLong(currentInvoice.month)}
                    tone="primary"
                    icon={<CreditCard className="size-4" aria-hidden="true" />}
                  />
                ) : null}
                {futureMonths.length ? (
                  <MetricCard
                    label="Parcelas futuras"
                    value={formatMoney(futureTotal)}
                    subtitle={pluralParcelas(futureCount)}
                    icon={<CalendarClock className="size-4" aria-hidden="true" />}
                  />
                ) : null}
              </section>

              {months.length > 1 ? (
                <>
                  <ChartCard title="Faturas por mês">
                    <BarChart
                      labels={months.map((month) => formatMonthCompact(month.month))}
                      ariaLabel="Compromissos de cartão por mês"
                      datasets={[
                        {
                          label: "Comprometido",
                          data: months.map((month) => month.total),
                          backgroundColor: "#93c5fd",
                          backgroundColors: barColors,
                        },
                      ]}
                      tooltipValueOnly
                      showValueLabels
                      onBarClick={(index) => setSelectedMonth(months[index]?.month || null)}
                    />
                  </ChartCard>
                  <MonthStrip
                    months={months.map((month) => month.month)}
                    value={selectedMonth}
                    onChange={setSelectedMonth}
                  />
                </>
              ) : null}

              {selected ? (
                <>
                  <Card className="p-5 sm:p-6">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h2 className="text-sm font-semibold text-ink-900">
                            {formatMonthLong(selected.month)}
                          </h2>
                          {selected.is_current_invoice ? (
                            <Badge tone="primary">Fatura em aberto</Badge>
                          ) : null}
                        </div>
                        <p className="mt-2 text-3xl font-bold tracking-tight tabular text-ink-900">
                          {formatMoney(selected.total)}
                        </p>
                        <p className="mt-1 text-xs text-ink-500">{pluralParcelas(selected.count || 0)}</p>
                      </div>
                    </div>
                    {selected.cards?.length ? (
                      <div className="mt-4 grid gap-2 border-t border-ink-100 pt-4 sm:grid-cols-2">
                        {selected.cards.map((card) => (
                          <div
                            key={card.account_id}
                            className="flex items-center justify-between gap-3 rounded-control bg-surface-muted px-3 py-2.5"
                          >
                            <span className="min-w-0 truncate text-xs font-medium text-ink-700">
                              {cardLabel(card)}
                            </span>
                            <span className="shrink-0 text-xs font-bold tabular text-ink-900">
                              {formatMoney(card.pending_total ?? card.total_amount ?? 0)}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </Card>

                  {selected.categories?.length ? (
                    <section className="space-y-3" aria-label="Compromissos por categoria">
                      {selected.categories.map((category) => {
                        const total = Number(category.total || 0);
                        return (
                          <details
                            key={String(category.id ?? category.name)}
                            name="proximos-categoria"
                            className="group overflow-hidden rounded-card border border-ink-200/70 bg-surface shadow-card"
                          >
                            <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 hover:bg-surface-muted [&::-webkit-details-marker]:hidden">
                              <span
                                className="size-2.5 shrink-0 rounded-[4px]"
                                style={{ background: categoryColor(category.name) }}
                                aria-hidden="true"
                              />
                              <span className="min-w-0 flex-1 truncate text-sm font-semibold text-ink-900">
                                {category.name || "Outros"}
                              </span>
                              <span className="text-xs text-ink-500">
                                {pluralParcelas(category.count || 0)}
                              </span>
                              <span className="ml-3 text-sm font-bold tabular text-ink-900">
                                {formatMoney(total)}
                              </span>
                              <ChevronDown
                                className="ml-1 size-4 shrink-0 text-ink-400 transition-transform group-open:rotate-180"
                                aria-hidden="true"
                              />
                            </summary>
                            {transactionList(category.transactions)}
                          </details>
                        );
                      })}
                    </section>
                  ) : selected.transactions?.length ? (
                    <Card className="overflow-hidden">{transactionList(selected.transactions)}</Card>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : (
            <EmptyState
              icon={<CalendarClock className="size-5" aria-hidden="true" />}
              title="Nenhum compromisso futuro"
              detail="As próximas faturas e parcelas aparecerão aqui."
            />
          )
        ) : null}
      </PageContainer>
    </>
  );
}
