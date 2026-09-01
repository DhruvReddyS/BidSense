import type {
  AskResponse,
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
      `Cannot reach the TenderIQ API at ${BASE}. Is the backend running?`,
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

  gapReport: (tenderId: string, vendorId: string) =>
    request<GapReportResponse>("/api/gap-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tender_id: tenderId, vendor_id: vendorId }),
    }),

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
