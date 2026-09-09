"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { LogoMark } from "./Logo";

export type Command = { id: string; label: string; detail: string; group: string; href?: string; run?: () => void };
export const PALETTE_EVENT = "bidsense:commands";
export function reportCommand(name: string) { window.dispatchEvent(new CustomEvent("bidsense:report-action", { detail: name })); }

function relevance(query: string, text: string) {
  const q = query.toLocaleLowerCase().trim(), hay = text.toLocaleLowerCase();
  if (!q) return 1;
  if (hay.includes(q)) return 100 - hay.indexOf(q) / 100;
  let at = -1, gaps = 0;
  for (const letter of q.replace(/\s/g, "")) { const next = hay.indexOf(letter, at + 1); if (next < 0) return 0; gaps += next - at - 1; at = next; }
  return 1 / (gaps + 1);
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const [remote, setRemote] = useState<Command[]>([]);
  const [context, setContext] = useState<Command[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const listener = (e: Event) => setContext((e as CustomEvent<Command[]>).detail);
    window.addEventListener(PALETTE_EVENT, listener);
    return () => window.removeEventListener(PALETTE_EVENT, listener);
  }, []);

  useEffect(() => {
    if (!open) { dialog.current?.close(); return; }
    window.dispatchEvent(new CustomEvent("bidsense:request-commands"));
    const previous = document.activeElement as HTMLElement | null;
    setQuery(""); setSelected(0); setRemote([]); dialog.current?.showModal(); input.current?.focus();
    let cancelled = false;
    setLoading(true); setError("");
    (async () => {
      const commands: Command[] = [];
      let offset = 0;
      while (true) {
        const page = await api.listNotifications(50, offset);
        for (const tender of page.items) commands.push({ id: `tender-${tender.tender_id}`, label: tender.title, detail: tender.issuing_authority || tender.tender_id, group: "Tenders", href: `/tenders/${encodeURIComponent(tender.tender_id)}` });
        // Bound requests to four simultaneous bid lookups.
        for (let i = 0; i < page.items.length; i += 4) {
          const outcomes = await Promise.allSettled(page.items.slice(i, i + 4).map(async tender => {
            const bids = await api.submissions(tender.tender_id);
            for (const bid of bids) commands.push({ id: `bid-${tender.tender_id}/${bid.vendor_id}`, label: bid.vendor_name || bid.vendor_id, detail: `${bid.vendor_id} · ${tender.issuing_authority || tender.title}`, group: "Bids", href: `/tenders/${encodeURIComponent(tender.tender_id)}/bids/${encodeURIComponent(bid.vendor_id)}` });
          }));
          if (outcomes.some(result => result.status === "rejected")) setError("Some bids could not be indexed. Tender navigation is still available.");
          if (cancelled) return;
        }
        if (!cancelled) setRemote([...commands]);
        if (page.items.length < 50) break;
        offset += page.items.length;
      }
    })().catch(() => { if (!cancelled) setError("Tenders could not be indexed. The built-in commands are still available."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; previous?.focus(); };
  }, [open]);

  const commands = useMemo<Command[]>(() => [
    { id: "home", label: "All tenders", detail: "Your document workspace", group: "Navigate", href: "/" },
    { id: "upload", label: "Add a tender", detail: "Upload the official notification", group: "Actions", href: "/upload" },
    ...context, ...remote,
    ...["light", "dark", "system"].map(mode => ({ id: `theme-${mode}`, label: `${mode[0].toUpperCase()}${mode.slice(1)} appearance`, detail: "Change colour theme", group: "Settings", run: () => window.dispatchEvent(new CustomEvent("bidsense:theme", { detail: mode })) })),
  ], [context, remote]);
  const results = useMemo(() => commands.map(command => ({ command, score: relevance(query, `${command.label} ${command.detail} ${command.group}`) })).filter(r => r.score > 0).sort((a, b) => b.score - a.score).slice(0, 60).map(r => r.command), [commands, query]);
  useEffect(() => { setSelected(0); }, [query]);
  useEffect(() => { document.getElementById(`command-${selected}`)?.scrollIntoView({ block: "nearest" }); }, [selected]);
  const active = Math.min(selected, Math.max(0, results.length - 1));
  function execute(command: Command) { onClose(); if (command.href) router.push(command.href); else command.run?.(); }

  return <dialog ref={dialog} className="command-dialog" aria-label="Command palette" onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="command-input"><LogoMark className="h-7 w-7 shrink-0" /><input ref={input} role="combobox" aria-label="Search tenders, bids, actions and settings" aria-autocomplete="list" aria-expanded="true" aria-controls="command-results" aria-activedescendant={results.length ? `command-${active}` : undefined} value={query} onChange={e => setQuery(e.target.value)} placeholder="Where would you like to go?" onKeyDown={e => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setSelected((active + (e.key === "ArrowDown" ? 1 : -1) + results.length) % Math.max(1, results.length)); }
      if (e.key === "Home" && results.length) { e.preventDefault(); setSelected(0); }
      if (e.key === "End" && results.length) { e.preventDefault(); setSelected(results.length - 1); }
      if (e.key === "Enter" && results[active]) { e.preventDefault(); execute(results[active]); }
    }} /><button className="keycap" onClick={onClose} aria-label="Close command palette">esc</button></div>
    <div className="command-results" role="listbox" id="command-results" aria-label="Commands">
      {results.map((command, i) => <div key={`${command.group}-${command.id}`}>
        {(i === 0 || results[i - 1].group !== command.group) && <p className="command-group">{command.group}</p>}
        <div id={`command-${i}`} role="option" aria-selected={i === active} className={`command-option ${i === active ? "is-selected" : ""}`} onMouseMove={() => setSelected(i)} onClick={() => execute(command)}>
          <span className="command-glyph" aria-hidden>{command.group === "Settings" ? "◐" : command.group === "Bids" ? "↳" : "→"}</span><span className="min-w-0"><strong>{command.label}</strong><small>{command.detail}</small></span><span className="command-enter" aria-hidden>↵</span>
        </div>
      </div>)}
      {!results.length && <div className="command-empty"><LogoMark className="mx-auto mb-3 h-7 w-7" /><p>No matching pages.</p><small>Try a bidder, authority, or part of a tender reference.</small></div>}
    </div>
    <footer className="command-footer"><span>{loading ? "Indexing your documents…" : "Your workspace, a few keystrokes away."}</span><span><kbd>↑</kbd><kbd>↓</kbd> navigate <kbd>↵</kbd> open</span></footer>
    {error && <p role="status" className="command-error">{error}</p>}
  </dialog>;
}
