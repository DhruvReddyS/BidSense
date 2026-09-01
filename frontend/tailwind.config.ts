import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Status colours are used consistently across the gap report; defining
        // them once keeps "missing" from meaning one thing in the table and
        // another in the action list.
        status: {
          match: "#15803d",
          partial: "#b45309",
          missing: "#b91c1c",
          manual: "#4338ca",
          unknown: "#525252",
        },
      },
    },
  },
  plugins: [],
};
export default config;
