"use client";

/**
 * What an amendment does to bids that have already been evaluated.
 *
 * A corrigendum is the most consequential event in a live tender: raising a
 * turnover floor from Rs 3 Cr to Rs 5 Cr means bidders who qualified no longer
 * do, and they have to be told. The backend computes that inside a database
 * savepoint and rolls back, so opening this panel never changes a verdict.
 *
 * The screen is ordered by what a reviewer has to decide, not by what the API
 * returns. The authorisation notice comes first when it applies, because an
 * amendment issued after the deadline that excludes a bidder is the one case
 * the system deliberately refuses to apply on its own -- a bid prepared against
 * the published rules cannot answer a requirement that did not exist when it
 * was written. Then who must be notified, then the per-bid detail, then the
 * mechanical outcome of each change.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { BidImpact, CorrigendumImpact } from "@/lib/types";
import { Card, Chip, EmptyState, ErrorNote, SectionTitle, formatDate } from "./ui";
import type { Tone } from "./ui";

/** Direction -> how to read it. `bad` is reserved for "you no longer qualify",
 *  which is the only irreversible outcome here. */
const DIRECTION_META: Record<
  string,
  { label: string; tone: Tone; blurb: string }
> = {
  newly_eliminated: {
    label: "No longer qualifies",
    tone: "bad",
    blurb: "Qualified before this amendment; does not now.",
  },
  reinstated: {
    label: "Qualifies again",
    tone: "ok",
    blurb: "Was excluded before this amendment; qualifies now.",
  },
  reason_changed: {
    label: "Same verdict, new clause",
    tone: "warn",
    blurb:
      "Still excluded, but under a different clause — which is what they would contest, so they are owed the new one.",
  },
  unchanged: {
    label: "Unaffected",
    tone: "neutral",
    blurb: "Standing is the same before and after.",
  },
};

const OUTCOME_TONE: Record<string, Tone> = {
  applied: "ok",
  conflict: "warn",
  ambiguous: "warn",
  unsupported: "neutral",
};

const OUTCOME_HINT: Record<string, string> = {
  conflict:
    "Nothing stored matches the value this amendment says it is replacing — usually because the tender was already amended and this corrigendum was drafted against the original.",
  ambiguous:
    "More than one stored requirement matches, so the system will not pick one.",
  unsupported: "No rule maps this field, so it was left alone.",
};

export function AmendmentImpact({
  tenderId,
  corrigendumId,
}: {
  tenderId: string;
  corrigendumId: string;
}) {
  const [impact, setImpact] = useState<CorrigendumImpact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .corrigendumImpact(tenderId, corrigendumId)
      .then((result) => live && setImpact(result))
      .catch((caught: unknown) =>
        live &&
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not assess this amendment.",
        ),
      )
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [tenderId, corrigendumId]);

  useEffect(load, [load]);

  if (loading) {
    return (
      <Card>
        <p
          className="text-sm text-[hsl(var(--fg-muted))]"
          role="status"
          aria-live="polite"
        >
          Working out what this amendment would change…
        </p>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <ErrorNote>{error}</ErrorNote>
        <button type="button" onClick={load} className="btn btn-ghost mt-3">
          Try again
        </button>
      </Card>
    );
  }

  if (!impact) return null;

  const moved = impact.impacts.filter((i) => i.direction !== "unchanged");
  const unchangedCount = impact.impacts.length - moved.length;

  return (
    <div className="space-y-4">
      {/* The decision the system refuses to take on its own. */}
      {impact.requires_human_review && (
        <Card className="border-[hsl(var(--bad-border))] bg-[hsl(var(--bad-soft))]">
          <div className="flex items-start gap-3">
            <span
              aria-hidden
              className="mt-0.5 text-base font-semibold text-[hsl(var(--bad))]"
            >
              !
            </span>
            <div>
              <h3 className="text-sm font-semibold text-[hsl(var(--bad))]">
                Needs your authorisation — not applied
              </h3>
              <p className="mt-1 max-w-prose text-sm">
                This amendment was issued on{" "}
                <strong>{formatDate(impact.issued_date)}</strong>, after the
                submission deadline of{" "}
                <strong>{formatDate(impact.submission_deadline)}</strong>, and it
                would newly exclude{" "}
                {impact.impacts.filter((i) => i.direction === "newly_eliminated")
                  .length}{" "}
                bidder(s).
              </p>
              <p className="mt-2 max-w-prose text-sm text-[hsl(var(--fg-muted))]">
                A bid prepared against the rules as published cannot answer a
                requirement that did not exist at submission time. Whether it may
                be excluded on that basis is a decision for the evaluation
                committee, so nothing has been written.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <SectionTitle
          title="Amendment impact"
          hint={impact.summary}
          right={
            <div className="flex flex-wrap items-center gap-2">
              {impact.is_retroactive && (
                <Chip tone="warn">After the deadline</Chip>
              )}
              <Chip tone={impact.applied ? "ok" : "pending"}>
                {impact.applied ? "Applied" : "Not applied"}
              </Chip>
            </div>
          }
        />

        <p className="text-xs text-[hsl(var(--fg-muted))]">
          Assessed without applying it: the amendment is replayed in a database
          savepoint and rolled back, so opening this view cannot change a
          verdict.
        </p>

        {impact.notify.length > 0 && (
          <div className="mt-4 rounded-xl border border-[hsl(var(--info-border))] bg-[hsl(var(--info-soft))] px-4 py-3">
            <p className="text-sm font-medium text-[hsl(var(--info))]">
              {impact.notify.length} bidder(s) must be notified
            </p>
            <p className="mt-1 font-mono text-xs text-[hsl(var(--fg-muted))]">
              {impact.notify.join(", ")}
            </p>
          </div>
        )}

        {moved.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              title="No bidder's standing changes"
              body={
                impact.impacts.length === 0
                  ? "No bids have been evaluated against this tender yet, so there is nothing to re-decide."
                  : `All ${impact.impacts.length} evaluated bid(s) are unaffected by this amendment.`
              }
            />
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <caption className="sr-only">
                Bidders whose standing changes under this amendment
              </caption>
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-[hsl(var(--fg-muted))]">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Bidder
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Change
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    Detail
                  </th>
                </tr>
              </thead>
              <tbody>
                {moved.map((item) => (
                  <ImpactRow key={item.vendor_id} item={item} />
                ))}
              </tbody>
            </table>
            {unchangedCount > 0 && (
              <p className="mt-3 text-xs text-[hsl(var(--fg-muted))]">
                {unchangedCount} further bid(s) unaffected.
              </p>
            )}
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle
          title="What the amendment changes"
          hint="Each clause the corrigendum alters, and whether it could be applied to the stored requirements."
        />
        <ul className="space-y-3">
          {impact.changes.map((change, index) => (
            <li
              key={`${change.field_path}-${index}`}
              className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b pb-3 last:border-b-0 last:pb-0"
            >
              <Chip tone={OUTCOME_TONE[change.outcome] ?? "neutral"}>
                {change.outcome}
              </Chip>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{change.label}</p>
                {change.detail && (
                  <p className="mt-0.5 text-sm text-[hsl(var(--fg-muted))]">
                    {change.detail}
                  </p>
                )}
                {OUTCOME_HINT[change.outcome] && (
                  <p className="mt-1 max-w-prose text-xs text-[hsl(var(--fg-muted))]">
                    {OUTCOME_HINT[change.outcome]}
                  </p>
                )}
                <p className="mt-1 font-mono text-[11px] text-[hsl(var(--fg-subtle))]">
                  {change.field_path}
                </p>
              </div>
            </li>
          ))}
        </ul>

        {impact.warnings.length > 0 && (
          <div className="mt-4 rounded-xl border border-[hsl(var(--warn-border))] bg-[hsl(var(--warn-soft))] px-4 py-3">
            <p className="text-sm font-medium text-[hsl(var(--warn))]">
              Worth a look
            </p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
              {impact.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}

function ImpactRow({ item }: { item: BidImpact }) {
  const meta = DIRECTION_META[item.direction] ?? DIRECTION_META.unchanged;
  return (
    <tr className="border-b last:border-b-0 align-top">
      <th scope="row" className="py-3 pr-4 text-left font-mono text-xs font-normal">
        {item.vendor_id}
      </th>
      <td className="py-3 pr-4">
        <Chip tone={meta.tone}>{meta.label}</Chip>
      </td>
      <td className="py-3">
        <p className="text-sm">{item.description}</p>
        <p className="mt-0.5 max-w-prose text-xs text-[hsl(var(--fg-muted))]">
          {meta.blurb}
        </p>
      </td>
    </tr>
  );
}
