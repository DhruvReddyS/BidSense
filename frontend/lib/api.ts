import type {
  AskResponse,
  GapReportResponse,
  Health,
  IngestResponse,
  NotificationSummary,
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

  listNotifications: () =>
    request<NotificationSummary[]>("/api/notifications"),

  uploadNotification: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<IngestResponse>("/api/notifications", { method: "POST", body });
  },

  uploadSubmission: (file: File, vendorId: string, tenderId: string) => {
    const body = new FormData();
    body.append("file", file);
    body.append("vendor_id", vendorId);
    body.append("tender_id", tenderId);
    return request<IngestResponse>("/api/submissions", { method: "POST", body });
  },

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
    request<{ vendor_id: string; vendor_name: string; status: string }[]>(
      `/api/notifications/${encodeURIComponent(tenderId)}/submissions`,
    ),
};
