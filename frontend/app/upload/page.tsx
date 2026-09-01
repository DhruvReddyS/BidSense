"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { FileField, UploadResult } from "@/components/UploadCard";
import type { IngestResponse } from "@/lib/types";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.uploadNotification(file);
      setResult(response);
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">
        Upload a tender notification
      </h1>
      <p className="mt-1 text-sm text-neutral-600">
        The official tender document (PDF or DOCX). Everything your bid is
        checked against comes from this file.
      </p>

      <div className="mt-6 rounded-lg border border-neutral-200 bg-white p-6">
        <FileField
          label="Tender notification"
          hint="PDF or DOCX, up to 50MB. Large tenders take a minute or two to extract."
          onSelect={setFile}
          disabled={busy}
        />

        <button
          onClick={submit}
          disabled={!file || busy}
          className="mt-5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Extracting…" : "Upload and extract"}
        </button>

        {busy && (
          <p className="mt-3 text-xs text-neutral-500">
            Parsing the document and extracting eligibility criteria, required
            documents and deadlines. This runs several passes over the text.
          </p>
        )}

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            {error}
          </div>
        )}

        {result && <UploadResult result={result} />}
      </div>
    </div>
  );
}
