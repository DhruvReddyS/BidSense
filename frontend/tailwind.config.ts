import type { Config } from "tailwindcss";

const config: Config = {
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
          "ui-monospace", "SFMono-Regular", "Menlo", "Monaco",
          "Consolas", "monospace",
        ],
      },
      borderRadius: {
        xl: "var(--radius)",
      },
    },
  },
  plugins: [],
};
export default config;
