/** A common processing mark for every long-running document operation. */
export function DocumentProcess({
  label = "Reading the record",
  detail,
  compact = false,
}: {
  label?: string;
  detail?: string;
  compact?: boolean;
}) {
  return (
    <div className={`document-process ${compact ? "is-compact" : ""}`} role="status" aria-live="polite">
      <span className="document-process-mark" aria-hidden>
        <i className="process-sheet process-sheet-back" />
        <i className="process-sheet process-sheet-mid" />
        <i className="process-sheet process-sheet-front"><b /><b /><b /><em /></i>
      </span>
      <span className="document-process-copy">
        <strong>{label}</strong>
        {detail && <small>{detail}</small>}
      </span>
    </div>
  );
}
