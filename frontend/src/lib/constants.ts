export const INTERNAL_ROUTES = [
  "/dashboard",
  "/planejamento",
  "/historico",
  "/proximos",
  "/regras",
] as const;

export const MAX_CUSTOM_CATEGORIES = 5;

export const CATEGORY_COLORS: Record<string, string> = {
  Alimentacao: "#16a34a",
  Alimentação: "#16a34a",
  Mercado: "#22c55e",
  Transporte: "#2563eb",
  Moradia: "#7c3aed",
  Saude: "#dc2626",
  Saúde: "#dc2626",
  Educacao: "#ea580c",
  Educação: "#ea580c",
  Lazer: "#0891b2",
  Compras: "#db2777",
  Outros: "#64748b",
};

export const TEMPLATE_ICONS: Record<string, string> = {
  Aluguel: "home",
  Condomínio: "building",
  Internet: "wifi",
  Energia: "zap",
  Água: "droplets",
  Escola: "book",
  "Plano de saúde": "heart",
  Streaming: "tv",
  Seguro: "shield",
  Pet: "paw",
  Academia: "dumbbell",
};
