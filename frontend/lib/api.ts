import type {
  AskResponse,
  Corrigendum,
  GapReportResponse,
  Health,
  JobAccepted,
  JobStatus,
  NotificationList,
  TenderDetail,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8100";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    // A dead backend is the single most common local failure. Say so plainly
    // instead of surfacing "Failed to fetch" to the user.
    throw new ApiError(
      `Cannot reach the BidSense API at ${BASE}. Is the backend running?`,
      0,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),

  listNotifications: (limit = 50, offset = 0) =>
    request<NotificationList>(`/api/notifications?limit=${limit}&offset=${offset}`),

  notification: (tenderId: string) =>
    request<TenderDetail>(`/api/notifications/${encodeURIComponent(tenderId)}`),

  uploadNotification: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<JobAccepted>("/api/notifications", { method: "POST", body });
  },

  uploadSubmission: (file: File, vendorId: string, tenderId: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("vendor_id", vendorId);
    body.append("tender_id", tenderId);
    return request<JobAccepted>("/api/submissions", { method: "POST", body });
  },

  job: (jobId: string) => request<JobStatus>(`/api/jobs/${jobId}`),

  gapReport: (tenderId: string, vendorId: string, acknowledgeAmendments = false) =>
    request<GapReportResponse>("/api/gap-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tender_id: tenderId,
        vendor_id: vendorId,
        acknowledge_amendments: acknowledgeAmendments,
      }),
    }),

  corrigenda: (tenderId: string) =>
    request<Corrigendum[]>(
      `/api/notifications/${encodeURIComponent(tenderId)}/corrigenda`,
    ),

  uploadCorrigendum: (file: File, tenderId: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("tender_id", tenderId);
    return request<JobAccepted>("/api/corrigenda", { method: "POST", body });
  },

  /** The rendered page a citation points at, with the passage marked. Returned
   *  as an object URL the caller revokes: these are ~200KB PNGs and leaking one
   *  per citation click adds up over a session. */
  citationPage: async (
    contentHash: string,
    page: number,
    highlight?: string | null,
  ): Promise<{
    url: string;
    highlights: number;
    pageCount: number;
    /** Where the marked passage sits, as a fraction of page height. */
    highlightAt: number | null;
  }> => {
    const params = new URLSearchParams();
    if (highlight) params.set("highlight", highlight.slice(0, 2000));
    const response = await fetch(
      `${BASE}/api/documents/${contentHash}/page/${page}?${params}`,
      { cache: "force-cache" },
    );
    if (!response.ok) {
      throw new ApiError(
        response.status === 404
          ? "The source document for this citation is not retained. Re-upload it to enable page previews."
          : `Could not render page ${page}.`,
        response.status,
      );
    }
    const blob = await response.blob();
    const at = response.headers.get("X-Highlight-At");
    return {
      url: URL.createObjectURL(blob),
      highlights: Number(response.headers.get("X-Highlights") ?? 0),
      pageCount: Number(response.headers.get("X-Page-Count") ?? 0),
      highlightAt: at ? Number(at) : null,
    };
  },

  documentUrl: (contentHash: string) => `${BASE}/api/documents/${contentHash}`,

  exportGapReport: async (tenderId: string, vendorId: string, fmt: "pdf" | "docx") => {
    const response = await fetch(`${BASE}/api/gap-report/export?fmt=${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tender_id: tenderId, vendor_id: vendorId }),
    });
    if (!response.ok) throw new ApiError(`Export failed (${response.status}).`, response.status);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `compliance_${vendorId}.${fmt}`.replace(/[^\w.-]+/g, "_");
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },

  ask: (question: string, tenderId: string, vendorId?: string) =>
    request<AskResponse>("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        tender_id: tenderId,
        vendor_id: vendorId || null,
      }),
    }),

  submissions: (tenderId: string) =>
    request<
      {
        vendor_id: string;
        vendor_name: string;
        status: string;
        is_blacklisted: boolean;
        elimination_reason: string | null;
      }[]
    >(`/api/notifications/${encodeURIComponent(tenderId)}/submissions`),
};

/**
 * Poll a job until it reaches a terminal state.
 *
 * Extraction runs for minutes under free-tier pacing, so the interval backs off:
 * fast at first (the file may be small), then slower, so a three-minute
 * extraction does not generate two hundred requests.
 */
export async function pollJob(
  jobId: string,
  onUpdate: (job: JobStatus) => void,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const TERMINAL = new Set(["succeeded", "partial", "failed"]);
  let delay = 900;

  for (;;) {
    if (signal?.aborted) throw new ApiError("Cancelled", 0);
    const job = await api.job(jobId);
    onUpdate(job);
    if (TERMINAL.has(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 1.25, 4000);
  }
}
