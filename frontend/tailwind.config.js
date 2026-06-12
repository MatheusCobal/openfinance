import colors from "tailwindcss/colors";

/**
 * OpenFinance design tokens — "Quiet Cockpit" language.
 *
 * - One action color: `primary` (cobalt blue ramp).
 * - One neutral ramp: `ink` (slate alias) so pages never mix gray families.
 * - Semantic ramps: positive / warning / danger map to financial states.
 * - `accent` (violet) is reserved for rare, intentional highlights (charts).
 * - Surfaces: `surface` for light cards, `cockpit` for the dark hero shell.
 */

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        primary: colors.blue,
        ink: colors.slate,
        positive: colors.emerald,
        warning: colors.amber,
        danger: colors.rose,
        accent: colors.violet,
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f6f7f9",
          sunken: "#eef0f4",
        },
        cockpit: {
          DEFAULT: "#0b1220",
          raised: "#111a2c",
          edge: "#1e293b",
        },
      },
      borderRadius: {
        card: "1rem",
        control: "0.625rem",
      },
      boxShadow: {
        soft: "0 12px 30px -24px rgba(15, 23, 42, 0.45)",
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -20px rgba(15, 23, 42, 0.28)",
        lift: "0 2px 4px rgba(15, 23, 42, 0.05), 0 16px 40px -24px rgba(15, 23, 42, 0.35)",
        cockpit: "0 24px 60px -28px rgba(2, 6, 23, 0.65)",
        overlay: "0 24px 64px -16px rgba(15, 23, 42, 0.4)",
      },
      transitionTimingFunction: {
        swift: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};
