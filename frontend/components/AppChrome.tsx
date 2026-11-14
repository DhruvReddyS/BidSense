"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { CommandPalette } from "./CommandPalette";
import { LogoMark } from "./Logo";
import { ThemeToggle } from "./Theme";
import { HealthPill } from "./HealthPill";
import { api } from "@/lib/api";
import { companySubmissionLabel } from "@/lib/submission-labels";

export function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [role, setRole] = useState<"vendor" | "reviewer">("vendor");
  const [projects, setProjects] = useState<{ id: string; title: string; href: string; bids: { href: string; label: string; meta: string; timestamp: string }[] }[]>([]);
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
  useEffect(() => { try { setRailCollapsed(localStorage.getItem("bidsense-rail") === "collapsed"); setRole(localStorage.getItem("bidsense_role") === "reviewer" ? "reviewer" : "vendor"); } catch {} }, []);
  useEffect(() => {
    let active = true;
    api.listNotifications().then(data => Promise.all(data.items.map(async tender => {
      const bids = await api.submissions(tender.tender_id).catch(() => []);
      return {
        id: tender.tender_id,
        title: tender.title,
        href: role === "reviewer" ? `/tenders/${encodeURIComponent(tender.tender_id)}/review` : `/tenders/${encodeURIComponent(tender.tender_id)}`,
        bids: bids.map(bid => ({
          href: `/tenders/${encodeURIComponent(tender.tender_id)}/bids/${encodeURIComponent(bid.vendor_id)}`,
          label: role === "reviewer" ? companySubmissionLabel(bid.vendor_id, bid.vendor_name) : (bid.vendor_name || bid.vendor_id),
          meta: role === "reviewer" ? (bid.status === "eliminated" ? "Eliminated" : bid.status === "shortlisted" ? "Shortlisted" : "Cleared") : `${bid.completion_satisfied ?? 0}/${bid.completion_total ?? 0} checks`,
          timestamp: bid.last_checked_at || bid.uploaded_at,
        })).sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()),
      };
    }))).then(items => { if (active) setProjects(items); }).catch(() => { if (active) setProjects([]); });
    return () => { active = false; };
  }, [role, pathname]);
  function toggleRail() { setRailCollapsed(value => { const next = !value; try { localStorage.setItem("bidsense-rail", next ? "collapsed" : "open"); } catch {} return next; }); }
  return <>
    <div className="workspace-aurora" aria-hidden><i /><i /><i /></div>
    <aside className={`workspace-rail ${railCollapsed ? "is-collapsed" : ""}`} aria-label="Workspace navigation">
      <div className="rail-brand-row"><Link href="/" className="workspace-brand" aria-label="BidSense home"><LogoMark className="h-7 w-7" /><span>BidSense<span className="brand-period">.</span></span></Link><button className="rail-collapse" onClick={toggleRail} aria-label={railCollapsed ? "Expand navigation" : "Collapse navigation"} title={railCollapsed ? "Expand navigation" : "Collapse navigation"}>‹</button></div>
      <button className="workspace-search" onClick={() => setPalette(true)}><span aria-hidden>⌕</span> Search anything <kbd>⌘ K</kbd></button>
      <p className="rail-label">{role === "reviewer" ? "Company workspace" : "Vendor workspace"}</p>
      <nav>
        <Link title={role === "reviewer" ? "Company tenders" : "My tenders"} className={`rail-link ${pathname === "/" || pathname.startsWith("/tenders/") ? "active" : ""}`} href="/"><svg viewBox="0 0 20 20" aria-hidden><rect x="3" y="3" width="14" height="14" rx="1"/><path d="M3 8h14M8 8v9"/></svg><span>{role === "reviewer" ? "Company tenders" : "My tenders"}</span></Link>
        <Link title="Add tender" className={`rail-link ${pathname === "/upload" ? "active" : ""}`} href="/upload"><svg viewBox="0 0 20 20" aria-hidden><path d="M10 3v14M3 10h14"/></svg><span>Add tender</span></Link>
        <Link title="Profile" className={`rail-link ${pathname === "/profile" ? "active" : ""}`} href="/profile"><svg viewBox="0 0 20 20" aria-hidden><circle cx="10" cy="7" r="3"/><path d="M4 17c.8-3.2 2.8-5 6-5s5.2 1.8 6 5"/></svg><span>{role === "reviewer" ? "Company profile" : "My profile"}</span></Link>
      </nav>
      <section className="rail-recent" aria-label="Tender projects"><p className="rail-label">Tender projects</p><div className="rail-recent-list">{projects.length ? projects.map(project => <details key={project.id} className="rail-project" open><summary title={project.title}><span>⌄</span><b>{project.title}</b><small>{project.bids.length}</small></summary><Link href={project.href} className="rail-project-open">Open tender →</Link><div className="rail-project-bids">{project.bids.map(bid => <Link key={bid.href} href={bid.href} className="rail-recent-item" title={bid.label}><span>{bid.label}</span><small>{bid.meta}</small></Link>)}</div></details>) : <p className="rail-recent-empty">No tenders yet</p>}</div></section>
      <div className="rail-note"><span className="rail-note-rule"/><p>A clearer path<br/>from clause to confidence.</p><span className="ref">BIDSENSE / WORKSPACE</span></div>
      <div className="rail-bottom"><button className="rail-link" onClick={() => setHelp(true)}><span className="keycap">?</span> Keyboard shortcuts</button><button className="rail-link" onClick={() => { localStorage.removeItem("bidsense_token"); localStorage.removeItem("bidsense_role"); document.cookie = "bidsense_token=; Path=/; Max-Age=0; SameSite=Lax"; window.location.href = "/login"; }}><span aria-hidden>↪</span> Sign out</button><div className="theme-row"><span>Appearance</span><ThemeToggle /></div><p>Every claim, connected to its source.</p></div>
    </aside>
    <div className={`workspace-content ${railCollapsed ? "rail-is-collapsed" : ""}`}>
      <header className="workspace-topbar"><span><span className="text-fg-subtle">{role === "reviewer" ? "Company" : "Vendor"}</span><span className="breadcrumb-slash">/</span>{pathname.includes("/review") ? "Evaluation" : pathname.includes("/bids/") ? "Bid result" : pathname.startsWith("/tenders/") ? "Tender" : pathname === "/upload" ? "New tender" : "Tenders"}</span><div className="topbar-actions"><span className="chip">{role === "reviewer" ? "Reviewer" : "Vendor"}</span><HealthPill /><button onClick={() => setPalette(true)} className="topbar-command">Quick jump <kbd>⌘ K</kbd></button></div></header>
      <main id="main" className="workspace-main">{children}</main>
      <footer className="workspace-footer"><span>Prepared with BidSense.</span><span>Always verify against the official document.</span></footer>
    </div>
    <CommandPalette open={palette} onClose={() => setPalette(false)} />
    <dialog ref={helpDialog} className="help-dialog" aria-labelledby="shortcut-title" onCancel={() => setHelp(false)} onClick={e => { if (e.target === e.currentTarget) setHelp(false); }}><div className="help-header"><LogoMark className="h-7 w-7"/><button className="keycap" onClick={() => setHelp(false)} aria-label="Close shortcuts">esc</button></div><h2 id="shortcut-title">Less reaching.<br/>More reviewing.</h2><p className="text-fg-muted text-sm">A few keys to keep you in the document.</p><dl>{[["Quick jump to any page or action", "⌘ / Ctrl K"], ["Show this guide", "?"], ["Move through commands", "↑ ↓"], ["Open a command or focused row", "Enter"], ["Preview a focused citation", "Tab"], ["Close preview or dialog", "Esc"]].map(([label, key]) => <div key={label}><dt>{label}</dt><dd><kbd>{key}</kbd></dd></div>)}</dl></dialog>
  </>;
}
