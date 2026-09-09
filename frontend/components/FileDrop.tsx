"use client";

import { useCallback, useRef, useState } from "react";

const ACCEPTED = [".pdf", ".docx"];

export function FileDrop({
  onSelect,
  disabled,
  hint,
  label = "Drop a file here, or click to browse",
}: {
  onSelect: (file: File | null) => void;
  disabled?: boolean;
  hint?: string;
  label?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [name, setName] = useState<string | null>(null);
  const [size, setSize] = useState<number>(0);
  const [over, setOver] = useState(false);
  const [rejected, setRejected] = useState<string | null>(null);

  const accept = useCallback(
    (file: File | null) => {
      if (!file) return;
      const ok = ACCEPTED.some((ext) => file.name.toLowerCase().endsWith(ext));
      if (!ok) {
        // Rejected in the browser rather than after an upload round trip: the
        // file may be tens of megabytes and the answer is already knowable.
        setRejected(`${file.name.split(".").pop()?.toUpperCase()} files are not supported`);
        setName(null);
        onSelect(null);
        return;
      }
      setRejected(null);
      setName(file.name);
      setSize(file.size);
      onSelect(file);
    },
    [onSelect],
  );

  return (
    <div>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onClick={() => !disabled && input.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!disabled) accept(e.dataTransfer.files?.[0] ?? null);
        }}
        className={`group relative flex min-h-[13rem] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-[4px] border border-dashed px-6 py-8 text-center transition-all
          ${over ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]" : "bg-[hsl(var(--surface-2)/.55)] hover:border-[hsl(var(--accent)/.55)] hover:bg-[hsl(var(--accent-soft)/.35)]"}
          ${disabled ? "pointer-events-none opacity-50" : ""}`}
      >
        <svg
          className="relative mb-4 h-10 w-10 rounded bg-[hsl(var(--accent-soft))] p-2.5 text-[hsl(var(--accent))]"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z"
          />
        </svg>
        {name ? (
          <>
            <p className="relative break-anywhere text-base font-semibold">{name}</p>
            <p className="relative mt-1 text-xs text-[hsl(var(--fg-muted))]">
              {(size / 1024 / 1024).toFixed(1)} MB · click to replace
            </p>
          </>
        ) : (
          <>
            <p className="relative text-base font-semibold">{label}</p>
            <p className="relative mt-2 text-xs text-[hsl(var(--fg-muted))]">or click to browse from your device</p>
            {hint && <p className="relative mt-4 rounded-full border bg-[hsl(var(--surface)/.7)] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[.08em] text-[hsl(var(--fg-muted))]">{hint}</p>}
          </>
        )}
      </div>

      <input
        ref={input}
        type="file"
        accept={ACCEPTED.join(",")}
        disabled={disabled}
        className="sr-only"
        onChange={(e) => accept(e.target.files?.[0] ?? null)}
      />

      {rejected && (
        <p className="mt-2 text-xs text-[hsl(var(--bad))]">
          {rejected}. Upload a PDF or DOCX — convert the file first if you need to.
        </p>
      )}
    </div>
  );
}
