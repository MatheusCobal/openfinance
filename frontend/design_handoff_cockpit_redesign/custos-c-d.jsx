// ── Custos Fixos — Concepts C & D
const C2 = window.OFX;
const DD = window.OFX_DATA;
const { money: m$, money0: m0$, pct: pc, catColor: cc, STATUS_META: SM } = DD;

// ════════════════════════════════════════════════════════════════
// CONCEPT C — "Cascata" (waterfall: receita → categorias → sobra)
// ════════════════════════════════════════════════════════════════
function ConceptWaterfall() {
  const on = C2.useMounted(150);
  const income = DD.EXPECTED_INCOME;
  const total = DD.fixedTotal();
  const remaining = income - total;
  const cats = DD.byCategory();

  const chartH = 250;
  const scale = chartH / income;

  // build steps with running balance
  let running = income;
  const steps = [{ key: "rec", label: "Receita", value: income, kind: "pos" }];
  cats.forEach((g) => { const before = running; running -= g.total; steps.push({ key: g.name, label: g.name, value: g.total, kind: "drop", color: g.color, before, after: running }); });
  steps.push({ key: "rem", label: "Sobra p/ o mês", value: remaining, kind: "pos" });

  return (
    <div className="ofx h-full bg-surface-muted p-7">
      <div className="ofx-rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary-600">Custos fixos · {DD.MONTH_LABEL}</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-ink-900">Para onde a receita escorre</h2>
          <p className="mt-0.5 text-sm text-ink-500">Da receita esperada, os fixos consomem {pc((total / income) * 100)} antes de qualquer gasto do dia a dia.</p>
        </div>
        <div className="text-right">
          <p className="text-xs font-medium text-ink-500">Sobra após fixos</p>
          <p className="text-2xl font-bold tabular text-positive-600">{m$(remaining)}</p>
        </div>
      </div>

      {/* waterfall chart */}
      <div className="ofx-rise mt-5 rounded-card border border-ink-200/70 bg-surface p-6 shadow-card" style={{ animationDelay: "80ms" }}>
        <div className="relative flex items-end gap-3" style={{ height: chartH }}>
          {/* baseline grid */}
          {[0.25, 0.5, 0.75, 1].map((g) => (
            <div key={g} className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-ink-100" style={{ bottom: chartH * g }}>
              <span className="absolute -top-2 right-0 bg-surface pl-1 text-[10px] tabular text-ink-300">{m0$(income * g)}</span>
            </div>
          ))}
          {steps.map((s, i) => {
            const h = (s.kind === "pos" ? s.value : s.value) * scale;
            const bottom = s.kind === "drop" ? s.after * scale : 0;
            const color = s.kind === "pos" ? (s.key === "rec" ? "#0ea5e9" : "#10b981") : s.color;
            return (
              <div key={s.key} className="group relative flex h-full flex-1 flex-col items-center justify-end">
                {/* connector to previous running level */}
                {s.kind === "drop" ? <span className="pointer-events-none absolute left-[-12px] right-1/2 border-t border-ink-200" style={{ bottom: s.before * scale }} /> : null}
                <span className="mb-1 text-[11px] font-bold tabular text-ink-700" style={{ marginBottom: bottom + h + 4 - 0, position: "absolute", bottom: bottom + h + 2 }}>
                  {s.kind === "drop" ? "–" : ""}{m0$(s.value)}
                </span>
                <div className="relative w-full" style={{ height: chartH }}>
                  <div className="bar-fill absolute left-1/2 w-[68%] -translate-x-1/2 rounded-t-md" style={{ bottom, height: on ? h : 0, background: color, transitionDelay: `${i * 80}ms`, opacity: s.kind === "drop" ? 0.92 : 1 }} />
                </div>
              </div>
            );
          })}
        </div>
        {/* labels */}
        <div className="mt-3 flex gap-3 border-t border-ink-100 pt-3">
          {steps.map((s) => (
            <div key={s.key} className="flex flex-1 items-center justify-center gap-1.5 text-center">
              {s.kind === "drop" ? <span className="size-2 shrink-0 rounded-full" style={{ background: s.color }} /> : null}
              <span className={`text-[11px] font-medium leading-tight ${s.kind === "pos" ? "text-ink-700" : "text-ink-500"}`}>{s.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ranked category list */}
      <div className="ofx-rise mt-5 grid grid-cols-2 gap-4" style={{ animationDelay: "140ms" }}>
        {cats.map((g, i) => {
          const share = (g.total / total) * 100;
          const paidPct = (g.paid / g.total) * 100;
          return (
            <div key={g.name} className="rounded-card border border-ink-200/70 bg-surface p-4 shadow-card">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="size-2.5 rounded-[4px]" style={{ background: g.color }} />
                  <p className="text-sm font-semibold text-ink-900">{g.name}</p>
                  <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-500">{g.items.length} {g.items.length === 1 ? "conta" : "contas"}</span>
                </div>
                <p className="text-sm font-bold tabular text-ink-900">{m$(g.total)}</p>
              </div>
              <div className="mt-3"><C2.Bar value={paidPct} color={g.color} on={on} delay={200 + i * 60} h={6} /></div>
              <div className="mt-1.5 flex items-center justify-between text-[11px] text-ink-500">
                <span>{pc(share)} dos fixos</span>
                <span className="tabular">{m$(g.paid)} pago · {m$(g.total - g.paid)} a pagar</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// CONCEPT D — "Painel de comando" (donut + ranked list + upcoming)
// ════════════════════════════════════════════════════════════════
function ConceptCommand() {
  const on = C2.useMounted(150);
  const total = DD.fixedTotal();
  const paidSum = DD.paidTotal();
  const cats = DD.byCategory();
  const segments = cats.map((g) => ({ value: g.total, color: g.color, label: g.name }));
  const upcoming = [...DD.FIXED_COSTS].filter((c) => c.status !== "paid").sort((a, b) => a.dueDay - b.dueDay).slice(0, 4);

  return (
    <div className="ofx h-full bg-surface-muted p-7">
      <div className="ofx-rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary-600">Custos fixos · {DD.MONTH_LABEL}</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-ink-900">Painel de comando</h2>
        </div>
        <C2.StatusPill tone="primary">{pc((total / DD.EXPECTED_INCOME) * 100)} da receita</C2.StatusPill>
      </div>

      <div className="ofx-rise mt-5 grid grid-cols-[360px_minmax(0,1fr)] gap-5" style={{ animationDelay: "80ms" }}>
        {/* donut card */}
        <div className="rounded-card border border-ink-200/70 bg-surface p-6 shadow-card">
          <div className="flex justify-center">
            <C2.Donut segments={segments} size={210} thickness={24} on={on}>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">Total fixo</p>
              <p className="text-2xl font-bold tabular tracking-tight text-ink-900">{m$(total)}</p>
              <p className="mt-0.5 text-[11px] text-ink-500">{DD.FIXED_COSTS.length} contas</p>
            </C2.Donut>
          </div>
          <div className="mt-5 space-y-2.5">
            {cats.map((g) => (
              <div key={g.name} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 text-ink-600"><span className="size-2.5 rounded-[4px]" style={{ background: g.color }} />{g.name}</span>
                <span className="flex items-center gap-2"><span className="text-xs tabular text-ink-400">{pc((g.total / total) * 100)}</span><span className="font-semibold tabular text-ink-900">{m$(g.total)}</span></span>
              </div>
            ))}
          </div>
        </div>

        {/* right column */}
        <div className="flex flex-col gap-5">
          {/* paid progress */}
          <div className="rounded-card border border-ink-200/70 bg-surface p-5 shadow-card">
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold text-ink-900">Progresso do mês</h3>
              <span className="text-xs text-ink-500">{m$(paidSum)} de {m$(total)} quitado</span>
            </div>
            <div className="mt-3"><C2.Bar value={(paidSum / total) * 100} color="#10b981" on={on} delay={250} h={10} /></div>
            <div className="mt-4 grid grid-cols-3 gap-3">
              {[["Pago", paidSum, "positive"], ["A pagar", total - paidSum, "warning"], ["Vencido", DD.FIXED_COSTS.filter(c=>c.status==="overdue").reduce((s,c)=>s+c.amount,0), "danger"]].map(([l, v, t]) => (
                <div key={l} className="rounded-control bg-surface-muted p-3">
                  <p className="text-[11px] font-medium text-ink-500">{l}</p>
                  <p className={`mt-0.5 text-base font-bold tabular ${t === "positive" ? "text-positive-700" : t === "warning" ? "text-warning-700" : "text-danger-600"}`}>{m$(v)}</p>
                </div>
              ))}
            </div>
          </div>

          {/* upcoming */}
          <div className="flex-1 rounded-card border border-ink-200/70 bg-surface p-5 shadow-card">
            <div className="mb-3 flex items-center gap-2">
              <C2.Icon name="bell" className="size-4 text-ink-400" />
              <h3 className="text-sm font-semibold text-ink-900">Próximos vencimentos</h3>
            </div>
            <ul className="space-y-1">
              {upcoming.map((c) => {
                const st = SM[c.status];
                return (
                  <li key={c.id} className="flex items-center gap-3 rounded-control px-2 py-2 transition-colors hover:bg-surface-muted">
                    <C2.DayBadge day={c.dueDay} tone={c.status === "overdue" ? "danger" : c.status === "due_soon" ? "warning" : "neutral"} size={36} />
                    <C2.CatAvatar cost={c} size={34} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink-900">{c.name}</p>
                      <p className="text-xs" style={{ color: cc(c.cat) }}>{c.cat}</p>
                    </div>
                    <C2.CostStatus status={c.status} />
                    <p className="w-20 shrink-0 text-right text-sm font-bold tabular text-ink-900">{m$(c.amount)}</p>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ConceptWaterfall, ConceptCommand });
