import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { NotificationList, NotificationSummary } from "@/lib/types";
import { Card, Chip, EmptyState, ErrorNote, formatDate, formatInr } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Home() {
  let data: NotificationList | null = null;
  let error: string | null = null;

  try {
    data = await api.listNotifications();
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Something went wrong.";
  }

  const tenders = data?.items ?? [];
  const totalBids = tenders.reduce((sum, t) => sum + t.submission_count, 0);
  const totalCriteria = tenders.reduce(
    (sum, t) => sum + t.eligibility_count + t.document_count,
    0,
  );

  return (
    <div className="space-y-8">
      <section className="relative -mx-5 -mt-9 px-5 pb-2 pt-12">
        <div className="grid-backdrop pointer-events-none absolute inset-0 -z-10" />
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <h1 className="text-[2rem] font-semibold leading-tight tracking-tight">
              Know what is missing
              <br />
              <span className="text-[hsl(var(--fg-muted))]">
                before you submit.
              </span>
            </h1>
            <p className="mt-3 max-w-lg text-sm leading-relaxed text-[hsl(var(--fg-muted))]">
              Upload a tender notification and your draft bid. Every requirement
              is checked against the clause it comes from, and anything we
              cannot verify is said plainly rather than guessed.
            </p>
          </div>

          {tenders.length > 0 && (
            <dl className="flex gap-7">
              <Metric label="Tenders" value={String(data!.page.total)} />
              <Metric label="Bids checked" value={String(totalBids)} />
              <Metric label="Requirements" value={String(totalCriteria)} />
            </dl>
          )}
        </div>
      </section>

      {error && <ErrorNote>{error}</ErrorNote>}

      {!error && tenders.length === 0 && (
        <EmptyState
          title="No tenders yet"
          body="Upload the official tender notification. Everything your bid is checked against is read from that document, so use the version the authority published."
          action={
            <Link href="/upload" className="btn btn-primary">
              Add your first tender
            </Link>
          }
        />
      )}

      {tenders.length > 0 && (
        <div className="stagger grid gap-3">
          {tenders.map((tender) => (
            <TenderCard key={tender.tender_id} tender={tender} />
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="tnum mt-1 text-2xl font-semibold leading-none">{value}</dd>
    </div>
  );
}

function TenderCard({ tender }: { tender: NotificationSummary }) {
  const deadline = tender.submission_deadline;
  const daysLeft = deadline
    ? Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000)
    : null;
  const closed = daysLeft !== null && daysLeft < 0;
  const urgent = daysLeft !== null && daysLeft >= 0 && daysLeft <= 14;

  return (
    <Link
      href={`/tenders/${encodeURIComponent(tender.tender_id)}`}
      className="block"
    >
      <Card className="card-hover group relative overflow-hidden p-5">
        {/* A hairline that warms on hover — enough to signal the whole card is
            a target without adding a button that competes with it. */}
        <span className="absolute inset-y-0 left-0 w-[2px] bg-[hsl(var(--accent))] opacity-0 transition-opacity group-hover:opacity-100" />

        <div className="flex items-start justify-between gap-5">
          <div className="min-w-0 flex-1">
            <h2 className="break-anywhere font-medium leading-snug transition-colors group-hover:text-[hsl(var(--accent))]">
              {tender.title}
            </h2>
            <p className="mt-1.5 truncate text-sm text-[hsl(var(--fg-muted))]">
              {tender.issuing_authority ?? "Issuing authority not stated"}
            </p>
            <p className="mt-1.5 break-anywhere font-mono text-[11px] text-[hsl(var(--fg-subtle))]">
              {tender.tender_id}
            </p>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-1.5">
            {tender.sector && <Chip>{tender.sector}</Chip>}
            {tender.submission_count > 0 && (
              <Chip tone="accent">
                {tender.submission_count} bid
                {tender.submission_count === 1 ? "" : "s"}
              </Chip>
            )}
            {closed && <Chip tone="neutral">closed</Chip>}
            {urgent && <Chip tone="warn">{daysLeft}d left</Chip>}
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-t pt-4 text-xs sm:grid-cols-4">
          <Field label="Closes" value={formatDate(deadline)} />
          <Field label="EMD" value={formatInr(tender.emd_amount_inr)} />
          <Field label="Eligibility" value={`${tender.eligibility_count} criteria`} />
          <Field label="Documents" value={`${tender.document_count} required`} />
        </dl>
      </Card>
    </Link>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="label">{label}</dt>
      <dd className="tnum mt-1 truncate font-medium" title={value}>
        {value}
      </dd>
    </div>
  );
}
