/**
 * Shared primitives.
 *
 * Status vocabulary lives here and nowhere else. The gap report shows the same
 * five states in a table, a filter row, a summary bar and an action list; if
 * each rendered them independently they would drift, and a compliance tool that
 * uses a colour inconsistently is a tool nobody trusts twice.
 */
import type { CheckStatus, Severity, Verdict } from "@/lib/types";

type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "accent";

const TONE: Record<Tone, string> = {
  ok: "bg-[hsl(var(--ok-soft))] text-[hsl(var(--ok))] border-[hsl(var(--ok-border))]",
  warn: "bg-[hsl(var(--warn-soft))] text-[hsl(var(--warn))] border-[hsl(var(--warn-border))]",
  bad: "bg-[hsl(var(--bad-soft))] text-[hsl(var(--bad))] border-[hsl(var(--bad-border))]",
  info: "bg-[hsl(var(--info-soft))] text-[hsl(var(--info))] border-[hsl(var(--info-border))]",
  neutral:
    "bg-[hsl(var(--neutral-soft))] text-[hsl(var(--fg-muted))] border-[hsl(var(--neutral-border))]",
  accent:
    "bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))] border-[hsl(var(--accent-border))]",
};

export const STATUS_META: Record<
  CheckStatus,
  { label: string; tone: Tone; token: string; dot: string; blurb: string }
> = {
  match: {
    label: "Met",
    tone: "ok",
    token: "ok",
    dot: "bg-[hsl(var(--ok))]",
    blurb: "Found in your submission",
  },
  partial: {
    label: "Check",
    tone: "warn",
    token: "warn",
    dot: "bg-[hsl(var(--warn))]",
    blurb: "Probably covered, but confirm it",
  },
  missing: {
    label: "Missing",
    tone: "bad",
    token: "bad",
    dot: "bg-[hsl(var(--bad))]",
    blurb: "Not found — this blocks your bid",
  },
  // Worded as an instruction, not a verdict. The system has not checked these,
  // and the label must not imply that it has.
  manual_check: {
    label: "Your call",
    tone: "info",
    token: "info",
    dot: "bg-[hsl(var(--info))]",
    blurb: "Needs a human eye",
  },
  // "We could not read this" must never look like "you failed".
  not_assessable: {
    label: "Unreadable",
    tone: "neutral",
    token: "fg-subtle",
    dot: "bg-[hsl(var(--fg-subtle))]",
    blurb: "We could not read a value to compare",
  },
};

export const SEVERITY_META: Record<Severity, { label: string; tone: Tone }> = {
  disqualifying: { label: "Blocks submission", tone: "bad" },
  action_needed: { label: "Fix before submitting", tone: "warn" },
  review: { label: "Review", tone: "info" },
  info: { label: "Fine", tone: "ok" },
};

export function StatusChip({ status }: { status: CheckStatus }) {
  const meta = STATUS_META[status];
  return (
    <span className={`chip ${TONE[meta.tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  return <span className={`chip ${TONE[meta.tone]}`}>{meta.label}</span>;
}

export function Chip({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  return <span className={`chip ${TONE[tone]}`}>{children}</span>;
}

export const VERDICT_META: Record<
  Verdict,
  { title: string; body: string; tone: Tone; icon: string }
> = {
  compliant: {
    title: "No blocking issues found",
    body: "Every mandatory requirement we could check is satisfied. Formatting and signing rules still need your own eye before you submit.",
    tone: "ok",
    icon: "✓",
  },
  needs_review: {
    title: "Nearly there — some items need you",
    body: "Nothing failed outright, but some requirements could not be checked automatically. Work through the list below before submitting.",
    tone: "info",
    icon: "!",
  },
  not_compliant: {
    title: "You do not currently qualify",
    body: "At least one mandatory requirement is not met. Each one is listed below with the clause it comes from.",
    tone: "bad",
    icon: "✕",
  },
  // Not a pass. Nothing was checked, which is a different thing from nothing
  // being wrong, and conflating them would green-light every bid on a tender
  // whose extraction failed.
  not_checked: {
    title: "We could not check this bid",
    body: "No requirements were read from the tender notification, so there was nothing to check your bid against. Re-upload the notification, or check whether it is a scanned document that needs OCR.",
    tone: "neutral",
    icon: "?",
  },
};

export function Card({
  className = "",
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function SectionTitle({
  title,
  hint,
  right,
}: {
  title: string;
  hint?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-[hsl(var(--fg-muted))]">{hint}</p>}
      </div>
      {right}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed px-6 py-14 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-[hsl(var(--fg-muted))]">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className={`rounded-xl border px-4 py-3 text-sm ${TONE.bad}`}
    >
      {children}
    </div>
  );
}

/** A horizontal breakdown of the five statuses, sized by count. */
export function StatusBar({ counts }: { counts: Record<string, number> }) {
  const order: CheckStatus[] = [
    "match",
    "partial",
    "manual_check",
    "not_assessable",
    "missing",
  ];
  const total = order.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
  if (total === 0) return null;

  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
      {order.map((key) => {
        const value = counts[key] ?? 0;
        if (value === 0) return null;
        return (
          <div
            key={key}
            className={STATUS_META[key].dot}
            style={{ width: `${(value / total) * 100}%` }}
            title={`${STATUS_META[key].label}: ${value}`}
          />
        );
      })}
    </div>
  );
}

export function formatInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  if (n >= 1e7) return `₹${trim(n / 1e7)} Cr`;
  if (n >= 1e5) return `₹${trim(n / 1e5)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}

function trim(n: number): string {
  return n.toFixed(2).replace(/\.?0+$/, "");
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
