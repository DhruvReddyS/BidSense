"use client";

import { useEffect, useState } from "react";

type Mode = "light" | "dark" | "system";

const KEY = "tenderiq-theme";

function resolve(mode: Mode): "light" | "dark" {
  if (mode !== "system") return mode;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(mode: Mode) {
  document.documentElement.dataset.theme = resolve(mode);
}

/**
 * Blocking script that sets the theme before first paint.
 *
 * Without this the page renders light and then flips, which on a dark-mode
 * machine is a white flash on every navigation. It has to run inline in the
 * document head, before React hydrates.
 */
export function ThemeScript() {
  const code = `(function(){try{var m=localStorage.getItem(${JSON.stringify(KEY)})||"system";var d=m==="dark"||(m==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light"}catch(e){document.documentElement.dataset.theme="light"}})()`;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}

export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("system");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let stored: Mode = "system";
    try { const value = localStorage.getItem(KEY); if (value === "light" || value === "dark") stored = value; } catch {}
    setMode(stored);
    setReady(true);

    // Follow the OS while the user has not made an explicit choice.
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      let preference: string | null = null;
      try { preference = localStorage.getItem(KEY); } catch {}
      if (!preference || preference === "system") apply("system");
    };
    media.addEventListener("change", onChange);
    const onTheme = (event: Event) => { const next = (event as CustomEvent).detail; if (["light", "dark", "system"].includes(next)) choose(next); };
    window.addEventListener("bidsense:theme", onTheme);
    return () => { media.removeEventListener("change", onChange); window.removeEventListener("bidsense:theme", onTheme); };
  }, []);

  function choose(next: Mode) {
    setMode(next);
    try { localStorage.setItem(KEY, next); } catch {}
    apply(next);
  }

  const options: { key: Mode; label: string; icon: React.ReactNode }[] = [
    { key: "light", label: "Light", icon: <SunIcon /> },
    { key: "system", label: "System", icon: <SystemIcon /> },
    { key: "dark", label: "Dark", icon: <MoonIcon /> },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex items-center gap-0.5 rounded-lg border bg-[hsl(var(--surface-2))] p-0.5"
    >
      {options.map(({ key, label, icon }) => (
        <button
          key={key}
          role="radio"
          aria-checked={ready && mode === key}
          aria-label={label}
          title={label}
          onClick={() => choose(key)}
          className={`grid h-6 w-6 place-items-center rounded-md transition-colors ${
            ready && mode === key
              ? "bg-[hsl(var(--surface))] text-[hsl(var(--fg))] shadow-sm"
              : "text-[hsl(var(--fg-subtle))] hover:text-[hsl(var(--fg-muted))]"
          }`}
        >
          {icon}
        </button>
      ))}
    </div>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path strokeLinecap="round" d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <rect x="2" y="4" width="20" height="13" rx="2" />
      <path strokeLinecap="round" d="M8 21h8m-4-4v4" />
    </svg>
  );
}
