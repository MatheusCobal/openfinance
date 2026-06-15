// ── Custos Fixos — Concepts A & B
const { Icon, useMounted, useCountUp, StatusPill, Badge, CostStatus, CatAvatar, Bar, FlowBar, DayBadge, costIcon } = window.OFX;
const D = window.OFX_DATA;
const { money, money0, pct, catColor, STATUS_META } = D;

const STATUS_RANK = { overdue: 4, due_soon: 3, scheduled: 2, paid: 1 };

// Shared: weekday of June 1 2026 = Monday → 1 leading blank in a Sun-start grid
const WEEK_LABELS = ["D", "S", "T", "Q", "Q", "S", "S"];
const LEADING_BLANKS = 1;

// ════════════════════════════════════════════════════════════════
// CONCEPT A — "Agenda do mês"
// Dark cockpit hero (total + live paid bar + month calendar) over a
// vertical timeline with a "hoje" divider and live paid toggles.
// ════════════════════════════════════════════════════════════════
function ConceptAgenda() {
  const on = useMounted(120);
  const [paid, setPaid] = React.useState(() => {
    const s = new Set(); D.FIXED_COSTS.forEach((c) => { if (c.status === "paid") s.add(c.id); }); return s;
  });
  const toggle = (id) => setPaid((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const total = D.fixedTotal();
  const paidSum = D.FIXED_COSTS.filter((c) => paid.has(c.id)).reduce((s, c) => s + c.amount, 0);
  const pendingSum = total - paidSum;

  // effective status given live paid set
  const effStatus = (c) => (paid.has(c.id) ? "paid" : (c.status === "paid" ? "scheduled" : c.status));
  const ordered = [...D.FIXED_COSTS].sort((a, b) => a.dueDay - b.dueDay);

  // calendar map
  const byDay = {};
  D.FIXED_COSTS.forEach((c) => { (byDay[c.dueDay] = byDay[c.dueDay] || []).push(c); });

  const incomeShare = (total / D.EXPECTED_INCOME) * 100;

  return (
    <div className="ofx h-full bg-surface-muted p-7">
      {/* HERO */}
      <section className="cockpit-surface ofx-rise relative overflow-hidden rounded-card p-6 text-white shadow-cockpit">
        <div className="cockpit-grid pointer-events-none absolute inset-0 opacity-40" />
        <div className="relative grid grid-cols-[minmax(0,1fr)_300px] gap-8">
          <div className="flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2.5">
                <span className="inline-flex size-8 items-center justify-center rounded-control bg-white/10 ring-1 ring-inset ring-white/15"><Icon name="calendar" className="size-4 text-white/80" /></span>
                <p className="text-sm font-medium text-white/70">Custos fixos · {D.MONTH_LABEL}</p>
              </div>
              <p className="mt-4 text-5xl font-bold leading-none tracking-tight tabular">{money(total)}</p>
              <p className="mt-3 max-w-sm text-sm leading-relaxed text-white/55">
                Compromissos que se repetem todo mês. Ocupam <span className="font-semibold text-white/80">{pct(incomeShare)}</span> da sua receita esperada de {money0(D.EXPECTED_INCOME)}.
              </p>
            </div>
            <div className="mt-6">
              <div className="flex items-center justify-between text-xs">
                <span className="inline-flex items-center gap-1.5 font-medium text-white/70"><span className="size-2 rounded-[3px] bg-positive-400" /> Pago {money(paidSum)}</span>
                <span className="inline-flex items-center gap-1.5 font-medium text-white/70"><span className="size-2 rounded-[3px] bg-white/30" /> A pagar {money(pendingSum)}</span>
              </div>
              <div className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-white/10">
                <div className="bar-fill h-full rounded-l-full" style={{ width: on ? `${(paidSum / total) * 100}%` : 0, background: "rgba(52,211,153,0.95)" }} />
              </div>
              <p className="mt-2 text-[11px] text-white/45">{paid.size} de {D.FIXED_COSTS.length} contas quitadas · marque conforme paga</p>
            </div>
          </div>

          {/* Mini calendar */}
          <div className="rounded-card border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm">
            <div className="mb-2 grid grid-cols-7 gap-1 text-center text-[10px] font-semibold uppercase text-white/40">
              {WEEK_LABELS.map((w, i) => <div key={i}>{w}</div>)}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {Array.from({ length: LEADING_BLANKS }).map((_, i) => <div key={"b" + i} />)}
              {Array.from({ length: D.MONTH_DAYS }).map((_, i) => {
                const day = i + 1;
                const items = byDay[day] || [];
                const isToday = day === D.TODAY;
                const worst = items.reduce((w, c) => Math.max(w, STATUS_RANK[effStatus(c)]), 0);
                const dotColor = worst === 4 ? "#fb7185" : worst === 3 ? "#fbbf24" : worst === 2 ? "#94a3b8" : worst === 1 ? "#34d399" : null;
                return (
                  <div key={day} className={`relative flex aspect-square flex-col items-center justify-center rounded-md text-[11px] tabular ${isToday ? "bg-primary-500 font-bold text-white" : items.length ? "bg-white/[0.06] text-white/80" : "text-white/30"}`}>
                    {day}
                    {dotColor && !isToday ? <span className="absolute bottom-1 size-1 rounded-full" style={{ background: dotColor }} /> : null}
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-white/10 pt-2.5 text-[10px] text-white/50">
              <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-positive-400" />pago</span>
              <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-warning-400" />em breve</span>
              <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-danger-400" />vencido</span>
            </div>
          </div>
        </div>
      </section>

      {/* TIMELINE */}
      <div className="ofx-rise mt-6" style={{ animationDelay: "120ms" }}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink-900">Linha do tempo de pagamentos</h3>
          <span className="text-xs text-ink-500">ordenado por vencimento</span>
        </div>
        <div className="relative rounded-card border border-ink-200/70 bg-surface p-2 shadow-card">
          <ul>
            {ordered.map((c, idx) => {
              const st = effStatus(c);
              const m = STATUS_META[st];
              const isPaid = st === "paid";
              const prev = idx > 0 ? ordered[idx - 1] : null;
              const showToday = (prev ? prev.dueDay < D.TODAY : false) && c.dueDay >= D.TODAY;
              return (
                <React.Fragment key={c.id}>
                  {showToday ? (
                    <li className="flex items-center gap-3 px-3 py-2">
                      <span className="rounded-full bg-primary-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">Hoje · {D.TODAY} {D.MONTH_SHORT}</span>
                      <span className="h-px flex-1 bg-primary-200" />
                    </li>
                  ) : null}
                  <li className="group flex items-center gap-3 rounded-control px-3 py-2.5 transition-colors hover:bg-surface-muted">
                    <DayBadge day={c.dueDay} tone={isPaid ? "positive" : st === "overdue" ? "danger" : st === "due_soon" ? "warning" : "neutral"} />
                    <CatAvatar cost={c} size={38} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className={`text-sm font-semibold ${isPaid ? "text-ink-500" : "text-ink-900"}`}>{c.name}</p>
                        <span className="text-xs text-ink-400">·</span>
                        <span className="text-xs font-medium" style={{ color: catColor(c.cat) }}>{c.cat}</span>
                      </div>
                      <p className="mt-0.5 truncate text-xs text-ink-500">
                        {c.matched ? <span className="inline-flex items-center gap-1 text-positive-700"><Icon name="link" className="size-3" />{c.matched}</span> : <span className="text-ink-400">sem pagamento vinculado</span>}
                      </p>
                    </div>
                    <p className={`shrink-0 text-sm font-bold tabular ${isPaid ? "text-ink-400" : "text-ink-900"}`}>{money(c.amount)}</p>
                    <div className="hidden w-28 shrink-0 justify-end sm:flex"><CostStatus status={st} /></div>
                    <button onClick={() => toggle(c.id)}
                      className={`flex size-7 shrink-0 items-center justify-center rounded-full border-2 transition-all duration-200 ${isPaid ? "border-positive-500 bg-positive-500 text-white" : "border-ink-300 text-transparent hover:border-positive-400"}`}
                      title={isPaid ? "Marcar como não pago" : "Marcar como pago"}>
                      <Icon name="check" className="size-3.5" style={{ strokeWidth: 3 }} />
                    </button>
                  </li>
                </React.Fragment>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// CONCEPT B — "Compromissos" (subscriptions-manager grid)
// ════════════════════════════════════════════════════════════════
function ConceptGrid() {
  const on = useMounted(120);
  const [paid, setPaid] = React.useState(() => { const s = new Set(); D.FIXED_COSTS.forEach((c) => { if (c.status === "paid") s.add(c.id); }); return s; });
  const [filter, setFilter] = React.useState("Todas");
  const toggle = (id) => setPaid((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const effStatus = (c) => (paid.has(c.id) ? "paid" : (c.status === "paid" ? "scheduled" : c.status));

  const total = D.fixedTotal();
  const paidSum = D.FIXED_COSTS.filter((c) => paid.has(c.id)).reduce((s, c) => s + c.amount, 0);
  const cats = ["Todas", ...D.byCategory().map((g) => g.name)];
  const shown = D.FIXED_COSTS.filter((c) => filter === "Todas" || c.cat === filter);

  return (
    <div className="ofx h-full bg-surface-muted p-7">
      {/* header */}
      <div className="ofx-rise flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary-600">Custos fixos · {D.MONTH_LABEL}</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-ink-900">{D.FIXED_COSTS.length} compromissos recorrentes</h2>
        </div>
        <button className="inline-flex items-center gap-2 rounded-control bg-primary-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary-700">
          <Icon name="plus" className="size-4" />Novo custo
        </button>
      </div>

      {/* summary cards */}
      <div className="ofx-rise mt-5 grid grid-cols-3 gap-4" style={{ animationDelay: "60ms" }}>
        {[
          { label: "Total no mês", val: total, sub: `${pct((total / D.EXPECTED_INCOME) * 100)} da receita`, tone: "primary", icon: "wallet" },
          { label: "Já pago", val: paidSum, sub: `${paid.size} de ${D.FIXED_COSTS.length} contas`, tone: "positive", icon: "check" },
          { label: "A pagar", val: total - paidSum, sub: `${D.FIXED_COSTS.length - paid.size} pendentes`, tone: "warning", icon: "clock" },
        ].map((s) => (
          <div key={s.label} className="rounded-card border border-ink-200/70 bg-surface p-4 shadow-card">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-ink-500">{s.label}</p>
                <p className="mt-1.5 text-2xl font-bold tabular tracking-tight text-ink-900">{money(s.val)}</p>
              </div>
              <span className={`inline-flex size-9 items-center justify-center rounded-control ${s.tone === "primary" ? "bg-primary-50 text-primary-600" : s.tone === "positive" ? "bg-positive-50 text-positive-600" : "bg-warning-50 text-warning-600"}`}><Icon name={s.icon} className="size-4" /></span>
            </div>
            <p className="mt-2 text-xs text-ink-500">{s.sub}</p>
          </div>
        ))}
      </div>

      {/* filter chips */}
      <div className="ofx-rise mt-5 flex flex-wrap gap-1.5" style={{ animationDelay: "100ms" }}>
        {cats.map((cat) => {
          const active = filter === cat;
          const color = cat === "Todas" ? "#475569" : catColor(cat);
          return (
            <button key={cat} onClick={() => setFilter(cat)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${active ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-surface text-ink-600 hover:border-ink-300"}`}>
              {cat !== "Todas" ? <span className="size-2 rounded-full" style={{ background: active ? "#fff" : color }} /> : null}
              {cat}
            </button>
          );
        })}
      </div>

      {/* grid */}
      <div className="ofx-rise mt-5 grid grid-cols-3 gap-4" style={{ animationDelay: "140ms" }}>
        {shown.map((c) => {
          const st = effStatus(c);
          const isPaid = st === "paid";
          const m = STATUS_META[st];
          return (
            <div key={c.id} className="group flex flex-col rounded-card border border-ink-200/70 bg-surface p-4 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lift">
              <div className="flex items-start justify-between">
                <CatAvatar cost={c} size={44} radius={13} />
                <CostStatus status={st} />
              </div>
              <p className="mt-3 text-sm font-semibold text-ink-900">{c.name}</p>
              <p className="text-xs font-medium" style={{ color: catColor(c.cat) }}>{c.cat}</p>
              <p className="mt-3 text-2xl font-bold tabular tracking-tight text-ink-900">{money(c.amount)}</p>
              <div className="mt-1 flex items-center gap-1.5 text-xs text-ink-500">
                <Icon name="calendar" className="size-3.5 text-ink-400" />vence dia {c.dueDay}
              </div>
              <button onClick={() => toggle(c.id)}
                className={`mt-4 inline-flex items-center justify-center gap-1.5 rounded-control border px-3 py-1.5 text-xs font-semibold transition-all duration-200 ${isPaid ? "border-positive-200 bg-positive-50 text-positive-700" : "border-ink-200 bg-surface text-ink-700 hover:border-positive-300 hover:bg-positive-50/40"}`}>
                <Icon name={isPaid ? "check" : "banknote"} className="size-3.5" style={isPaid ? { strokeWidth: 3 } : undefined} />
                {isPaid ? "Pago" : "Marcar pago"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { ConceptAgenda, ConceptGrid });
