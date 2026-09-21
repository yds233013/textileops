import type { Config } from "tailwindcss";

/**
 * TextileOps design tokens.
 *
 * The palette is deliberately restrained. This is a tool people stare at for
 * eight hours: colour carries meaning — severity, risk, provenance — and
 * almost nothing else. There is one brand colour, an indigo taken from the dye
 * that coloured most of the world's cloth, used for primary actions, the
 * current page and focus. Everything else is ink.
 *
 * Provenance has its own colours, because the one thing this interface must
 * never do is make a model's opinion look like the system's record:
 *   - `fact`   what the deterministic engine calculated or the database holds
 *   - `source` text quoted from a third party (a supplier email, a document)
 *   - `ai`     interpretation written by a model
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          25: "#fbfbfc",
          50: "#f6f7f9",
          100: "#eceef2",
          150: "#e2e5eb",
          200: "#d5dae2",
          300: "#b0b9c8",
          400: "#8593a8",
          500: "#65748c",
          600: "#505d73",
          700: "#424c5e",
          800: "#2f3643",
          900: "#232833",
          950: "#161a22",
        },
        brand: {
          50: "#eef0fb",
          100: "#dde2f7",
          200: "#bcc5ef",
          300: "#93a1e4",
          400: "#6b7ad6",
          500: "#4c5ac7",
          600: "#3a45b0",
          700: "#30398f",
          800: "#2a3174",
          900: "#262c5e",
        },
        critical: { bg: "#fef2f2", border: "#fecaca", text: "#991b1b", solid: "#dc2626" },
        high: { bg: "#fff7ed", border: "#fed7aa", text: "#9a3412", solid: "#ea580c" },
        medium: { bg: "#fefce8", border: "#fde68a", text: "#854d0e", solid: "#ca8a04" },
        low: { bg: "#f0f9ff", border: "#bae6fd", text: "#075985", solid: "#0284c7" },
        good: { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534", solid: "#16a34a" },
        info: { bg: "#eff6ff", border: "#bfdbfe", text: "#1e40af", solid: "#2563eb" },
        fact: { bg: "#f6f7f9", border: "#d5dae2", text: "#2f3643" },
        source: { bg: "#fffbeb", border: "#fcd34d", text: "#78350f" },
        ai: { bg: "#f5f3ff", border: "#ddd6fe", text: "#5b21b6", solid: "#7c3aed" },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        DEFAULT: "6px",
        md: "6px",
        lg: "8px",
        xl: "10px",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(22 26 34 / 0.04), 0 0 0 1px rgb(22 26 34 / 0.02)",
        raised: "0 4px 12px -2px rgb(22 26 34 / 0.08), 0 2px 4px -2px rgb(22 26 34 / 0.05)",
        overlay: "0 20px 40px -12px rgb(22 26 34 / 0.25), 0 0 0 1px rgb(22 26 34 / 0.06)",
      },
      maxWidth: {
        // Content widths. Pages pick one; nothing floats across a 2560 px canvas.
        page: "1320px",
        wide: "1560px",
        narrow: "960px",
        prose: "68ch",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
      },
      animation: {
        shimmer: "shimmer 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
