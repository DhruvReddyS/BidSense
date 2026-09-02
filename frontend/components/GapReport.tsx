"use client";

import { useCallback, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type {
  ActionItem,
  CheckStatus,
  GapItem,
  GapReportResponse,
} from "@/lib/types";
import { ActionList } from "./ActionList";
import { DataQualityBanner, StalenessBanner } from "./Banners";
import { CitationViewer, type CitationTarget } from "./CitationViewer";
import { CompletionMeter } from "./CompletionMeter";
import { Amount, Cited, STATE, StateTag } from "./Cited";
import { TONE_EDGE, TONE_SURFACE, TONE_TEXT, VERDICT_META } from "./ui";

const KIND_LABEL: Record<GapItem["kind"], string> = {
  document: "Document",
  numeric: "Threshold",
  boolean: "Condition",
  format_rule: "Submission rule",
};

const FILTERS: (CheckStatus | "all" | "blocking")[] = [
  "all",
  "blocking",
  "missing",
  "partial",
  "manual_check",
  "not_assessable",
  "match",
];

const FILTER_LABEL: Record<string, string> = {
  all: "All",
  blocking: "Cannot be fixed",
  missing: "Outstanding",
  partial: "Confirm",
  manual_check: "Your check",
  not_assessable: "Unreadable",
  match: "Met",
};

// The same shapes as the rows, so a filter reads as the state it selects.
const FILTER_MARKER: Record<string, string> = {
  blocking: "marker-fail",
  missing: "marker-outstanding",
  partial: "marker-check",
  manual_check: "marker-check",
  not_assessable: "marker-check",
  match: "marker-met",
};

export function GapReport({
  data,
  onRefresh,
}: {
  data: GapReportResponse;
  onRefresh?: (acknowledgeAmendments: boolean) => Promise<void> | void;
}) {
  const [filter, setFilter] = useState<CheckStatus | "all" | "blocking">("all");
  const [tab, setTab] = useState<"actions" | "requirements">("actions");
  // Density, not a breakpoint. A vendor checking one bid and a reviewer
  // scanning fifteen are different jobs on the same laptop.
  const [dense, setDense] = useState(false);
  const [citation, setCitation] = useState<CitationTarget | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [exporting, setExporting] = useState<"pdf" | "docx" | null>(null);

  const { report, verdict, counts, staleness, data_quality, completion, sources } = data;
  const meta = VERDICT_META[verdict];

  const blocking = useMemo(
    () => report.items.filter((item) => item.severity === "disqualifying"),
    [report.items],
  );

  // Only the genuinely irreversible ones. `action_counts.blocking` also counts
  // documents to attach -- they block a submission, but they are fixable by
  // definition, and labelling them "cannot be fixed" put the SAME item under
  // two contradictory headings on a real report.
  const unfixable = useMemo(
    () => report.action_list.filter((action) => action.group === "hard_fail").length,
    [report.action_list],
  );

  const visible = useMemo(() => {
    if (filter === "all") return report.items;
    if (filter === "blocking") return blocking;
    return report.items.filter((item) => item.status === filter);
  }, [filter, report.items, blocking]);

  const tenderLabel = report.tender_id;
  const bidLabel = report.vendor_name ?? report.vendor_id;

  /** Open a citation on whichever document it belongs to. */
  const openCitation = useCallback(
    (side: "notification" | "bid", item: GapItem) => {
      const provenance =
        side === "notification" ? item.notification_provenance : item.submission_provenance;
      setCitation({
        contentHash: side === "notification" ? sources.notification : sources.bid,
        page: provenance?.source_page ?? null,
        snippet: provenance?.source_snippet ?? null,
        clauseRef: provenance?.clause_ref ?? null,
        documentLabel: side === "notification" ? tenderLabel : bidLabel,
      });
    },
    [sources, tenderLabel, bidLabel],
  );

  const openActionCitation = useCallback(
    (action: ActionItem) => {
      // The action list carries a clause reference; the matching gap item
      // carries the page and the snippet needed to mark the passage.
      const source = report.items.find(
        (item) => item.requirement === action.requirement,
      );
      setCitation({
        contentHash: sources.notification,
        page: source?.notification_provenance?.source_page ?? null,
        snippet: source?.notification_provenance?.source_snippet ?? null,
        clauseRef: action.clause_ref,
        documentLabel: tenderLabel,
      });
    },
    [report.items, sources.notification, tenderLabel],
  );

  async function recheck() {
    if (!onRefresh) return;
    setRechecking(true);
    try {
      await onRefresh(true);
    } finally {
      setRechecking(false);
    }
  }

  async function exportAs(fmt: "pdf" | "docx") {
    setExporting(fmt);
    try {
      await api.exportGapReport(report.tender_id, report.vendor_id, fmt);
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="space-y-5" data-density={dense ? "compact" : "comfortable"}>
      <StalenessBanner staleness={staleness} onRecheck={recheck} rechecking={rechecking} />

      {/* Verdict — the answer to the question the vendor came with. */}
      <section
        className={`card overflow-hidden border-2 ${TONE_EDGE[meta.tone]}`}
        aria-labelledby="verdict-heading"
      >
        <div className={`px-5 py-4 sm:px-6 sm:py-5 ${TONE_SURFACE[meta.tone]}`}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="label">Verdict</p>
              <h2
                id="verdict-heading"
                className={`mt-1 text-xl font-semibold tracking-tight sm:text-2xl ${TONE_TEXT[meta.tone]}`}
              >
                {meta.title}
              </h2>
              <p className="mt-1.5 max-w-xl text-[13.5px] leading-relaxed text-fg-muted">
                {meta.body}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                className="btn btn-ghost text-xs"
                onClick={() => exportAs("pdf")}
                disabled={exporting !== null}
              >
                {exporting === "pdf" ? "Preparing…" : "Export PDF"}
              </button>
              <button
                className="btn btn-ghost text-xs"
                onClick={() => exportAs("docx")}
                disabled={exporting !== null}
              >
                {exporting === "docx" ? "Preparing…" : "Export DOCX"}
              </button>
            </div>
          </div>
        </div>

        <dl className="grid grid-cols-2 divide-x divide-y border-t sm:grid-cols-4 sm:divide-y-0">
          <Stat
            label="Cannot be fixed"
            value={unfixable}
            marker="marker-fail"
            colour="text-[hsl(var(--bad))]"
          />
          <Stat
            label="Outstanding"
            value={counts.missing ?? 0}
            marker="marker-outstanding"
            colour="text-[hsl(var(--pending))]"
          />
          <Stat
            label="Your own check"
            value={(counts.manual_check ?? 0) + (counts.partial ?? 0) + (counts.not_assessable ?? 0)}
            marker="marker-check"
            colour="text-[hsl(var(--warn))]"
          />
          <Stat
            label="Met"
            value={counts.match ?? 0}
            marker="marker-met"
            colour="text-[hsl(var(--ok))]"
          />
        </dl>
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="order-2 min-w-0 space-y-5 lg:order-1">
          <div
            className="flex gap-1 rounded-lg border bg-[hsl(var(--surface-2))] p-1"
            role="tablist"
          >
            {(
              [
                ["actions", `What to do (${report.action_list.length})`],
                ["requirements", `Every requirement (${report.items.length})`],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`flex-1 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                  tab === key
                    ? "bg-[hsl(var(--surface))] text-fg shadow-sm"
                    : "text-fg-muted hover:text-fg"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "requirements" ? (
            <div className="flex items-center justify-end">
              <button
                className="ref text-fg-subtle underline-offset-2 hover:text-fg hover:underline"
                onClick={() => setDense((value) => !value)}
                title="Denser rows for working across many requirements"
              >
                {dense ? "comfortable rows" : "compact rows"}
              </button>
            </div>
          ) : null}

          {tab === "actions" ? (
            <ActionList actions={report.action_list} onCite={openActionCitation} />
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5">
                {FILTERS.map((key) => {
                  const count =
                    key === "all"
                      ? report.items.length
                      : key === "blocking"
                        ? blocking.length
                        : (counts[key] ?? 0);
                  if (!count && key !== "all") return null;
                  return (
                    <button
                      key={key}
                      onClick={() => setFilter(key)}
                      className={`chip transition-colors ${
                        filter === key
                          ? "border-[hsl(var(--accent-border))] bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]"
                          : "border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-fg-muted hover:text-fg"
                      }`}
                    >
                      {FILTER_MARKER[key] ? (
                        <span className={`marker ${FILTER_MARKER[key]}`} aria-hidden />
                      ) : null}
                      {FILTER_LABEL[key]}
                      <span className="tnum opacity-70">{count}</span>
                    </button>
                  );
                })}
              </div>

              <div className="card divide-y overflow-hidden">
                {visible.map((item, index) => (
                  <RequirementRow
                    key={`${item.requirement}-${index}`}
                    item={item}
                    onCite={openCitation}
                    hasSources={Boolean(sources.notification || sources.bid)}
                  />
                ))}
                {!visible.length ? (
                  <p className="px-5 py-8 text-center text-sm text-fg-muted">
                    No requirements in this category.
                  </p>
                ) : null}
              </div>
            </>
          )}
        </div>

        <aside className="order-1 space-y-5 lg:order-2">
          <CompletionMeter completion={completion} verdict={verdict} />
          <DataQualityBanner quality={data_quality} />
          {!report.score_preview.available ? (
            <section className="card p-5">
              <h2 className="label">Score preview</h2>
              <p className="mt-2 text-[13px] leading-relaxed text-fg-muted">
                {report.score_preview.unavailable_reason ??
                  "This tender does not publish scoring weightings, so no score is shown."}
              </p>
              <p className="mt-2 text-xs leading-relaxed text-fg-muted">
                Inventing one would be a number you could not trace to a clause.
              </p>
            </section>
          ) : null}
        </aside>
      </div>

      <CitationViewer target={citation} onClose={() => setCitation(null)} />
    </div>
  );
}

function Stat({
  label,
  value,
  marker,
  colour,
}: {
  label: string;
  value: number;
  marker: string;
  colour: string;
}) {
  return (
    <div className="px-5 py-3.5">
      <dt className={`flex items-center gap-1.5 label ${value ? colour : ""}`}>
        <span className={`marker ${marker}`} aria-hidden />
        {label}
      </dt>
      <dd className={`tnum mt-1 text-2xl font-semibold ${value ? colour : "text-fg-subtle"}`}>
        {value}
      </dd>
    </div>
  );
}

function RequirementRow({
  item,
  onCite,
  hasSources,
}: {
  item: GapItem;
  onCite: (side: "notification" | "bid", item: GapItem) => void;
  hasSources: boolean;
}) {
  const [why, setWhy] = useState(false);
  const blocking = item.severity === "disqualifying";
  const state = STATE[item.status];

  return (
    <article
      className="px-[var(--row-x)] py-[var(--row-y)]"
      data-status={item.status}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-[5px] ${blocking ? "text-[hsl(var(--bad))]" : state.colour}`}>
          <span className={`marker ${blocking ? "marker-fail" : state.marker}`} aria-hidden />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h3 className="break-anywhere min-w-0 text-[13.5px] font-medium leading-snug">
              {item.requirement}
            </h3>
            <StateTag status={item.status} blocking={blocking} />
          </div>

          <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">
            {item.explanation}
          </p>

          {/* Required and found sit side by side so the comparison the verdict
              rests on is the thing the eye lands on, with each side carrying
              its own source. */}
          {item.required_value || item.found_value ? (
            <dl className="mt-2.5 grid gap-x-6 gap-y-1.5 text-[12.5px] sm:grid-cols-2">
              {item.required_value ? (
                <div>
                  <dt className="label !tracking-normal !normal-case">Tender asks</dt>
                  <dd className="mt-0.5">
                    {hasSources ? (
                      <Cited
                        provenance={item.notification_provenance}
                        onOpen={() => onCite("notification", item)}
                      >
                        <Amount value={item.required_value} />
                      </Cited>
                    ) : (
                      <Amount value={item.required_value} />
                    )}
                  </dd>
                </div>
              ) : null}
              {item.found_value ? (
                <div>
                  <dt className="label !tracking-normal !normal-case">Your bid</dt>
                  <dd className="mt-0.5">
                    {hasSources && item.submission_provenance?.source_page ? (
                      <Cited
                        provenance={item.submission_provenance}
                        onOpen={() => onCite("bid", item)}
                      >
                        <Amount value={item.found_value} />
                      </Cited>
                    ) : (
                      <Amount value={item.found_value} />
                    )}
                  </dd>
                </div>
              ) : null}
            </dl>
          ) : null}

          {item.match_method ? (
            <button
              className="ref mt-2 text-fg-subtle underline-offset-2 hover:text-fg hover:underline"
              onClick={() => setWhy((value) => !value)}
            >
              matched by {item.match_method}
              {item.match_score !== null ? ` · ${item.match_score.toFixed(2)}` : ""}
            </button>
          ) : null}

          {why && item.match_method ? (
            <p className="mt-2 rounded border-l-2 border-[hsl(var(--border-strong))] bg-[hsl(var(--surface-2))] px-3 py-2 text-xs leading-relaxed text-fg-muted">
              {MATCH_EXPLANATION[item.match_method] ?? "Matched by name comparison."}
            </p>
          ) : null}
        </div>
      </div>
    </article>
  );
}

const MATCH_EXPLANATION: Record<string, string> = {
  exact: "The names are identical once punctuation and filler are removed.",
  alias:
    "A curated synonym table for standard Indian tender documents matched these two names — for example “GST Registration Certificate” and “Goods & Services Tax Certificate”.",
  lexical:
    "Known vocabulary matched them — “statutory auditor” and “chartered accountant” are the same role, and spelling and plurals are folded before comparison.",
  embedding:
    "No table covered these names, so they were compared by meaning. The score is cosine similarity; anything below the acceptance floor is shown for confirmation rather than counted as met.",
};
