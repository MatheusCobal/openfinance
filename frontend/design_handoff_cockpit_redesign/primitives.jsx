// ── Shared primitives for all concepts. Exported to window at the end.
const { money, money0, pct, catColor, STATUS_META } = window.OFX_DATA;

// ───────────────────────────────────────────────────────────────
// Inline icon set (lucide-style: 24 viewBox, 1.8 stroke, round caps)
// ───────────────────────────────────────────────────────────────
const ICONS = {
  home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
  building: '<rect x="6" y="3" width="12" height="18" rx="1.5"/><path d="M10 7h0M14 7h0M10 11h0M14 11h0M10 15h0M14 15h0M10 21v-3h4v3"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.5 1-1a5.5 5.5 0 0 0 0-7.8z"/>',
  dumbbell: '<path d="M6 7v10M3 9.5v5M18 7v10M21 9.5v5M6 12h12"/>',
  wifi: '<path d="M2 8.8a15 15 0 0 1 20 0"/><path d="M5 12.3a10 10 0 0 1 14 0"/><path d="M8.5 15.8a5 5 0 0 1 7 0"/><path d="M12 19h.01"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
  tv: '<rect x="2" y="7" width="20" height="13" rx="2"/><path d="m17 2-5 5-5-5"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.7-9h1.8a4.5 4.5 0 1 1 0 9Z"/>',
  car: '<path d="M5 17a2 2 0 1 0 0 .01M17 17a2 2 0 1 0 0 .01"/><path d="M3 17h-.5a.5.5 0 0 1-.5-.5V13l2-5a1.5 1.5 0 0 1 1.4-1h11.2a1.5 1.5 0 0 1 1.4 1l2 5v3.5a.5.5 0 0 1-.5.5H21M7 17h10M3 13h18"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5"/>',
  link: '<path d="M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 1 1 0 10h-2M8 12h8"/>',
  arrowUpRight: '<path d="M7 17 17 7M8 7h9v9"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  wallet: '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>',
  creditCard: '<rect x="2" y="5" width="20" height="14" rx="2.5"/><path d="M2 10h20"/>',
  calendar: '<rect x="3" y="4" width="18" height="17" rx="2.5"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  trendingUp: '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
  gauge: '<path d="m12 14 3.5-3.5"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.7 1.8L21 17.5l-1.3.7L19 20l-.7-1.8L17 17.5l1.3-.7z"/>',
  pencil: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  pie: '<path d="M21.2 15.9A10 10 0 1 1 8 2.8"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1.1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 6.5s3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2.4-2.3 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  banknote: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 12h.01M18 12h.01"/>',
  scale: '<path d="M12 3v18M7 21h10M5 7h14"/><path d="m5 7-3 6a3 3 0 0 0 6 0zM19 7l-3 6a3 3 0 0 0 6 0z"/>',
  arrowRight: '<path d="M5 12h14M13 5l7 7-7 7"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
};

function Icon({ name, className = "size-4", style }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" className={className} style={style}
      aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICONS[name] || "" }} />
  );
}

// Map cost.icon -> available icon name (fallback receipt-ish)
function costIcon(name) { return ICONS[name] ? name : "creditCard"; }

// ───────────────────────────────────────────────────────────────
// Hooks
// ───────────────────────────────────────────────────────────────
function useMounted(delay = 60) {
  const [on, setOn] = React.useState(false);
  React.useEffect(() => { const t = setTimeout(() => setOn(true), delay); return () => clearTimeout(t); }, [delay]);
  return on;
}

// Count-up number — degrades to the final value when motion can't run
// (hidden tab / reduced motion), so the correct figure is always shown.
function useCountUp(target, on, dur = 900) {
  const [v, setV] = React.useState(target);
  React.useEffect(() => {
    if (!on) { setV(target); return; }
    if (typeof document !== "undefined" && document.hidden) { setV(target); return; }
    let raf, start;
    setV(0);
    const tick = (t) => {
      if (start == null) start = t;
      const p = Math.min((t - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setV(target * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
      else setV(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, on, dur]);
  return v;
}

// ───────────────────────────────────────────────────────────────
// Pills / badges
// ───────────────────────────────────────────────────────────────
const PILL_TONES = {
  positive: "bg-positive-50 text-positive-700 ring-positive-200",
  warning: "bg-warning-50 text-warning-800 ring-warning-200",
  danger: "bg-danger-50 text-danger-700 ring-danger-200",
  neutral: "bg-ink-100 text-ink-600 ring-ink-200",
  primary: "bg-primary-50 text-primary-700 ring-primary-200",
};
const DOT_TONES = { positive: "bg-positive-500", warning: "bg-warning-500", danger: "bg-danger-500", neutral: "bg-ink-400", primary: "bg-primary-500" };

function StatusPill({ tone = "neutral", children, inverse = false, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${inverse ? "bg-white/10 text-white ring-white/15" : PILL_TONES[tone]} ${className}`}>
      <span className={`size-1.5 rounded-full ${DOT_TONES[tone]}`} />
      {children}
    </span>
  );
}

function Badge({ tone = "neutral", children, className = "" }) {
  const tones = {
    neutral: "bg-ink-100 text-ink-700", primary: "bg-primary-50 text-primary-700",
    positive: "bg-positive-50 text-positive-700", warning: "bg-warning-50 text-warning-800",
    danger: "bg-danger-50 text-danger-700", accent: "bg-accent-50 text-accent-700",
  };
  return <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}>{children}</span>;
}

// Status pill straight from a cost.status
function CostStatus({ status, inverse }) {
  const m = STATUS_META[status] || STATUS_META.scheduled;
  return <StatusPill tone={m.tone} inverse={inverse}>{m.label}</StatusPill>;
}

// ───────────────────────────────────────────────────────────────
// Category avatar — rounded tile, tinted with category color
// ───────────────────────────────────────────────────────────────
function CatAvatar({ cost, size = 40, radius = 12 }) {
  const color = catColor(cost.cat);
  return (
    <span className="inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size, borderRadius: radius, background: color + "1A", color }}>
      <Icon name={costIcon(cost.icon)} className="" style={{ width: size * 0.45, height: size * 0.45 }} />
    </span>
  );
}

// ───────────────────────────────────────────────────────────────
// Animated progress bar
// ───────────────────────────────────────────────────────────────
function Bar({ value, color = "#2563eb", track = "rgba(15,23,42,0.08)", h = 6, on = true, delay = 0, className = "" }) {
  const w = Math.max(0, Math.min(100, value));
  return (
    <div className={`w-full overflow-hidden rounded-full ${className}`} style={{ height: h, background: track }}>
      <div className="bar-fill h-full rounded-full" style={{ width: on ? `${w}%` : 0, background: color, transitionDelay: `${delay}ms` }} />
    </div>
  );
}

// ───────────────────────────────────────────────────────────────
// Donut — animated draw-on, with optional center content
// segments: [{ value, color, label }]
// ───────────────────────────────────────────────────────────────
function Donut({ segments, size = 200, thickness = 22, on = true, gap = 2, children }) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let acc = 0;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(15,23,42,0.06)" strokeWidth={thickness} />
        {segments.map((seg, i) => {
          const frac = seg.value / total;
          const len = Math.max(0, c * frac - gap);
          const off = c * (1 - acc);
          acc += frac;
          return (
            <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={seg.color} strokeWidth={thickness} strokeLinecap="round"
              strokeDasharray={`${on ? len : 0} ${c}`} strokeDashoffset={off}
              className="ring-anim" style={{ transitionDelay: `${i * 90}ms` }} />
          );
        })}
      </svg>
      {children ? <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div> : null}
    </div>
  );
}

// ───────────────────────────────────────────────────────────────
// FlowBar — the "composição do mês" strip (receita → blocos → sobra)
// ───────────────────────────────────────────────────────────────
function FlowBar({ total, segments, remainder, inverse = false, on = true, h = 12 }) {
  const used = segments.reduce((s, x) => s + Math.max(0, x.value), 0);
  const denom = Math.max(total, used) || 1;
  const wf = (v) => (v / denom) * 100;
  const overflow = remainder.value < 0;
  const remW = overflow ? 0 : wf(Math.max(remainder.value, 0));
  return (
    <div>
      <div className="flex w-full overflow-hidden rounded-full" style={{ height: h, background: inverse ? "rgba(255,255,255,0.10)" : "rgba(15,23,42,0.07)" }}>
        {segments.map((s, i) => (
          <div key={s.key} className="h-full bar-fill" style={{ width: on ? `${wf(s.value)}%` : 0, background: s.color, transitionDelay: `${i * 70}ms` }} />
        ))}
        {remW > 0 ? <div className="h-full bar-fill" style={{ width: on ? `${remW}%` : 0, background: inverse ? "rgba(52,211,153,0.9)" : "#34d399", transitionDelay: `${segments.length * 70}ms` }} /> : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
        {[...segments, { key: "rem", label: remainder.label, value: remainder.value, color: overflow ? "#fb7185" : "#34d399" }].map((s) => (
          <div key={s.key} className="flex items-start gap-1.5">
            <span className="mt-1 size-2 shrink-0 rounded-[3px]" style={{ background: s.color }} />
            <div className="min-w-0">
              <p className={`truncate text-[11px] font-medium uppercase tracking-wide ${inverse ? "text-white/55" : "text-ink-500"}`}>{s.label}</p>
              <p className={`text-sm font-semibold tabular ${s.key === "rem" && overflow ? (inverse ? "text-danger-300" : "text-danger-600") : (inverse ? "text-white/90" : "text-ink-800")}`}>{money(s.value)}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────
// Day badge (due_day) — square, like the real app
// ───────────────────────────────────────────────────────────────
function DayBadge({ day, tone = "neutral", size = 38 }) {
  const tones = {
    neutral: "bg-surface-muted text-ink-700", positive: "bg-positive-100 text-positive-700",
    danger: "bg-danger-100 text-danger-700", warning: "bg-warning-100 text-warning-800", primary: "bg-primary-50 text-primary-700",
  };
  return (
    <span className={`flex shrink-0 flex-col items-center justify-center rounded-control ${tones[tone]}`} style={{ width: size, height: size }}>
      <span className="text-sm font-bold tabular leading-none">{day}</span>
      <span className="text-[9px] font-medium uppercase opacity-60 leading-none mt-0.5">dia</span>
    </span>
  );
}

// Generic header band for a concept (light)
function PanelHeader({ kicker, title, sub, right }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {kicker ? <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary-600">{kicker}</p> : null}
        <h2 className="mt-1 text-lg font-bold tracking-tight text-ink-900">{title}</h2>
        {sub ? <p className="mt-0.5 text-sm text-ink-500">{sub}</p> : null}
      </div>
      {right}
    </div>
  );
}

Object.assign(window, {
  OFX: {
    Icon, costIcon, useMounted, useCountUp,
    StatusPill, Badge, CostStatus, CatAvatar, Bar, Donut, FlowBar, DayBadge, PanelHeader,
  },
});
