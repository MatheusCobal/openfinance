import { useState } from "react";
import {
  ArrowUpRight,
  Banknote,
  CalendarDays,
  CreditCard,
  Link as LinkIcon,
  RefreshCw,
  Tags,
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
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingState } from "../components/ui/LoadingState";
import { MetricCard } from "../components/ui/MetricCard";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Table } from "../components/ui/Table";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../hooks/useToast";
import { formatDayLabel, formatMonthLong, formatMonthShort, getDefaultPlanningMonth } from "../lib/dates";
import { dashboardAvailableToSpend, normalizePlanningOverview, planStatusLabel } from "../lib/planning";
import { extractPluggyItemId, ensurePluggyConnectSdkLoaded } from "../lib/pluggy";
import { formatMoney } from "../lib/money";
import type { Transaction } from "../types/common";

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
    recentCardPurchases: latestCardPurchases(currentInvoice.raw_purchase_transactions || []),
  };
}

function statusTone(status: string) {
  if (status === "over") return "rose";
  if (status === "tight") return "amber";
  if (status === "unknown") return "slate";
  return "emerald";
}

function InvoiceReconciliation({ reconciliation }: { reconciliation?: Record<string, any> }) {
  if (!reconciliation) return null;
  const rows = [
    ["Compras classificadas", reconciliation.classified_purchase_total],
    ["Pagamentos/estornos", reconciliation.refund_abs_total],
    ["Diferença", reconciliation.difference],
  ].filter(([, value]) => value !== undefined && value !== null);
  if (rows.length === 0) return null;
  return (
    <div className="mt-5 rounded-lg border border-slate-100 bg-slate-50/80 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Reconciliação</p>
      <div className="mt-3 grid gap-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label as string} className="flex items-center justify-between gap-4">
            <span className="text-slate-500">{label as string}</span>
            <span className="font-semibold tabular text-slate-800">{formatMoney(value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { showToast } = useToast();
  const { data, loading, error, run } = useAsync(loadDashboardData, []);
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
  const adjustedCard = (data?.currentInvoice.cards || []).find((card) => (card.adjustments || []).length > 0);

  return (
    <>
      <Topbar
        subtitle={data ? `Planejamento de ${formatMonthLong(data.planningMonth)}` : "Resumo executivo"}
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
        {loading && !data ? <LoadingState label="Carregando dashboard..." /> : null}
        {error && !data ? <ErrorState message={error} onRetry={() => void run()} /> : null}
        {data && dashCap ? (
          <div className="space-y-8">
            <Card className="bg-slate-950 p-6 text-white">
              <div className="flex min-h-[190px] flex-col justify-between gap-6">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-slate-300">Disponível para gastar</p>
                  <Badge tone={statusTone(dashCap.status)}>{planStatusLabel(dashCap.status)}</Badge>
                </div>
                <div>
                  <p className="text-4xl font-bold leading-tight tabular sm:text-5xl">
                    {formatMoney(dashCap.availableToSpend)}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-slate-400">
                    <span>{formatMonthLong(data.planningMonth)}</span>
                    <span>{data.capacity.days_remaining_in_month ?? 0} dias restantes</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">
                    Fatura vigente no cálculo:{" "}
                    <span className="font-medium text-slate-200">
                      {formatMoney(dashCap.currentInvoiceAmount)}
                    </span>
                  </p>
                </div>
                <p className="text-sm text-slate-400">
                  Plano detalhado em{" "}
                  <Link to="/planejamento" className="font-medium text-white hover:underline">
                    Planejamento
                  </Link>
                </p>
              </div>
            </Card>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <Card className="p-6">
                <div className="flex min-h-[160px] flex-col justify-between gap-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-slate-500">Saldo bancário</p>
                      <p className="mt-3 text-3xl font-semibold text-slate-950 tabular">
                        {data.bankBalance ? formatMoney(data.bankBalance.total) : "-"}
                      </p>
                    </div>
                    <span className="inline-flex size-10 items-center justify-center rounded-md bg-blue-50 text-blue-700">
                      <Wallet className="size-5" aria-hidden="true" />
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed text-slate-500">
                    {data.bankBalance
                      ? `${data.bankBalance.account_count} contas ativas · fonte ${data.bankBalance.source}`
                      : "Saldo indisponível agora; o restante do Dashboard segue carregado."}
                  </p>
                </div>
              </Card>

              <Card className="p-6">
                <div className="flex min-h-[160px] flex-col justify-between gap-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-slate-500">Fatura do cartão</p>
                      <p className="mt-3 text-3xl font-semibold text-slate-950 tabular">
                        {formatMoney(invoiceAmount)}
                      </p>
                    </div>
                    <span className="inline-flex size-10 items-center justify-center rounded-md bg-amber-50 text-amber-700">
                      <CreditCard className="size-5" aria-hidden="true" />
                    </span>
                  </div>
                  <div className="space-y-1 text-xs leading-relaxed text-slate-500">
                    <p className="text-sm text-slate-600">
                      {data.currentInvoice.source_label || "Fatura vigente ajustada"}
                    </p>
                    <p>
                      {adjustedCard
                        ? `Saldo Pluggy ajustado: ${formatMoney(adjustedCard.raw_balance)} - fatura anterior ${formatMoney(
                            adjustedCard.latest_bill_amount,
                          )}`
                        : "Saldo Pluggy ajustado"}
                    </p>
                  </div>
                </div>
                <InvoiceReconciliation reconciliation={data.currentInvoice.reconciliation} />
              </Card>

              <Card className="p-6">
                <div className="flex min-h-[160px] flex-col justify-between gap-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-slate-500">Próxima fatura</p>
                      <p className="mt-3 text-3xl font-semibold text-slate-950 tabular">
                        {data.upcoming?.next_invoice
                          ? formatMoney(data.upcoming.next_invoice.amount)
                          : "-"}
                      </p>
                    </div>
                    <span className="inline-flex size-10 items-center justify-center rounded-md bg-indigo-50 text-indigo-700">
                      <CalendarDays className="size-5" aria-hidden="true" />
                    </span>
                  </div>
                  <div className="space-y-2 text-xs leading-relaxed text-slate-500">
                    <p className="text-sm text-slate-600">
                      {data.upcoming?.next_invoice
                        ? `${formatMonthLong(data.upcoming.next_invoice.year_month)} · ${
                            data.upcoming.next_invoice.source_label || "Fatura vigente"
                          }`
                        : "Próximos indisponível agora."}
                    </p>
                    <Link to="/proximos" className="font-medium text-blue-700 hover:text-blue-800">
                      Ver próximos gastos
                    </Link>
                  </div>
                </div>
              </Card>
            </div>

            <section>
              <SectionHeader title="Resumo do mês" subtitle={formatMonthShort(data.planningMonth)} />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <MetricCard
                  label="Entradas"
                  value={formatMoney(data.capacity.received_income_total)}
                  subtitle="Entradas bancárias reais"
                  tone="emerald"
                  icon={<Banknote className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Saídas"
                  value={formatMoney(data.capacity.bank_outflows_total)}
                  subtitle="Saídas bancárias reais"
                  tone="rose"
                  icon={<ArrowUpRight className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="A receber"
                  value={formatMoney(data.capacity.income_to_receive)}
                  subtitle="Receitas previstas para o mês"
                  tone="amber"
                  icon={<Banknote className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Custos fixos"
                  value={formatMoney(dashCap.fixedCosts)}
                  subtitle={`${data.capacity.fixed_costs?.entries?.length ?? 0} itens no planejamento`}
                  icon={<Wallet className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Variável usado"
                  value={formatMoney(dashCap.variableUsed)}
                  subtitle={`Meta ${formatMoney(dashCap.variableBudget)} · restante ${formatMoney(
                    dashCap.variableRemaining,
                  )}`}
                  icon={<Tags className="size-4" aria-hidden="true" />}
                />
                <MetricCard
                  label="Fatura vigente"
                  value={formatMoney(invoiceAmount)}
                  subtitle="Fonte operacional do Dashboard"
                  tone="blue"
                  icon={<CreditCard className="size-4" aria-hidden="true" />}
                />
              </div>
            </section>

            <section>
              <SectionHeader
                title="Últimas compras do cartão"
                subtitle="Compras mais recentes da fatura vigente"
              />
              {data.recentCardPurchases.length === 0 ? (
                <EmptyState
                  title="Nenhuma compra recente na fatura vigente."
                  detail="Quando houver compras ativas no cartão, elas aparecem aqui."
                />
              ) : (
                <Card className="overflow-hidden">
                  <Table>
                    <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-5 py-3">Data</th>
                        <th className="px-5 py-3">Compra</th>
                        <th className="px-5 py-3">Classificação</th>
                        <th className="px-5 py-3 text-right">Valor</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {data.recentCardPurchases.map((tx) => (
                        <tr key={tx.id}>
                          <td className="whitespace-nowrap px-5 py-4 text-sm text-slate-500">
                            {formatDayLabel(tx.date)}
                          </td>
                          <td className="px-5 py-4">
                            <p className="max-w-[34rem] truncate text-sm font-medium text-slate-950">
                              {tx.description}
                            </p>
                            {tx.installment_number && tx.total_installments ? (
                              <p className="mt-1 text-xs text-slate-500">
                                Parcela {tx.installment_number}/{tx.total_installments}
                              </p>
                            ) : null}
                          </td>
                          <td className="px-5 py-4 text-sm text-slate-600">
                            {tx.internal_category || tx.category || "Sem classificação"}
                          </td>
                          <td className="whitespace-nowrap px-5 py-4 text-right text-sm font-semibold tabular text-slate-950">
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
    </>
  );
}
