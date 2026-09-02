import type { Metadata } from "next";
import { IBM_Plex_Mono, Newsreader } from "next/font/google";
import Link from "next/link";
import "./globals.css";

/*
 * Three faces, each doing a job this document actually has.
 *
 * NEWSREADER (serif) for the things a reader stops on: the verdict, the
 * headline numbers, tender titles. A tender is a legal instrument and its
 * report should carry some of that register -- a serif at large size reads as
 * considered rather than generated, which is exactly the feeling this tool is
 * trying to produce. It appears ONLY at display sizes; a serif in a dense table
 * would be affectation.
 *
 * IBM PLEX MONO for identifiers -- clause refs, page numbers, tender ids. These
 * are matched character-by-character against a printed document, and Plex Mono
 * has unambiguous 1/l/I and 0/O, which a general-purpose mono does not
 * guarantee. This is the face that carries the citation grammar.
 *
 * System sans stays for everything read as prose.
 */
const display = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});
import { HealthPill } from "@/components/HealthPill";
import { Logo } from "@/components/Logo";
import { ThemeScript, ThemeToggle } from "@/components/Theme";

export const metadata: Metadata = {
  title: "BidSense — check your bid before you submit",
  description:
    "Upload a tender and your bid. See exactly what is missing, with the clause it comes from.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning className={`${display.variable} ${mono.variable}`}>
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
            <Link
              href="/"
              className="shrink-0 text-fg transition-opacity hover:opacity-80"
              aria-label="BidSense — home"
            >
              <Logo className="text-[26px]" />
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
              BidSense assists and summarises — it does not decide. Always check
              the official tender document before you submit.
            </p>
            <HealthPill />
          </div>
        </footer>
      </body>
    </html>
  );
}
