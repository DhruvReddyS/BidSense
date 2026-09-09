"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Level1Result, PerformanceSummary, PoolQueryResponse, ReviewLevel1Response, ReviewLevel2Response, VendorSubmissionSummary } from "@/lib/types";
import { PALETTE_EVENT, type Command } from "./CommandPalette";
import { DocumentProcess } from "./DocumentProcess";
import { BulkBidUpload } from "./BulkBidUpload";

type Filter = "all" | "pending" | "eliminated" | "debarred";
const FILTER_LABEL: Record<Filter, string> = {
  all: "All submissions",
  pending: "Cleared Level 1",
  eliminated: "Eliminated",
  debarred: "Debarment flagged",
};

export function ReviewerWorkspace({
  tenderId,
  tenderTitle,
  initialBids,
}: {
  tenderId: string;
  tenderTitle: string;
  initialBids: VendorSubmissionSummary[];
}) {
  const [results, setResults] = useState<Level1Result[]>(() => initialBids.map(bid => ({
    vendor_id: bid.vendor_id,
    vendor_name: bid.vendor_name,
    status: bid.status === "eliminated" ? "eliminated" : "pending",
    elimination_reason: bid.elimination_reason,
    clause_ref: null,
    source_page: null,
    is_blacklisted: bid.is_blacklisted,
  })));
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [ran, setRan] = useState(initialBids.some(bid => bid.status === "eliminated"));
  const [error, setError] = useState("");
  const [targetCount, setTargetCount] = useState(Math.min(3, Math.max(1, initialBids.filter(bid => bid.status !== "eliminated").length)));
  const [factors, setFactors] = useState<Record<string, boolean>>({ experience: true, project_scale: true, technical_approach: true, pricing: false });
  const [shortlist, setShortlist] = useState<ReviewLevel2Response | null>(null);
  const [shortlisting, setShortlisting] = useState(false);
  const [question, setQuestion] = useState("");
  const [queryResult, setQueryResult] = useState<PoolQueryResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [performance, setPerformance] = useState<PerformanceSummary | null>(null);
  const search = useRef<HTMLInputElement>(null);

  const counts = useMemo(() => ({
    all: results.length,
    pending: results.filter(result => result.status === "pending").length,
    eliminated: results.filter(result => result.status === "eliminated").length,
    debarred: results.filter(result => result.is_blacklisted).length,
  }), [results]);
  const visible = useMemo(() => results.filter(result => {
    const inFilter = filter === "all" || (filter === "debarred" ? result.is_blacklisted : result.status === filter);
    const needle = query.trim().toLocaleLowerCase();
    return inFilter && (!needle || `${result.vendor_name} ${result.vendor_id} ${result.elimination_reason ?? ""} ${result.clause_ref ?? ""}`.toLocaleLowerCase().includes(needle));
  }), [results, filter, query]);

  const runEvaluation = useCallback(async () => {
    setRunning(true); setError("");
    try {
      const [response]: [ReviewLevel1Response, unknown] = await Promise.all([
        api.reviewLevel1(tenderId),
        new Promise(resolve => window.setTimeout(resolve, 900)),
      ]);
      const blacklist = new Map(initialBids.map(bid => [bid.vendor_id, bid.is_blacklisted]));
      setResults(response.results.map(result => ({ ...result, is_blacklisted: blacklist.get(result.vendor_id) ?? false })));
      setRan(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Level 1 evaluation could not be completed.");
    } finally { setRunning(false); }
  }, [tenderId, initialBids]);

  const runShortlist = useCallback(async () => {
    setShortlisting(true); setError("");
    try {
      const weights = Object.fromEntries(Object.entries(factors).filter(([, enabled]) => enabled).map(([key]) => [key, 1]));
      const [response] = await Promise.all([api.reviewLevel2(tenderId, targetCount, weights), new Promise(resolve => window.setTimeout(resolve, 900))]);
      setShortlist(response);
    } catch (e) { setError(e instanceof ApiError ? e.message : "The qualified pool could not be prepared."); }
    finally { setShortlisting(false); }
  }, [factors, targetCount, tenderId]);

  const askPool = useCallback(async () => {
    if (question.trim().length < 3) return;
    setAsking(true); setError("");
    try { setQueryResult(await api.queryPool(tenderId, question.trim())); }
    catch (e) { setError(e instanceof ApiError ? e.message : "The vendor pool could not be queried."); }
    finally { setAsking(false); }
  }, [question, tenderId]);

  useEffect(() => {
    api.reviewPerformance().then(setPerformance).catch(() => undefined);
  }, []);

  useEffect(() => {
    const commands: Command[] = [
      { id: "review-run", label: ran ? "Run Level 1 again" : "Run Level 1 elimination", detail: "Apply mandatory rules to every submission", group: "Company review", run: () => void runEvaluation() },
      { id: "review-find", label: "Find a bidder", detail: "Search the Level 1 register", group: "Company review", run: () => search.current?.focus() },
      ...(["pending", "eliminated", "debarred"] as Filter[]).map(key => ({ id: `review-${key}`, label: `Show ${FILTER_LABEL[key].toLowerCase()}`, detail: `${counts[key]} submissions`, group: "Company review", run: () => setFilter(key) })),
    ];
    const publish = () => window.dispatchEvent(new CustomEvent(PALETTE_EVENT, { detail: commands }));
    publish(); window.addEventListener("bidsense:request-commands", publish);
    return () => { window.removeEventListener("bidsense:request-commands", publish); window.dispatchEvent(new CustomEvent(PALETTE_EVENT, { detail: [] })); };
  }, [counts, ran, runEvaluation]);

  return <div className="reviewer-workspace">
    <nav className="reviewer-steps" aria-label="Company review stages"><a href="#level-1"><b>01</b><span>Eliminate</span><small>Mandatory rules</small></a><a href="#level-2"><b>02</b><span>Shortlist</span><small>Qualified pool</small></a><a href="#level-3"><b>03</b><span>Interrogate</span><small>Evidence assistant</small></a></nav>
    <section className="reviewer-hero">
      <div>
        <p className="eyebrow">Company review / Level 1</p>
        <h1>Elimination,<br/>with a reason.</h1>
        <p><span className="reviewer-tender-title">{tenderTitle}</span> Mandatory eligibility rules are applied deterministically across every submission. No ranking and no LLM judgment enters this decision.</p>
        <div className="reviewer-actions">
          <button className="btn btn-primary" disabled={running || !initialBids.length} onClick={() => void runEvaluation()}>{running ? "Evaluating…" : ran ? "Run evaluation again" : "Run Level 1 evaluation"}</button>
          <button className="btn btn-subtle" disabled={exporting} onClick={async () => { setExporting(true); setError(""); try { await api.exportCommitteeReport(tenderId); } catch (e) { setError(e instanceof Error ? e.message : "Committee report could not be exported."); } finally { setExporting(false); } }}>{exporting ? "Preparing report…" : "Committee PDF"}</button>
          <Link className="btn btn-subtle" href={`/tenders/${encodeURIComponent(tenderId)}`}>Tender workspace</Link>
        </div>
      </div>
      <aside className="reviewer-principle"><span className="ref">DECISION RULE / 01</span><p>Only a failed mandatory criterion can eliminate a bidder.</p><small>Every eliminated row keeps the exact reason and source reference for committee review.</small></aside>
    </section>

    {running && <div className="reviewer-processing"><DocumentProcess label="Checking every submission" detail="Comparing extracted facts with mandatory tender clauses" /></div>}
    {error && <p className="review-error" role="alert">{error}</p>}
    <BulkBidUpload tenderId={tenderId} />

    {performance && <section className="performance-pulse" aria-label="Recent processing performance">
      <div><p className="eyebrow">Operational pulse</p><h2>Fast is useful.<br/>Visible is trustworthy.</h2><p>Decision-ready latency is measured separately from background evidence indexing. Figures use the latest {performance.completed_jobs} completed jobs.</p></div>
      <dl>
        <ReviewMetric label="Median" value={performance.median_seconds ?? 0} note="seconds to structured result" />
        <ReviewMetric label="P95" value={performance.p95_seconds ?? 0} note="slow-tail latency, seconds" />
        <ReviewMetric label="Cache reuse" value={performance.cache_reuse_percent} note="percent skipping model calls" />
        <ReviewMetric label="Throughput" value={performance.pages_per_second ?? 0} note="pages per second" />
      </dl>
    </section>}

    <section id="level-1" className="reviewer-register" aria-labelledby="level1-register-title">
      <div className="reviewer-register-head"><div><p className="eyebrow">Evaluation register</p><h2 id="level1-register-title">Level 1 outcomes</h2></div><p>{ran ? "Evaluation recorded" : "Ready to evaluate"}<span className={`marker ${ran ? "marker-met" : "marker-outstanding"}`} aria-hidden /></p></div>
      <dl className="reviewer-metrics">
        <ReviewMetric label="Submissions" value={counts.all} note="in this tender" />
        <ReviewMetric label="Cleared Level 1" value={counts.pending} note="awaiting shortlist review" />
        <ReviewMetric label="Eliminated" value={counts.eliminated} note="mandatory rule failed" bad={counts.eliminated > 0} />
        <ReviewMetric label="Debarment flags" value={counts.debarred} note="reviewer or bid-declared" warn={counts.debarred > 0} />
      </dl>
      <div className="reviewer-toolbar"><div className="register-filters">{(["all", "pending", "eliminated", "debarred"] as Filter[]).map(key => <button key={key} className={filter === key ? "selected" : ""} aria-pressed={filter === key} onClick={() => setFilter(key)}>{FILTER_LABEL[key]}<span>{counts[key]}</span></button>)}</div><label className="register-search"><span aria-hidden>⌕</span><input ref={search} value={query} onChange={e => setQuery(e.target.value)} aria-label="Find a bidder, reason, or clause" placeholder="Find bidder or clause…"/></label></div>
      <div className="reviewer-columns" aria-hidden><span>Bidder</span><span>Level 1</span><span>Decision record</span><span/></div>
      <div className="reviewer-results">{visible.map((result, index) => <article className="reviewer-row" key={result.vendor_id}>
        <div className="reviewer-vendor"><span className="ref">{String(results.indexOf(result) + 1).padStart(2, "0")}</span><div><h3>{result.vendor_name || result.vendor_id}</h3><p className="ref">{result.vendor_id}</p></div></div>
        <div><span className={`reviewer-state ${result.status === "eliminated" ? "is-eliminated" : "is-cleared"}`}><i aria-hidden />{result.status === "eliminated" ? "Eliminated" : "Cleared Level 1"}</span>{result.is_blacklisted && <span className="reviewer-debarred">Debarment flagged</span>}</div>
        <div className="reviewer-reason">{result.elimination_reason ? <><p>{result.elimination_reason}</p><span className="ref">{result.clause_ref ? `Clause ${result.clause_ref}` : "Reason recorded"}{result.source_page ? ` · page ${result.source_page}` : ""}</span></> : <p className="text-fg-muted">No mandatory failure recorded.</p>}</div>
        <Link className="reviewer-evidence" href={`/tenders/${encodeURIComponent(tenderId)}/bids/${encodeURIComponent(result.vendor_id)}`}>Open evidence <span aria-hidden>↗</span></Link>
      </article>)}</div>
      {!visible.length && <div className="register-empty"><h3>No matching submissions.</h3><p>Clear the search or choose another decision state.</p><button className="btn btn-subtle" onClick={() => { setFilter("all"); setQuery(""); }}>Show all submissions</button></div>}
      <footer className="reviewer-foot"><span className="ref">{visible.length} of {results.length} submissions</span><span>Final selection remains with the evaluation committee.</span></footer>
    </section>

    <section id="level-2" className="review-stage">
      <div className="review-stage-intro"><p className="eyebrow">Level 2 / Qualified pool</p><h2>Reduce the room,<br/>without inventing a rank.</h2><p>Choose the evidence that matters for this review. BidSense forms a manageable pool from recorded facts; the candidates are deliberately shown alphabetically.</p></div>
      <div className="shortlist-control">
        <label className="target-control"><span>Target pool size</span><input type="number" min={1} max={Math.max(1, counts.pending)} value={targetCount} onChange={event => setTargetCount(Math.max(1, Number(event.target.value)))} /><small>From {counts.pending} Level 1-cleared submissions</small></label>
        <fieldset><legend>Factors to consider</legend>{Object.entries({ experience: "Relevant experience", project_scale: "Past project scale", technical_approach: "Technical approach", pricing: "Pricing competitiveness" }).map(([key, label]) => <label key={key}><input type="checkbox" checked={factors[key]} onChange={event => setFactors(current => ({ ...current, [key]: event.target.checked }))}/><span>{label}</span></label>)}</fieldset>
        <button className="btn btn-primary" disabled={shortlisting || counts.pending === 0 || !Object.values(factors).some(Boolean)} onClick={() => void runShortlist()}>{shortlisting ? "Building qualified pool…" : "Prepare qualified pool"}</button>
        <p className="decision-caveat">No rank or winner is produced. Membership is grounded in the factors selected above.</p>
      </div>
      {shortlisting && <div className="stage-processing"><DocumentProcess label="Forming the qualified pool" detail="Reading comparable facts without scoring prose fluency" /></div>}
      {shortlist && <div className="shortlist-result"><div className="shortlist-result-head"><span>{shortlist.shortlisted} candidates</span><p>{shortlist.caveat}</p></div>{shortlist.candidates.map(candidate => <article key={candidate.vendor_id}><div><p className="eyebrow">Qualified candidate</p><h3>{candidate.vendor_name}</h3><span className="ref">{candidate.vendor_id}</span></div><p>{candidate.summary}</p><ul>{candidate.evidence.map(item => <li key={item}>{item}</li>)}</ul></article>)}</div>}
    </section>

    <section id="level-3" className="review-stage query-stage">
      <div className="review-stage-intro"><p className="eyebrow">Level 3 / Evidence assistant</p><h2>Ask across<br/>the whole record.</h2><p>Structured questions use stored facts. Narrative questions use scoped retrieval. Audit questions preserve eliminated bids and their reasons.</p></div>
      <div className="pool-query"><div className="query-suggestions">{["Why was Sahu Brothers Engineering Works eliminated?", "Compare shortlisted vendors on experience and project value", "Which approach discusses execution methodology?"].map(prompt => <button key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>)}</div><label><span className="sr-only">Question about vendor pool</span><textarea value={question} onChange={event => setQuestion(event.target.value)} placeholder="Ask about status, experience, project scale, pricing or technical approach…" /></label><button className="btn btn-primary" disabled={asking || question.trim().length < 3} onClick={() => void askPool()}>{asking ? "Routing question…" : "Ask the evidence"}</button></div>
      {asking && <div className="stage-processing"><DocumentProcess label="Routing the question" detail="Choosing structured facts, narrative evidence, or both" /></div>}
      {queryResult && <article className="query-answer" aria-live="polite"><header><span className="eyebrow">{queryResult.route} route</span><small>Assistance, not adjudication</small></header><p>{queryResult.answer}</p>{queryResult.citations.length > 0 && <details><summary>Evidence used · {queryResult.citations.length}</summary>{queryResult.citations.map((citation, index) => <blockquote key={`${citation.vendor_id}-${index}`}><span className="ref">{citation.vendor_id || citation.source_file || "Tender record"}{citation.source_page ? ` · page ${citation.source_page}` : ""}{citation.clause_ref ? ` · clause ${citation.clause_ref}` : ""}</span>{citation.snippet}</blockquote>)}</details>}<footer>{queryResult.caveat}</footer></article>}
    </section>
  </div>;
}

function ReviewMetric({ label, value, note, bad, warn }: { label: string; value: number; note: string; bad?: boolean; warn?: boolean }) {
  return <div><dt>{label}</dt><dd className={bad ? "is-bad" : warn ? "is-warn" : ""}>{value}</dd><p>{note}</p></div>;
}
