"use client";

import { useState } from "react";

import type { DataQuality, Staleness } from "@/lib/types";

/**
 * Section 5.6 — the tender changed after this vendor last read their report.
 *
 * Deliberately the loudest thing on the page. A stale compliance answer is not
 * a degraded feature, it is a wrong answer that looks right, and a vendor who
 * scrolls past this can submit against terms that no longer apply. It sits
 * above the verdict rather than beside it for the same reason.
 *
 * The re-check is an explicit button, not something that happens on render:
 * viewing a report must not clear the flag, because the moment it renders is
 * exactly when the vendor has not yet acted on it.
 */
export function StalenessBanner({
  staleness,
  onRecheck,
  rechecking,
}: {
  staleness: Staleness;
  onRecheck: () => void;
  rechecking: boolean;
}) {
  if (!staleness.stale || !staleness.banner) return null;

  return (
    <div
      role="alert"
      className="animate-rise overflow-hidden rounded-xl border-2 border-[hsl(var(--warn-border))]
                 bg-[hsl(var(--warn-soft))]"
    >
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
        <div className="flex min-w-0 items-start gap-3">
          <span
            aria-hidden
            className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full
                       bg-[hsl(var(--warn))] text-sm font-bold text-white"
          >
            !
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-fg">
              This tender was amended after your last check
            </p>
            <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">
              {staleness.banner}
            </p>
            {staleness.changed_fields.length ? (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {staleness.changed_fields.map((field) => (
                  <li
                    key={field}
                    className="chip border-[hsl(var(--warn-border))] bg-[hsl(var(--surface))]
                               text-[hsl(var(--warn))]"
                  >
                    {field}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
        <button
          className="btn btn-primary shrink-0 self-start sm:self-auto"
          onClick={onRecheck}
          disabled={rechecking}
        >
          {rechecking ? "Re-checking…" : "Re-check now"}
        </button>
      </div>
    </div>
  );
}

/**
 * How much the figures below can be trusted.
 *
 * Kept separate from the verdict on purpose: one answers "does this bid meet
 * the tender", the other "how good was our reading of either document". A
 * confident verdict computed from a notification whose deadline and EMD were
 * never extracted is the failure this exists to make visible.
 *
 * Collapsed by default — on a clean run it says nothing, and when it does fire
 * the summary is the part that matters; the field-by-field detail is for
 * whoever wants to check.
 */
export function DataQualityBanner({ quality }: { quality: DataQuality }) {
  const [open, setOpen] = useState(false);
  if (quality.ok || !quality.banner) return null;

  const errors = quality.findings.filter(
    (finding) => finding.severity === "error" && finding.affects_confidence,
  );

  return (
    <div className="rounded-xl border border-[hsl(var(--info-border))] bg-[hsl(var(--info-soft))]">
      <button
        className="flex w-full items-start gap-3 p-4 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span
          aria-hidden
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full
                     border border-[hsl(var(--info-border))] bg-[hsl(var(--surface))]
                     text-xs font-bold text-[hsl(var(--info))]"
        >
          i
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-fg">
            Check the extraction before relying on this
          </span>
          <span className="mt-1 block text-[13px] leading-relaxed text-fg-muted">
            {quality.banner}
          </span>
        </span>
        <span className="shrink-0 text-xs font-medium text-[hsl(var(--info))]">
          {open ? "Hide" : `Show ${quality.findings.length}`}
        </span>
      </button>

      {open ? (
        <ul className="space-y-2 border-t border-[hsl(var(--info-border))] px-4 py-3">
          {quality.findings.map((finding, index) => (
            <li key={`${finding.field}-${index}`} className="flex gap-2.5 text-[13px]">
              <span
                className={`chip mt-0.5 h-fit shrink-0 ${
                  finding.severity === "error"
                    ? "border-[hsl(var(--bad-border))] bg-[hsl(var(--bad-soft))] text-[hsl(var(--bad))]"
                    : "border-[hsl(var(--neutral-border))] bg-[hsl(var(--surface))] text-fg-muted"
                }`}
              >
                {finding.source}
              </span>
              <span className="min-w-0">
                <span className="break-anywhere font-mono text-xs text-fg">
                  {finding.field}
                </span>
                <span className="mt-0.5 block leading-relaxed text-fg-muted">
                  {finding.message}
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {errors.length && !open ? (
        <p className="border-t border-[hsl(var(--info-border))] px-4 py-2 text-xs text-fg-muted">
          {errors.length} value{errors.length === 1 ? " is" : "s are"} present in
          the document but were not extracted.
        </p>
      ) : null}
    </div>
  );
}
