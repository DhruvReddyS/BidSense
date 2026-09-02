"use client";

import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";

/**
 * The cited passage, on the page it came from.
 *
 * This is the component that turns "page 67, clause 1" from a label into
 * something a vendor can check, so it is deliberately prominent: a full
 * overlay, the page at readable size, and the highlight drawn by the backend
 * from the same word coordinates the extractor read.
 *
 * Three states it must not blur together:
 *   - the page rendered and the passage was found  -> shown, marked
 *   - the page rendered and the passage was NOT found -> shown, and SAID so.
 *     A silent unmarked page reads as "there is nothing here".
 *   - the document was never retained -> a plain explanation, not a broken image.
 */
export interface CitationTarget {
  contentHash: string | null;
  page: number | null;
  snippet: string | null;
  clauseRef: string | null;
  /** "This tender" / the bidder's name — whose document is being opened. */
  documentLabel: string;
}

export function CitationViewer({
  target,
  onClose,
}: {
  target: CitationTarget | null;
  onClose: () => void;
}) {
  const [state, setState] = useState<{
    url?: string;
    highlights?: number;
    pageCount?: number;
    highlightAt?: number | null;
    error?: string;
    loading: boolean;
  }>({ loading: false });
  const objectUrl = useRef<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target?.contentHash || !target.page) {
      setState({ loading: false });
      return;
    }
    let cancelled = false;
    setState({ loading: true });

    api
      .citationPage(target.contentHash, target.page, target.snippet)
      .then((result) => {
        if (cancelled) {
          URL.revokeObjectURL(result.url);
          return;
        }
        objectUrl.current = result.url;
        setState({
          loading: false,
          url: result.url,
          highlights: result.highlights,
          pageCount: result.pageCount,
          highlightAt: result.highlightAt,
        });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          loading: false,
          error:
            error instanceof ApiError
              ? error.message
              : "That page could not be rendered.",
        });
      });

    return () => {
      cancelled = true;
      // ~200KB per page; one leaked object URL per citation click adds up fast.
      if (objectUrl.current) {
        URL.revokeObjectURL(objectUrl.current);
        objectUrl.current = null;
      }
    };
  }, [target]);

  /*
   * Land ON the marked passage.
   *
   * A panel that opens at the top of a 68-page tender and leaves the highlight
   * below the fold has technically shown the citation and practically hidden
   * it -- the reader has to hunt for the thing they clicked to see.
   *
   * Done in an effect rather than the image's onLoad: a blob URL frequently
   * finishes loading before React attaches the handler, so onLoad never fires
   * and the scroll silently never happens. This waits for layout instead, which
   * is the condition that actually matters.
   */
  useEffect(() => {
    const at = state.highlightAt;
    const box = scroller.current;
    if (at == null || !box) return;

    let frame = 0;
    const settle = () => {
      const image = box.querySelector("img");
      if (!image || !image.offsetHeight) {
        frame = requestAnimationFrame(settle);
        return;
      }
      box.scrollTo({
        top: Math.max(0, image.offsetTop + image.offsetHeight * at - box.clientHeight / 2),
        behavior: "auto",
      });
    };
    frame = requestAnimationFrame(settle);
    return () => cancelAnimationFrame(frame);
  }, [state.url, state.highlightAt]);

  useEffect(() => {
    if (!target) return;
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [target, onClose]);

  if (!target) return null;

  const notRetained = !target.contentHash;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                 bg-[hsl(var(--fg)/0.45)] p-4 backdrop-blur-sm sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label="Source document"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="animate-rise raised card w-full max-w-4xl overflow-hidden">
        <header className="flex items-start justify-between gap-4 border-b bg-[hsl(var(--surface-2))] px-5 py-3.5">
          <div className="min-w-0">
            <p className="label">Source</p>
            <h3 className="break-anywhere mt-0.5 text-sm font-semibold">
              {target.documentLabel}
            </h3>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
              {target.page ? (
                <span className="tnum">
                  Page {target.page}
                  {state.pageCount ? ` of ${state.pageCount}` : ""}
                </span>
              ) : null}
              {target.clauseRef ? (
                <span className="break-anywhere font-mono">
                  clause {target.clauseRef}
                </span>
              ) : null}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {target.contentHash ? (
              <a
                className="btn btn-ghost !px-2.5 !py-1.5 text-xs"
                href={api.documentUrl(target.contentHash)}
                target="_blank"
                rel="noreferrer"
              >
                Open full PDF
              </a>
            ) : null}
            <button
              ref={closeButton}
              className="btn btn-subtle !px-2.5 !py-1.5 text-xs"
              onClick={onClose}
              aria-label="Close"
            >
              Close
            </button>
          </div>
        </header>

        {target.snippet ? (
          <blockquote
            className="max-h-28 overflow-y-auto border-b bg-[hsl(var(--warn-soft))]
                       px-5 py-3 text-[13px] leading-relaxed text-fg"
          >
            <span className="label mb-1 block text-[hsl(var(--warn))]">
              Cited text
            </span>
            {/* Capped for DISPLAY only. A retrieved chunk runs to hundreds of
                characters and would push the page image -- the thing the reader
                came for -- below the fold. The full text still goes to the
                matcher, where more context makes the highlight more accurate. */}
            “{target.snippet.length > 320
              ? `${target.snippet.slice(0, 320)}…`
              : target.snippet}”
          </blockquote>
        ) : null}

        <div
          ref={scroller}
          className="max-h-[65vh] overflow-auto bg-[hsl(var(--surface-2))] p-4"
        >
          {notRetained ? (
            <Notice>
              This document was ingested before source pages were retained, so
              the page cannot be shown. The citation itself is still exact —
              re-upload the document to enable the preview.
            </Notice>
          ) : state.loading ? (
            <div className="skeleton mx-auto h-[60vh] w-full max-w-2xl" />
          ) : state.error ? (
            <Notice tone="bad">{state.error}</Notice>
          ) : state.url ? (
            <figure>
              {state.highlights === 0 ? (
                <figcaption className="mb-3 rounded bg-[hsl(var(--warn-soft))] px-3 py-2 text-xs text-fg">
                  The page is shown, but the exact cited wording could not be
                  located on it — read the page rather than looking for a mark.
                </figcaption>
              ) : null}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={state.url}
                alt={`Page ${target.page} of ${target.documentLabel}, with the cited passage highlighted`}
                className="mx-auto w-full max-w-2xl rounded bg-white"
              />
            </figure>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Notice({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "bad";
}) {
  return (
    <p
      className={`mx-auto max-w-lg rounded-lg border px-4 py-6 text-center text-sm ${
        tone === "bad"
          ? "border-[hsl(var(--bad-border))] bg-[hsl(var(--bad-soft))]"
          : "bg-[hsl(var(--surface))] text-fg-muted"
      }`}
    >
      {children}
    </p>
  );
}
