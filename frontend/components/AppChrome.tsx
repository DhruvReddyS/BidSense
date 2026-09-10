"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { CommandPalette } from "./CommandPalette";
import { LogoMark } from "./Logo";
import { ThemeToggle } from "./Theme";
import { HealthPill } from "./HealthPill";

export function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const helpDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(target.tagName);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!helpDialog.current?.open) setPalette(p => !p); }
      if (e.key === "?" && !typing && !document.querySelector("dialog[open]")) { e.preventDefault(); setHelp(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (help) helpDialog.current?.showModal(); else helpDialog.current?.close(); }, [help]);
  return <>
    <div className="workspace-aurora" aria-hidden><i /><i /><i /></div>
    <aside className="workspace-rail" aria-label="Workspace navigation">
      <Link href="/" className="workspace-brand" aria-label="BidSense home"><LogoMark className="h-7 w-7" /><span>BidSense<span className="brand-period">.</span></span></Link>
      <button className="workspace-search" onClick={() => setPalette(true)}><span aria-hidden>⌕</span> Search anything <kbd>⌘ K</kbd></button>
      <p className="rail-label">Workspace</p>
      <nav>
        <Link className={`rail-link ${pathname !== "/upload" ? "active" : ""}`} href="/"><svg viewBox="0 0 20 20" aria-hidden><rect x="3" y="3" width="14" height="14" rx="1"/><path d="M3 8h14M8 8v9"/></svg>All tenders</Link>
        <Link className={`rail-link ${pathname === "/upload" ? "active" : ""}`} href="/upload"><svg viewBox="0 0 20 20" aria-hidden><path d="M10 3v14M3 10h14"/></svg>Add tender</Link>
      </nav>
      <div className="rail-note"><span className="rail-note-rule"/><p>A clearer path<br/>from clause to confidence.</p><span className="ref">BIDSENSE / WORKSPACE</span></div>
      <div className="rail-bottom"><button className="rail-link" onClick={() => setHelp(true)}><span className="keycap">?</span> Keyboard shortcuts</button><div className="theme-row"><span>Appearance</span><ThemeToggle /></div><p>Every claim, connected to its source.</p></div>
    </aside>
    <div className="workspace-content">
      <header className="workspace-topbar"><span><span className="text-fg-subtle">Workspace</span><span className="breadcrumb-slash">/</span>{pathname.endsWith("/review") ? "Company review" : pathname.includes("/bids/") ? "Bid review" : pathname.startsWith("/tenders/") ? "Tender workspace" : pathname === "/upload" ? "New tender" : "Overview"}</span><div className="topbar-actions"><HealthPill /><button onClick={() => setPalette(true)} className="topbar-command">Quick jump <kbd>⌘ K</kbd></button></div></header>
      <main id="main" className="workspace-main">{children}</main>
      <footer className="workspace-footer"><span>Prepared with BidSense.</span><span>Always verify against the official document.</span></footer>
    </div>
    <CommandPalette open={palette} onClose={() => setPalette(false)} />
    <dialog ref={helpDialog} className="help-dialog" aria-labelledby="shortcut-title" onCancel={() => setHelp(false)} onClick={e => { if (e.target === e.currentTarget) setHelp(false); }}><div className="help-header"><LogoMark className="h-7 w-7"/><button className="keycap" onClick={() => setHelp(false)} aria-label="Close shortcuts">esc</button></div><h2 id="shortcut-title">Less reaching.<br/>More reviewing.</h2><p className="text-fg-muted text-sm">A few keys to keep you in the document.</p><dl>{[["Quick jump to any page or action", "⌘ / Ctrl K"], ["Show this guide", "?"], ["Move through commands", "↑ ↓"], ["Open a command or focused row", "Enter"], ["Preview a focused citation", "Tab"], ["Close preview or dialog", "Esc"]].map(([label, key]) => <div key={label}><dt>{label}</dt><dd><kbd>{key}</kbd></dd></div>)}</dl></dialog>
  </>;
}
