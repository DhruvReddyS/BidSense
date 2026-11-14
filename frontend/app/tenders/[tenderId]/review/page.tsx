import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { ReviewerLoader } from "@/components/ReviewerLoader";
import { ErrorNote } from "@/components/ui";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

export default async function ReviewerPage({ params, searchParams }: { params: { tenderId: string }; searchParams: { stage?: string } }) {
  const tenderId = decodeURIComponent(params.tenderId);
  const token = cookies().get("bidsense_token")?.value;
  try {
    const tender = await api.notification(tenderId, token);
    const initialStage = searchParams.stage === "shortlist" ? "level2" : searchParams.stage === "evidence" ? "level3" : "level1";
    return <ReviewerLoader tenderId={tenderId} tenderTitle={tender.title} initialStage={initialStage} />;
  } catch (e) {
    return <div className="space-y-4"><Link href={`/tenders/${encodeURIComponent(tenderId)}`} className="review-back">← Tender workspace</Link><ErrorNote>{e instanceof ApiError ? e.message : "Could not load the company review."}</ErrorNote></div>;
  }
}
