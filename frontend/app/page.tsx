import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { NotificationSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

function formatInr(value: string | null): string {
  if (!value) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2).replace(/\.00$/, "")} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2).replace(/\.00$/, "")} Lakh`;
  return `₹${n.toLocaleString("en-IN")}`;
}

export default async function Home() {
  let tenders: NotificationSummary[] = [];
  let error: string | null = null;

  try {
    tenders = await api.listNotifications();
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Something went wrong.";
  }

  return (
    <div>
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tenders</h1>
          <p className="mt-1 text-sm text-neutral-600">
            Upload a tender notification, then check a bid against it.
          </p>
        </div>
        <Link
          href="/upload"
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          Upload tender
        </Link>
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          {error}
        </div>
      )}

      {!error && tenders.length === 0 && (
        <div className="mt-6 rounded-lg border border-dashed border-neutral-300 p-10 text-center">
          <p className="text-sm text-neutral-600">
            No tenders yet. Upload a tender notification to get started.
          </p>
        </div>
      )}

      <div className="mt-6 grid gap-4">
        {tenders.map((tender) => (
          <Link
            key={tender.tender_id}
            href={`/tenders/${encodeURIComponent(tender.tender_id)}`}
            className="rounded-lg border border-neutral-200 bg-white p-5 transition hover:border-indigo-300 hover:shadow-sm"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="truncate font-medium text-neutral-900">
                  {tender.title}
                </h2>
                <p className="mt-0.5 truncate text-sm text-neutral-600">
                  {tender.issuing_authority ?? "Issuing authority not stated"}
                </p>
                <p className="mt-1 font-mono text-xs text-neutral-500">
                  {tender.tender_id}
                </p>
              </div>
              {tender.sector && (
                <span className="shrink-0 rounded bg-neutral-100 px-2 py-1 text-xs text-neutral-700">
                  {tender.sector}
                </span>
              )}
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-4 text-xs sm:grid-cols-4">
              <div>
                <dt className="text-neutral-500">Deadline</dt>
                <dd className="mt-0.5 font-medium">
                  {tender.submission_deadline ?? "not stated"}
                </dd>
              </div>
              <div>
                <dt className="text-neutral-500">EMD</dt>
                <dd className="mt-0.5 font-medium">
                  {formatInr(tender.emd_amount_inr)}
                </dd>
              </div>
              <div>
                <dt className="text-neutral-500">Criteria</dt>
                <dd className="mt-0.5 font-medium">
                  {tender.eligibility_count} eligibility · {tender.document_count} docs
                </dd>
              </div>
              <div>
                <dt className="text-neutral-500">Bids</dt>
                <dd className="mt-0.5 font-medium">{tender.submission_count}</dd>
              </div>
            </dl>
          </Link>
        ))}
      </div>
    </div>
  );
}
