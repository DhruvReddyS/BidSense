"use client";

import { useState } from "react";
import Link from "next/link";
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
        className="flex overflow-x-auto border-b"
      >
        {TABS.map(({ key, label, hint }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            title={hint}
            onClick={() => setTab(key)}
            className={`relative shrink-0 px-4 py-3 text-sm font-medium transition-colors ${
              tab === key
                ? "text-[hsl(var(--accent))]"
                : "text-[hsl(var(--fg-muted))] hover:text-[hsl(var(--fg))]"
            }`}
          >
            {label}
            {key === "requirements" && <span className="tnum ml-1.5 rounded-full bg-[hsl(var(--surface-2))] px-1.5 py-0.5 text-[10px] text-[hsl(var(--fg-muted))]">{tender.eligibility_criteria.length + tender.mandatory_documents.length}</span>}
            {tab === key && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-[hsl(var(--accent))]" />}
          </button>
        ))}
        <Link href={`/tenders/${encodeURIComponent(tender.tender_id)}/review`} className="ml-auto shrink-0 px-4 py-3 text-sm font-medium text-[hsl(var(--accent))]">Company review <span aria-hidden>↗</span></Link>
      </div>

      <div className="pt-7">
        {tab === "check" && (
          <BidChecker tenderId={tender.tender_id} bids={bids} />
        )}
        {tab === "requirements" && <RequirementsView tender={tender} />}
        {tab === "ask" && <AskPanel tenderId={tender.tender_id} />}
      </div>
    </div>
  );
}
