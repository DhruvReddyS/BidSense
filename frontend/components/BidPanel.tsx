"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { FileField, UploadResult } from "./UploadCard";
import { GapReportView } from "./GapReportView";
import type { GapReportResponse, IngestResponse } from "@/lib/types";

/**
 * Section 4.2 + 4.3: upload a bid, then cross-check it against the tender.
 *
 * Upload and check are separate steps on purpose — a bid whose extraction was
 * partial should be visible as such before its gap report is read as complete.
 */
export function BidPanel({
  tenderId,
  bids,
}: {
  tenderId: string;
  bids: { vendor_id: string; vendor_name: string; status: string }[];
}) {
  const [file, setFile] = useState<File | null>(null);
  const [vendorId, setVendorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState<IngestResponse | null>(null);
  const [report, setReport] = useState<GapReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const known = bids.map((b) => b.vendor_id);

  async function uploadBid() {
    if (!file || !vendorId.trim()) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setUpload(await api.uploadSubmission(file, vendorId.trim(), tenderId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function check(id: string) {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.gapReport(tenderId, id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not build the report.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <h3 className="font-medium">Check your bid</h3>
        <p className="mt-1 text-xs text-neutral-500">
          Upload your draft bid to see what is missing before you submit it.
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <FileField label="Your bid" onSelect={setFile} disabled={busy} />
          <label className="block">
            <span className="text-sm font-medium text-neutral-800">Your reference</span>
            <span className="mt-0.5 block text-xs text-neutral-500">
              Any identifier for this bid, e.g. your company code.
            </span>
            <input
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
              placeholder="V-01"
              disabled={busy}
              className="mt-2 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:opacity-50"
            />
          </label>
        </div>

        <button
          onClick={uploadBid}
          disabled={!file || !vendorId.trim() || busy}
          className="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? "Working…" : "Upload bid"}
        </button>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            {error}
          </div>
        )}
        {upload && <UploadResult result={upload} />}
        {upload?.identifier && (
          <button
            onClick={() => check(vendorId.trim())}
            disabled={busy}
            className="mt-4 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            Run compliance check
          </button>
        )}

        {known.length > 0 && (
          <div className="mt-5 border-t border-neutral-100 pt-4">
            <p className="text-xs font-medium text-neutral-600">
              Bids already uploaded
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {bids.map((bid) => (
                <button
                  key={bid.vendor_id}
                  onClick={() => check(bid.vendor_id)}
                  disabled={busy}
                  className="rounded-md border border-neutral-200 px-3 py-1.5 text-xs hover:bg-neutral-50 disabled:opacity-50"
                >
                  {bid.vendor_name || bid.vendor_id}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {report && <GapReportView data={report} />}
    </section>
  );
}
