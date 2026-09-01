"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { FileDrop } from "@/components/FileDrop";
import { JobProgress } from "@/components/JobProgress";
import { Card, ErrorNote } from "@/components/ui";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tenderId, setTenderId] = useState<string | null>(null);

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setJobId(null);
    setTenderId(null);
    try {
      const accepted = await api.uploadNotification(file);
      setJobId(accepted.job_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Add a tender</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Upload the official tender notification. Every check we run is measured
          against this document, so use the version the authority published.
        </p>
      </div>

      <Card className="p-6">
        <FileDrop
          onSelect={(f) => {
            setFile(f);
            setJobId(null);
            setError(null);
          }}
          disabled={busy || (!!jobId && !tenderId)}
          hint="PDF or DOCX, up to 50 MB. Scanned documents are read with OCR."
        />

        {!jobId && (
          <button
            onClick={submit}
            disabled={!file || busy}
            className="btn btn-primary mt-5 w-full sm:w-auto"
          >
            {busy ? "Uploading…" : "Upload and read"}
          </button>
        )}

        {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}

        {jobId && (
          <div className="mt-6 border-t pt-5">
            <JobProgress
              jobId={jobId}
              onDone={(job) => {
                if (job.tender_id) setTenderId(job.tender_id);
                router.refresh();
              }}
            />
            {tenderId && (
              <div className="mt-5 flex flex-wrap gap-2">
                <button
                  onClick={() =>
                    router.push(`/tenders/${encodeURIComponent(tenderId)}`)
                  }
                  className="btn btn-primary"
                >
                  Open this tender
                </button>
                <button
                  onClick={() => {
                    setJobId(null);
                    setFile(null);
                    setTenderId(null);
                  }}
                  className="btn btn-ghost"
                >
                  Add another
                </button>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
