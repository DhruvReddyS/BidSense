"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AskResponse } from "@/lib/types";
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
    <Card className="flex min-h-[30rem] flex-col p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold tracking-tight">Ask this tender</h2>
          <p className="mt-1 max-w-lg text-xs leading-relaxed text-[hsl(var(--fg-muted))]">
            Answers come only from the uploaded document and every one cites the
            clause it came from. If the document does not say, the answer says
            so rather than filling the gap.
          </p>
        </div>
        {turns.length > 0 && (
          <button
            onClick={() => setTurns([])}
            className="btn btn-subtle !px-2 !py-1 text-xs"
          >
            Clear
          </button>
        )}
      </div>

      {turns.length === 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => ask(s)}
              disabled={busy}
              className="chip bg-[hsl(var(--surface))] transition-colors hover:bg-[hsl(var(--surface-2))] disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="mt-5 flex-1 space-y-6">
        {turns.map((turn, i) => (
          <div key={i} className="animate-rise">
            <div className="flex gap-2.5">
              <span
                className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[hsl(var(--surface-2))] text-[10px] font-semibold text-[hsl(var(--fg-muted))]"
                aria-hidden
              >
                Q
              </span>
              <p className="text-sm font-medium leading-snug">{turn.question}</p>
            </div>
            <div className="mt-2.5 pl-[1.9rem]">
              {turn.error ? (
                <p className="rounded-lg border border-[hsl(var(--bad-border))] bg-[hsl(var(--bad-soft))] px-3 py-2 text-sm text-[hsl(var(--bad))]">
                  {turn.error}
                </p>
              ) : turn.response ? (
                <Answer response={turn.response} />
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
    </Card>
  );
}

function Answer({ response }: { response: AskResponse }) {
  const { answer, grounded } = response;
  const [open, setOpen] = useState(false);

  return (
    <div>
      <p className="whitespace-pre-wrap break-anywhere text-sm leading-relaxed">
        {answer.answer}
      </p>

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

          {open && (
            <ol className="animate-rise mt-2 space-y-2.5">
              {answer.citations.map((c) => (
                <li key={c.index} className="text-xs">
                  <span className="font-mono text-[hsl(var(--fg-subtle))]">[{c.index}]</span>{" "}
                  <span className="text-[hsl(var(--fg-muted))]">{c.label}</span>
                  <blockquote className="mt-1 border-l-2 border-[hsl(var(--border-strong))] pl-3 italic leading-relaxed text-[hsl(var(--fg-muted))] break-anywhere">
                    {c.text.length > 420 ? `${c.text.slice(0, 420)}…` : c.text}
                  </blockquote>
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
