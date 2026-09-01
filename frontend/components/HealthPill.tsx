"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Health } from "@/lib/types";

/**
 * Dependency status in the footer.
 *
 * Deliberately visible rather than hidden behind a debug page: this system
 * degrades in ways a user would otherwise mistake for bad results. Without OCR
 * a scanned tender comes back with clauses missing, and the only honest thing
 * is to say so where someone will see it.
 */
export function HealthPill() {
  const [health, setHealth] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then((h) => alive && setHealth(h))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  if (failed) {
    return (
      <span className="chip bg-[hsl(var(--bad-soft))] text-[hsl(var(--bad))] border-[hsl(var(--bad-border))]">
        <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--bad))]" />
        API unreachable
      </span>
    );
  }
  if (!health) return <span className="h-5 w-28 skeleton" />;

  const problems = [
    !health.postgres && "database",
    !health.qdrant && "search index",
    !health.embeddings && "embeddings",
    !health.llm_reachable && "language model",
    !health.ocr_available && "OCR",
  ].filter(Boolean) as string[];

  const ok = problems.length === 0;
  return (
    <span
      title={
        ok
          ? `All services healthy · ${health.llm_provider}`
          : `Unavailable: ${problems.join(", ")}`
      }
      className={`chip ${
        ok
          ? "border-[hsl(var(--ok-border))] bg-[hsl(var(--ok-soft))] text-[hsl(var(--ok))]"
          : "border-[hsl(var(--warn-border))] bg-[hsl(var(--warn-soft))] text-[hsl(var(--warn))]"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          ok ? "bg-[hsl(var(--ok))]" : "bg-[hsl(var(--warn))]"
        }`}
      />
      {ok ? "All systems ready" : `${problems.length} service unavailable`}
    </span>
  );
}
