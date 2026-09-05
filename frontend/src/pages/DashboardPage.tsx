import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  CalendarClock,
  CreditCard,
  Link as LinkIcon,
  RefreshCw,
  Search,
  Wallet,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  createConnectToken,
  getBankConnections,
  getCurrentInvoice,
  getPlanningMonth,
  registerPluggyItem,
  syncPluggyItem,
} from "../api/dashboard";
import { ApiError } from "../api/client";
import { Topbar } from "../components/layout/Topbar";
import { PageContainer } from "../components/layout/PageContainer";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { CategoryBreakdown } from "../components/ui/CategoryBreakdown";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState, StaleDataWarning } from "../components/ui/ErrorState";
import { FinancialFlow } from "../components/ui/FinancialFlow";
import { Input } from "../components/ui/Input";
import { LoadingState } from "../components/ui/LoadingState";
import { Modal } from "../components/ui/Modal";
import { SectionHeader } from "../components/ui/SectionHeader";
import { StatusPill } from "../components/ui/StatusPill";
import { Table } from "../components/ui/Table";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { currentYearMonth, formatDayLabel, formatMonthLong, formatMonthShort } from "../lib/dates";
import { pluralCompras, pluralize } from "../lib/labels";
import { dashboardAvailableToSpend, normalizePlanningOverview, planStatusMeta } from "../lib/planning";
import { extractPluggyItemId, ensurePluggyConnectSdkLoaded } from "../lib/pluggy";
import { formatMoney } from "../lib/money";
import type { Transaction } from "../types/common";
import type { InvoiceCategory } from "../types/planejamento";

const INITIAL_RECENT_CARD_PURCHASE_LIMIT = 8;
const RECENT_CARD_PURCHASE_INCREMENT = 8;
const MAX_RECENT_CARD_PURCHASE_LIMIT = 50;

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
    .slice(0, MAX_RECENT_CARD_PURCHASE_LIMIT);
}

function transactionDisplayCategory(tx: Transaction) {
  return tx.effective_category || tx.resolved_category || tx.credit_category || tx.internal_category || tx.category;
}

async function loadDashboardData() {
  const planningMonth = currentYearMonth();
  const [planning, currentInvoice, connectionsResult] = await Promise.all([
    getPlanningMonth(planningMonth),
    getCurrentInvoice(),
    getBankConnections().then(
      (value) => ({ status: "fulfilled" as const, value }),
      () => ({ status: "rejected" as const }),
    ),
  ]);
  const partialErrors: string[] = [];
  if (connectionsResult.status === "rejected") partialErrors.push("conexões bancárias");
  const capacity = normalizePlanningOverview(planning);
  return {
    planningMonth,
    capacity,
    currentInvoice,
    hasActiveConnection:
      connectionsResult.status === "fulfilled"
        ? connectionsResult.value.some((connection) => connection.is_active)
        : null,
    partialErrors,
    categories: currentInvoice.categories || [],
    recentCardPurchases: latestCardPurchases(
      currentInvoice.recent_purchase_transactions || currentInvoice.raw_purchase_transactions || [],
    ),
  };
}

export function DashboardPage() {
  const { showToast } = useToast();
  const { data, loading, error, run } = useAsync(loadDashboardData);
  const [selectedCategory, setSelectedCategory] = useState<InvoiceCategory | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [purchaseSearch, setPurchaseSearch] = useState("");
  const [visibleRecentPurchaseCount, setVisibleRecentPurchaseCount] = useState(
    INITIAL_RECENT_CARD_PURCHASE_LIMIT,
  );

  useEffect(() => {
    setVisibleRecentPurchaseCount(INITIAL_RECENT_CARD_PURCHASE_LIMIT);
  }, [data?.currentInvoice]);

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
            const syncResult = await syncPluggyItem(itemId).catch((err) => {
              if (err instanceof ApiError && err.status === 409) return null;
              throw err;
            });
            if (syncResult === null) {
              showToast("Banco conectado. Já existe uma sincronização em andamento.");
            } else if (syncResult.failed_accounts.length > 0) {
              showToast(
                `Banco conectado, mas ${syncResult.failed_accounts.length} conta(s) falharam ao sincronizar.`,
                "error",
              );
            } else {
              showToast("Banco conectado e sincronizado.", "success");
            }
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

  const statusMeta = planStatusMeta(dashCap?.status);
  const daysRemaining = data?.capacity.days_remaining_in_month ?? 0;
  const perDay =
    dashCap && dashCap.availableToSpend > 0 && daysRemaining > 0
      ? dashCap.availableToSpend / daysRemaining
      : null;
  const hasFinancialData = Boolean(
    dashCap &&
      (dashCap.expectedIncome > 0 ||
        dashCap.fixedCosts > 0 ||
        Number(invoiceAmount) !== 0 ||
        data?.hasActiveConnection),
  );
  const searchTerm = purchaseSearch.trim().toLocaleLowerCase("pt-BR");
  const filteredPurchases = (data?.recentCardPurchases || []).filter((tx) =>
    `${tx.description} ${transactionDisplayCategory(tx) || ""}`.toLocaleLowerCase("pt-BR").includes(searchTerm),
  );

  return (
    <>
      <Topbar
        subtitle={data ? formatMonthLong(data.planningMonth) : undefined}
        actions={
          <>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label="Atualizar"
              title="Atualizar"
              onClick={() => void run()}
              loading={loading}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Atualizar
            </Button>
            {data?.hasActiveConnection === false ? (
              <Button type="button" variant="primary" loading={connecting} onClick={connectBank}>
                <LinkIcon className="size-4" aria-hidden="true" />
                Conectar banco
              </Button>
            ) : null}
          </>
        }
      />
      <PageContainer>
        {loading && !data ? <LoadingState label="Carregando resumo..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {error && data ? (
          <StaleDataWarning message={error} loading={loading} onRetry={() => void run()} />
        ) : null}
        {data?.partialErrors.length ? (
          <StaleDataWarning
            message={`Dados parciais: não foi possível carregar ${data.partialErrors.join(" e ")}.`}
            loading={loading}
            onRetry={() => void run()}
          />
        ) : null}
        {data && dashCap ? (
          hasFinancialData ? (
            <div className="space-y-8" aria-busy={loading}>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="page-eyebrow">Visão geral</p>
                <p className="mt-1 text-sm text-ink-600">Seu mês, dos compromissos à liberdade para gastar.</p>
              </div>
              <Link to="/historico" className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-700 hover:text-primary-900">
                Explorar histórico <ArrowUpRight className="size-4" aria-hidden="true" />
              </Link>
            </div>
            <div className="grid items-stretch gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
            <section
              aria-label="Resumo do mês"
              className="cockpit-surface rounded-card p-6 text-white shadow-cockpit sm:p-8"
            >
              <div className="grid grid-cols-1 gap-7">
                <div className="flex flex-col justify-between gap-6">
                  <div>
                    <div className="flex flex-wrap items-center gap-2.5">
                      <p className="text-sm font-medium text-white/70">Disponível para gastar</p>
                      <StatusPill inverse tone={statusMeta.tone} label={statusMeta.label} />
                    </div>
                    <p
                      className={`mt-4 break-words text-[clamp(1.8rem,4vw,3.5rem)] font-semibold leading-tight tracking-tight tabular ${
                        dashCap.availableToSpend < 0 ? "text-danger-300" : "text-white"
                      }`}
                    >
                      {formatMoney(dashCap.availableToSpend)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                    <span className="inline-flex items-center gap-1.5 text-white/70">
                      <CalendarClock className="size-4 text-primary-200" aria-hidden="true" />
                      {pluralize(daysRemaining, "dia restante", "dias restantes")}
                    </span>
                    {perDay ? (
                      <span className="inline-flex items-center gap-1.5 text-white/70">
                        <Wallet className="size-4 text-primary-200" aria-hidden="true" />
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
                      Abrir planejamento
                      <ArrowUpRight className="size-3.5" aria-hidden="true" />
                    </Link>
                  </div>
                </div>
                <div className="border-t border-white/15 pt-5">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary-100/80">
                    Composição do mês
                  </p>
                  <FinancialFlow
                    className="mt-4"
                    inverse
                    total={dashCap.expectedIncome}
                    segments={[
                      { key: "fixed", label: "Custos fixos", value: dashCap.fixedCosts, color: "#fbbf24" },
                      { key: "invoice", label: "Fatura vigente", value: Number(invoiceAmount), color: "#fda4af" },
                    ]}
                    remainder={{ label: "Disponível", value: dashCap.availableToSpend }}
                  />
                  <p className="mt-4 text-xs text-primary-100/80">
                    Receita esperada de{" "}
                    <span className="font-semibold tabular text-white/80">
                      {formatMoney(dashCap.expectedIncome)}
                    </span>{" "}
                    em {formatMonthShort(data.planningMonth)}
                  </p>
                </div>
              </div>
            </section>

            <section
              aria-label={`Indicadores de ${formatMonthShort(data.planningMonth)}`}
              className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-1"
            >
              <Card className="flex min-w-0 flex-col justify-between p-5 sm:p-6">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-medium text-ink-600">Fatura em aberto</h2>
                  <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-control bg-danger-50 text-danger-600">
                    <CreditCard className="size-5" aria-hidden="true" />
                  </span>
                </div>
                <p className="mt-3 break-words text-3xl font-semibold leading-tight tracking-tight tabular text-ink-900">
                  {formatMoney(invoiceAmount)}
                </p>
                <Link to="/proximos" className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-primary-700 hover:underline">
                  Ver faturas e parcelas <ArrowUpRight className="size-3.5" aria-hidden="true" />
                </Link>
              </Card>
              {[
                { label: "Custos fixos a pagar", value: dashCap.fixedCostsPending, Icon: Wallet },
              ].map(({ label, value, Icon }) => (
                <Card key={label} className="flex min-w-0 flex-col justify-between gap-3 p-5 sm:p-6">
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-sm font-medium text-ink-600">{label}</h2>
                    <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-control bg-warning-50 text-warning-700">
                      <Icon className="size-4" aria-hidden="true" />
                    </span>
                  </div>
                  <p className="text-2xl font-bold leading-tight tracking-tight tabular text-ink-900 lg:text-3xl">
                    {formatMoney(value)}
                  </p>
                  <Link to="/planejamento?tab=custos" className="inline-flex items-center gap-1 text-xs font-semibold text-primary-700 hover:underline">
                    Gerenciar custos recorrentes <ArrowUpRight className="size-3.5" aria-hidden="true" />
                  </Link>
                </Card>
              ))}
            </section>
            </div>

            {/* Categories use the full width, without an empty invoice column. */}
            {data.categories.length ? (
              <section aria-label="Categorias da fatura">
                <SectionHeader title="Onde se concentram os gastos" subtitle="Categorias da fatura · selecione uma categoria para ver os lançamentos." />
                <CategoryBreakdown
                  className="sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2 xl:grid-cols-3"
                  items={data.categories.map((category) => ({
                    id: category.id,
                    name: category.name,
                    total: Number(category.total),
                    count: category.count ?? 0,
                    color: category.color,
                    subtitle:
                      category.name === "Créditos / Estornos"
                        ? pluralize(category.count ?? 0, "crédito", "créditos")
                        : undefined,
                  }))}
                  onSelect={(id) =>
                    setSelectedCategory(
                      data.categories.find((category) => String(category.id) === String(id)) || null,
                    )
                  }
                />
              </section>
            ) : null}

            {/* Recent card purchases */}
            {data.recentCardPurchases.length ? (
              <section>
                <SectionHeader title="Últimas compras do cartão" subtitle="Acompanhe os lançamentos mais recentes e suas categorias." action={
                  <label className="relative block w-full sm:w-64">
                    <Search className="pointer-events-none absolute left-3 top-3 size-4 text-ink-400" aria-hidden="true" />
                    <Input aria-label="Buscar nas últimas compras" placeholder="Buscar compra ou categoria" className="pl-9" value={purchaseSearch} onChange={(event) => { setPurchaseSearch(event.target.value); setVisibleRecentPurchaseCount(INITIAL_RECENT_CARD_PURCHASE_LIMIT); }} />
                  </label>
                } />
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
                      {filteredPurchases
                        .slice(0, visibleRecentPurchaseCount)
                        .map((tx) => (
                          <tr key={tx.id} className="transition-colors hover:bg-surface-muted">
                            <td className="whitespace-nowrap px-5 py-3.5 text-sm text-ink-500">
                              {formatDayLabel(tx.date)}
                            </td>
                            <td className="px-5 py-3.5">
                              <p className="min-w-40 max-w-[34rem] text-sm font-medium text-ink-900">
                                {tx.description}
                              </p>
                              {tx.installment_number && tx.total_installments ? (
                                <p className="mt-0.5 text-xs text-ink-500">
                                  Parcela {tx.installment_number} de {tx.total_installments}
                                </p>
                              ) : null}
                            </td>
                            <td className="px-5 py-3.5 text-sm text-ink-600">
                              <span className="inline-flex rounded-md bg-surface-sunken px-2 py-1 text-xs font-medium text-ink-600">{transactionDisplayCategory(tx) || "Sem categoria"}</span>
                              {tx.classification_source === "manual_override" ? (
                                <span className="block text-xs text-ink-400">Ajuste manual</span>
                              ) : null}
                            </td>
                            <td className="whitespace-nowrap px-5 py-3.5 text-right text-sm font-semibold tabular text-ink-900">
                              {formatMoney(tx.amount)}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </Table>
                  {!filteredPurchases.length ? <p className="px-5 py-10 text-center text-sm text-ink-500">Nenhuma compra corresponde à busca. Tente outro nome ou categoria.</p> : null}
                  {visibleRecentPurchaseCount < filteredPurchases.length ? (
                    <div className="flex justify-center border-t border-ink-100 bg-surface px-5 py-4">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() =>
                          setVisibleRecentPurchaseCount((current) =>
                            Math.min(
                              current + RECENT_CARD_PURCHASE_INCREMENT,
                              MAX_RECENT_CARD_PURCHASE_LIMIT,
                            ),
                          )
                        }
                      >
                        Ver mais
                      </Button>
                    </div>
                  ) : null}
                </Card>
              </section>
            ) : null}
            </div>
          ) : (
            <EmptyState
              icon={<Wallet className="size-5" aria-hidden="true" />}
              title="Configure seu primeiro mês"
              detail="Adicione sua receita e seus compromissos para montar o resumo financeiro."
              action={
                <Link
                  to="/planejamento"
                  className="inline-flex min-h-9 items-center justify-center rounded-control bg-primary-600 px-3.5 py-1.5 text-sm font-medium text-white hover:bg-primary-700"
                >
                  Abrir planejamento
                </Link>
              }
            />
          )
        ) : null}
      </PageContainer>

      <Modal
        open={!!selectedCategory}
        title={selectedCategory?.name || ""}
        subtitle={
          selectedCategory
            ? `${
                selectedCategory.name === "Créditos / Estornos"
                  ? pluralize(selectedCategory.count ?? 0, "crédito", "créditos")
                  : pluralCompras(selectedCategory.count ?? 0)
              } · ${formatMoney(selectedCategory.total)}`
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
                  {tx.classification_source === "manual_override" ? " · ajuste manual" : ""}
                </p>
              </div>
              <span className="shrink-0 text-sm font-semibold tabular text-ink-900">
                {formatMoney(tx.signed_amount ?? tx.amount)}
              </span>
            </li>
          ))}
          {selectedCategory?.transactions?.length ? null : (
            <li className="px-5 py-8 text-center text-sm text-ink-500">Não há lançamentos detalhados disponíveis para esta categoria na fatura atual.</li>
          )}
        </ul>
      </Modal>
    </>
  );
}
