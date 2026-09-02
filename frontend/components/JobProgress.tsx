"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, pollJob } from "@/lib/api";
import type { JobStatus } from "@/lib/types";
import { Chip } from "./ui";

/**
 * Live progress for a background extraction.
 *
 * Extraction takes minutes: six LLM calls paced by a free-tier quota, and the
 * first can take two of them on its own. A spinner alone reads as a hang, so
 * this names the stage in flight, counts completed field groups, and shows the
 * elapsed time — enough for a user to tell "slow" from "stuck".
 */
export function JobProgress({
  jobId,
  onDone,
}: {
  jobId: string;
  onDone?: (job: JobStatus) => void;
}) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const done = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    done.current = false;

    pollJob(jobId, setJob, controller.signal)
      .then((final) => {
        if (!done.current) {
          done.current = true;
          onDone?.(final);
        }
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "Lost track of this upload.");
      });

    return () => controller.abort();
    // onDone is intentionally not a dependency: a parent re-render must not
    // restart polling and duplicate the completion callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (error) {
    return (
      <p className="text-sm text-[hsl(var(--bad))]">{error}</p>
    );
  }
  if (!job) {
    return <div className="h-16 skeleton rounded-xl" />;
  }

  const failed = job.status === "failed";
  const finished = job.status === "succeeded" || job.status === "partial";
  const percent = Math.round(job.progress * 100);

  return (
    <div className="animate-rise space-y-3">
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{job.file_name}</p>
          <p className="mt-0.5 text-xs text-[hsl(var(--fg-muted))]">
            {failed
              ? "Extraction failed"
              : finished
                ? `Read ${job.result?.pages ?? "?"} pages in ${job.seconds_elapsed}s`
                : (job.stage ?? "starting") +
                  (job.seconds_elapsed ? ` · ${Math.round(job.seconds_elapsed)}s` : "")}
          </p>
        </div>
        {failed ? (
          <Chip tone="bad">Failed</Chip>
        ) : finished ? (
          <Chip tone={job.status === "partial" ? "warn" : "ok"}>
            {job.status === "partial" ? "Partly read" : "Done"}
          </Chip>
        ) : (
          <span className="tnum text-xs text-[hsl(var(--fg-muted))]">
            {job.steps_done}/{job.steps_total ?? "?"}
          </span>
        )}
      </div>

      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            failed
              ? "bg-[hsl(var(--bad))]"
              : job.status === "partial"
                ? "bg-[hsl(var(--warn))]"
                : "bg-[hsl(var(--accent))]"
          }`}
          style={{ width: `${failed ? 100 : Math.max(percent, 4)}%` }}
        />
      </div>

      {!finished && !failed && (
        <p className="text-xs text-[hsl(var(--fg-subtle))]">
          Large tenders take two to three minutes. You can leave this page — the
          extraction continues on the server.
        </p>
      )}

      {failed && job.error && (
        <pre className="max-h-32 overflow-auto rounded-lg border bg-[hsl(var(--surface-2))] p-3 text-[11px] leading-relaxed text-[hsl(var(--fg-muted))] break-anywhere whitespace-pre-wrap">
          {job.error}
        </pre>
      )}

      {finished && job.result && <JobResultSummary result={job.result} />}
    </div>
  );
}

function JobResultSummary({ result }: { result: NonNullable<JobStatus["result"]> }) {
  const { extraction_errors: errors, parse_warnings: warnings } = result;
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
        <Stat label="Reference" value={result.identifier ?? "—"} mono />
        <Stat
          label="Pages"
          value={`${result.pages}${result.ocr_pages ? ` (${result.ocr_pages} scanned)` : ""}`}
        />
        <Stat label="Indexed" value={`${result.chunks_indexed} passages`} />
        <Stat label="Time" value={`${result.seconds}s`} />
      </dl>

      {errors.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--warn-border))] bg-[hsl(var(--warn-soft))] p-3">
          <p className="text-xs font-medium text-[hsl(var(--warn))]">
            {errors.length} section{errors.length === 1 ? "" : "s"} could not be read.
            What was read has been saved; the rest is missing from this record.
          </p>
          <ul className="mt-1.5 space-y-1 text-[11px] text-[hsl(var(--fg-muted))]">
            {errors.map((e, i) => (
              <li key={i} className="break-anywhere">
                {e.split(":")[0]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <details className="text-xs text-[hsl(var(--fg-muted))]">
          <summary className="cursor-pointer select-none hover:text-[hsl(var(--fg))]">
            {warnings.length} parsing warning{warnings.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-1.5 space-y-1 pl-4">
            {warnings.slice(0, 12).map((w, i) => (
              <li key={i} className="list-disc break-anywhere">
                {w}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="label">{label}</dt>
      <dd
        className={`mt-0.5 truncate font-medium ${mono ? "font-mono text-[11px]" : ""}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
