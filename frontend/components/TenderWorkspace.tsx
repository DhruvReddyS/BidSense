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
        className="flex gap-1 border-b"
      >
        {TABS.map(({ key, label, hint }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            title={hint}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
              tab === key
                ? "border-[hsl(var(--accent))] text-[hsl(var(--accent))]"
                : "border-transparent text-fg-muted hover:text-fg"
            }`}
          >
            {label}
            {key === "requirements" && (
              <span className="tnum ml-1.5 text-xs opacity-60">
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
