"use client";

import { useEffect, useRef, useState } from "react";
import { DataQualityBanner } from "./Banners";
import { api, ApiError } from "@/lib/api";
import type { AskResponse, Citation } from "@/lib/types";
import { CitationViewer, type CitationTarget } from "./CitationViewer";
import { Card, Chip } from "./ui";

interface Turn {
  question: string;
  response: AskResponse | null;
  error: string | null;
}

const SUGGESTIONS = [
  "What is the EMD amount?",
  "What turnover do I need to qualify?",
  "When is the last date for submission?",
  "Which documents must I enclose?",
  "Is a partnership firm eligible?",
];

export function AskPanel({
  tenderId,
  vendorId,
}: {
  tenderId: string;
  vendorId?: string;
}) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [citation, setCitation] = useState<CitationTarget | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns]);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || busy) return;

    setBusy(true);
    setQuestion("");
    const index = turns.length;
    setTurns((t) => [...t, { question: trimmed, response: null, error: null }]);

    try {
      const response = await api.ask(trimmed, tenderId, vendorId);
      setTurns((t) => t.map((v, i) => (i === index ? { ...v, response } : v)));
    } catch (e) {
      const message =
        e instanceof ApiError ? e.message : "Could not get an answer.";
      setTurns((t) => t.map((v, i) => (i === index ? { ...v, error: message } : v)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="grid min-h-[26rem] overflow-hidden p-0 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <aside className="border-b bg-[hsl(var(--surface-2)/.6)] p-5 lg:border-b-0 lg:border-r lg:p-6">
          <p className="label">Document Q&amp;A</p>
          <h2 className="font-display mt-2 text-2xl font-medium">Ask this tender</h2>
          <p className="mt-2 text-xs leading-relaxed text-[hsl(var(--fg-muted))]">
            Every answer is drawn from the uploaded document and carries the
            clause it came from. Where the document does not say, the answer
            says so rather than filling the gap.
          </p>
        <p className="label mt-7">Common questions</p>
        <div className="mt-2 divide-y border-y">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => ask(s)}
              disabled={busy}
              className="group flex w-full items-start justify-between gap-3 py-2.5 text-left text-xs leading-snug text-[hsl(var(--fg-muted))] transition-colors hover:text-[hsl(var(--fg))] disabled:opacity-50"
            >
              <span>{s}</span><span className="text-[hsl(var(--fg-subtle))] group-hover:text-[hsl(var(--accent))]">→</span>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-col p-5 lg:p-6">
        <div className="flex items-center justify-between border-b pb-3">
          <p className="text-xs font-medium text-[hsl(var(--fg-muted))]">Answers include source clauses and page references</p>
          {turns.length > 0 && <button onClick={() => setTurns([])} className="text-xs text-[hsl(var(--fg-muted))] hover:text-[hsl(var(--fg))]">Clear history</button>}
        </div>
      <div className="mt-5 flex-1 space-y-6">
        {turns.length === 0 && <div className="grid min-h-[12rem] place-items-center text-center"><div><p className="font-display text-xl font-medium">What would you like to verify?</p><p className="mt-2 text-xs text-[hsl(var(--fg-muted))]">Choose a common question or write your own below.</p></div></div>}
        {turns.map((turn, i) => (
          <div key={i} className="animate-rise">
            {/* No avatar, no bubble. This is a question put to a document and
                an answer drawn from it — the moment it looks like a chat
                transcript, a reader starts treating the answer as opinion. */}
            <p className="border-l-2 border-[hsl(var(--border-strong))] pl-3 text-sm font-medium leading-snug">
              {turn.question}
            </p>
            <div className="mt-3 pl-3">
              {turn.error ? (
                <p className="rounded-lg border border-[hsl(var(--bad-border))] bg-[hsl(var(--bad-soft))] px-3 py-2 text-sm text-[hsl(var(--bad))]">
                  {turn.error}
                </p>
              ) : turn.response ? (
                <Answer response={turn.response} onCite={setCitation} />
              ) : (
                <div className="space-y-2">
                  <div className="h-4 w-3/4 skeleton" />
                  <div className="h-4 w-1/2 skeleton" />
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
        className="mt-6 flex gap-2 border-t pt-5"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask anything about this tender…"
          disabled={busy}
          aria-label="Your question"
          className="input flex-1"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 3}
          className="btn btn-primary"
        >
          {busy ? "…" : "Ask"}
        </button>
      </form>
      </div>

      <CitationViewer target={citation} onClose={() => setCitation(null)} />
    </Card>
  );
}

/**
 * How well retrieval matched the question, said out loud.
 *
 * A confident-sounding answer built on loosely related passages is the failure
 * citations were meant to prevent, and citations alone do not prevent it — the
 * citations are real, they are just not about the question. `none` never
 * reaches here: the model is not called at all below the floor.
 */
const CONFIDENCE_META: Record<
  string,
  { label: string; tone: "ok" | "warn" | "neutral" } | undefined
> = {
  high: { label: "Strong match", tone: "ok" },
  low: { label: "Weak match", tone: "warn" },
  none: { label: "No match", tone: "neutral" },
};

function Answer({
  response,
  onCite,
}: {
  response: AskResponse;
  onCite: (target: CitationTarget) => void;
}) {
  const { answer, grounded, sources } = response;
  const [open, setOpen] = useState(true);
  const confidence = CONFIDENCE_META[answer.confidence];

  const openCitation = (citation: Citation) =>
    onCite({
      contentHash:
        citation.doc_kind === "submission" ? sources.bid : sources.notification,
      page: citation.source_page,
      snippet: citation.text,
      clauseRef: citation.clause_ref,
      documentLabel:
        citation.source_file ??
        (citation.doc_kind === "submission" ? "Your bid" : "This tender"),
    });

  return (
    <div>
      {response.data_quality && <DataQualityBanner quality={response.data_quality} />}
      {answer.provider && <p className="ref mb-2 text-fg-muted">Answered by {answer.provider}</p>}
      <p className="whitespace-pre-wrap break-anywhere text-sm leading-relaxed">
        {answer.answer}
      </p>

      {/* Weak retrieval is stated beside the answer, not buried. */}
      {answer.caveat ? (
        <p className="mt-2 rounded-lg border border-[hsl(var(--warn-border))] bg-[hsl(var(--warn-soft))] px-3 py-2 text-xs leading-relaxed text-[hsl(var(--fg))]">
          {answer.caveat}
        </p>
      ) : null}

      {/* An ungrounded answer looks identical to a grounded one. Marking it is
          the difference between a citation and a claim. */}
      {answer.answered && !grounded && (
        <p className="mt-2 rounded-lg border border-[hsl(var(--warn-border))] bg-[hsl(var(--warn-soft))] px-3 py-2 text-xs text-[hsl(var(--warn))]">
          {answer.invented_citations.length > 0
            ? "This answer referred to sources that do not exist. "
            : "This answer cites nothing in the document. "}
          Check it against the tender before relying on it.
        </p>
      )}

      {answer.citations.length > 0 && (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2">
            {confidence ? (
              <Chip tone={confidence.tone}>{confidence.label}</Chip>
            ) : null}
            <button
              onClick={() => setOpen((o) => !o)}
              className="flex items-center gap-2 text-xs text-[hsl(var(--fg-muted))] hover:text-[hsl(var(--fg))]"
            >
              <Chip tone="ok">
                {answer.citations.length} source
                {answer.citations.length === 1 ? "" : "s"}
              </Chip>
              <span className="underline-offset-2 hover:underline">
                {open ? "hide" : "show"}
              </span>
            </button>
          </div>

          {open && (
            <ol className="animate-rise mt-2.5 space-y-2">
              {answer.citations.map((c) => (
                <li key={c.index}>
                  <button
                    onClick={() => openCitation(c)}
                    className="cited group w-full !items-start rounded border-l-2
                               border-[hsl(var(--border))] py-1 pl-3 text-left
                               hover:border-[hsl(var(--accent))]"
                    title="Open this passage on its page in the source document"
                  >
                    <span className="block min-w-0 flex-1">
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="src !border-transparent !bg-transparent !px-0">
                          [{c.index}]
                        </span>
                        <span className="ref text-[hsl(var(--fg-muted))]">{c.label}</span>
                        <span className="go">open ↗</span>
                      </span>
                      <span className="break-anywhere mt-1 block text-xs leading-relaxed text-[hsl(var(--fg-muted))]">
                        {c.text.length > 420 ? `${c.text.slice(0, 420)}…` : c.text}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {!answer.answered && answer.retrieved.length > 0 && (
        <p className="mt-2 text-xs text-[hsl(var(--fg-subtle))]">
          {answer.retrieved.length} passages were searched; none contained the answer.
        </p>
      )}
    </div>
  );
}
