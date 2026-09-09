import type { Metadata } from "next";
import { IBM_Plex_Mono, Newsreader } from "next/font/google";
import { AppChrome } from "@/components/AppChrome";
import { ThemeScript } from "@/components/Theme";
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
    <html lang="en" className={`${display.variable} ${mono.variable}`} suppressHydrationWarning>
      <head><ThemeScript /></head>
      <body className="app-shell min-h-screen">
        <a href="#main" className="skip-link">Skip to content</a>
        <AppChrome>{children}</AppChrome>
      </body>
    </html>
  );
}
