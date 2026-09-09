"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { DocumentProcess } from "./DocumentProcess";

type Entry = { file: File; vendorId: string; state: "ready" | "queueing" | "queued" | "failed"; jobId?: string };

const vendorId = (name: string, index: number) => name.replace(/\.(pdf|docx)$/i, "").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 220) || `VENDOR_${index + 1}`;

export function BulkBidUpload({ tenderId, onQueued }: { tenderId: string; onQueued?: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  const queued = entries.filter(entry => entry.state === "queued").length;
  const failed = entries.filter(entry => entry.state === "failed").length;

  function select(files: FileList | null) {
    const valid = Array.from(files ?? []).filter(file => /\.(pdf|docx)$/i.test(file.name));
    setEntries(valid.map((file, index) => ({ file, vendorId: vendorId(file.name, index), state: "ready" })));
  }
  async function queue() {
    setBusy(true);
    let cursor = 0;
    async function worker() {
      for (;;) {
        const index = cursor++;
        if (index >= entries.length) return;
        const entry = entries[index];
        setEntries(current => current.map((item, i) => i === index ? { ...item, state: "queueing" } : item));
        try {
          const accepted = await api.uploadSubmission(entry.file, entry.vendorId, tenderId);
          setEntries(current => current.map((item, i) => i === index ? { ...item, state: "queued", jobId: accepted.job_id } : item));
        } catch {
          setEntries(current => current.map((item, i) => i === index ? { ...item, state: "failed" } : item));
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, entries.length) }, () => worker()));
    setBusy(false); onQueued?.();
  }
  return <details className="bulk-upload"><summary><span>＋ Add a batch of bids</span><small>PDF / DOCX · independent extraction jobs</small></summary><div className="bulk-upload-body">
    <input ref={input} className="sr-only" type="file" multiple accept=".pdf,.docx" onChange={event => select(event.target.files)} />
    {!entries.length ? <button className="bulk-drop" onClick={() => input.current?.click()}><b>Choose vendor submissions</b><span>Select several files; the filename becomes an editable vendor ID.</span></button> : <>
      <div className="bulk-list">{entries.map((entry, index) => <label key={`${entry.file.name}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><b>{entry.file.name}</b><input aria-label={`Vendor ID for ${entry.file.name}`} value={entry.vendorId} disabled={busy} onChange={event => setEntries(current => current.map((item, i) => i === index ? { ...item, vendorId: event.target.value } : item))}/></div><em className={`is-${entry.state}`}>{entry.state}</em></label>)}</div>
      {busy && <><DocumentProcess compact label="Queueing bid records" detail="Three controlled upload lanes keep the review service responsive" /><div className="bulk-queue-meter"><i style={{ width: `${Math.max(4, ((queued + failed) / entries.length) * 100)}%` }} /><span>{queued + failed} / {entries.length} accepted</span></div></>}
      <div className="bulk-actions"><button className="btn btn-primary" disabled={busy || entries.some(entry => !entry.vendorId.trim())} onClick={() => void queue()}>Queue {entries.length} submissions</button><button className="btn btn-subtle" disabled={busy} onClick={() => input.current?.click()}>Replace selection</button></div>
    </>}
  </div></details>;
}
