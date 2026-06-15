// ── Dashboard — reorganized concept (with product shell / sidebar)
const O = window.OFX;
const DB = window.OFX_DATA;
const { money: mD, money0: m0D, pct: pcD } = DB;

const DASH = {
  income: 10000, received: 8500, toReceive: 1500,
  fixed: 4779.70, invoice: 2340.00, variable: 1800, variableUsed: 980,
  bank: 6420.00, daysLeft: 17,
};
DASH.available = DASH.income - DASH.fixed - DASH.invoice - DASH.variable; // 1080.30
DASH.perDay = DASH.available / DASH.daysLeft;

const INVOICE_CATS = [
  { name: "Alimentação", total: 720, color: "#ea580c", count: 18 },
  { name: "Mercado", total: 540, color: "#16a34a", count: 6 },
  { name: "Transporte", total: 310, color: "#2563eb", count: 22 },
  { name: "Compras", total: 280, color: "#db2777", count: 4 },
  { name: "Lazer", total: 240, color: "#0d9488", count: 7 },
  { name: "Outros", total: 250, color: "#64748b", count: 9 },
];

const NAV = [
  { label: "Dashboard", icon: "gauge", active: true },
  { label: "Planejamento", icon: "list" },
  { label: "Próximos", icon: "clock" },
  { label: "Histórico", icon: "trendingUp" },
  { label: "Regras", icon: "sliders" },
];

function DashSidebar() {
  return (
    <aside className="flex w-[228px] shrink-0 flex-col bg-cockpit">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <span className="flex size-8 items-center justify-center rounded-control bg-primary-600 text-white"><O.Icon name="wallet" className="size-4" /></span>
        <span>
          <span className="block text-sm font-semibold leading-tight text-white">OpenFinance</span>
          <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-ink-500">Cockpit financeiro</span>
        </span>
      </div>
      <nav className="flex-1 space-y-0.5 px-3 py-3">
        {NAV.map((n) => (
          <a key={n.label} className={`group relative flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm font-medium ${n.active ? "bg-white/10 text-white" : "text-ink-400 hover:bg-white/5"}`}>
            {n.active ? <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary-400" /> : null}
            <O.Icon name={n.icon} className="size-4" />{n.label}
          </a>
        ))}
      </nav>
      <div className="border-t border-white/5 px-5 py-4">
        <p className="text-[11px] leading-relaxed text-ink-500">Seu mês, suas regras.<br />Dados via Open Finance.</p>
      </div>
    </aside>
  );
}

function DashMetric({ label, value, sub, tone = "neutral", icon }) {
  const tones = { neutral: "bg-ink-100 text-ink-600", primary: "bg-primary-50 text-primary-600", positive: "bg-positive-50 text-positive-600", warning: "bg-warning-50 text-warning-600", danger: "bg-danger-50 text-danger-600" };
  return (
    <div className="rounded-card border border-ink-200/70 bg-surface p-4 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink-500">{label}</p>
          <p className="mt-1.5 text-2xl font-bold tabular leading-tight tracking-tight text-ink-900">{value}</p>
        </div>
        {icon ? <span className={`inline-flex size-9 shrink-0 items-center justify-center rounded-control ${tones[tone]}`}><O.Icon name={icon} className="size-4" /></span> : null}
      </div>
      {sub ? <p className="mt-2 text-xs leading-relaxed text-ink-500">{sub}</p> : null}
    </div>
  );
}

function DashboardConcept() {
  const on = O.useMounted(120);
  const invoiceTotal = INVOICE_CATS.reduce((s, c) => s + c.total, 0);
  const maxCat = Math.max(...INVOICE_CATS.map((c) => c.total));

  const meters = [
    { label: "Fatura no mês", v: (DASH.invoice / DASH.income) * 100, detail: mD(DASH.invoice) },
    { label: "Custos fixos", v: (DASH.fixed / DASH.income) * 100, detail: mD(DASH.fixed) },
    { label: "Meta variável usada", v: (DASH.variableUsed / DASH.variable) * 100, detail: `${mD(DASH.variableUsed)} de ${mD(DASH.variable)}` },
  ];
  const meterTone = (v) => (v > 95 ? "#e11d48" : v > 70 ? "#f59e0b" : "#10b981");
  const meterText = (v) => (v > 95 ? "text-danger-700" : v > 70 ? "text-warning-700" : "text-positive-700");

  const insights = [
    { icon: "sparkles", tone: "primary", title: "Alimentação lidera a fatura", body: `${mD(720)} em 18 compras — 31% das compras classificadas.` },
    { icon: "scale", tone: "warning", title: "Custos fixos são o maior compromisso", body: `Os fixos (${mD(DASH.fixed)}) pesam mais que a fatura vigente (${mD(DASH.invoice)}).` },
    { icon: "check", tone: "positive", title: "Variáveis dentro do plano", body: `Ainda restam ${mD(DASH.variable - DASH.variableUsed)} da meta de ${mD(DASH.variable)}.` },
    { icon: "banknote", tone: "positive", title: "Saldo cobre a fatura", body: `O saldo em conta (${mD(DASH.bank)}) é suficiente para a fatura vigente.` },
  ];

  return (
    <div className="ofx flex h-full bg-surface-muted">
      <DashSidebar />
      <div className="flex-1 overflow-hidden">
        {/* topbar */}
        <header className="flex items-center justify-between border-b border-ink-200/70 bg-surface-muted/90 px-7 py-3.5">
          <div>
            <h1 className="text-lg font-bold tracking-tight text-ink-900">Dashboard</h1>
            <p className="text-xs text-ink-500">Visão executiva de {DB.MONTH_LABEL}</p>
          </div>
          <div className="flex items-center gap-2">
            <button className="inline-flex items-center gap-2 rounded-control border border-ink-200 bg-surface px-3.5 py-1.5 text-sm font-medium text-ink-700 shadow-sm"><O.Icon name="refresh" className="size-4" />Atualizar</button>
            <button className="inline-flex items-center gap-2 rounded-control bg-primary-600 px-3.5 py-1.5 text-sm font-semibold text-white shadow-sm"><O.Icon name="link" className="size-4" />Conectar banco</button>
          </div>
        </header>

        <div className="space-y-6 p-7">
          {/* HERO */}
          <section className="cockpit-surface ofx-rise relative overflow-hidden rounded-card p-6 text-white shadow-cockpit">
            <div className="cockpit-grid pointer-events-none absolute inset-0 opacity-40" />
            <div className="relative grid grid-cols-[minmax(0,1fr)_340px] gap-10">
              <div className="flex flex-col justify-between">
                <div>
                  <div className="flex items-center gap-2.5">
                    <p className="text-sm font-medium text-white/70">Disponível para gastar</p>
                    <O.StatusPill tone="positive" inverse>Saudável</O.StatusPill>
                  </div>
                  <p className="mt-3 text-5xl font-bold leading-none tracking-tight tabular">{mD(DASH.available)}</p>
                  <p className="mt-4 max-w-md text-sm leading-relaxed text-white/55">O que sobra da receita de junho depois dos custos fixos, da fatura vigente e da reserva variável.</p>
                </div>
                <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
                  <span className="inline-flex items-center gap-1.5 text-white/70"><O.Icon name="clock" className="size-4 text-white/40" />{DASH.daysLeft} dias restantes</span>
                  <span className="inline-flex items-center gap-1.5 text-white/70"><O.Icon name="wallet" className="size-4 text-white/40" /><span className="font-semibold tabular text-white/90">{mD(DASH.perDay)}</span> por dia</span>
                  <span className="inline-flex items-center gap-1 font-medium text-primary-300">Ajustar plano do mês <O.Icon name="arrowUpRight" className="size-3.5" /></span>
                </div>
              </div>
              <div className="rounded-card border border-white/10 bg-white/[0.04] p-5 backdrop-blur-sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/50">Composição do mês</p>
                <div className="mt-4">
                  <O.FlowBar inverse on={on} total={DASH.income}
                    segments={[
                      { key: "f", label: "Custos fixos", value: DASH.fixed, color: "#64748b" },
                      { key: "i", label: "Fatura vigente", value: DASH.invoice, color: "#38bdf8" },
                      { key: "v", label: "Meta variável", value: DASH.variable, color: "#a78bfa" },
                    ]}
                    remainder={{ label: "Disponível", value: DASH.available }} />
                </div>
                <p className="mt-4 border-t border-white/10 pt-3 text-xs text-white/50">Receita esperada de <span className="font-semibold tabular text-white/80">{mD(DASH.income)}</span> em jun</p>
              </div>
            </div>
          </section>

          {/* KPI ROW */}
          <section className="ofx-rise grid grid-cols-4 gap-4" style={{ animationDelay: "60ms" }}>
            <DashMetric label="Entradas recebidas" value={mD(DASH.received)} sub="Crédito que já caiu na conta" tone="positive" icon="banknote" />
            <DashMetric label="Custos fixos" value={mD(DASH.fixed)} sub="Reservados ou já pagos" icon="wallet" />
            <DashMetric label="Variável usado" value={mD(DASH.variableUsed)} sub={`Meta ${mD(DASH.variable)} · restam ${mD(DASH.variable - DASH.variableUsed)}`} icon="target" />
            <DashMetric label="Saldo em conta" value={mD(DASH.bank)} sub="2 contas ativas consideradas" tone="primary" icon="banknote" />
          </section>

          {/* PRESSURE + INSIGHTS */}
          <section className="ofx-rise grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4" style={{ animationDelay: "100ms" }}>
            <div className="rounded-card border border-ink-200/70 bg-surface p-5 shadow-card">
              <div className="mb-4 flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-ink-900">Pressão do mês</h2>
                <p className="text-xs text-ink-500">quanto da receita cada bloco consome</p>
              </div>
              <div className="space-y-4">
                {meters.map((mt, i) => (
                  <div key={mt.label}>
                    <div className="flex items-baseline justify-between">
                      <p className="text-xs font-medium text-ink-600">{mt.label}</p>
                      <p className={`text-xs font-semibold tabular ${meterText(mt.v)}`}>{pcD(mt.v)}</p>
                    </div>
                    <div className="mt-1.5"><O.Bar value={mt.v} color={meterTone(mt.v)} on={on} delay={150 + i * 80} h={7} /></div>
                    <p className="mt-1 text-[11px] text-ink-500">{mt.detail}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3">
              {insights.map((ins) => (
                <div key={ins.title} className="flex items-start gap-3 rounded-card border border-ink-200/70 bg-surface p-3.5 shadow-card">
                  <span className={`mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-control ${ins.tone === "primary" ? "bg-primary-50 text-primary-600" : ins.tone === "warning" ? "bg-warning-50 text-warning-600" : "bg-positive-50 text-positive-600"}`}><O.Icon name={ins.icon} className="size-4" /></span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-ink-900">{ins.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-500">{ins.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* INVOICE + CATEGORIES */}
          <section className="ofx-rise grid grid-cols-[320px_minmax(0,1fr)] gap-4" style={{ animationDelay: "140ms" }}>
            <div className="h-fit rounded-card border border-ink-200/70 bg-surface p-5 shadow-card">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-xs font-medium text-ink-500">Fatura vigente · cartão</p>
                  <p className="mt-1.5 text-3xl font-bold tabular tracking-tight text-ink-900">{mD(DASH.invoice)}</p>
                </div>
                <span className="inline-flex size-9 items-center justify-center rounded-control bg-primary-50 text-primary-600"><O.Icon name="creditCard" className="size-4" /></span>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-ink-500">Valor considerado no cálculo do disponível para gastar.</p>
              <div className="mt-4 flex items-start gap-2.5 rounded-control border border-ink-100 bg-surface-muted p-3.5">
                <O.Icon name="calendar" className="mt-0.5 size-4 shrink-0 text-ink-400" />
                <div className="text-xs leading-relaxed text-ink-500">Próxima fatura (julho): <span className="font-semibold tabular text-ink-800">{mD(2580)}</span><br /><span className="font-medium text-primary-700">Ver compromissos futuros</span></div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {INVOICE_CATS.map((c, i) => {
                const share = (c.total / invoiceTotal) * 100;
                const w = (c.total / maxCat) * 100;
                return (
                  <div key={c.name} className="rounded-card border border-ink-200/70 bg-surface p-4 shadow-card">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2"><span className="size-2.5 rounded-[4px]" style={{ background: c.color }} /><h3 className="text-sm font-semibold text-ink-900">{c.name}</h3></div>
                      <p className="text-sm font-bold tabular text-ink-900">{mD(c.total)}</p>
                    </div>
                    <p className="mt-1 text-xs text-ink-500">{c.count} compras · {Math.round(share)}% do total</p>
                    <div className="mt-3"><O.Bar value={w} color={c.color} on={on} delay={200 + i * 50} /></div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

window.DashboardConcept = DashboardConcept;
