import type { Completion, Verdict } from "@/lib/types";

/**
 * "7 of 9 mandatory requirements satisfied" — a count, not a score.
 *
 * Section 4.4 forbids inventing a score the tender did not publish, and a bare
 * fraction beside a progress bar reads as one to everybody who has ever seen a
 * progress bar. The caveat is therefore rendered INSIDE the same bordered
 * block as the number, at a size that is read rather than skipped — not
 * relegated to a tooltip or a footnote, where the first thing a reader does is
 * screenshot the number without it.
 *
 * The bar carries three segments, not two. Requirements we could not establish
 * either way are their own colour: rolling them into "met" flatters the bid and
 * rolling them into "not met" reports a vendor as failing something nobody
 * checked.
 */
export function CompletionMeter({
  completion,
  verdict,
}: {
  completion: Completion;
  verdict: Verdict;
}) {
  const { satisfied, total, undetermined, caveat } = completion;
  const outstanding = Math.max(0, total - satisfied - undetermined);
  const pct = (value: number) => (total > 0 ? (value / total) * 100 : 0);

  return (
    <section
      className="card p-5"
      aria-labelledby="completion-heading"
      data-testid="completion-meter"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="completion-heading" className="label">
          Mandatory requirements
        </h2>
        <span className="text-xs text-fg-subtle">
          {verdict === "not_checked" ? "nothing checked" : `${total} checked`}
        </span>
      </div>

      <p className="mt-2.5 flex items-baseline gap-2">
        <span className="tnum text-[2.6rem] font-semibold leading-none tracking-tight">
          {satisfied}
        </span>
        <span className="text-lg text-fg-muted">
          of <span className="tnum font-medium text-fg">{total}</span> satisfied
        </span>
      </p>

      {/*
        A tally, not a progress bar.
        
        A filled bar that grows toward 100% is the visual language of a goal
        being achieved, and this is an audit: there is no prize for a full bar,
        and two of the three segments are not achievements at all. So it is a
        thin measurement rule -- proportion at a glance, no fill animation, no
        celebratory shape -- and the counts beneath it carry the actual reading.
      */}
      <div
        className="mt-4 flex h-[3px] w-full gap-[2px]"
        role="img"
        aria-label={`${satisfied} met, ${undetermined} not established either way, ${outstanding} outstanding, of ${total}`}
      >
        {[
          { value: satisfied, colour: "ok" },
          { value: undetermined, colour: "warn" },
          { value: outstanding, colour: "pending" },
        ]
          .filter((segment) => segment.value > 0)
          .map((segment) => (
            <div
              key={segment.colour}
              className="h-full"
              style={{
                width: `${pct(segment.value)}%`,
                background: `hsl(var(--${segment.colour}))`,
              }}
            />
          ))}
      </div>

      <ul className="mt-3 space-y-1.5 text-[12.5px]">
        <Legend colour="ok" marker="marker-met" label="Met" value={satisfied} />
        <Legend
          colour="warn"
          marker="marker-check"
          label="Not established either way"
          value={undetermined}
        />
        <Legend
          colour="pending"
          marker="marker-outstanding"
          label="Outstanding"
          value={outstanding}
        />
      </ul>

      {/* Attached to the number, not filed away from it. */}
      <p className="mt-4 border-t pt-3 text-[12.5px] leading-relaxed text-fg-muted">
        <span className="font-medium text-fg">This is a count, not a score.</span>{" "}
        {caveat.replace(/^This is a count of requirements met, not a score\.\s*/, "")}
      </p>
    </section>
  );
}

function Legend({
  colour,
  marker,
  label,
  value,
}: {
  colour: "ok" | "warn" | "pending";
  marker: string;
  label: string;
  value: number;
}) {
  return (
    <li className="flex items-baseline gap-2">
      <span
        className={`marker ${marker} translate-y-[1px]`}
        style={{ color: `hsl(var(--${colour}))` }}
        aria-hidden
      />
      <span className="tnum w-6 shrink-0 font-medium tabular-nums">{value}</span>
      <span className="text-fg-muted">{label}</span>
    </li>
  );
}
