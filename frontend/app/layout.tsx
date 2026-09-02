import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { HealthPill } from "@/components/HealthPill";
import { ThemeScript, ThemeToggle } from "@/components/Theme";

export const metadata: Metadata = {
  title: "TenderIQ — check your bid before you submit",
  description:
    "Upload a tender and your bid. See exactly what is missing, with the clause it comes from.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-screen">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-[hsl(var(--surface))] focus:px-4 focus:py-2 focus:text-sm focus:shadow-lg"
        >
          Skip to content
        </a>

        <header className="sticky top-0 z-40 border-b bg-[hsl(var(--bg))]/80 backdrop-blur-xl">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-5">
            <Link href="/" className="flex shrink-0 items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-[hsl(var(--accent))] text-[13px] font-bold text-[hsl(var(--accent-fg))] shadow-sm">
                T
              </span>
              <span className="text-[15px] font-semibold tracking-tight">
                Tender<span className="text-[hsl(var(--accent))]">IQ</span>
              </span>
            </Link>

            <nav className="flex items-center gap-2">
              <Link
                href="/"
                className="rounded-lg px-3 py-1.5 text-sm text-[hsl(var(--fg-muted))] transition-colors hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--fg))]"
              >
                Tenders
              </Link>
              <ThemeToggle />
              <Link href="/upload" className="btn btn-primary !px-3 !py-1.5">
                Add tender
              </Link>
            </nav>
          </div>
        </header>

        <main id="main" className="mx-auto max-w-6xl px-5 py-9">
          {children}
        </main>

        <footer className="mt-20 border-t bg-[hsl(var(--bg-alt))]">
          <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-7 text-xs text-[hsl(var(--fg-muted))] sm:flex-row sm:items-center sm:justify-between">
            {/* Section 5.4 asks for this to be stated persistently in the UI. */}
            <p className="max-w-xl leading-relaxed">
              TenderIQ assists and summarises — it does not decide. Always check
              the official tender document before you submit.
            </p>
            <HealthPill />
          </div>
        </footer>
      </body>
    </html>
  );
}
