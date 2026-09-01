"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AskResponse } from "@/lib/types";

interface Turn {
  question: string;
  response: AskResponse | null;
  error: string | null;
}

const SUGGESTIONS = [
  "What is the EMD amount?",
  "What is the last date for submission?",
  "What turnover do I need to qualify?",
  "Which documents must I enclose?",
];

/**
 * Renders an answer with its citations.
 *
 * The [n] markers in the text are turned into anchors that line up with the
 * numbered sources below, so a reader can check each claim against the quoted
 * clause rather than taking the answer on trust.
 */
function AnswerBody({ response }: { response: AskResponse }) {
  const { answer, grounded } = response;

  return (
    <div>
      <p className="whitespace-pre-wrap text-sm text-neutral-800">
        {answer.answer}
      </p>

      {/* An ungrounded answer must be visibly marked. It looks identical to a
          grounded one otherwise, which is how an unverifiable claim gets
          believed. */}
      {answer.answered && !grounded && (
        <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          This answer is not fully backed by the documents
          {answer.invented_citations.length > 0
            ? " — it referred to sources that do not exist."
            : " — it cited nothing."}{" "}
          Verify it against the tender document before relying on it.
        </p>
      )}

      {answer.citations.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium text-neutral-600">Sources</p>
          <ol className="mt-1 space-y-2">
            {answer.citations.map((citation) => (
              <li key={citation.index} className="text-xs">
                <span className="font-mono text-neutral-500">
                  [{citation.index}]
                </span>{" "}
                <span className="text-neutral-600">{citation.label}</span>
                <blockquote className="mt-1 border-l-2 border-neutral-300 py-0.5 pl-3 italic text-neutral-700">
                  {citation.text.length > 400
                    ? `${citation.text.slice(0, 400)}…`
                    : citation.text}
                </blockquote>
              </li>
            ))}
          </ol>
        </div>
      )}

      {!answer.answered && answer.retrieved.length > 0 && (
        <details className="mt-3 text-xs text-neutral-600">
          <summary className="cursor-pointer">
            {answer.retrieved.length} passages were searched but none answered this
          </summary>
          <ul className="mt-1 space-y-1">
            {answer.retrieved.map((r) => (
              <li key={r.index} className="text-neutral-500">
                {r.label}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

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

  async function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || busy) return;

    setBusy(true);
    setQuestion("");
    const index = turns.length;
    setTurns((t) => [...t, { question: trimmed, response: null, error: null }]);

    try {
      const response = await api.ask(trimmed, tenderId, vendorId);
      setTurns((t) =>
        t.map((turn, i) => (i === index ? { ...turn, response } : turn)),
      );
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Could not get an answer.";
      setTurns((t) =>
        t.map((turn, i) => (i === index ? { ...turn, error: message } : turn)),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-5">
      <h3 className="font-medium">Ask about this tender</h3>
      <p className="mt-1 text-xs text-neutral-500">
        Answers come only from the uploaded documents, and every answer cites the
        clause it came from.
      </p>

      {turns.length === 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => ask(s)}
              disabled={busy}
              className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 space-y-5">
        {turns.map((turn, i) => (
          <div key={i}>
            <p className="text-sm font-medium text-neutral-900">{turn.question}</p>
            <div className="mt-2">
              {turn.error ? (
                <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                  {turn.error}
                </p>
              ) : turn.response ? (
                <AnswerBody response={turn.response} />
              ) : (
                <p className="text-sm text-neutral-500">Searching the documents…</p>
              )}
            </div>
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="mt-5 flex gap-2"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Is a partnership firm eligible?"
          disabled={busy}
          className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 3}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          Ask
        </button>
      </form>
    </div>
  );
}
