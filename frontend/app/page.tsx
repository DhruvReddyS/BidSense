import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { NotificationList, NotificationSummary } from "@/lib/types";
import { Chip, EmptyState, ErrorNote, formatDate, formatInr } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Home() {
  let data: NotificationList | null = null;
  let error: string | null = null;
  try { data = await api.listNotifications(); }
  catch (e) { error = e instanceof ApiError ? e.message : "Could not load tenders."; }

  const tenders = data?.items ?? [];
  const now = Date.now();
  const active = tenders.filter((t) => !t.submission_deadline || new Date(t.submission_deadline).getTime() >= now).length;
  const archived = tenders.length - active;
  const bids = tenders.reduce((sum, t) => sum + t.submission_count, 0);
  const requirements = tenders.reduce((sum, t) => sum + t.eligibility_count + t.document_count, 0);

  return (
    <div className="space-y-9">
      <section className="lux-hero flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Intelligence workspace</p>
          <h1 className="font-display mt-2 text-4xl font-medium tracking-[-.025em] sm:text-5xl">Tenders</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[hsl(var(--fg-muted))]">
            Review tender requirements, check draft bids, and keep every decision connected to its source clause.
          </p>
        </div>
        <div className="lux-hero-actions"><span><i /> Audit-grade evidence</span><Link href="/upload" className="btn btn-primary shrink-0">Add tender <b>↗</b></Link></div>
      </section>

      <section aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="sr-only">Portfolio overview</h2>
        <dl className="lux-stats grid grid-cols-2 lg:grid-cols-4">
          <Summary label="Active tenders" value={active} note={active === 1 ? "Open workspace" : "Open workspaces"} />
          <Summary label="Archived" value={archived} note="Past deadlines" />
          <Summary label="Bids checked" value={bids} note="Across all tenders" />
          <Summary label="Requirements" value={requirements} note="Tracked to source" accent />
        </dl>
      </section>

      {error && <ErrorNote>{error}</ErrorNote>}
      {!error && tenders.length === 0 && (
        <EmptyState
          title="No tenders yet"
          body="Add the official tender notification to create your first review workspace."
          action={<Link href="/upload" className="btn btn-primary">Add your first tender</Link>}
        />
      )}

      {tenders.length > 0 && (
        <section aria-labelledby="portfolio-heading">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h2 id="portfolio-heading" className="text-lg font-semibold">All tenders</h2>
              <p className="mt-1 text-xs text-[hsl(var(--fg-muted))]">Select a tender to continue your review.</p>
            </div>
            <span className="tnum text-xs text-[hsl(var(--fg-subtle))]">{tenders.length} total</span>
          </div>
          <div className="lux-table overflow-hidden">
            <div className="hidden grid-cols-[minmax(0,1fr)_8rem_7rem_7rem_2rem] gap-5 border-b bg-[hsl(var(--surface-2))] px-5 py-3 lg:grid">
              <span className="label">Tender</span><span className="label">Deadline</span><span className="label">EMD</span><span className="label">Bids</span><span />
            </div>
            <div className="divide-y">
              {tenders.map((tender) => <TenderRow key={tender.tender_id} tender={tender} />)}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function Summary({ label, value, note, accent = false }: { label: string; value: number; note: string; accent?: boolean }) {
  return (
    <div className="border-b px-1 py-5 odd:border-r lg:border-b-0 lg:border-r lg:px-5 lg:first:pl-0 lg:last:border-r-0">
      <dt className="label">{label}</dt>
      <dd className={`font-display tnum mt-2 text-3xl font-medium sm:text-4xl ${accent ? "text-[hsl(var(--accent))]" : ""}`}>{value}</dd>
      <p className="mt-1 text-[11px] text-[hsl(var(--fg-subtle))]">{note}</p>
    </div>
  );
}

function TenderRow({ tender }: { tender: NotificationSummary }) {
  const deadline = tender.submission_deadline;
  const daysLeft = deadline ? Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000) : null;
  const closed = daysLeft !== null && daysLeft < 0;
  const urgent = daysLeft !== null && daysLeft >= 0 && daysLeft <= 14;

  return (
    <Link href={`/tenders/${encodeURIComponent(tender.tender_id)}`} className="group grid gap-4 px-5 py-5 transition-colors hover:bg-[hsl(var(--surface-2))] lg:grid-cols-[minmax(0,1fr)_8rem_7rem_7rem_2rem] lg:items-center lg:gap-5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {closed ? <Chip>Closed</Chip> : urgent ? <Chip tone="warn">Closing soon</Chip> : <Chip tone="ok">Active</Chip>}
          {tender.sector && <span className="text-[11px] capitalize text-[hsl(var(--fg-muted))]">{tender.sector}</span>}
        </div>
        <h3 className="mt-2 break-anywhere text-sm font-semibold leading-5 transition-colors group-hover:text-[hsl(var(--accent))]">{tender.title}</h3>
        <p className="mt-1 truncate text-xs text-[hsl(var(--fg-muted))]">{tender.issuing_authority ?? "Issuing authority not stated"}</p>
        <p className="mt-1 truncate font-mono text-[9px] text-[hsl(var(--fg-subtle))]">{tender.tender_id}</p>
      </div>
      <Data label="Deadline" value={formatDate(deadline)} />
      <Data label="EMD" value={formatInr(tender.emd_amount_inr)} />
      <Data label="Bids checked" value={String(tender.submission_count)} accent />
      <span className="hidden text-lg text-[hsl(var(--fg-subtle))] transition-transform group-hover:translate-x-0.5 group-hover:text-[hsl(var(--accent))] lg:block">→</span>
    </Link>
  );
}

function Data({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <div className="min-w-0"><p className="label lg:hidden">{label}</p><p className={`tnum mt-1 truncate text-xs font-medium lg:mt-0 ${accent ? "text-[hsl(var(--accent))]" : ""}`}>{value}</p></div>;
}
