import { BidReportLoader } from "@/components/BidReportLoader";

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

  return <div className="bid-review-page"><BidReportLoader tenderId={tenderId} vendorId={vendorId}/></div>;
}
