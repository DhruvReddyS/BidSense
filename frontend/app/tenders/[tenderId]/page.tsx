import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { TenderWorkspace } from "@/components/TenderWorkspace";
import { ErrorNote, formatDate, formatInr } from "@/components/ui";
import type { TenderDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function TenderPage({
  params,
}: {
  params: { tenderId: string };
}) {
  const tenderId = decodeURIComponent(params.tenderId);

  let tender: TenderDetail | null = null;
  let bids: Awaited<ReturnType<typeof api.submissions>> = [];
  let error: string | null = null;

  try {
    tender = await api.notification(tenderId);
    bids = await api.submissions(tenderId).catch(() => []);
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Could not load this tender.";
  }

  if (error || !tender) {
    return (
      <div className="space-y-4">
        <Link href="/" className="text-sm text-[hsl(var(--accent))] hover:underline">
          ← All tenders
        </Link>
        <ErrorNote>{error ?? "Tender not found."}</ErrorNote>
      </div>
    );
  }

  const deadline = tender.submission_deadline;
  const daysLeft = deadline
    ? Math.ceil(
        (new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
      )
    : null;

  return (
    <div className="space-y-7">
      <div className="relative -mx-5 -mt-9 px-5 pb-1 pt-9">
        <div className="grid-backdrop pointer-events-none absolute inset-0 -z-10" />
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--fg-muted))] transition-colors hover:text-[hsl(var(--accent))]"
        >
          <span aria-hidden>←</span> All tenders
        </Link>
        <h1 className="mt-3 max-w-4xl break-anywhere text-[1.7rem] font-semibold leading-[1.2] tracking-tight">
          {tender.title}
        </h1>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <span className="text-[hsl(var(--fg-muted))]">
            {tender.issuing_authority ?? "Issuing authority not stated"}
          </span>
          {tender.sector && (
            <>
              <span className="text-[hsl(var(--fg-subtle))]" aria-hidden>·</span>
              <span className="text-[hsl(var(--fg-muted))]">{tender.sector}</span>
            </>
          )}
        </div>
        <p className="mt-1.5 break-anywhere font-mono text-[11px] text-[hsl(var(--fg-subtle))]">
          {tender.tender_id}
        </p>
      </div>

      <div className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Bids close"
          value={formatDate(deadline)}
          note={
            daysLeft === null
              ? "not stated in the document"
              : daysLeft < 0
                ? "closed"
                : `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`
          }
          urgent={daysLeft !== null && daysLeft >= 0 && daysLeft <= 7}
        />
        <Stat
          label="Pre-bid queries by"
          value={formatDate(tender.pre_bid_query_deadline)}
        />
        <Stat
          label="EMD"
          value={
            tender.emd_amount?.amount_inr
              ? formatInr(tender.emd_amount.amount_inr)
              : (tender.emd_amount?.raw_text ?? "—")
          }
          note={tender.emd_amount?.raw_text ?? undefined}
        />
        <Stat
          label="Estimated value"
          value={
            tender.contract_value_estimate?.amount_inr
              ? formatInr(tender.contract_value_estimate.amount_inr)
              : (tender.contract_value_estimate?.raw_text ?? "—")
          }
        />
      </div>

      <TenderWorkspace tender={tender} bids={bids} />
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  urgent,
}: {
  label: string;
  value: string;
  note?: string;
  urgent?: boolean;
}) {
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p
        className={`tnum mt-1.5 break-anywhere text-lg font-semibold leading-tight ${
          urgent ? "text-[hsl(var(--warn))]" : ""
        }`}
      >
        {value}
      </p>
      {note && (
        <p
          className="mt-1 truncate text-xs text-[hsl(var(--fg-subtle))]"
          title={note}
        >
          {note}
        </p>
      )}
    </div>
  );
}
