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
      <section className="card p-6 text-center">
        <p className="text-sm font-medium">Nothing outstanding.</p>
        <p className="mt-1 text-[13px] text-fg-muted">
          Every requirement we could check is satisfied. Formatting and signing
          are still yours to verify.
        </p>
      </section>
    );
  }

  const unconditional = actions.filter((action) => !action.applies_only_if);
  const conditional = actions.filter((action) => action.applies_only_if);

  return (
    <section className="space-y-4" aria-label="What to do next">
      {GROUPS.map((group) => {
        const items = unconditional.filter((action) => action.group === group.key);
        if (!items.length) return null;
        const tone = TONE[group.tone];

        return (
          <div key={group.key} className={`card overflow-hidden ${tone.border}`}>
            <header className={`border-b px-5 py-3 ${tone.bg} ${tone.border}`}>
              <div className="flex items-center gap-2.5">
                <span
                  className={`tnum flex h-6 min-w-6 items-center justify-center rounded-full
                              border bg-[hsl(var(--surface))] px-1.5 text-xs font-bold
                              ${tone.border} ${tone.fg}`}
                >
                  {items.length}
                </span>
                <h3 className="text-sm font-semibold">{group.heading}</h3>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-fg-muted">{group.blurb}</p>
            </header>
            <ol className="divide-y">
              {items.map((action, index) => (
                <Row key={`${group.key}-${index}`} action={action} onCite={onCite} />
              ))}
            </ol>
          </div>
        );
      })}

      {conditional.length ? (
        <div className="card overflow-hidden">
          <button
            className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left"
            onClick={() => setShowConditional((value) => !value)}
            aria-expanded={showConditional}
          >
            <span className="min-w-0">
              <span className="block text-sm font-medium">
                {conditional.length} item{conditional.length === 1 ? "" : "s"} that may
                not apply to you
              </span>
              <span className="mt-0.5 block text-xs text-fg-muted">
                Joint-venture and concession paperwork. Ignore these if you are
                bidding on your own.
              </span>
            </span>
            <span className="shrink-0 text-xs font-medium text-[hsl(var(--accent))]">
              {showConditional ? "Hide" : "Show"}
            </span>
          </button>
          {showConditional ? (
            <ol className="divide-y border-t">
              {conditional.map((action, index) => (
                <Row key={`cond-${index}`} action={action} onCite={onCite} conditional />
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </section>
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
    <li className="flex items-start gap-3 px-5 py-3.5">
      <span
        aria-hidden
        className={`mt-[3px] h-4 w-4 shrink-0 rounded border-2 ${
          conditional ? "border-[hsl(var(--border-strong))]" : "border-[hsl(var(--border-strong))]"
        }`}
      />
      <p className="min-w-0 flex-1 text-[13.5px] leading-relaxed">{action.action}</p>
      {action.clause_ref ? (
        <button
          className="chip shrink-0 border-transparent bg-[hsl(var(--surface-2))] font-mono
                     text-[11px] text-fg-muted transition-colors
                     hover:border-[hsl(var(--accent-border))] hover:bg-[hsl(var(--accent-soft))]
                     hover:text-[hsl(var(--accent))]"
          onClick={() => onCite?.(action)}
          title="Show this clause in the tender"
        >
          {action.clause_ref}
        </button>
      ) : null}
    </li>
  );
}
