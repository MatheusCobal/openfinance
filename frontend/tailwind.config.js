import colors from "tailwindcss/colors";

/**
 * OpenFinance: petroleum blue for orientation and actions, semantic colors
 * for financial meaning. Keep user-defined category colors independent.
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
        primary: {
          50: "#eef8f9", 100: "#d8eef1", 200: "#b2dce2", 300: "#7fc0cb",
          400: "#47a2b3", 500: "#27899e", 600: "#18778a", 700: "#176073",
          800: "#164e5e", 900: "#123e4b", 950: "#0b2b35",
        },
        ink: colors.slate,
        positive: colors.emerald,
        warning: colors.amber,
        danger: colors.rose,
        accent: colors.cyan,
        information: colors.sky,
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f3f7f8",
          sunken: "#eaf0f2",
        },
        cockpit: {
          DEFAULT: "#123e4b",
          raised: "#194c59",
          edge: "#2e606c",
        },
      },
      borderRadius: {
        card: "1.125rem",
        control: "0.625rem",
      },
      boxShadow: {
        soft: "0 12px 30px -24px rgba(15, 23, 42, 0.45)",
        card: "0 2px 4px -2px rgba(18, 62, 75, 0.06)",
        lift: "0 2px 4px rgba(15, 23, 42, 0.05), 0 16px 40px -24px rgba(15, 23, 42, 0.35)",
        cockpit: "0 12px 32px -24px rgba(18, 62, 75, 0.4)",
        overlay: "0 24px 64px -16px rgba(15, 23, 42, 0.4)",
      },
      transitionTimingFunction: {
        swift: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};
