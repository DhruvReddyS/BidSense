import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { NotificationList } from "@/lib/types";
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

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tenders</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Add a tender notification, then check a bid against it before you submit.
          </p>
        </div>
        {tenders.length > 0 && (
          <p className="tnum text-xs text-fg-muted">
            {data!.page.total} tender{data!.page.total === 1 ? "" : "s"}
          </p>
        )}
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}

      {!error && tenders.length === 0 && (
        <EmptyState
          title="No tenders yet"
          body="Upload the official tender notification. Everything your bid is checked against is read from that document."
          action={
            <Link href="/upload" className="btn btn-primary">
              Add your first tender
            </Link>
          }
        />
      )}

      <div className="grid gap-3">
        {tenders.map((tender) => (
          <Link
            key={tender.tender_id}
            href={`/tenders/${encodeURIComponent(tender.tender_id)}`}
            className="block"
          >
            <Card className="card-hover p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <h2 className="break-anywhere font-medium leading-snug">
                    {tender.title}
                  </h2>
                  <p className="mt-1 truncate text-sm text-fg-muted">
                    {tender.issuing_authority ?? "Issuing authority not stated"}
                  </p>
                  <p className="mt-1.5 break-anywhere font-mono text-[11px] text-fg-subtle">
                    {tender.tender_id}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  {tender.sector && <Chip>{tender.sector}</Chip>}
                  {tender.submission_count > 0 && (
                    <Chip tone="accent">
                      {tender.submission_count} bid
                      {tender.submission_count === 1 ? "" : "s"}
                    </Chip>
                  )}
                </div>
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-4 border-t pt-4 text-xs sm:grid-cols-4">
                <Field label="Closes" value={formatDate(tender.submission_deadline)} />
                <Field label="EMD" value={formatInr(tender.emd_amount_inr)} />
                <Field
                  label="Eligibility"
                  value={`${tender.eligibility_count} criteria`}
                />
                <Field
                  label="Documents"
                  value={`${tender.document_count} required`}
                />
              </dl>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="tnum mt-0.5 font-medium">{value}</dd>
    </div>
  );
}
