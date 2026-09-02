"use client";

import type { CheckStatus, Provenance } from "@/lib/types";

/**
 * A claim and the clause it rests on, as one unit.
 *
 * This is the product's core visual grammar rather than a formatting helper.
 * The thing BidSense does that a careful person with a highlighter does not is
 * refuse to assert anything without a page and clause behind it — so the
 * pairing is expressed identically in the gap report, the action list, the RAG
 * answer and the export, and a reader learns it once.
 *
 * The rule is absolute: a value carrying provenance is never rendered bare. A
 * figure with no dotted rule under it is a figure with no source, and that
 * difference has to be visible without reading.
 */
export function Cited({
  children,
  provenance,
  onOpen,
  destination,
}: {
  children: React.ReactNode;
  provenance: Provenance | null | undefined;
  onOpen?: () => void;
  /** What clicking opens, named before the click: "page 67". */
  destination?: string;
}) {
  const reference = provenance?.clause_ref
    ? provenance.clause_ref
    : provenance?.source_page
      ? `p${provenance.source_page}`
      : null;

  // No provenance means no claim to check. Rendered plainly, and the absence of
  // the rule is itself information.
  if (!provenance || !reference) {
    return <span>{children}</span>;
  }

  const page = provenance.source_page ? `page ${provenance.source_page}` : null;

  return (
    <button
      type="button"
      className="cited text-left"
      onClick={onOpen}
      title={
        page
          ? `Open ${page}${provenance.clause_ref ? `, clause ${provenance.clause_ref}` : ""} in the source document`
          : "Open the source document"
      }
    >
      <span className="claim">{children}</span>
      <span className="src">{reference}</span>
      {destination ?? page ? (
        <span className="go" aria-hidden>
          {destination ?? page} ↗
        </span>
      ) : null}
    </button>
  );
}

/**
 * A rupee amount, typeset so magnitudes compare.
 *
 * The digits carry the comparison — "is 3.45 below 3.77" — and the magnitude
 * word is context. Tabular figures so columns align; the unit a step down so
 * the number dominates the glance.
 */
export function Amount({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-fg-subtle">—</span>;
  // "₹3.45 Lakh" / "₹49.855 Cr" — split the unit off the digits.
  const match = value.match(/^(\D*[\d,.]+)\s*(Cr|Crore|Lakh|Lakhs|L)?\s*$/i);
  if (!match) return <span className="amount">{value}</span>;
  return (
    <span className="amount font-medium">
      {match[1]}
      {match[2] ? <span className="unit">{match[2]}</span> : null}
    </span>
  );
}

/**
 * The state of one requirement, on three channels at once.
 *
 * Colour is one channel and it fails alone — for a colour-blind reader it
 * carries nothing, and in a screenshot at a glance it carries little. Each
 * state therefore also has a SHAPE and a WORD, which is what makes the
 * three-state honesty (found / not found / needs your own check) as legible as
 * the four-way verdict rather than a footnote to it.
 */
export const STATE: Record<
  CheckStatus,
  { label: string; marker: string; colour: string; note: string }
> = {
  match: {
    label: "Met",
    marker: "marker-met",
    colour: "text-[hsl(var(--ok))]",
    note: "Found in your bid.",
  },
  missing: {
    label: "Outstanding",
    marker: "marker-outstanding",
    colour: "text-[hsl(var(--pending))]",
    note: "Not found. Most of these are fixable before you submit.",
  },
  partial: {
    label: "Confirm",
    marker: "marker-check",
    colour: "text-[hsl(var(--warn))]",
    note: "Something close was found. You decide whether it is the same document.",
  },
  manual_check: {
    label: "Your check",
    marker: "marker-check",
    colour: "text-[hsl(var(--warn))]",
    note: "Formatting and signing are visual. We do not claim to have verified them.",
  },
  not_assessable: {
    label: "Unreadable",
    marker: "marker-check",
    colour: "text-[hsl(var(--warn))]",
    note: "We could not read this value. That is not the same as failing it.",
  },
};

export function StateTag({
  status,
  blocking = false,
}: {
  status: CheckStatus;
  blocking?: boolean;
}) {
  // A blocking item is the one genuinely irreversible state, and it is the only
  // thing on screen that earns the strong colour.
  const state = STATE[status];
  const colour = blocking ? "text-[hsl(var(--bad))]" : state.colour;
  const marker = blocking ? "marker-fail" : state.marker;
  const label = blocking ? "Does not qualify" : state.label;

  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[11.5px]
                  font-medium ${colour}`}
    >
      <span className={`marker ${marker}`} aria-hidden />
      {label}
    </span>
  );
}
