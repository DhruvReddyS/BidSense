import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { AskPanel } from "@/components/AskPanel";
import { BidPanel } from "@/components/BidPanel";

export const dynamic = "force-dynamic";

export default async function TenderPage({
  params,
}: {
  params: { tenderId: string };
}) {
  const tenderId = decodeURIComponent(params.tenderId);

  let tender: any = null;
  let bids: { vendor_id: string; vendor_name: string; status: string }[] = [];
  let error: string | null = null;

  try {
    [tender, bids] = await Promise.all([
      fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8100"}/api/notifications/${encodeURIComponent(tenderId)}`,
        { cache: "no-store" },
      ).then((r) => {
        if (!r.ok) throw new ApiError("Tender not found", r.status);
        return r.json();
      }),
      api.submissions(tenderId).catch(() => []),
    ]);
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Could not load this tender.";
  }

  if (error) {
    return (
      <div>
        <Link href="/" className="text-sm text-indigo-600 hover:underline">
          ← All tenders
        </Link>
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <Link href="/" className="text-sm text-indigo-600 hover:underline">
          ← All tenders
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {tender.title}
        </h1>
        <p className="mt-1 text-sm text-neutral-600">
          {tender.issuing_authority ?? "Issuing authority not stated"}
        </p>
        <p className="mt-1 font-mono text-xs text-neutral-500">{tenderId}</p>
      </div>

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-neutral-200 bg-white p-4">
          <p className="text-xs text-neutral-500">Submission deadline</p>
          <p className="mt-1 font-medium">
            {tender.submission_deadline ?? "not stated"}
          </p>
        </div>
        <div className="rounded-lg border border-neutral-200 bg-white p-4">
          <p className="text-xs text-neutral-500">Pre-bid queries by</p>
          <p className="mt-1 font-medium">
            {tender.pre_bid_query_deadline ?? "not stated"}
          </p>
        </div>
        <div className="rounded-lg border border-neutral-200 bg-white p-4">
          <p className="text-xs text-neutral-500">EMD</p>
          <p className="mt-1 font-medium">
            {tender.emd_amount?.raw_text ?? "not stated"}
          </p>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="font-medium">
            Eligibility criteria ({tender.eligibility_criteria.length})
          </h3>
          <ul className="mt-3 space-y-3">
            {tender.eligibility_criteria.map((c: any, i: number) => (
              <li key={i} className="text-sm">
                <p className="text-neutral-900">{c.criterion}</p>
                <p className="mt-0.5 text-xs text-neutral-500">
                  {c.threshold_raw ?? "no threshold stated"}
                  {c.provenance?.clause_ref && ` · clause ${c.provenance.clause_ref}`}
                  {c.provenance?.source_page && `, page ${c.provenance.source_page}`}
                </p>
              </li>
            ))}
            {tender.eligibility_criteria.length === 0 && (
              <li className="text-sm text-neutral-500">
                No eligibility criteria were extracted from this document.
              </li>
            )}
          </ul>
        </div>

        <div className="rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="font-medium">
            Required documents ({tender.mandatory_documents.length})
          </h3>
          <ul className="mt-3 space-y-2">
            {tender.mandatory_documents.map((d: any, i: number) => (
              <li key={i} className="text-sm">
                <span className="text-neutral-900">{d.doc_name}</span>
                {d.provenance?.clause_ref && (
                  <span className="ml-2 text-xs text-neutral-500">
                    clause {d.provenance.clause_ref}
                  </span>
                )}
              </li>
            ))}
            {tender.mandatory_documents.length === 0 && (
              <li className="text-sm text-neutral-500">
                No document list was extracted from this document.
              </li>
            )}
          </ul>
        </div>
      </section>

      <BidPanel tenderId={tenderId} bids={bids} />

      <AskPanel tenderId={tenderId} />
    </div>
  );
}
