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
    <div className="space-y-8">
      <div className="border-b pb-7">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[.1em] text-[hsl(var(--fg-muted))] transition-colors hover:text-[hsl(var(--accent))]"
        >
          <span aria-hidden>←</span> All tenders
        </Link>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          {daysLeft !== null && daysLeft < 0 ? <span className="chip bg-[hsl(var(--neutral-soft))] text-[hsl(var(--fg-muted))]">Closed</span> : daysLeft !== null ? <span className="chip bg-[hsl(var(--warn-soft))] text-[hsl(var(--warn))]">{daysLeft} days remaining</span> : null}
          {tender.sector && <span className="chip capitalize bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]">{tender.sector}</span>}
        </div>
        <h1 className="font-display text-balance mt-4 max-w-5xl break-anywhere text-3xl font-medium leading-[1.08] tracking-[-.025em] sm:text-5xl">
          {tender.title}
        </h1>
        <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <span className="text-[hsl(var(--fg-muted))]">
            {tender.issuing_authority ?? "Issuing authority not stated"}
          </span>
        </div>
        <p className="mt-3 inline-flex max-w-full break-anywhere rounded-md bg-[hsl(var(--surface-2))] px-2 py-1 font-mono text-[10px] text-[hsl(var(--fg-subtle))]">
          {tender.tender_id}
        </p>
      </div>

      <div className="stagger grid grid-cols-2 border-y lg:grid-cols-4">
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
    <div className="relative border-b border-r px-3 py-5 even:border-r-0 sm:px-5 lg:border-b-0 lg:even:border-r lg:last:border-r-0">
      <p className="label">{label}</p>
      <p
        className={`font-display tnum mt-2 break-anywhere text-2xl font-medium leading-tight ${
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
