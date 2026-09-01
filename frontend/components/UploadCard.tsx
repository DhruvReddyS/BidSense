"use client";

import { useState } from "react";
import type { IngestResponse } from "@/lib/types";

/**
 * Reports the outcome of an ingestion honestly.
 *
 * A partial extraction is stored and flagged rather than discarded, so this
 * shows three distinct outcomes — clean, partial, failed — instead of a binary
 * success toast that hides the fact that a field group came back empty.
 */
export function UploadResult({ result }: { result: IngestResponse }) {
  const failed = result.extraction_errors.length > 0;
  return (
    <div
      className={`mt-4 rounded-lg border p-4 text-sm ${
        failed
          ? "border-amber-200 bg-amber-50"
          : "border-green-200 bg-green-50"
      }`}
    >
      <p className="font-medium">
        {failed ? "Uploaded with problems" : "Uploaded"}: {result.file_name}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-neutral-700 sm:grid-cols-4">
        <div>
          <dt className="text-neutral-500">Reference</dt>
          <dd className="font-mono">{result.identifier ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-neutral-500">Pages</dt>
          <dd>
            {result.pages}
            {result.ocr_pages > 0 ? ` (${result.ocr_pages} OCR'd)` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-neutral-500">Indexed</dt>
          <dd>{result.chunks_indexed} chunks</dd>
        </div>
        <div>
          <dt className="text-neutral-500">Time</dt>
          <dd>{result.seconds}s</dd>
        </div>
      </dl>

      {result.extraction_errors.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium text-amber-900">
            Some fields could not be extracted. What was extracted has been
            saved; the rest is missing from this record.
          </p>
          <ul className="mt-1 list-disc pl-5 text-xs text-amber-800">
            {result.extraction_errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {result.parse_warnings.length > 0 && (
        <details className="mt-3 text-xs text-neutral-600">
          <summary className="cursor-pointer">
            {result.parse_warnings.length} parsing warning
            {result.parse_warnings.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {result.parse_warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function FileField({
  label,
  hint,
  onSelect,
  disabled,
}: {
  label: string;
  hint?: string;
  onSelect: (file: File | null) => void;
  disabled?: boolean;
}) {
  const [name, setName] = useState<string | null>(null);
  return (
    <label className="block">
      <span className="text-sm font-medium text-neutral-800">{label}</span>
      {hint && <span className="mt-0.5 block text-xs text-neutral-500">{hint}</span>}
      <input
        type="file"
        accept=".pdf,.docx"
        disabled={disabled}
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          setName(file?.name ?? null);
          onSelect(file);
        }}
        className="mt-2 block w-full text-sm text-neutral-600 file:mr-4 file:rounded-md file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-indigo-700 disabled:opacity-50"
      />
      {name && <span className="mt-1 block text-xs text-neutral-500">{name}</span>}
    </label>
  );
}
