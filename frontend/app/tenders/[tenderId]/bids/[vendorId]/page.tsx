import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { LiveGapReport } from "@/components/LiveGapReport";
import { ErrorNote } from "@/components/ui";
import type { GapReportResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * A gap report at its own URL.
 *
 * Worth a route rather than only living inside a tab: a vendor works through
 * these gaps over days, and forwards them to whoever holds the missing
 * certificate. A report you cannot link to is a report that gets screenshotted.
 */
export default async function BidReportPage({
  params,
}: {
  params: { tenderId: string; vendorId: string };
}) {
  const tenderId = decodeURIComponent(params.tenderId);
  const vendorId = decodeURIComponent(params.vendorId);

  let report: GapReportResponse | null = null;
  let error: string | null = null;

  try {
    report = await api.gapReport(tenderId, vendorId);
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Could not build this report.";
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/tenders/${encodeURIComponent(tenderId)}`}
          className="text-sm text-[hsl(var(--accent))] hover:underline"
        >
          ← Back to tender
        </Link>
        <h1 className="display-lg mt-3 text-[2.1rem]">
          Compliance report
        </h1>
        <p className="mt-1 break-anywhere text-sm text-[hsl(var(--fg-muted))]">
          {report?.report.vendor_name ?? vendorId} · checked against{" "}
          <span className="font-mono text-xs">{tenderId}</span>
        </p>
      </div>

      {error ? <ErrorNote>{error}</ErrorNote> : report && <LiveGapReport initial={report} />}
    </div>
  );
}
