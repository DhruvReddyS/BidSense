"use client";

import { useState } from "react";
import type { EligibilityCriterion, TenderDetail } from "@/lib/types";
import { Card, Chip, EmptyState, SectionTitle, formatInr } from "./ui";

/**
 * What the tender asks for, as extracted.
 *
 * Every value carries the clause and page it came from. That is not decoration:
 * extraction can be wrong, and a user who can see the source can catch it. A
 * figure shown without its provenance asks to be trusted blindly.
 */
export function RequirementsView({ tender }: { tender: TenderDetail }) {
  const [showAllDocs, setShowAllDocs] = useState(false);
  const docs = showAllDocs
    ? tender.mandatory_documents
    : tender.mandatory_documents.slice(0, 12);

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <SectionTitle
          title="Eligibility criteria"
          hint="Conditions you must satisfy for your bid to be considered."
          right={
            <span className="tnum text-xs text-fg-muted">
              {tender.eligibility_criteria.length}
            </span>
          }
        />
        {tender.eligibility_criteria.length === 0 ? (
          <EmptyState
            title="No eligibility criteria extracted"
            body="Either this document does not state them, or they could not be read. Check the tender document directly."
          />
        ) : (
          <ul className="divide-y">
            {tender.eligibility_criteria.map((c, i) => (
              <CriterionRow key={i} criterion={c} />
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-5">
        <SectionTitle
          title="Required documents"
          hint="Papers that must accompany your bid."
          right={
            <span className="tnum text-xs text-fg-muted">
              {tender.mandatory_documents.length}
            </span>
          }
        />
        <ul className="divide-y">
          {docs.map((doc, i) => (
            <li key={i} className="flex items-start gap-3 py-2.5">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[hsl(var(--fg-subtle))]" />
              <span className="min-w-0 flex-1 break-anywhere text-sm">
                {doc.doc_name}
              </span>
              {doc.provenance.clause_ref && (
                <span className="shrink-0 font-mono text-[11px] text-fg-subtle">
                  {doc.provenance.clause_ref}
                </span>
              )}
            </li>
          ))}
        </ul>
        {tender.mandatory_documents.length > 12 && (
          <button
            onClick={() => setShowAllDocs((v) => !v)}
            className="mt-3 text-xs text-[hsl(var(--accent))] hover:underline"
          >
            {showAllDocs
              ? "Show fewer"
              : `Show all ${tender.mandatory_documents.length}`}
          </button>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <SectionTitle
            title="Evaluation criteria"
            hint={
              tender.evaluation_criteria.some((c) => c.weightage_if_stated !== null)
                ? "This tender publishes its weightage."
                : "This tender does not publish weightage, so no score can be estimated."
            }
          />
          {tender.evaluation_criteria.length === 0 ? (
            <p className="text-sm text-fg-muted">
              No evaluation criteria are published in this document.
            </p>
          ) : (
            <ul className="divide-y">
              {tender.evaluation_criteria.map((c, i) => (
                <li key={i} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0 break-anywhere text-sm">{c.factor}</span>
                  <span className="tnum shrink-0 text-sm text-fg-muted">
                    {c.weightage_if_stated === null
                      ? "not stated"
                      : `${c.weightage_if_stated}%`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-5">
          <SectionTitle
            title="Submission rules"
            hint="Formatting and procedure. These need your own eye — they are usually visual."
          />
          {tender.submission_format_rules.length === 0 ? (
            <p className="text-sm text-fg-muted">None extracted.</p>
          ) : (
            <ul className="space-y-2">
              {tender.submission_format_rules.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[hsl(var(--info))]" />
                  <span className="break-anywhere">{r.rule}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function CriterionRow({ criterion }: { criterion: EligibilityCriterion }) {
  const threshold =
    criterion.threshold_amount?.amount_inr
      ? formatInr(criterion.threshold_amount.amount_inr)
      : criterion.threshold_number !== null
        ? `${criterion.threshold_number}${criterion.unit ? ` ${criterion.unit}` : ""}`
        : null;

  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 break-anywhere text-sm">{criterion.criterion}</p>
        <div className="flex shrink-0 gap-1.5">
          {!criterion.is_mandatory && <Chip>desirable</Chip>}
          <Chip tone={criterion.type === "numeric" ? "accent" : "neutral"}>
            {criterion.type}
          </Chip>
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
        {threshold ? (
          <span className="tnum font-medium">{threshold}</span>
        ) : criterion.threshold_raw ? (
          // Shown as printed, uninterpreted: we could not resolve it to a
          // number, and displaying a guess would be worse than showing the text.
          <span className="text-fg-muted">
            “{criterion.threshold_raw}” — could not be read as a number
          </span>
        ) : null}
        {threshold && criterion.threshold_raw && (
          <span className="text-fg-subtle">as printed: {criterion.threshold_raw}</span>
        )}
        <span className="ml-auto font-mono text-[11px] text-fg-subtle">
          {criterion.provenance.clause_ref && `clause ${criterion.provenance.clause_ref}`}
          {criterion.provenance.source_page && ` · p${criterion.provenance.source_page}`}
        </span>
      </div>
    </li>
  );
}
