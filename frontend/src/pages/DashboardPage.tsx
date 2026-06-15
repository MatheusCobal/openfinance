import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  Banknote,
  CalendarClock,
  CalendarDays,
  CreditCard,
  Landmark,
  Link as LinkIcon,
  RefreshCw,
  Scale,
  ShieldCheck,
  Tags,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  createConnectToken,
  getBankBalance,
  getCurrentInvoice,
  getPlanningMonth,
  getUpcoming,
  registerPluggyItem,
  syncPluggyItem,
} from "../api/dashboard";
import { Topbar } from "../components/layout/Topbar";
import { PageContainer } from "../components/layout/PageContainer";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { CategoryBreakdown } from "../components/ui/CategoryBreakdown";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { FinancialFlow } from "../components/ui/FinancialFlow";
import { InsightCard } from "../components/ui/InsightCard";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
import { Modal } from "../components/ui/Modal";
import { PressureMeter } from "../components/ui/PressureMeter";
import { SectionHeader } from "../components/ui/SectionHeader";
import { StatusPill } from "../components/ui/StatusPill";
import { Table } from "../components/ui/Table";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { formatDayLabel, formatMonthLong, formatMonthShort, getDefaultPlanningMonth } from "../lib/dates";
import {
  classificationSourceLabel,
  invoiceSourceLabel,
  pluralCompras,
  pluralItens,
  pluralize,
} from "../lib/labels";
import { dashboardAvailableToSpend, normalizePlanningOverview, planStatusMeta } from "../lib/planning";
import { extractPluggyItemId, ensurePluggyConnectSdkLoaded } from "../lib/pluggy";
import { formatMoney } from "../lib/money";
import type { Transaction } from "../types/common";
import type { InvoiceCategory } from "../types/planejamento";

const RECENT_CARD_PURCHASE_LIMIT = 8;

function latestCardPurchases(transactions: Transaction[] = []) {
  return [...transactions]
    .filter((tx) => {
      const cashflowType = String(tx.cashflow_type ?? "expense").toLowerCase();
      return !tx.ignored_from_totals && cashflowType === "expense";
    })
    .sort((a, b) => {
      const dateOrder = new Date(b.date).getTime() - new Date(a.date).getTime();
      if (dateOrder !== 0) return dateOrder;
      return String(a.description || "").localeCompare(String(b.description || ""), "pt-BR");
    })
    .slice(0, RECENT_CARD_PURCHASE_LIMIT);
}

function transactionDisplayCategory(tx: Transaction) {
  return tx.effective_category || tx.resolved_category || tx.credit_category || tx.internal_category || tx.category;
}

async function loadDashboardData() {
  const planningMonth = getDefaultPlanningMonth();
  const [planning, currentInvoice] = await Promise.all([
    getPlanningMonth(planningMonth),
    getCurrentInvoice(),
  ]);
  const [bankBalance, upcoming] = await Promise.all([
    getBankBalance().catch(() => null),
    getUpcoming().catch(() => null),
  ]);
  const capacity = normalizePlanningOverview(planning);
  return {
    planningMonth,
    capacity,
    currentInvoice,
    bankBalance,
    upcoming,
    categories: currentInvoice.categories || [],
    recentCardPurchases: latestCardPurchases(currentInvoice.raw_purchase_transactions || []),
  };
}

function InvoiceReconciliation({ reconciliation }: { reconciliation?: Record<string, any> }) {
  if (!reconciliation) return null;
  const rows = [
    ["Compras classificadas", reconciliation.classified_purchase_total],
    ["Pagamentos e estornos", reconciliation.refund_abs_total],
    ["Diferença", reconciliation.difference],
  ].filter(([, value]) => value !== undefined && value !== null);
  if (rows.length === 0) return null;
  return (
    <div className="mt-4 rounded-control border border-ink-100 bg-surface-muted p-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
        Conferência da fatura
      </p>
      <div className="mt-2.5 grid gap-1.5 text-sm">
        {rows.map(([label, value]) => (
          <div key={label as string} className="flex items-center justify-between gap-4">
            <span className="text-xs text-ink-500">{label as string}</span>
            <span className="text-xs font-semibold tabular text-ink-800">{formatMoney(value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { showToast } = useToast();
  const { data, loading, error, run } = useAsync(loadDashboardData, []);
  const [selectedCategory, setSelectedCategory] = useState<InvoiceCategory | null>(null);
  const [connecting, setConnecting] = useState(false);

  const connectBank = async () => {
    setConnecting(true);
    try {
      await ensurePluggyConnectSdkLoaded();
      const token = await createConnectToken();
      if (!token.accessToken) throw new Error("connect-token não retornou accessToken.");
      if (!window.PluggyConnect) throw new Error("SDK Pluggy Connect indisponível.");

      new window.PluggyConnect({
        connectToken: token.accessToken,
        includeSandbox: false,
        language: "pt",
        countries: ["BR"],
        connectorIds: [200],
        onSuccess: async (payload: any) => {
          const itemId = extractPluggyItemId(payload);
          if (!itemId) {
            showToast("Banco conectado, mas o widget não retornou o ID do item.", "error");
            return;
          }
          try {
            await registerPluggyItem(itemId);
            await syncPluggyItem(itemId).catch((err) => {
              if (err instanceof Error && err.message.includes("409")) return null;
              throw err;
            });
            showToast("Banco conectado. Sincronização iniciada.", "success");
            await run();
          } catch (err) {
            showToast(err instanceof Error ? err.message : "Erro ao sincronizar banco.", "error");
          }
        },
        onError: (err: any) => {
          showToast(`Erro ao conectar banco: ${err?.message ?? JSON.stringify(err)}`, "error");
        },
      }).init();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Não foi possível conectar ao Pluggy.", "error");
    } finally {
      setConnecting(false);
    }
  };

  const dashCap = data ? dashboardAvailableToSpend(data.capacity, data.currentInvoice) : null;
  const invoiceAmount = data?.currentInvoice.amount ?? data?.currentInvoice.adjusted_total ?? 0;
  const adjustedCard = (data?.currentInvoice.cards || []).find(
    (card) => (card.adjustments || []).length > 0,
  );
  const nextInvoice = data?.upcoming?.next_invoice || null;

  const insights = useMemo(() => {
    if (!data || !dashCap) return [];
    const list: Array<{
      key: string;
      icon: React.ReactNode;
      title: string;
      body: string;
      tone: "primary" | "positive" | "warning" | "danger" | "neutral";
    }> = [];

    const income = dashCap.expectedIncome;
    const categories = [...data.categories].sort((a, b) => Number(b.total) - Number(a.total));
    const topCategory = categories[0];
    const categoriesTotal = categories.reduce((sum, item) => sum + Number(item.total || 0), 0);

    if (topCategory && categoriesTotal > 0) {
      const share = Math.round((Number(topCategory.total) / categoriesTotal) * 100);
      list.push({
        key: "top-category",
        icon: <Tags className="size-4" aria-hidden="true" />,
        title: `${topCategory.name} lidera a fatura`,
        body: `${formatMoney(topCategory.total)} em ${pluralCompras(topCategory.count ?? 0)} — ${share}% das compras classificadas.`,
        tone: "primary",
      });
    }

    if (income > 0 && Number(invoiceAmount) > 0) {
      const heavier = Number(invoiceAmount) >= dashCap.fixedCosts;
      list.push({
        key: "biggest-commitment",
        icon: <Scale className="size-4" aria-hidden="true" />,
        title: heavier ? "A fatura é o maior compromisso" : "Custos fixos são o maior compromisso",
        body: heavier
          ? `A fatura vigente (${formatMoney(invoiceAmount)}) pesa mais que os custos fixos (${formatMoney(dashCap.fixedCosts)}).`
          : `Os custos fixos (${formatMoney(dashCap.fixedCosts)}) pesam mais que a fatura vigente (${formatMoney(invoiceAmount)}).`,
        tone: heavier ? "warning" : "neutral",
      });
    }

    if (dashCap.variableBudget > 0) {
      const withinBudget = dashCap.variableRemaining >= 0;
      list.push({
        key: "variable-budget",
        icon: withinBudget ? (
          <ShieldCheck className="size-4" aria-hidden="true" />
        ) : (
          <TrendingUp className="size-4" aria-hidden="true" />
        ),
        title: withinBudget ? "Variáveis dentro do plano" : "Variáveis acima do plano",
        body: withinBudget
          ? `Ainda restam ${formatMoney(dashCap.variableRemaining)} da meta de ${formatMoney(dashCap.variableBudget)}.`
          : `Você passou ${formatMoney(Math.abs(dashCap.variableRemaining))} da meta de ${formatMoney(dashCap.variableBudget)}.`,
        tone: withinBudget ? "positive" : "warning",
      });
    }

    if (data.bankBalance && Number(invoiceAmount) > 0) {
      const covers = Number(data.bankBalance.total) >= Number(invoiceAmount);
      list.push({
        key: "bank-coverage",
        icon: <Landmark className="size-4" aria-hidden="true" />,
        title: covers ? "Saldo cobre a fatura" : "Saldo não cobre a fatura",
        body: covers
          ? `O saldo em conta (${formatMoney(data.bankBalance.total)}) é suficiente para a fatura vigente.`
          : `Faltam ${formatMoney(Number(invoiceAmount) - Number(data.bankBalance.total))} em conta para cobrir a fatura vigente.`,
        tone: covers ? "positive" : "danger",
      });
    }

    return list.slice(0, 4);
  }, [data, dashCap, invoiceAmount]);

  const statusMeta = planStatusMeta(dashCap?.status);
  const daysRemaining = data?.capacity.days_remaining_in_month ?? 0;
  const perDay =
    dashCap && dashCap.availableToSpend > 0 && daysRemaining > 0
      ? dashCap.availableToSpend / daysRemaining
      : null;

  return (
    <>
      <Topbar
        subtitle={data ? `Visão executiva de ${formatMonthLong(data.planningMonth)}` : "Visão executiva do mês"}
        actions={
          <>
            <Button type="button" onClick={() => void run()} loading={loading}>
              <RefreshCw className="size-4" aria-hidden="true" />
              Atualizar
            </Button>
            <Button type="button" variant="primary" loading={connecting} onClick={connectBank}>
              <LinkIcon className="size-4" aria-hidden="true" />
              Conectar banco
            </Button>
          </>
        }
      />
      <PageContainer>
        {loading && !data ? <LoadingState label="Preparando seu cockpit..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {data && dashCap ? (
          <div className="space-y-8">
            {/* Cockpit hero */}
            <section
              aria-label="Resumo do mês"
              className="cockpit-surface rounded-card p-6 text-white shadow-cockpit sm:p-8"
            >
              <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)] lg:gap-12">
                <div className="flex flex-col justify-between gap-6">
                  <div>
                    <div className="flex flex-wrap items-center gap-2.5">
                      <p className="text-sm font-medium text-white/70">Disponível para gastar</p>
                      <StatusPill inverse tone={statusMeta.tone} label={statusMeta.label} />
                    </div>
                    <p
                      className={`mt-3 whitespace-nowrap text-4xl font-bold leading-none tracking-tight tabular sm:text-5xl lg:text-6xl ${
                        dashCap.availableToSpend < 0 ? "text-danger-300" : "text-white"
                      }`}
                    >
                      {formatMoney(dashCap.availableToSpend)}
                    </p>
                    <p className="mt-4 max-w-md text-sm leading-relaxed text-white/60">
                      O que sobra da receita de {formatMonthLong(data.planningMonth).toLowerCase()} depois
                      dos custos fixos, da fatura vigente e da reserva para gastos variáveis.{" "}
                      {statusMeta.description}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                    <span className="inline-flex items-center gap-1.5 text-white/70">
                      <CalendarClock className="size-4 text-white/40" aria-hidden="true" />
                      {pluralize(daysRemaining, "dia restante", "dias restantes")}
                    </span>
                    {perDay ? (
                      <span className="inline-flex items-center gap-1.5 text-white/70">
                        <Wallet className="size-4 text-white/40" aria-hidden="true" />
                        <span>
                          <span className="font-semibold tabular text-white/90">{formatMoney(perDay)}</span>{" "}
                          por dia
                        </span>
                      </span>
                    ) : null}
                    <Link
                      to="/planejamento"
                      className="inline-flex items-center gap-1 font-medium text-primary-300 transition-colors hover:text-primary-200"
                    >
                      Ajustar plano do mês
                      <ArrowUpRight className="size-3.5" aria-hidden="true" />
                    </Link>
                  </div>
                </div>
                <div className="rounded-card border border-white/10 bg-white/5 p-5 backdrop-blur-sm">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/50">
                    Composição do mês
                  </p>
                  <FinancialFlow
                    className="mt-4"
                    inverse
                    total={dashCap.expectedIncome}
                    segments={[
                      { key: "fixed", label: "Custos fixos", value: dashCap.fixedCosts, color: "#64748b" },
                      { key: "invoice", label: "Fatura vigente", value: Number(invoiceAmount), color: "#38bdf8" },
                      { key: "variable", label: "Meta variável", value: dashCap.variableBudget, color: "#a78bfa" },
                    ]}
                    remainder={{ label: "Disponível", value: dashCap.availableToSpend }}
                  />
                  <p className="mt-4 border-t border-white/10 pt-3 text-xs text-white/50">
                    Receita esperada de{" "}
                    <span className="font-semibold tabular text-white/80">
                      {formatMoney(dashCap.expectedIncome)}
                    </span>{" "}
                    em {formatMonthShort(data.planningMonth)}
                  </p>
                </div>
              </div>
            </section>

            {/* KPI row — the four headline numbers of the month */}
            <section
              aria-label={`Indicadores de ${formatMonthShort(data.planningMonth)}`}
              className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
            >
              <MetricCard
                label="Entradas recebidas"
                value={formatMoney(data.capacity.received_income_total)}
                subtitle="Crédito que já caiu na conta"
                tone="positive"
                icon={<Banknote className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="Custos fixos"
                value={formatMoney(dashCap.fixedCosts)}
                subtitle={`${pluralItens(data.capacity.fixed_costs?.entries?.length ?? 0)} reservados ou pagos`}
                icon={<Wallet className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="Variável usado"
                value={formatMoney(dashCap.variableUsed)}
                subtitle={`Meta ${formatMoney(dashCap.variableBudget)} · restam ${formatMoney(dashCap.variableRemaining)}`}
                icon={<Tags className="size-4" aria-hidden="true" />}
              />
              <MetricCard
                label="Saldo em conta"
                value={data.bankBalance ? formatMoney(data.bankBalance.total) : "—"}
                subtitle={
                  data.bankBalance
                    ? pluralize(
                        data.bankBalance.account_count,
                        "conta ativa considerada",
                        "contas ativas consideradas",
                      )
                    : "Saldo indisponível agora; o restante segue atualizado"
                }
                tone="primary"
                icon={<Landmark className="size-4" aria-hidden="true" />}
              />
            </section>

            {/* Pressure + quick readings, side by side */}
            {dashCap.expectedIncome > 0 || insights.length ? (
              <section
                aria-label="Pressão e leituras do mês"
                className="grid grid-cols-1 gap-4 lg:grid-cols-2"
              >
                {dashCap.expectedIncome > 0 ? (
                  <Card className="p-5 sm:p-6">
                    <div className="mb-5 flex items-baseline justify-between gap-3">
                      <h2 className="text-sm font-semibold text-ink-900">Pressão do mês</h2>
                      <p className="text-xs text-ink-500">quanto da receita cada bloco consome</p>
                    </div>
                    <div className="space-y-5">
                      <PressureMeter
                        label="Fatura no mês"
                        value={(Number(invoiceAmount) / dashCap.expectedIncome) * 100}
                        detail={formatMoney(invoiceAmount)}
                      />
                      <PressureMeter
                        label="Custos fixos"
                        value={(dashCap.fixedCosts / dashCap.expectedIncome) * 100}
                        detail={formatMoney(dashCap.fixedCosts)}
                      />
                      <PressureMeter
                        label="Meta variável usada"
                        value={
                          dashCap.variableBudget > 0
                            ? (dashCap.variableUsed / dashCap.variableBudget) * 100
                            : 0
                        }
                        detail={`${formatMoney(dashCap.variableUsed)} de ${formatMoney(dashCap.variableBudget)}`}
                      />
                    </div>
                  </Card>
                ) : null}
                {insights.length ? (
                  <div className="grid grid-cols-1 gap-3">
                    {insights.map((insight) => (
                      <InsightCard
                        key={insight.key}
                        icon={insight.icon}
                        title={insight.title}
                        body={insight.body}
                        tone={insight.tone}
                      />
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}

            {/* Current invoice + categories */}
            <section>
              <SectionHeader
                title="Fatura vigente"
                subtitle="Para onde as compras do cartão estão indo"
              />
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
                <Card className="h-fit p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs font-medium text-ink-500">
                        {invoiceSourceLabel(
                          data.currentInvoice.source,
                          data.currentInvoice.source_label || "Fatura vigente",
                        )}
                      </p>
                      <p className="mt-1.5 text-3xl font-bold tracking-tight tabular text-ink-900">
                        {formatMoney(invoiceAmount)}
                      </p>
                    </div>
                    <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-control bg-primary-50 text-primary-600">
                      <CreditCard className="size-4" aria-hidden="true" />
                    </span>
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-ink-500">
                    {adjustedCard
                      ? `Saldo do cartão de ${formatMoney(adjustedCard.raw_balance)}, já descontada a fatura anterior de ${formatMoney(adjustedCard.latest_bill_amount)}.`
                      : "Valor considerado no cálculo do disponível para gastar."}
                  </p>
                  <InvoiceReconciliation reconciliation={data.currentInvoice.reconciliation} />
                  {nextInvoice ? (
                    <div className="mt-4 flex items-start gap-2.5 rounded-control border border-ink-100 bg-surface-muted p-3.5">
                      <CalendarDays className="mt-0.5 size-4 shrink-0 text-ink-400" aria-hidden="true" />
                      <div className="min-w-0 text-xs leading-relaxed text-ink-500">
                        <p>
                          Próxima fatura ({formatMonthLong(nextInvoice.year_month)}):{" "}
                          <span className="font-semibold tabular text-ink-800">
                            {formatMoney(nextInvoice.amount)}
                          </span>
                        </p>
                        <Link
                          to="/proximos"
                          className="mt-0.5 inline-block font-medium text-primary-700 hover:text-primary-800"
                        >
                          Ver compromissos futuros
                        </Link>
                      </div>
                    </div>
                  ) : null}
                </Card>
                <div>
                  {data.categories.length === 0 ? (
                    <EmptyState
                      icon={<Tags className="size-5" aria-hidden="true" />}
                      title="Nenhuma compra categorizada na fatura vigente."
                      detail="Assim que houver compras ativas classificadas, a leitura por categoria aparece aqui."
                    />
                  ) : (
                    <CategoryBreakdown
                      items={data.categories.map((category) => ({
                        id: category.id,
                        name: category.name,
                        total: Number(category.total),
                        count: category.count ?? 0,
                        color: category.color,
                      }))}
                      onSelect={(id) =>
                        setSelectedCategory(
                          data.categories.find((category) => String(category.id) === String(id)) || null,
                        )
                      }
                    />
                  )}
                </div>
              </div>
            </section>

            {/* Recent card purchases */}
            <section>
              <SectionHeader
                title="Últimas compras do cartão"
                subtitle="As compras mais recentes da fatura vigente"
              />
              {data.recentCardPurchases.length === 0 ? (
                <EmptyState
                  icon={<CreditCard className="size-5" aria-hidden="true" />}
                  title="Nenhuma compra recente na fatura vigente."
                  detail="Quando houver compras ativas no cartão, elas aparecem aqui."
                />
              ) : (
                <Card className="overflow-hidden">
                  <Table>
                    <thead className="bg-surface-muted text-left text-xs font-medium uppercase tracking-wide text-ink-500">
                      <tr>
                        <th className="px-5 py-2.5">Data</th>
                        <th className="px-5 py-2.5">Compra</th>
                        <th className="px-5 py-2.5">Categoria</th>
                        <th className="px-5 py-2.5 text-right">Valor</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-100 bg-surface">
                      {data.recentCardPurchases.map((tx) => (
                        <tr key={tx.id} className="transition-colors hover:bg-surface-muted">
                          <td className="whitespace-nowrap px-5 py-3.5 text-sm text-ink-500">
                            {formatDayLabel(tx.date)}
                          </td>
                          <td className="px-5 py-3.5">
                            <p className="max-w-[34rem] truncate text-sm font-medium text-ink-900">
                              {tx.description}
                            </p>
                            {tx.installment_number && tx.total_installments ? (
                              <p className="mt-0.5 text-xs text-ink-500">
                                Parcela {tx.installment_number} de {tx.total_installments}
                              </p>
                            ) : null}
                          </td>
                          <td className="px-5 py-3.5 text-sm text-ink-600">
                            {transactionDisplayCategory(tx) || "Sem categoria"}
                            {classificationSourceLabel(tx.classification_source) ? (
                              <span className="block text-xs text-ink-400">
                                {classificationSourceLabel(tx.classification_source)}
                              </span>
                            ) : null}
                          </td>
                          <td className="whitespace-nowrap px-5 py-3.5 text-right text-sm font-semibold tabular text-ink-900">
                            {formatMoney(tx.amount)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </Card>
              )}
            </section>
          </div>
        ) : null}
      </PageContainer>

      <Modal
        open={!!selectedCategory}
        title={selectedCategory?.name || ""}
        subtitle={
          selectedCategory
            ? `${pluralCompras(selectedCategory.count ?? 0)} · ${formatMoney(selectedCategory.total)}`
            : undefined
        }
        onClose={() => setSelectedCategory(null)}
      >
        <ul className="divide-y divide-ink-100">
          {(selectedCategory?.transactions || []).map((tx) => (
            <li key={tx.id} className="flex items-baseline justify-between gap-4 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-900">{tx.description}</p>
                <p className="mt-0.5 text-xs text-ink-500">
                  {formatDayLabel(tx.date)}
                  {tx.installment_number && tx.total_installments
                    ? ` · parcela ${tx.installment_number} de ${tx.total_installments}`
                    : ""}
                  {classificationSourceLabel(tx.classification_source)
                    ? ` · ${classificationSourceLabel(tx.classification_source)}`
                    : ""}
                </p>
              </div>
              <span className="shrink-0 text-sm font-semibold tabular text-ink-900">
                {formatMoney(tx.amount)}
              </span>
            </li>
          ))}
          {selectedCategory?.transactions?.length ? null : (
            <li className="px-5 py-8 text-center text-sm text-ink-500">Sem compras detalhadas.</li>
          )}
        </ul>
      </Modal>
    </>
  );
}
