import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CalendarClock,
  CalendarDays,
  ChevronDown,
  CreditCard,
  Layers3,
  RefreshCw,
} from "lucide-react";
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
import { MonthStrip } from "../components/ui/MonthStrip";
import { useAsync } from "../hooks/useAsync";
import { categoryColor } from "../lib/categories";
import { CHART_COLORS } from "../lib/chartTheme";
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
        <li key={tx.id} className="flex items-start justify-between gap-3 px-5 py-4 transition-colors hover:bg-surface-muted/60 sm:gap-5 sm:px-6">
          <div className="min-w-0 flex-1">
            <p className="break-words text-sm font-semibold leading-relaxed text-ink-900">{tx.description}</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">
              {formatDayLabel(tx.date)}
              {tx.installment_number && tx.total_installments
                ? ` · parcela ${tx.installment_number} de ${tx.total_installments}`
                : ""}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-primary-700">{cardLabel(tx)}</span>
              {tx.is_projected ? <Badge tone="warning">Prevista</Badge> : null}
            </div>
          </div>
          <p
            className={`shrink-0 pt-0.5 text-sm font-semibold tabular ${Number(tx.signed_amount ?? tx.amount) < 0 ? "text-positive-700" : "text-ink-900"
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
    month.month === selected?.month ? CHART_COLORS.primarySelected : CHART_COLORS.primarySoft,
  );

  return (
    <>
      <Topbar
        subtitle="Fatura em aberto e parcelas dos próximos meses"
        actions={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Atualizar compromissos"
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
        {loading && !data ? <LoadingState label="Carregando compromissos..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {error && data ? (
          <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
        ) : null}
        {data ? (
          months.length ? (
            <div className="space-y-6">
              <section className={`grid gap-5 ${currentInvoice && futureMonths.length ? "lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]" : "grid-cols-1"}`} aria-label="Resumo dos compromissos">
                {currentInvoice ? (
                  <div className="cockpit-surface rounded-card p-6 text-white sm:p-7">
                    <div className="flex items-center justify-between gap-4">
                      <p className="text-xs font-semibold uppercase tracking-wider text-white/70">Fatura em aberto</p>
                      <CreditCard className="size-5 text-white/70" aria-hidden="true" />
                    </div>
                    <p className="mt-4 text-3xl font-bold tracking-tight tabular sm:text-4xl">
                      {formatMoney(currentInvoice.total)}
                    </p>
                    <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                      <p className="text-sm text-white/75">{formatMonthLong(currentInvoice.month)}</p>
                      <Button type="button" variant="inverse" size="sm" onClick={() => setSelectedMonth(currentInvoice.month)}>
                        Ver fatura <ArrowRight className="size-3.5" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>
                ) : null}
                {futureMonths.length ? (
                  <Card className="flex flex-col justify-between p-6 sm:p-7">
                    <div className="flex items-center justify-between gap-4">
                      <p className="text-xs font-semibold uppercase tracking-wider text-ink-500">Parcelas futuras</p>
                      <span className="flex size-9 items-center justify-center rounded-control bg-warning-50 text-warning-700">
                        <CalendarClock className="size-5" aria-hidden="true" />
                      </span>
                    </div>
                    <p className="mt-3 text-3xl font-bold tracking-tight tabular text-ink-900">{formatMoney(futureTotal)}</p>
                    <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                      <span className="text-sm text-ink-500">{pluralParcelas(futureCount)}</span>
                      <span className="text-xs font-medium text-ink-500">Nos próximos meses</span>
                    </div>
                  </Card>
                ) : null}
              </section>

              {months.length > 1 ? (
                <ChartCard
                  title="Faturas por mês"
                  subtitle="Veja o que já está comprometido. Selecione um mês para explorar os detalhes."
                  aside={<Badge tone="primary">{selected ? formatMonthCompact(selected.month) : ""}</Badge>}
                >
                  <BarChart
                    labels={months.map((month) => formatMonthCompact(month.month))}
                    ariaLabel="Compromissos de cartão por mês"
                    datasets={[
                      {
                        label: "Comprometido",
                        data: months.map((month) => month.total),
                        backgroundColor: CHART_COLORS.primarySoft,
                        backgroundColors: barColors,
                      },
                    ]}
                    tooltipValueOnly
                    showValueLabels
                    onBarClick={(index) => setSelectedMonth(months[index]?.month || null)}
                  />
                </ChartCard>
              ) : null}

              {selected ? (
                <section className="space-y-4" aria-label="Detalhes da fatura selecionada">
                  <div className="flex flex-col gap-4">
                    <div className="flex items-center gap-2">
                      <CalendarDays className="size-4 text-primary-600" aria-hidden="true" />
                      <h2 className="text-sm font-semibold text-ink-900">Explore suas faturas</h2>
                    </div>
                    {months.length > 1 ? (
                      <MonthStrip
                        months={months.map((month) => month.month)}
                        value={selected.month}
                        onChange={setSelectedMonth}
                        captionFor={(ym) => formatMoney(months.find((month) => month.month === ym)?.total || 0)}
                      />
                    ) : null}
                  </div>
                  <div className="grid items-start gap-5 xl:grid-cols-[minmax(270px,.8fr)_minmax(0,1.8fr)]">
                    <Card className="overflow-hidden">
                      <div className="border-b border-ink-100 p-5 sm:p-6">
                        <Badge tone={selected.is_current_invoice ? "primary" : "warning"}>
                          {selected.is_current_invoice ? "Fatura em aberto" : "Compromisso futuro"}
                        </Badge>
                        <h3 className="mt-4 text-sm font-semibold text-ink-900">{formatMonthLong(selected.month)}</h3>
                        <p className="mt-2 text-3xl font-bold tracking-tight tabular text-ink-900">{formatMoney(selected.total)}</p>
                        <p className="mt-2 text-xs text-ink-500">{pluralParcelas(selected.count || 0)}</p>
                      </div>
                      {selected.cards?.length ? (
                        <div className="p-5 sm:p-6">
                          <div className="mb-2 flex items-center gap-2">
                            <CreditCard className="size-4 text-primary-600" aria-hidden="true" />
                            <h4 className="text-xs font-semibold text-ink-600">Por cartão</h4>
                          </div>
                          <div className="divide-y divide-ink-100">
                            {selected.cards.map((card) => (
                              <div
                                key={card.account_id}
                                className="flex flex-wrap items-center justify-between gap-2 py-3"
                              >
                                <span className="min-w-0 text-xs font-medium leading-relaxed text-ink-700">
                                  {cardLabel(card)}
                                </span>
                                <span className="shrink-0 text-xs font-bold tabular text-ink-900">
                                  {formatMoney(card.total_amount)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </Card>

                    {selected.categories?.length ? (
                      <Card key={selected.month} className="overflow-hidden" aria-label="Compromissos por categoria">
                        <div className="flex items-center gap-3 border-b border-ink-100 px-5 py-5 sm:px-6">
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-primary-50 text-primary-700">
                            <Layers3 className="size-4" aria-hidden="true" />
                          </span>
                          <div>
                            <h3 className="text-sm font-semibold text-ink-900">Compromissos por categoria</h3>
                            <p className="mt-1 text-xs text-ink-500">Abra uma categoria para ver compras e parcelas.</p>
                          </div>
                        </div>
                        <div className="divide-y divide-ink-100">
                          {selected.categories.map((category) => {
                            const total = Number(category.total || 0);
                            return (
                              <details
                                key={String(category.id ?? category.name)}
                                name="proximos-categoria"
                                className="group"
                              >
                                <summary className="grid cursor-pointer list-none grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-3 px-5 py-5 transition-colors hover:bg-surface-muted group-open:bg-primary-50/60 sm:px-6 [&::-webkit-details-marker]:hidden">
                                  <span
                                    className="size-2.5 shrink-0 rounded-[4px]"
                                    style={{ background: categoryColor(category.name) }}
                                    aria-hidden="true"
                                  />
                                  <span className="min-w-0">
                                    <span className="block text-sm font-semibold text-ink-900">{category.name || "Outros"}</span>
                                    <span className="mt-1 block text-xs text-ink-500">{pluralParcelas(category.count || 0)}</span>
                                  </span>
                                  <span className="text-sm font-bold tabular text-ink-900">
                                    {formatMoney(total)}
                                  </span>
                                  <ChevronDown
                                    className="size-4 shrink-0 text-ink-400 transition-transform group-open:rotate-180"
                                    aria-hidden="true"
                                  />
                                </summary>
                                <div className="border-t border-ink-100">
                                  {transactionList(category.transactions) || (
                                    <p className="px-5 py-5 text-sm text-ink-500">As transações detalhadas desta categoria ainda não estão disponíveis.</p>
                                  )}
                                </div>
                              </details>
                            );
                          })}
                        </div>
                      </Card>
                    ) : selected.transactions?.length ? (
                      <Card className="overflow-hidden">
                        <div className="border-b border-ink-100 px-5 py-5">
                          <h3 className="text-sm font-semibold text-ink-900">Compras e parcelas</h3>
                        </div>
                        {transactionList(selected.transactions)}
                      </Card>
                    ) : (
                      <EmptyState
                        icon={<Layers3 className="size-5" aria-hidden="true" />}
                        title="Detalhes ainda indisponíveis"
                        detail="O total desta fatura está disponível. As compras e parcelas aparecerão aqui quando houver detalhamento."
                      />
                    )}
                  </div>
                </section>
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
