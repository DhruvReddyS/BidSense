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
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors
          ${over ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]" : "hover:bg-[hsl(var(--surface-2))]"}
          ${disabled ? "pointer-events-none opacity-50" : ""}`}
      >
        <svg
          className="mb-3 h-8 w-8 text-fg-subtle"
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
            <p className="text-sm font-medium break-anywhere">{name}</p>
            <p className="mt-0.5 text-xs text-fg-muted">
              {(size / 1024 / 1024).toFixed(1)} MB · click to replace
            </p>
          </>
        ) : (
          <>
            <p className="text-sm font-medium">{label}</p>
            {hint && <p className="mt-1 text-xs text-fg-muted">{hint}</p>}
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
