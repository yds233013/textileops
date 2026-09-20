import type { Config } from "tailwindcss";

/**
 * The palette is deliberately restrained. This is a tool people stare at for
 * eight hours: colour carries meaning (severity, risk) and nothing else.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f6f7f9",
          100: "#eceef2",
          200: "#d5dae2",
          300: "#b0b9c8",
          400: "#8593a8",
          500: "#65748c",
          600: "#505d73",
          700: "#424c5e",
          800: "#39414f",
          900: "#333945",
          950: "#22262e",
        },
        critical: { bg: "#fef2f2", border: "#fecaca", text: "#991b1b", solid: "#dc2626" },
        high: { bg: "#fff7ed", border: "#fed7aa", text: "#9a3412", solid: "#ea580c" },
        medium: { bg: "#fefce8", border: "#fde68a", text: "#854d0e", solid: "#ca8a04" },
        low: { bg: "#f0f9ff", border: "#bae6fd", text: "#075985", solid: "#0284c7" },
        good: { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534", solid: "#16a34a" },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
