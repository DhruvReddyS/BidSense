"use client";

import { useState } from "react";
import type { TenderDetail } from "@/lib/types";
import { AskPanel } from "./AskPanel";
import { BidChecker } from "./BidChecker";
import { RequirementsView } from "./RequirementsView";

type Tab = "check" | "requirements" | "ask";

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "check", label: "Check my bid", hint: "Upload a bid and see the gaps" },
  { key: "requirements", label: "Requirements", hint: "What this tender asks for" },
  { key: "ask", label: "Ask", hint: "Questions answered from the document" },
];

export function TenderWorkspace({
  tender,
  bids,
}: {
  tender: TenderDetail;
  bids: Parameters<typeof BidChecker>[0]["bids"];
}) {
  const [tab, setTab] = useState<Tab>("check");

  return (
    <div>
      <div
        role="tablist"
        aria-label="Tender sections"
        className="inline-flex gap-0.5 rounded-xl border bg-[hsl(var(--surface-2))] p-1"
      >
        {TABS.map(({ key, label, hint }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            title={hint}
            onClick={() => setTab(key)}
            className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition-all ${
              tab === key
                ? "bg-[hsl(var(--surface))] text-[hsl(var(--fg))] shadow-sm"
                : "text-[hsl(var(--fg-muted))] hover:text-[hsl(var(--fg))]"
            }`}
          >
            {label}
            {key === "requirements" && (
              <span className="tnum ml-1.5 text-xs opacity-55">
                {tender.eligibility_criteria.length + tender.mandatory_documents.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="pt-6">
        {tab === "check" && (
          <BidChecker tenderId={tender.tender_id} bids={bids} />
        )}
        {tab === "requirements" && <RequirementsView tender={tender} />}
        {tab === "ask" && <AskPanel tenderId={tender.tender_id} />}
      </div>
    </div>
  );
}
