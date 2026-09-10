"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { FileDrop } from "@/components/FileDrop";
import { JobProgress } from "@/components/JobProgress";
import { Card, ErrorNote } from "@/components/ui";

const STEPS = [
  {
    title: "Preserve the source",
    body: "The exact file is retained by content hash so every citation remains auditable.",
  },
  {
    title: "Read in parallel",
    body: "Specialists extract deadlines, eligibility, documents and evaluation rules concurrently.",
  },
  {
    title: "Validate before use",
    body: "Dates, money, citations and required coverage pass deterministic quality gates.",
  },
  {
    title: "Open review early",
    body: "Structured review becomes usable first; evidence-search indexing can finish independently.",
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
    <div className="lux-upload mx-auto max-w-6xl">
      <div className="mb-10 max-w-3xl">
        <span className="eyebrow">Secure ingestion studio</span>
        <h1 className="font-display text-balance mt-3 text-4xl font-medium leading-tight sm:text-5xl">Upload the tender notification</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-[hsl(var(--fg-muted))]">Use the official document published by the authority. All requirements and subsequent bid checks will be traced back to this source.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-6">

        <Card className="lux-upload-card p-5 sm:p-8">
          <div className="relative mb-6 flex items-center justify-between gap-4">
            <div><p className="label">Source document</p><h2 className="mt-2 text-xl font-semibold">Official tender notification</h2></div>
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-[hsl(var(--accent-soft))] text-lg text-[hsl(var(--accent))]">↥</span>
          </div>
          <FileDrop
            onSelect={(f) => {
              setFile(f);
              setJobId(null);
              setError(null);
            }}
            disabled={busy || (!!jobId && !tenderId)}
            hint="PDF or DOCX · scanned files supported · up to 50 MB"
            label="Drop the official tender here"
          />

          {!jobId && (
            <button
              onClick={submit}
              disabled={!file || busy}
              className="btn btn-primary mt-5 w-full !min-h-12 sm:w-auto sm:!px-6"
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

      <aside className="card lux-process-map h-fit p-6 lg:sticky lg:top-28">
        <div className="mb-6 flex items-center justify-between"><p className="label">Fast, but defensible</p><span className="font-mono text-[10px] text-[hsl(var(--accent))]">LIVE STAGES</span></div>
        <ol className="space-y-6">
          {STEPS.map((step, i) => (
            <li key={i} className="feature-line flex gap-4 pl-5">
              <span className="tnum mt-0.5 text-[10px] font-semibold text-[hsl(var(--accent))]">
                0{i + 1}
              </span>
              <div>
                <p className="text-sm font-semibold leading-snug">{step.title}</p>
                <p className="mt-1.5 text-xs leading-relaxed text-[hsl(var(--fg-muted))]">
                  {step.body}
                </p>
              </div>
            </li>
          ))}
        </ol>

        <p className="mt-7 border-l border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft)/.25)] p-4 text-xs leading-relaxed text-[hsl(var(--fg-muted))]">
          <span className="mb-1 block font-semibold text-[hsl(var(--fg))]">Nothing is hidden behind a spinner</span>
          You will see the active field group, elapsed time, model, cache reuse, OCR count and a stage-by-stage timing receipt.
        </p>
      </aside>
      </div>
    </div>
  );
}
