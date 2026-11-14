"use client";

import { useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { GapReportResponse, JobStatus } from "@/lib/types";
import { FileDrop } from "./FileDrop";
import { GapReport } from "./GapReport";
import { JobProgress } from "./JobProgress";
import { DocumentProcess } from "./DocumentProcess";
import { Card, Chip, ErrorNote, SectionTitle } from "./ui";

interface Bid {
  vendor_id: string;
  vendor_name: string;
  status: string;
  is_blacklisted: boolean;
  elimination_reason: string | null;
  source_file?: string | null;
  content_hash?: string | null;
  uploaded_at?: string;
  last_checked_at?: string | null;
  verdict?: string | null;
  completion_satisfied?: number | null;
  completion_total?: number | null;
  completion_undetermined?: number | null;
  outstanding_count?: number | null;
}

/**
 * Section 4.2 + 4.3: upload a bid, then cross-check it.
 *
 * Reading and checking are separate steps on purpose. A bid whose extraction was
 * only partial must be visible as such *before* its gap report is read as
 * complete — otherwise a missing field group looks like a satisfied requirement.
 */
export function BidChecker({
  tenderId,
  bids,
}: {
  tenderId: string;
  bids: Bid[];
}) {
  const [file, setFile] = useState<File | null>(null);
  const [vendorId, setVendorId] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [readyVendor, setReadyVendor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState<string | null>(null);
  const [report, setReport] = useState<GapReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const history = [...bids].sort((a, b) => new Date(a.uploaded_at || 0).getTime() - new Date(b.uploaded_at || 0).getTime());

  async function upload() {
    if (!file || !vendorId.trim()) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setReadyVendor(null);
    try {
      const accepted = await api.uploadSubmission(file, vendorId.trim(), tenderId);
      setJobId(accepted.job_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function check(id: string) {
    setChecking(id);
    setError(null);
    try {
      setReport(await api.gapReport(tenderId, id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not build the report.");
    } finally {
      setChecking(null);
    }
  }

  function onJobDone(job: JobStatus) {
    if (job.status !== "failed" && job.vendor_id) {
      setReadyVendor(job.vendor_id);
      void check(job.vendor_id);
    }
  }

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <SectionTitle
          title="Check a bid"
          hint="Upload your draft bid to see what is missing while you can still fix it."
        />

        <div className="grid gap-4 sm:grid-cols-[1fr_220px]">
          <FileDrop
            onSelect={(f) => {
              setFile(f);
              setJobId(null);
            }}
            disabled={busy}
            label="Drop your bid here"
            hint="PDF or DOCX"
          />
          <div>
            <label className="label" htmlFor="vendor-id">
              Your reference
            </label>
            <input
              id="vendor-id"
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
              placeholder="e.g. ACME-01"
              disabled={busy}
              className="input mt-1.5"
            />
            <p className="mt-1.5 text-xs text-[hsl(var(--fg-subtle))]">
              Any identifier for this bid. Used to look it up again later.
            </p>
            <button
              onClick={upload}
              disabled={!file || !vendorId.trim() || busy}
              className="btn btn-primary mt-3 w-full"
            >
              {busy ? "Uploading…" : "Upload and check"}
            </button>
          </div>
        </div>

        {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}

        {jobId && (
          <div className="mt-5 border-t pt-5">
            <JobProgress jobId={jobId} onDone={onJobDone} />
          </div>
        )}

        {history.length > 0 && (
          <div className="mt-5 border-t pt-4">
            <p className="label">Bid check history</p>
            <p className="mt-1 text-xs text-[hsl(var(--fg-muted))]">Every uploaded version and result is retained. Compare completion to confirm whether the bid is improving.</p>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {history.map((bid, index) => {
                const previous = history[index - 1];
                const score = bid.completion_satisfied ?? null;
                const previousScore = previous?.completion_satisfied ?? null;
                const delta = score !== null && previousScore !== null ? score - previousScore : null;
                return <article key={bid.vendor_id} className={`rounded-xl border p-4 ${report?.report.vendor_id === bid.vendor_id ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]" : "bg-[hsl(var(--surface))]"}`}>
                  <div className="flex items-start justify-between gap-3"><div><p className="eyebrow">Version {index + 1}</p><h3 className="mt-1 break-anywhere text-sm font-semibold">{bid.vendor_name || bid.vendor_id}</h3><p className="mt-1 font-mono text-[10px] text-[hsl(var(--fg-subtle))]">{bid.vendor_id}</p></div><Chip tone={bid.verdict === "not_compliant" ? "warn" : "ok"}>{bid.verdict === "not_compliant" ? "Needs work" : "Checked"}</Chip></div>
                  <dl className="mt-4 grid grid-cols-3 gap-2 text-xs"><div><dt className="label">Completed</dt><dd className="tnum mt-1 font-semibold">{score ?? "—"}/{bid.completion_total ?? "—"}</dd></div><div><dt className="label">Change</dt><dd className={`tnum mt-1 font-semibold ${delta !== null && delta > 0 ? "text-[hsl(var(--ok))]" : delta !== null && delta < 0 ? "text-[hsl(var(--danger))]" : ""}`}>{delta === null ? "Baseline" : delta > 0 ? `+${delta} better` : delta < 0 ? `${delta} worse` : "No change"}</dd></div><div><dt className="label">Outstanding</dt><dd className="tnum mt-1 font-semibold">{bid.outstanding_count ?? "—"}</dd></div></dl>
                  <p className="mt-3 text-[11px] text-[hsl(var(--fg-subtle))]">{bid.last_checked_at ? `Checked ${new Date(bid.last_checked_at).toLocaleString()}` : "Saved — open to run the check"}{bid.source_file ? ` · ${bid.source_file.split(/[\\/]/).pop()}` : ""}</p>
                  <div className="mt-3 flex flex-wrap gap-2"><button onClick={() => check(bid.vendor_id)} disabled={checking !== null} className="btn btn-subtle">{checking === bid.vendor_id ? "Opening…" : "Open result"}</button>{bid.content_hash && <a className="btn btn-subtle" href={api.documentUrl(bid.content_hash)} target="_blank" rel="noreferrer">Bid document ↗</a>}</div>
                </article>;
              })}
            </div>
          </div>
        )}
      </Card>

      {checking && !report && (
        <div className="card p-6"><DocumentProcess label="Comparing the bid" detail="Matching evidence to tender clauses" /></div>
      )}

      {report && (
        <div className="animate-rise space-y-4">
          <div className="flex justify-end">
            <Link
              href={`/tenders/${encodeURIComponent(tenderId)}/bids/${encodeURIComponent(report.report.vendor_id)}`}
              className="text-xs text-[hsl(var(--accent))] hover:underline"
            >
              Open this report on its own page →
            </Link>
          </div>
          <GapReport
            data={report}
            onRefresh={async (acknowledge) => {
              setReport(await api.gapReport(tenderId, report.report.vendor_id, acknowledge));
            }}
          />
        </div>
      )}

      {readyVendor && !report && !checking && (
        <button onClick={() => check(readyVendor)} className="btn btn-primary">
          Run compliance check
        </button>
      )}
    </div>
  );
}
