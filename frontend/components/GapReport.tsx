"use client";

import { useMemo, useState } from "react";
import type {
  ActionGroup,
  ActionItem,
  CheckStatus,
  GapItem,
  GapReportResponse,
} from "@/lib/types";
import {
  Card,
  Chip,
  SectionTitle,
  SeverityChip,
  STATUS_META,
  StatusBar,
  StatusChip,
  VERDICT_META,
} from "./ui";

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

export function GapReport({ data }: { data: GapReportResponse }) {
  const [filter, setFilter] = useState<CheckStatus | "all" | "blocking">("all");
  const [group, setGroup] = useState(true);
  const { report, verdict, counts } = data;
  const meta = VERDICT_META[verdict];

  const blocking = useMemo(
    () => report.items.filter((i) => i.severity === "disqualifying"),
    [report.items],
  );

  const visible = useMemo(() => {
    if (filter === "all") return report.items;
    if (filter === "blocking") return blocking;
    return report.items.filter((i) => i.status === filter);
  }, [filter, report.items, blocking]);

  const grouped = useMemo(() => {
    if (!group) return [["All requirements", visible]] as [string, GapItem[]][];
    const buckets = new Map<string, GapItem[]>();
    for (const item of visible) {
      const key = KIND_LABEL[item.kind];
      buckets.set(key, [...(buckets.get(key) ?? []), item]);
    }
    // Thresholds first: a failed number is the most consequential kind of gap.
    const order = ["Threshold", "Document", "Condition", "Submission rule"];
    return order
      .filter((k) => buckets.has(k))
      .map((k) => [k, buckets.get(k)!] as [string, GapItem[]]);
  }, [visible, group]);

  return (
    <div className="space-y-6">
      {/* Verdict ------------------------------------------------------- */}
      <Card
        className={`overflow-hidden border-[hsl(var(--${meta.tone}-border))]`}
      >
        <div className={`bg-[hsl(var(--${meta.tone}-soft))] p-5`}>
          <div className="flex items-start gap-3.5">
            <span
              className={`grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[hsl(var(--${meta.tone}))] text-base font-bold text-white`}
              aria-hidden
            >
              {meta.icon}
            </span>
            <div className="min-w-0">
              <p className={`font-semibold text-[hsl(var(--${meta.tone}))]`}>
                {meta.title}
              </p>
              <p className="mt-1 text-sm text-fg-muted">{meta.body}</p>
              {report.vendor_name && (
                <p className="mt-2 text-xs text-fg-subtle">
                  Bid from {report.vendor_name}
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-3 p-5">
          <StatusBar counts={counts} />
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {(Object.keys(STATUS_META) as CheckStatus[]).map((key) => {
              const value = counts[key] ?? 0;
              if (!value) return null;
              return (
                <div key={key} className="flex items-center gap-2 text-xs">
                  <span className={`h-2 w-2 rounded-full ${STATUS_META[key].dot}`} />
                  <span className="tnum font-semibold">{value}</span>
                  <span className="text-fg-muted">{STATUS_META[key].label}</span>
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      {/* Section 4.6 — the action list, grouped by what the vendor can do. */}
      <ActionList actions={report.action_list} />

      {/* Section 4.4 — a score only if the tender published weights. */}
      <Card className="p-5">
        <SectionTitle
          title="Evaluation score"
          hint={
            report.score_preview.available
              ? `Estimated against the weightage this tender publishes (${report.score_preview.total_weightage}% total).`
              : undefined
          }
        />
        {report.score_preview.available ? (
          <ul className="divide-y">
            {report.score_preview.items.map((item, i) => (
              <li key={i} className="flex items-center justify-between gap-4 py-2.5">
                <span className="min-w-0 break-anywhere text-sm">{item.factor}</span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="tnum text-sm text-fg-muted">{item.weightage}%</span>
                  <StatusChip status={item.status} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">
            {report.score_preview.unavailable_reason}
          </p>
        )}
      </Card>

      {/* Requirements --------------------------------------------------- */}
      <div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {FILTERS.map((key) => {
            const count =
              key === "all"
                ? report.items.length
                : key === "blocking"
                  ? blocking.length
                  : (counts[key] ?? 0);
            if (count === 0 && key !== "all") return null;
            const label =
              key === "all"
                ? "Everything"
                : key === "blocking"
                  ? "Blocking"
                  : STATUS_META[key].label;
            const active = filter === key;
            return (
              <button
                key={key}
                onClick={() => setFilter(key)}
                aria-pressed={active}
                className={`chip transition-colors ${
                  active
                    ? "border-transparent bg-[hsl(var(--fg))] text-[hsl(var(--surface))]"
                    : "bg-[hsl(var(--surface))] hover:bg-[hsl(var(--surface-2))]"
                }`}
              >
                {label}
                <span className="tnum opacity-60">{count}</span>
              </button>
            );
          })}
          <button
            onClick={() => setGroup((g) => !g)}
            className="ml-auto text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline"
          >
            {group ? "Show as one list" : "Group by type"}
          </button>
        </div>

        <div className="space-y-6">
          {grouped.map(([heading, items]) => (
            <section key={heading}>
              {group && (
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
                  {heading}
                  <span className="tnum ml-2 font-normal opacity-60">
                    {items.length}
                  </span>
                </h3>
              )}
              <div className="space-y-2">
                {items.map((item, i) => (
                  <RequirementRow key={`${heading}-${i}`} item={item} />
                ))}
              </div>
            </section>
          ))}
          {visible.length === 0 && (
            <p className="py-10 text-center text-sm text-fg-muted">
              Nothing in this category.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function RequirementRow({ item }: { item: GapItem }) {
  const [open, setOpen] = useState(false);
  const provenance = item.notification_provenance;
  const hasDetail =
    !!provenance?.source_snippet || !!item.submission_provenance?.source_snippet;

  return (
    <Card
      className={`overflow-hidden ${
        item.severity === "disqualifying"
          ? "border-l-2 border-l-[hsl(var(--bad))]"
          : ""
      }`}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 break-anywhere text-sm font-medium leading-snug">
            {item.requirement}
          </p>
          <StatusChip status={item.status} />
        </div>

        <p className="mt-1.5 break-anywhere text-sm text-fg-muted">
          {item.explanation}
        </p>

        {(item.required_value || item.found_value) && (
          <div className="mt-3 grid grid-cols-1 gap-3 rounded-lg bg-[hsl(var(--surface-2))] p-3 text-xs sm:grid-cols-2">
            <div className="min-w-0">
              <p className="label">Tender requires</p>
              <p className="tnum mt-0.5 break-anywhere font-medium">
                {item.required_value ?? "—"}
              </p>
            </div>
            <div className="min-w-0">
              <p className="label">Your bid shows</p>
              <p
                className={`tnum mt-0.5 break-anywhere font-medium ${
                  item.status === "missing" ? "text-[hsl(var(--bad))]" : ""
                }`}
              >
                {item.found_value ?? "not found"}
              </p>
            </div>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-fg-subtle">
          {provenance?.clause_ref && (
            <span className="font-mono">clause {provenance.clause_ref}</span>
          )}
          {provenance?.source_page && <span>page {provenance.source_page}</span>}
          {/* An embedding match is a guess with a number on it. Show the number
              rather than presenting the match as settled. */}
          {item.match_method === "embedding" && item.match_score != null && (
            <Chip tone="warn">name similarity {item.match_score.toFixed(2)}</Chip>
          )}
          {!item.is_mandatory && <Chip>desirable, not mandatory</Chip>}
          {hasDetail && (
            <button
              onClick={() => setOpen((o) => !o)}
              className="ml-auto underline-offset-2 hover:text-fg hover:underline"
            >
              {open ? "Hide source" : "Show source text"}
            </button>
          )}
        </div>
      </div>

      {open && (
        <div className="animate-rise space-y-3 border-t bg-[hsl(var(--surface-2))] p-4">
          {provenance?.source_snippet && (
            <Quote label="From the tender" text={provenance.source_snippet} />
          )}
          {item.submission_provenance?.source_snippet && (
            <Quote label="From your bid" text={item.submission_provenance.source_snippet} />
          )}
        </div>
      )}
    </Card>
  );
}

function Quote({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <p className="label">{label}</p>
      {/* Verbatim and visibly quoted: the point is that the reader can check it
          against the source document, so it is never paraphrased or trimmed. */}
      <blockquote className="mt-1 border-l-2 border-[hsl(var(--border-strong))] pl-3 text-xs italic leading-relaxed text-fg-muted break-anywhere">
        {text}
      </blockquote>
    </div>
  );
}


const ACTION_GROUPS: {
  key: ActionGroup;
  title: string;
  blurb: string;
  tone: "bad" | "warn" | "info" | "neutral";
  openByDefault: boolean;
}[] = [
  {
    key: "hard_fail",
    title: "You do not meet these",
    blurb:
      "These cannot be fixed by attaching a document. Unless the figures are wrong, this tender is not open to you as a sole bidder.",
    tone: "bad",
    openByDefault: true,
  },
  {
    key: "clarify",
    title: "State these clearly",
    blurb:
      "Your bid does not say, or says it in a form we could not read. Put the figure in plain digits.",
    tone: "warn",
    openByDefault: true,
  },
  {
    key: "upload",
    title: "Documents to attach",
    blurb: "Each of these is required and was not found in your bid.",
    tone: "warn",
    openByDefault: false,
  },
  {
    key: "verify",
    title: "Check these yourself",
    blurb:
      "Formatting, signing, and requirements that may not apply to you. We cannot verify these from the text.",
    tone: "info",
    openByDefault: false,
  },
];

/**
 * The action list, grouped by fixability.
 *
 * A flat list ranked by severity is useless on a real tender: every unmet
 * mandatory requirement is "disqualifying", so a single unfixable failure sits
 * in a run of forty document uploads. Splitting them means the vendor sees "you
 * do not meet the turnover floor" before "attach Form FIN-2", which is the
 * order in which those two facts matter.
 */
function ActionList({ actions }: { actions: ActionItem[] }) {
  if (actions.length === 0) {
    return (
      <Card className="p-5">
        <p className="text-sm">
          Nothing to do — every requirement we could check is satisfied.
        </p>
      </Card>
    );
  }

  const known = new Set(ACTION_GROUPS.map((g) => g.key));
  // Anything the client does not recognise still has to be shown. A field the
  // API stopped sending, or a group added server-side, must not silently blank
  // the most important section of the report.
  const ungrouped = actions.filter((a) => !known.has(a.group));

  return (
    <div className="space-y-3">
      {ACTION_GROUPS.map((group) => {
        const items = actions.filter((a) => a.group === group.key);
        if (items.length === 0) return null;
        return <ActionGroupCard key={group.key} group={group} items={items} />;
      })}
      {ungrouped.length > 0 && (
        <ActionGroupCard
          group={{
            key: "verify",
            title: "What to do next",
            blurb: "Ordered by what will stop your bid first.",
            tone: "warn",
            openByDefault: true,
          }}
          items={ungrouped}
        />
      )}
    </div>
  );
}

function ActionGroupCard({
  group,
  items,
}: {
  group: (typeof ACTION_GROUPS)[number];
  items: ActionItem[];
}) {
  // Long groups collapse by default so a 44-item upload list does not push the
  // one unfixable failure off the screen.
  const [open, setOpen] = useState(group.openByDefault || items.length <= 6);

  return (
    <Card className={`overflow-hidden border-l-2 border-l-[hsl(var(--${group.tone}))]`}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-4 p-5 text-left transition-colors hover:bg-[hsl(var(--surface-2))]"
      >
        <div className="min-w-0">
          <p className={`text-sm font-semibold text-[hsl(var(--${group.tone}))]`}>
            {group.title}
            <span className="tnum ml-2 font-normal opacity-70">{items.length}</span>
          </p>
          <p className="mt-1 text-xs text-fg-muted">{group.blurb}</p>
        </div>
        <span className="shrink-0 text-xs text-fg-subtle">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <ol className="animate-rise divide-y border-t">
          {items.map((action, i) => (
            <li key={i} className="flex items-start gap-3 px-5 py-2.5">
              <span className="tnum mt-0.5 w-5 shrink-0 text-right text-xs text-fg-subtle">
                {i + 1}
              </span>
              <span className="min-w-0 flex-1 break-anywhere text-sm">
                {action.action}
                {action.clause_ref && (
                  <span className="ml-2 font-mono text-[11px] text-fg-subtle">
                    {action.clause_ref}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}