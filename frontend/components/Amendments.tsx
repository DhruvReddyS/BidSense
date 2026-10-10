"use client";

/**
 * Amendments filed against a tender, and what each one does to the bids.
 *
 * This surface did not exist. Corrigenda were extracted, stored, served by the
 * API and fetched by the client, and then rendered nowhere -- so the most
 * consequential event in a live tender was invisible to the person evaluating
 * it.
 *
 * Amendments are listed newest first and never collapsed into a single "current
 * state": a tender amended twice was amended twice, and the audit trail needs
 * both. Impact is loaded on demand rather than for every amendment at once,
 * because assessing one re-runs the rule engine over every bid.
 */

import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { Corrigendum } from "@/lib/types";
import { AmendmentImpact } from "./AmendmentImpact";
import { Card, Chip, EmptyState, ErrorNote, formatDate } from "./ui";

export function Amendments({ tenderId }: { tenderId: string }) {
  const [list, setList] = useState<Corrigendum[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .corrigenda(tenderId)
      .then((rows) => live && setList(rows))
      .catch((caught: unknown) =>
        live &&
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not load amendments.",
        ),
      );
    return () => {
      live = false;
    };
  }, [tenderId]);

  if (error) return <ErrorNote>{error}</ErrorNote>;

  if (list === null) {
    return (
      <p
        className="text-sm text-[hsl(var(--fg-muted))]"
        role="status"
        aria-live="polite"
      >
        Loading amendments…
      </p>
    );
  }

  if (list.length === 0) {
    return (
      <EmptyState
        title="No amendments filed"
        body="Nothing has been issued against this tender. If a corrigendum is published, upload it here and this page will show which bidders it moves."
      />
    );
  }

  return (
    <div className="space-y-5">
      <p className="max-w-prose text-sm text-[hsl(var(--fg-muted))]">
        Newest first, and not merged into one view — a tender amended twice was
        amended twice, and both belong in the record.
      </p>

      {list.map((amendment) => {
        const expanded = open === amendment.corrigendum_id;
        return (
          <Card key={amendment.corrigendum_id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-mono text-sm font-medium break-anywhere">
                    {amendment.corrigendum_id}
                  </h3>
                  <Chip tone={amendment.applied ? "ok" : "pending"}>
                    {amendment.applied ? "Applied" : "Outstanding"}
                  </Chip>
                </div>
                <p className="mt-1 text-xs text-[hsl(var(--fg-muted))]">
                  Issued {formatDate(amendment.issued_date)} ·{" "}
                  {amendment.changed_fields.length} change
                  {amendment.changed_fields.length === 1 ? "" : "s"}
                </p>
              </div>

              <button
                type="button"
                className="btn btn-ghost shrink-0"
                aria-expanded={expanded}
                aria-controls={`impact-${amendment.corrigendum_id}`}
                onClick={() =>
                  setOpen(expanded ? null : amendment.corrigendum_id)
                }
              >
                {expanded ? "Hide impact" : "Assess impact"}
              </button>
            </div>

            {/* The raw diff, always visible: it is the amendment itself. */}
            <ul className="mt-4 space-y-2 border-t pt-4">
              {amendment.changed_fields.map((change, index) => (
                <li
                  key={`${change.field_path}-${index}`}
                  className="text-sm"
                >
                  <span className="font-medium">{change.label}</span>
                  {change.clause_ref && (
                    <span className="ref ml-2 text-[hsl(var(--fg-muted))]">
                      clause {change.clause_ref}
                    </span>
                  )}
                  <div className="mt-0.5 flex flex-wrap items-baseline gap-2 text-[hsl(var(--fg-muted))]">
                    <span className="line-through">
                      {change.old_value ?? "—"}
                    </span>
                    <span aria-hidden>→</span>
                    <span className="font-medium text-[hsl(var(--fg))]">
                      {change.new_value ?? "—"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>

            {expanded && (
              <div id={`impact-${amendment.corrigendum_id}`} className="mt-5">
                <AmendmentImpact
                  tenderId={tenderId}
                  corrigendumId={amendment.corrigendum_id}
                />
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
