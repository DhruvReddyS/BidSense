import type { CheckStatus, Severity, Verdict } from "@/lib/types";

const STATUS_STYLES: Record<CheckStatus, { label: string; className: string }> = {
  match: { label: "Match", className: "bg-green-50 text-green-800 ring-green-600/20" },
  partial: { label: "Partial", className: "bg-amber-50 text-amber-800 ring-amber-600/20" },
  missing: { label: "Missing", className: "bg-red-50 text-red-800 ring-red-600/20" },
  // Deliberately worded as an instruction, not a verdict: the system has not
  // checked these, and the label must not imply that it has.
  manual_check: {
    label: "Check yourself",
    className: "bg-indigo-50 text-indigo-800 ring-indigo-600/20",
  },
  // "We could not read this" must never look like "you failed".
  not_assessable: {
    label: "Couldn't read",
    className: "bg-neutral-100 text-neutral-700 ring-neutral-500/20",
  },
};

export function StatusBadge({ status }: { status: CheckStatus }) {
  const { label, className } = STATUS_STYLES[status];
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}
    >
      {label}
    </span>
  );
}

const SEVERITY_STYLES: Record<Severity, string> = {
  disqualifying: "bg-red-600 text-white",
  action_needed: "bg-amber-500 text-white",
  review: "bg-indigo-500 text-white",
  info: "bg-neutral-300 text-neutral-800",
};

const SEVERITY_LABELS: Record<Severity, string> = {
  disqualifying: "Blocks submission",
  action_needed: "Fix before submitting",
  review: "Review",
  info: "Info",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[severity]}`}
    >
      {SEVERITY_LABELS[severity]}
    </span>
  );
}

const VERDICTS: Record<Verdict, { title: string; body: string; className: string }> = {
  compliant: {
    title: "No blocking issues found",
    body: "Every mandatory requirement this system could check was satisfied. Verify the formatting rules yourself before submitting.",
    className: "border-green-200 bg-green-50 text-green-900",
  },
  needs_review: {
    title: "Needs your review",
    body: "Nothing failed outright, but some requirements could not be checked automatically. Work through the list below before submitting.",
    className: "border-indigo-200 bg-indigo-50 text-indigo-900",
  },
  not_compliant: {
    title: "You do not currently qualify",
    body: "At least one mandatory requirement was not met. Each one is listed below with the clause it comes from.",
    className: "border-red-200 bg-red-50 text-red-900",
  },
};

export function VerdictBanner({ verdict }: { verdict: Verdict }) {
  const { title, body, className } = VERDICTS[verdict];
  return (
    <div className={`rounded-lg border p-4 ${className}`}>
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm opacity-90">{body}</p>
    </div>
  );
}
