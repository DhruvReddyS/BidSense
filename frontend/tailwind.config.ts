import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "hsl(var(--bg))",
        surface: "hsl(var(--surface))",
        "surface-2": "hsl(var(--surface-2))",
        border: "hsl(var(--border))",
        fg: {
          DEFAULT: "hsl(var(--fg))",
          muted: "hsl(var(--fg-muted))",
          subtle: "hsl(var(--fg-subtle))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          fg: "hsl(var(--accent-fg))",
          soft: "hsl(var(--accent-soft))",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI",
          "Inter", "Roboto", "Helvetica Neue", "Arial", "sans-serif",
        ],
        mono: [
          "var(--font-mono)", "ui-monospace", "SFMono-Regular",
          "Menlo", "Consolas", "monospace",
        ],
        display: ["var(--font-display)", "Georgia", "Times New Roman", "serif"],
      },
      // One radius. Every scale step resolves to the same near-sharp value, so
      // an accidental rounded-lg somewhere cannot reintroduce a second radius.
      borderRadius: {
        DEFAULT: "var(--radius)",
        sm: "var(--radius)",
        md: "var(--radius)",
        lg: "var(--radius)",
        xl: "var(--radius)",
        "2xl": "var(--radius)",
      },
      spacing: {
        tight: "var(--tight)",
        group: "var(--group)",
        section: "var(--section)",
      },
    },
  },
  plugins: [],
};
export default config;
