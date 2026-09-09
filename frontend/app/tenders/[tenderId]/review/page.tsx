import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { ReviewerLoader } from "@/components/ReviewerLoader";
import { ErrorNote } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function ReviewerPage({ params }: { params: { tenderId: string } }) {
  const tenderId = decodeURIComponent(params.tenderId);
  try {
    const tender = await api.notification(tenderId);
    return <ReviewerLoader tenderId={tenderId} tenderTitle={tender.title} />;
  } catch (e) {
    return <div className="space-y-4"><Link href={`/tenders/${encodeURIComponent(tenderId)}`} className="review-back">← Tender workspace</Link><ErrorNote>{e instanceof ApiError ? e.message : "Could not load the company review."}</ErrorNote></div>;
  }
}
