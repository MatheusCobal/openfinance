/**
 * Category palette — one stable, intentional color per internal category so
 * the user can recognize spending patterns across Dashboard, Histórico and
 * Próximos. Unknown names fall back to a deterministic chart-palette pick.
 */

export const CATEGORY_PALETTE: Record<string, string> = {
  "Alimentação": "#ea580c",
  "Mercado": "#16a34a",
  "Transporte": "#2563eb",
  "Moradia": "#7c3aed",
  "Casa": "#7c3aed",
  "Saúde": "#dc2626",
  "Compras": "#db2777",
  "Assinaturas": "#0891b2",
  "Educação": "#ca8a04",
  "Pet": "#65a30d",
  "Lazer": "#0d9488",
  "Viagem": "#0ea5e9",
  "Lazer / Viagem": "#0d9488",
  "Presentes": "#e11d48",
  "Beleza / Cuidados pessoais": "#c026d3",
  "Impostos / Taxas": "#78716c",
  "Financiamentos": "#475569",
  "Receitas": "#059669",
  "Transferências": "#64748b",
  "Pagamento de cartão": "#334155",
  "Investimentos": "#4f46e5",
  "Saque": "#71717a",
  "Estorno": "#14b8a6",
  "Ajustes": "#94a3b8",
  "Outros": "#64748b",
};

/** Accent rotation for categories outside the known taxonomy. */
export const FALLBACK_CATEGORY_COLORS = [
  "#2563eb",
  "#7c3aed",
  "#0d9488",
  "#ea580c",
  "#db2777",
  "#0ea5e9",
  "#ca8a04",
  "#65a30d",
];

function normalizeKey(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

const normalizedPalette = new Map(
  Object.entries(CATEGORY_PALETTE).map(([name, color]) => [normalizeKey(name), color]),
);

function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
}

export function categoryColor(name?: string | null, explicit?: string | null): string {
  // The taxonomy palette wins so the same category reads the same everywhere;
  // explicit colors only apply to names outside the known taxonomy
  // (e.g. user-defined categories).
  const known = name ? normalizedPalette.get(normalizeKey(name)) : undefined;
  if (known) return known;
  if (explicit) return explicit;
  if (!name) return CATEGORY_PALETTE.Outros;
  return FALLBACK_CATEGORY_COLORS[hashString(name) % FALLBACK_CATEGORY_COLORS.length];
}
