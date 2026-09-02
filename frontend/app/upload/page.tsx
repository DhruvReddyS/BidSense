"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { FileDrop } from "@/components/FileDrop";
import { JobProgress } from "@/components/JobProgress";
import { Card, ErrorNote } from "@/components/ui";

const STEPS = [
  {
    title: "Upload the notification",
    body: "The official tender document as the authority published it — PDF or DOCX. Scanned documents are read with OCR.",
  },
  {
    title: "We read it clause by clause",
    body: "Eligibility thresholds, required documents, deadlines and submission rules, each recorded with the clause and page it came from.",
  },
  {
    title: "Then check your bid against it",
    body: "Upload your draft and see what is missing while you can still fix it.",
  },
];

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
    <div className="mx-auto grid max-w-5xl gap-8 lg:grid-cols-[1fr_16rem]">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Add a tender</h1>
          <p className="mt-1.5 max-w-lg text-sm leading-relaxed text-[hsl(var(--fg-muted))]">
            Every check we run is measured against this document, so use the
            version the authority published rather than a summary.
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
            hint="PDF or DOCX, up to 50 MB"
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

          {error && (
            <div className="mt-4">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}

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

      <aside className="lg:pt-16">
        <ol className="space-y-5">
          {STEPS.map((step, i) => (
            <li key={i} className="flex gap-3">
              <span className="tnum mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[11px] font-semibold text-[hsl(var(--fg-muted))]">
                {i + 1}
              </span>
              <div>
                <p className="text-sm font-medium leading-snug">{step.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-[hsl(var(--fg-muted))]">
                  {step.body}
                </p>
              </div>
            </li>
          ))}
        </ol>

        <p className="mt-7 border-t pt-5 text-xs leading-relaxed text-[hsl(var(--fg-subtle))]">
          Large tenders take two to three minutes to read. You can leave the page
          once the upload starts — extraction continues on the server.
        </p>
      </aside>
    </div>
  );
}
