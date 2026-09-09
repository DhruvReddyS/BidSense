"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ActionItem, CheckStatus, GapItem, GapReportResponse } from "@/lib/types";
import { ActionList } from "./ActionList";
import { DataQualityBanner, StalenessBanner } from "./Banners";
import { CitationViewer, type CitationTarget } from "./CitationViewer";
import { CompletionMeter } from "./CompletionMeter";
import { Amount, Cited, StateTag } from "./Cited";
import { PALETTE_EVENT, type Command } from "./CommandPalette";

const KIND_LABEL: Record<GapItem["kind"], string> = { document: "Document", numeric: "Threshold", boolean: "Condition", format_rule: "Submission rule" };
const FILTERS = ["all", "blocking", "missing", "review", "match"] as const;
type Filter = typeof FILTERS[number];
const LABELS: Record<Filter, string> = { all: "All requirements", blocking: "Does not qualify", missing: "Outstanding", review: "Needs your check", match: "Met" };
const REVIEW: CheckStatus[] = ["partial", "manual_check", "not_assessable"];

export function GapReport({ data, onRefresh }: { data: GapReportResponse; onRefresh?: (acknowledge: boolean) => Promise<void> | void }) {
  const { report, verdict, staleness, completion, sources } = data;
  const [filter, setFilter] = useState<Filter>("all");
  const [tab, setTab] = useState<"actions" | "requirements">("requirements");
  const [dense, setDense] = useState(false);
  const [search, setSearch] = useState("");
  const [focusRow, setFocusRow] = useState<string | null>(null);
  const [citation, setCitation] = useState<CitationTarget | null>(null);
  const [rechecking, setRechecking] = useState(false);
  const [exporting, setExporting] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const hardFailures = useMemo(() => new Set(report.action_list.filter(a => a.group === "hard_fail").map(a => a.requirement)), [report.action_list]);
  const counts = useMemo(() => ({ all: report.items.length, blocking: report.items.filter(i => hardFailures.has(i.requirement)).length, missing: report.items.filter(i => i.status === "missing" && !hardFailures.has(i.requirement)).length, review: report.items.filter(i => REVIEW.includes(i.status)).length, match: report.items.filter(i => i.status === "match").length }), [report.items, hardFailures]);
  const visible = useMemo(() => report.items.filter(item => {
    const category = filter === "all" || (filter === "blocking" ? hardFailures.has(item.requirement) : filter === "review" ? REVIEW.includes(item.status) : filter === "missing" ? item.status === "missing" && !hardFailures.has(item.requirement) : item.status === filter);
    return category && `${item.requirement} ${item.required_value || ""} ${item.found_value || ""} ${item.notification_provenance?.clause_ref || ""}`.toLowerCase().includes(search.toLowerCase().trim());
  }), [report.items, filter, search, hardFailures]);

  useEffect(() => { try { setDense(localStorage.getItem("bidsense-density") === "compact"); } catch {} }, []);
  const toggleDensity = useCallback(() => setDense(value => { try { localStorage.setItem("bidsense-density", value ? "comfortable" : "compact"); } catch {} return !value; }), []);
  async function recheck() { if (!onRefresh) return; setRechecking(true); setError(""); try { await onRefresh(true); } catch (e) { setError(e instanceof Error ? e.message : "Could not recheck this bid."); } finally { setRechecking(false); } }
  const exportAs = useCallback(async (fmt: "pdf" | "docx") => { setExporting(fmt); setError(""); try { await api.exportGapReport(report.tender_id, report.vendor_id, fmt); } catch (e) { setError(e instanceof Error ? e.message : "Could not export this report."); } finally { setExporting(null); } }, [report.tender_id, report.vendor_id]);

  useEffect(() => {
    const commands: Command[] = [
      { id: "report-requirements", label: "Find a requirement", detail: "Search this bid's requirements and clauses", group: "This report", run: () => { setTab("requirements"); setTimeout(() => searchInput.current?.focus(), 50); } },
      { id: "report-density", label: "Toggle row density", detail: "Comfortable or compact", group: "This report", run: toggleDensity },
      { id: "report-pdf", label: "Export this report as PDF", detail: report.vendor_name || report.vendor_id, group: "This report", run: () => { if (!exporting) void exportAs("pdf"); } },
      ...report.action_list.map((action, i) => ({ id: `report-action-${i}`, label: action.action, detail: `This bid · ${action.clause_ref ? `clause ${action.clause_ref}` : "review evidence"}`, group: "Bid actions", run: () => { setTab("requirements"); setFilter("all"); setSearch(action.requirement); setFocusRow(action.requirement); } })),
    ];
    const publish = () => window.dispatchEvent(new CustomEvent(PALETTE_EVENT, { detail: commands }));
    publish(); window.addEventListener("bidsense:request-commands", publish);
    return () => { window.removeEventListener("bidsense:request-commands", publish); window.dispatchEvent(new CustomEvent(PALETTE_EVENT, { detail: [] })); };
  }, [report.action_list, report.vendor_id, report.vendor_name, toggleDensity, exportAs, exporting]);

  const openCitation = useCallback((side: "notification" | "bid", item: GapItem) => {
    const p = side === "notification" ? item.notification_provenance : item.submission_provenance;
    setCitation({ contentHash: side === "notification" ? sources.notification : sources.bid, page: p?.source_page ?? null, snippet: p?.source_snippet ?? null, clauseRef: p?.clause_ref ?? null, documentLabel: side === "notification" ? report.tender_id : report.vendor_name || report.vendor_id });
  }, [sources, report.tender_id, report.vendor_name, report.vendor_id]);
  const openActionCitation = useCallback((action: ActionItem) => { const item = report.items.find(i => i.requirement === action.requirement); if (item) openCitation("notification", item); }, [report.items, openCitation]);
  const title = verdict === "not_checked" ? "A closer look is needed." : counts.blocking ? "Some criteria aren’t met." : counts.missing ? "Put the final pieces in place." : "The details deserve a check.";

  return <div className="review-workspace" data-density={dense ? "compact" : "comfortable"}>
    <StalenessBanner staleness={staleness} onRecheck={recheck} rechecking={rechecking} />
    {!data.data_quality.ok && <details className="review-audit"><summary><span className="marker marker-check" aria-hidden /><span>Extraction needs review <span className="audit-summary-note">— verify the source before relying on this report</span></span><span className="ref">View findings +</span></summary><DataQualityBanner quality={data.data_quality}/><p className="ref mt-3">{Object.entries(data.data_quality.providers ?? {}).map(([source, provider]) => `${source}: ${provider || "not recorded"}`).join(" · ")}</p></details>}
    {error && <p role="alert" className="review-error">{error}</p>}
    <section className="review-intro" aria-labelledby="verdict-heading">
      <div className="review-intro-copy"><p className="eyebrow"><span className={`marker ${counts.blocking ? "marker-fail" : "marker-check"}`} aria-hidden />{counts.blocking ? "Qualification criteria unmet" : verdict === "not_checked" ? "Not yet assessable" : "Your bid, under review"}</p><h2 id="verdict-heading" className={counts.blocking ? "has-hard-fail" : ""}>{title}</h2><p>{counts.blocking ? "These eligibility gaps cannot be resolved by attaching another document. Check the cited criteria before proceeding." : counts.missing ? `${counts.missing} outstanding requirements, with the source beside every finding. Work through the details below before submitting.` : "No automatic hard failure is shown here. Signing, format and uncertain evidence still need your own review."}</p><div className="review-export"><button className="btn btn-primary" onClick={() => void exportAs("pdf")} disabled={exporting !== null}>{exporting === "pdf" ? "Preparing PDF…" : "Export report"}<span aria-hidden>↗</span></button><button className="btn btn-subtle" onClick={() => void exportAs("docx")} disabled={exporting !== null}>{exporting === "docx" ? "Preparing…" : "Word document"}</button></div></div>
      <div className="review-completion"><CompletionMeter completion={completion} verdict={verdict}/></div>
    </section>
    <section className="review-register" aria-label="Review requirements">
      <div className="review-tabs" role="tablist" aria-label="Report view"><button role="tab" id="requirements-tab" aria-controls="requirements-panel" aria-selected={tab === "requirements"} onClick={() => setTab("requirements")}>Requirement register <span>{report.items.length.toString().padStart(2, "0")}</span></button><button role="tab" id="actions-tab" aria-controls="actions-panel" aria-selected={tab === "actions"} onClick={() => setTab("actions")}>Action list <span>{report.action_list.length.toString().padStart(2, "0")}</span></button><div className="register-tools"><button className="density-control" aria-pressed={dense} onClick={toggleDensity} title="Toggle row density"><svg viewBox="0 0 16 16" aria-hidden><path d={dense ? "M2 3h12M2 6h12M2 9h12M2 12h12" : "M2 4h12M2 11h12"}/></svg>{dense ? "Compact" : "Comfortable"}</button></div></div>
      {tab === "requirements" ? <div role="tabpanel" id="requirements-panel" aria-labelledby="requirements-tab">
        <div className="register-toolbar"><div className="register-filters" aria-label="Filter by requirement state">{FILTERS.filter(f => f === "all" || counts[f] > 0).map(f => <button key={f} aria-pressed={filter === f} className={filter === f ? "selected" : ""} onClick={() => setFilter(f)}>{LABELS[f]}<span>{counts[f]}</span></button>)}</div><label className="register-search"><span aria-hidden>⌕</span><input ref={searchInput} aria-label="Find a requirement or clause" placeholder="Find a requirement…" value={search} onChange={e => setSearch(e.target.value)}/>{search && <button aria-label="Clear requirement search" onClick={() => { setSearch(""); setFocusRow(null); }}>×</button>}</label></div>
        <div className="register-columns" aria-hidden><span>Ref.</span><span>Requirement / evidence</span><span>State</span><span/></div>
        <div className="requirement-list">{visible.map(item => <RequirementRow key={report.items.indexOf(item)} item={item} index={report.items.indexOf(item) + 1} blocking={hardFailures.has(item.requirement)} onCite={openCitation} focused={focusRow === item.requirement} />)}</div>
        {!visible.length && <div className="register-empty"><svg viewBox="0 0 48 48" aria-hidden><path d="M12 5h17l8 8v30H12zM29 5v9h8M18 23h13M18 29h9"/></svg><h3>No matching requirements.</h3><p>Try a different clause, document name, or state.</p><button className="btn btn-subtle" onClick={() => { setSearch(""); setFilter("all"); }}>Show all requirements</button></div>}
        <div className="register-footnote"><span className="ref">{visible.length} of {report.items.length} requirements</span><span>Hover a citation to read. Expand a row to compare.</span></div>
      </div> : <div role="tabpanel" id="actions-panel" aria-labelledby="actions-tab" className="review-actions"><ActionList actions={report.action_list} onCite={openActionCitation}/></div>}
    </section>
    <CitationViewer target={citation} onClose={() => setCitation(null)}/>
  </div>;
}

function RequirementRow({ item, index, blocking, onCite, focused }: { item: GapItem; index: number; blocking: boolean; focused: boolean; onCite: (side: "notification" | "bid", item: GapItem) => void }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  useEffect(() => { if (focused) setOpen(true); }, [focused]);
  return <article className={`requirement-row ${open ? "expanded" : ""}`} data-status={item.status}>
    <div className="requirement-summary"><span className="row-number ref">{String(index).padStart(2, "0")}</span><div className="requirement-name"><button className="row-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(v => !v)}>{item.requirement.replace(/^Submit /, "")}</button><div className="row-subline"><span>{KIND_LABEL[item.kind]}</span><span className="row-separator">/</span><Cited provenance={item.notification_provenance} onOpen={() => onCite("notification", item)}><span>Source</span></Cited>{item.conditional_on && <span className="conditional-note">Conditional</span>}</div></div><StateTag status={item.status} blocking={blocking}/><button className="expand-button" aria-label={`${open ? "Collapse" : "Expand"} ${item.requirement}`} aria-expanded={open} aria-controls={id} onClick={() => setOpen(v => !v)}><svg viewBox="0 0 16 16" aria-hidden><path d="m4 6 4 4 4-4"/></svg></button></div>
    <div id={id} className="row-reveal" ref={element => { if (element) element.inert = !open; }} aria-hidden={!open}><div><div className="row-evidence"><p className="evidence-explanation">{item.explanation}</p><div className="evidence-comparison"><section><p className="label">In the tender</p><Cited provenance={item.notification_provenance} onOpen={() => onCite("notification", item)}><Amount value={item.required_value || item.requirement}/></Cited>{item.notification_provenance?.source_snippet && <blockquote>{item.notification_provenance.source_snippet}</blockquote>}</section><section><p className="label">In your bid</p>{item.found_value ? <Cited provenance={item.submission_provenance} onOpen={() => onCite("bid", item)}><Amount value={item.found_value}/></Cited> : <p className="text-fg-muted">{REVIEW.includes(item.status) ? "Needs a direct check of the bid." : "No matching evidence was recorded."}</p>}{item.submission_provenance?.source_snippet && <blockquote>{item.submission_provenance.source_snippet}</blockquote>}</section></div>{item.conditional_on && <p className="conditional-explanation">Applies only if: {item.conditional_on}</p>}<div className="evidence-footer"><span className="evidence-signal" aria-hidden><i/><i/><i/><i/><i/></span><span>{item.notification_provenance?.source_page ? `Source linked · page ${item.notification_provenance.source_page}` : "Source page not recorded"}</span>{item.notification_provenance?.extraction_confidence != null && <span>Extraction confidence {Math.round(item.notification_provenance.extraction_confidence * 100)}%</span>}{item.match_method && <span>Match method: {item.match_method}</span>}</div></div></div></div>
  </article>;
}
