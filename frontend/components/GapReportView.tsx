"use client";

import { useState } from "react";
import { ProvenanceNote } from "./Provenance";
import { SeverityBadge, StatusBadge, VerdictBanner } from "./StatusBadge";
import type { CheckStatus, GapReportResponse } from "@/lib/types";

const FILTERS: { key: CheckStatus | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "missing", label: "Missing" },
  { key: "partial", label: "Partial" },
  { key: "manual_check", label: "Check yourself" },
  { key: "not_assessable", label: "Couldn't read" },
  { key: "match", label: "Match" },
];

export function GapReportView({ data }: { data: GapReportResponse }) {
  const [filter, setFilter] = useState<CheckStatus | "all">("all");
  const { report, verdict, counts } = data;

  const items =
    filter === "all" ? report.items : report.items.filter((i) => i.status === filter);

  return (
    <div className="space-y-6">
      <VerdictBanner verdict={verdict} />

      {/* Section 4.6 — the action list comes first, because it is the thing a
          vendor actually needs to do something with. */}
      {report.action_list.length > 0 && (
        <section className="rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="font-medium">What to do next</h3>
          <ol className="mt-3 space-y-2">
            {report.action_list.map((action, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 w-6 shrink-0 text-right text-xs text-neutral-400">
                  {i + 1}.
                </span>
                <span className="flex-1">
                  {action.action}
                  {action.clause_ref && (
                    <span className="ml-2 text-xs text-neutral-500">
                      (clause {action.clause_ref})
                    </span>
                  )}
                </span>
                <SeverityBadge severity={action.severity} />
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* Section 4.4 — a score appears only if the tender published weights. */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h3 className="font-medium">Evaluation score</h3>
        {report.score_preview.available ? (
          <>
            <p className="mt-1 text-xs text-neutral-500">
              Estimated against the weightage published in this tender
              ({report.score_preview.total_weightage}% total). Indicative only.
            </p>
            <ul className="mt-3 space-y-2">
              {report.score_preview.items.map((item, i) => (
                <li key={i} className="flex items-center justify-between text-sm">
                  <span>{item.factor}</span>
                  <span className="flex items-center gap-3">
                    <span className="text-neutral-500">{item.weightage}%</span>
                    <StatusBadge status={item.status} />
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-sm text-neutral-600">
            {report.score_preview.unavailable_reason}
          </p>
        )}
      </section>

      <section>
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map(({ key, label }) => {
            const count = key === "all" ? report.items.length : (counts[key] ?? 0);
            if (count === 0 && key !== "all") return null;
            return (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                  filter === key
                    ? "bg-neutral-900 text-white"
                    : "bg-white text-neutral-700 ring-1 ring-inset ring-neutral-200 hover:bg-neutral-50"
                }`}
              >
                {label} ({count})
              </button>
            );
          })}
        </div>

        <div className="mt-4 space-y-3">
          {items.map((item, i) => (
            <article
              key={i}
              className="rounded-lg border border-neutral-200 bg-white p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <h4 className="font-medium text-neutral-900">{item.requirement}</h4>
                <StatusBadge status={item.status} />
              </div>

              <p className="mt-2 text-sm text-neutral-700">{item.explanation}</p>

              {(item.required_value || item.found_value) && (
                <dl className="mt-3 grid grid-cols-2 gap-4 text-xs">
                  <div>
                    <dt className="text-neutral-500">Required</dt>
                    <dd className="mt-0.5 font-medium">
                      {item.required_value ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-neutral-500">Found in your bid</dt>
                    <dd className="mt-0.5 font-medium">{item.found_value ?? "—"}</dd>
                  </div>
                </dl>
              )}

              {/* An embedding match is a guess with a number on it. Show the
                  number rather than presenting the match as settled fact. */}
              {item.match_method === "embedding" && item.match_score != null && (
                <p className="mt-2 text-xs text-neutral-500">
                  Matched by name similarity ({item.match_score.toFixed(2)}), not an
                  exact name match.
                </p>
              )}

              <ProvenanceNote
                provenance={item.notification_provenance}
                label="Tender clause"
              />
              <ProvenanceNote
                provenance={item.submission_provenance}
                label="From your bid"
              />
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
