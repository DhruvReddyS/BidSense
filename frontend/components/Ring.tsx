"use client";

import type { CheckStatus } from "@/lib/types";
import { STATUS_META } from "./ui";

/**
 * Compliance breakdown as a ring.
 *
 * A ring rather than a bar because the number in the middle is the headline —
 * how much of this tender you have actually satisfied — and a bar has nowhere
 * to put it. Segments are drawn in a fixed order so the same report always
 * looks the same, and each carries a title for hover inspection.
 */
export function ComplianceRing({
  counts,
  size = 132,
  stroke = 13,
}: {
  counts: Record<string, number>;
  size?: number;
  stroke?: number;
}) {
  const order: CheckStatus[] = [
    "match",
    "partial",
    "manual_check",
    "not_assessable",
    "missing",
  ];
  const total = order.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
  if (total === 0) return null;

  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const met = counts.match ?? 0;
  const pct = Math.round((met / total) * 100);

  let offset = 0;
  const segments = order.flatMap((key) => {
    const value = counts[key] ?? 0;
    if (value === 0) return [];
    const length = (value / total) * circumference;
    const segment = { key, value, length, offset };
    offset += length;
    return [segment];
  });

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        role="img"
        aria-label={`${met} of ${total} requirements met`}
        className="-rotate-90"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="hsl(var(--surface-2))"
          strokeWidth={stroke}
        />
        {segments.map(({ key, value, length, offset: start }) => (
          <circle
            key={key}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={`hsl(var(--${STATUS_META[key].token}))`}
            strokeWidth={stroke}
            strokeLinecap="butt"
            strokeDasharray={`${length} ${circumference - length}`}
            strokeDashoffset={-start}
            className="animate-draw"
            style={{ ["--dash-total" as string]: `${circumference}` }}
          >
            <title>{`${STATUS_META[key].label}: ${value}`}</title>
          </circle>
        ))}
      </svg>

      <div className="pointer-events-none absolute inset-0 grid place-items-center">
        <div className="text-center">
          <div className="tnum text-2xl font-semibold leading-none">{pct}%</div>
          <div className="mt-1 text-[10px] uppercase tracking-wider text-[hsl(var(--fg-subtle))]">
            met
          </div>
        </div>
      </div>
    </div>
  );
}
