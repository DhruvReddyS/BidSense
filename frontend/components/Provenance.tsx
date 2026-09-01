import type { Provenance } from "@/lib/types";

/**
 * Renders the citation anchor for an extracted value.
 *
 * The snippet is shown verbatim and visibly quoted, because its whole purpose
 * is that the user can compare it against the source document. Paraphrasing or
 * truncating it mid-sentence would defeat the point.
 */
export function ProvenanceNote({
  provenance,
  label,
}: {
  provenance: Provenance | null;
  label: string;
}) {
  if (!provenance) return null;
  const { clause_ref, source_page, source_snippet } = provenance;
  if (!clause_ref && !source_page && !source_snippet) return null;

  const anchor = [
    clause_ref ? `clause ${clause_ref}` : null,
    source_page ? `page ${source_page}` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <details className="mt-2 text-xs text-neutral-600">
      <summary className="cursor-pointer select-none hover:text-neutral-900">
        {label}
        {anchor ? ` — ${anchor}` : ""}
      </summary>
      {source_snippet ? (
        <blockquote className="mt-1 border-l-2 border-neutral-300 py-0.5 pl-3 italic text-neutral-700">
          {source_snippet}
        </blockquote>
      ) : (
        <p className="mt-1 text-neutral-500">
          No quoted text was captured for this value.
        </p>
      )}
    </details>
  );
}
