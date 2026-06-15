// ── Mock data (PT-BR) for the OpenFinance "Custos Fixos" / Dashboard redesign.
// Faithful to the real app's domain: categories carry palette colors from
// lib/categories.ts; costs have due_day + month status; income drives capacity.

const TODAY = 13; // dia "hoje" de junho/2026
const MONTH_DAYS = 30;
const MONTH_LABEL = "Junho 2026";
const MONTH_SHORT = "jun";

// status: paid | overdue | due_soon | scheduled
const FIXED_COSTS = [
  { id: "aluguel",   name: "Aluguel",            cat: "Moradia",     amount: 2200.00, dueDay: 5,  status: "paid",      icon: "home",    matched: "Imobiliária Vista · PIX" },
  { id: "condominio",name: "Condomínio",         cat: "Moradia",     amount: 680.00,  dueDay: 10, status: "paid",      icon: "building",matched: "Cond. Edifício Aurora" },
  { id: "luz",       name: "Energia (CPFL)",     cat: "Moradia",     amount: 180.00,  dueDay: 18, status: "scheduled", icon: "zap",     matched: null },
  { id: "plano",     name: "Plano de saúde",     cat: "Saúde",       amount: 612.00,  dueDay: 8,  status: "paid",      icon: "heart",   matched: "Amil Saúde · débito" },
  { id: "academia",  name: "Academia",           cat: "Saúde",       amount: 119.00,  dueDay: 1,  status: "paid",      icon: "dumbbell",matched: "Smart Fit" },
  { id: "internet",  name: "Internet 600MB",     cat: "Assinaturas", amount: 119.90,  dueDay: 12, status: "overdue",   icon: "wifi",    matched: null },
  { id: "celular",   name: "Celular (Vivo)",     cat: "Assinaturas", amount: 59.90,   dueDay: 12, status: "paid",      icon: "phone",   matched: "Vivo Controle" },
  { id: "netflix",   name: "Netflix",            cat: "Assinaturas", amount: 44.90,   dueDay: 15, status: "due_soon",  icon: "tv",      matched: null },
  { id: "spotify",   name: "Spotify",            cat: "Assinaturas", amount: 21.90,   dueDay: 15, status: "due_soon",  icon: "music",   matched: null },
  { id: "icloud",    name: "iCloud 200GB",       cat: "Assinaturas", amount: 12.90,   dueDay: 2,  status: "paid",      icon: "cloud",   matched: "Apple.com/bill" },
  { id: "seguro",    name: "Seguro do carro",    cat: "Transporte",  amount: 189.00,  dueDay: 20, status: "scheduled", icon: "car",     matched: null },
  { id: "faculdade", name: "Pós-graduação",      cat: "Educação",    amount: 540.00,  dueDay: 7,  status: "paid",      icon: "book",    matched: "FIA Online" },
];

const CATEGORY_COLORS = {
  "Moradia": "#7c3aed",
  "Saúde": "#dc2626",
  "Assinaturas": "#0891b2",
  "Transporte": "#2563eb",
  "Educação": "#ca8a04",
  "Outros": "#64748b",
};

const INCOME = [
  { id: "salario", name: "Salário", amount: 8500, day: 5, received: true },
  { id: "freela",  name: "Renda extra (freela)", amount: 1500, day: 20, received: false },
];

const EXPECTED_INCOME = INCOME.reduce((s, i) => s + i.amount, 0); // 10.000
const VARIABLE_BUDGET = 1800; // meta variável do mês

// ── derived helpers ───────────────────────────────────────────
function catColor(name) { return CATEGORY_COLORS[name] || CATEGORY_COLORS.Outros; }

function fixedTotal() { return FIXED_COSTS.reduce((s, c) => s + c.amount, 0); }
function paidTotal()  { return FIXED_COSTS.filter(c => c.status === "paid").reduce((s, c) => s + c.amount, 0); }
function pendingTotal(){ return fixedTotal() - paidTotal(); }

function byCategory() {
  const map = new Map();
  for (const c of FIXED_COSTS) {
    const g = map.get(c.cat) || { name: c.cat, color: catColor(c.cat), total: 0, paid: 0, items: [] };
    g.total += c.amount;
    if (c.status === "paid") g.paid += c.amount;
    g.items.push(c);
    map.set(c.cat, g);
  }
  return [...map.values()].sort((a, b) => b.total - a.total);
}

const STATUS_META = {
  paid:      { label: "Pago",          tone: "positive", dot: "#10b981" },
  overdue:   { label: "Vencido",       tone: "danger",   dot: "#f43f5e" },
  due_soon:  { label: "Vence em breve",tone: "warning",  dot: "#f59e0b" },
  scheduled: { label: "Previsto",      tone: "neutral",  dot: "#94a3b8" },
};

// pt-BR currency
const _brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
function money(v)  { return _brl.format(Number(v) || 0); }
function money0(v) { return _brl.format(Number(v) || 0).replace(/,\d{2}$/, ""); }
function pct(v)    { return `${Math.round(v)}%`; }

Object.assign(window, {
  OFX_DATA: {
    TODAY, MONTH_DAYS, MONTH_LABEL, MONTH_SHORT,
    FIXED_COSTS, CATEGORY_COLORS, INCOME, EXPECTED_INCOME, VARIABLE_BUDGET, STATUS_META,
    catColor, fixedTotal, paidTotal, pendingTotal, byCategory,
    money, money0, pct,
  },
});
