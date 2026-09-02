"use client";

import { useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { GapReportResponse, JobStatus } from "@/lib/types";
import { FileDrop } from "./FileDrop";
import { GapReport } from "./GapReport";
import { JobProgress } from "./JobProgress";
import { Card, Chip, ErrorNote, SectionTitle } from "./ui";

interface Bid {
  vendor_id: string;
  vendor_name: string;
  status: string;
  is_blacklisted: boolean;
  elimination_reason: string | null;
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

        {bids.length > 0 && (
          <div className="mt-5 border-t pt-4">
            <p className="label">Bids already checked</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {bids.map((bid) => (
                <button
                  key={bid.vendor_id}
                  onClick={() => check(bid.vendor_id)}
                  disabled={checking !== null}
                  className={`chip transition-colors ${
                    report?.report.vendor_id === bid.vendor_id
                      ? "border-transparent bg-[hsl(var(--fg))] text-[hsl(var(--surface))]"
                      : "bg-[hsl(var(--surface))] hover:bg-[hsl(var(--surface-2))]"
                  }`}
                  title={bid.vendor_name}
                >
                  {checking === bid.vendor_id ? "Checking…" : bid.vendor_name || bid.vendor_id}
                  {bid.is_blacklisted && <Chip tone="bad">debarred</Chip>}
                </button>
              ))}
            </div>
          </div>
        )}
      </Card>

      {checking && !report && (
        <div className="space-y-3">
          <div className="h-32 skeleton rounded-xl" />
          <div className="h-24 skeleton rounded-xl" />
        </div>
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
          <GapReport data={report} />
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
