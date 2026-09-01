import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { HealthPill } from "@/components/HealthPill";

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
    <html lang="en">
      <body className="min-h-screen">
        <header className="sticky top-0 z-40 border-b bg-[hsl(var(--surface))]/85 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-5">
            <Link href="/" className="group flex items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-[hsl(var(--accent))] text-[13px] font-bold text-[hsl(var(--accent-fg))]">
                T
              </span>
              <span className="text-[15px] font-semibold tracking-tight">
                Tender<span className="text-[hsl(var(--accent))]">IQ</span>
              </span>
            </Link>

            <nav className="flex items-center gap-1">
              <Link
                href="/"
                className="rounded-lg px-3 py-1.5 text-sm text-fg-muted transition-colors hover:bg-[hsl(var(--surface-2))] hover:text-fg"
              >
                Tenders
              </Link>
              <Link href="/upload" className="btn btn-primary ml-1 !px-3 !py-1.5">
                Add tender
              </Link>
            </nav>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>

        <footer className="mt-16 border-t">
          <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-6 text-xs text-fg-muted sm:flex-row sm:items-center sm:justify-between">
            {/* Section 5.4 asks for this to be stated persistently in the UI. */}
            <p className="max-w-xl">
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
