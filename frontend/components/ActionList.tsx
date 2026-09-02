"use client";

import { useState } from "react";

import type { ActionGroup, ActionItem } from "@/lib/types";

/**
 * Section 4.6 — what to do about it, in the order it needs doing.
 *
 * The ordering is the feature. Every unmet mandatory requirement is
 * "disqualifying", so sorting by severity alone once buried a turnover
 * shortfall at position 39 of 39, under thirty-eight documents that could be
 * attached in a morning. Grouping by what the vendor can DO about it puts the
 * unfixable first.
 *
 * Conditional items — joint-venture paperwork a sole proprietor neither has nor
 * needs — are collapsed behind a disclosure. On the GHMC tender they are six of
 * a compliant bidder's twenty-three to-dos, and a list that is mostly
 * inapplicable is a list people stop reading.
 */
const GROUPS: {
  key: ActionGroup;
  heading: string;
  blurb: string;
  tone: "bad" | "warn" | "info" | "neutral";
}[] = [
  {
    key: "hard_fail",
    heading: "Cannot be fixed by attaching a document",
    blurb: "You do not currently qualify on these. Consider a joint venture, or another tender.",
    tone: "bad",
  },
  {
    key: "upload",
    heading: "Documents to attach",
    blurb: "Each of these is a mandatory document we could not find in your bid.",
    tone: "warn",
  },
  {
    key: "clarify",
    heading: "Values to state clearly",
    blurb: "We could not read these from your bid. State them plainly so they can be checked.",
    tone: "info",
  },
  {
    key: "verify",
    heading: "To check yourself",
    blurb: "Formatting, signing and conditional rules are always left to a human.",
    tone: "neutral",
  },
];

const TONE: Record<string, { border: string; bg: string; fg: string }> = {
  bad: {
    border: "border-[hsl(var(--bad-border))]",
    bg: "bg-[hsl(var(--bad-soft))]",
    fg: "text-[hsl(var(--bad))]",
  },
  warn: {
    border: "border-[hsl(var(--warn-border))]",
    bg: "bg-[hsl(var(--warn-soft))]",
    fg: "text-[hsl(var(--warn))]",
  },
  info: {
    border: "border-[hsl(var(--info-border))]",
    bg: "bg-[hsl(var(--info-soft))]",
    fg: "text-[hsl(var(--info))]",
  },
  neutral: {
    border: "border-[hsl(var(--neutral-border))]",
    bg: "bg-[hsl(var(--surface-2))]",
    fg: "text-fg-muted",
  },
};

export function ActionList({
  actions,
  onCite,
}: {
  actions: ActionItem[];
  onCite?: (action: ActionItem) => void;
}) {
  const [showConditional, setShowConditional] = useState(false);

  if (!actions.length) {
    return (
      <p className="py-10 text-center text-sm text-fg-muted">
        Every requirement we could check is satisfied.
        <br />
        <span className="text-fg-subtle">
          Formatting and signing are still yours to verify.
        </span>
      </p>
    );
  }

  const unconditional = actions.filter((action) => !action.applies_only_if);
  const conditional = actions.filter((action) => action.applies_only_if);

  return (
    <div className="space-y-section" aria-label="What to do next">
      {GROUPS.map((group) => {
        const items = unconditional.filter((action) => action.group === group.key);
        if (!items.length) return null;
        const tone = TONE[group.tone];

        return (
          <section key={group.key}>
            {/*
              A section label and a rule, not a tinted card. Four groups meant
              four bordered boxes stacked inside the tab panel -- boxes within a
              box, which is the single thing that made this screen read as
              cheap. The heading and the whitespace above it do the same
              separating work, and the colour still lands where it matters:
              on the count and the marker.
            */}
            <header className="rule flex items-baseline gap-2.5 border-b pb-2">
              <span className={`tnum text-[15px] font-semibold ${tone.fg}`}>
                {items.length}
              </span>
              <h3 className="text-[13px] font-semibold tracking-tight">{group.heading}</h3>
            </header>
            <p className="mt-2 text-xs leading-relaxed text-fg-muted">{group.blurb}</p>

            <ol className="rule mt-3 divide-y divide-[hsl(var(--hairline))]">
              {items.map((action, index) => (
                <Row key={`${group.key}-${index}`} action={action} onCite={onCite} />
              ))}
            </ol>
          </section>
        );
      })}

      {conditional.length ? (
        <section>
          <button
            className="rule flex w-full items-baseline gap-2.5 border-b pb-2 text-left"
            onClick={() => setShowConditional((value) => !value)}
            aria-expanded={showConditional}
          >
            <span className="tnum text-[15px] font-semibold text-fg-subtle">
              {conditional.length}
            </span>
            <h3 className="flex-1 text-[13px] font-semibold tracking-tight text-fg-muted">
              May not apply to you
            </h3>
            <span className="ref text-[hsl(var(--accent))]">
              {showConditional ? "hide" : "show"}
            </span>
          </button>
          <p className="mt-2 text-xs leading-relaxed text-fg-muted">
            Joint-venture and concession paperwork. Ignore these if you are
            bidding on your own.
          </p>
          {showConditional ? (
            <ol className="rule mt-3 divide-y divide-[hsl(var(--hairline))]">
              {conditional.map((action, index) => (
                <Row key={`cond-${index}`} action={action} onCite={onCite} conditional />
              ))}
            </ol>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function Row({
  action,
  onCite,
  conditional = false,
}: {
  action: ActionItem;
  onCite?: (action: ActionItem) => void;
  conditional?: boolean;
}) {
  return (
    <li className="grid grid-cols-1 gap-x-5 py-[var(--row-y)] sm:grid-cols-[5.5rem_minmax(0,1fr)]">
      {/* Clause in the margin, as a printed statute sets it -- a reader
          checking "which clause was that" scans one column instead of hunting
          through prose. */}
      <div className="hidden pt-px text-right sm:block">
        {action.clause_ref ? (
          <button
            className="margin-note block w-full truncate hover:opacity-100 hover:underline"
            onClick={() => onCite?.(action)}
            title={`Clause ${action.clause_ref}`}
          >
            {action.clause_ref.length <= 14
              ? action.clause_ref
              : `${action.clause_ref.slice(0, 12)}…`}
          </button>
        ) : null}
      </div>

      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={`mt-[5px] h-3.5 w-3.5 shrink-0 rounded-[2px] border ${
            conditional
              ? "border-[hsl(var(--border))]"
              : "border-[hsl(var(--border-strong))]"
          }`}
        />
        <p className="min-w-0 flex-1 text-[13.5px] leading-relaxed">{action.action}</p>
      </div>
    </li>
  );
}
