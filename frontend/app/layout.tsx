import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "TenderIQ",
  description: "Check your bid against the tender before you submit it.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-neutral-200 bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              Tender<span className="text-indigo-600">IQ</span>
            </Link>
            <nav className="flex gap-6 text-sm text-neutral-600">
              <Link href="/" className="hover:text-neutral-900">
                Tenders
              </Link>
              <Link href="/upload" className="hover:text-neutral-900">
                Upload
              </Link>
            </nav>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>

        <footer className="mx-auto max-w-6xl px-6 pb-10 pt-4 text-xs text-neutral-500">
          {/* Section 5.4 asks for this to be stated persistently in the UI. */}
          TenderIQ assists and summarises. It does not decide. Always verify
          against the official tender document before submitting.
        </footer>
      </body>
    </html>
  );
}
