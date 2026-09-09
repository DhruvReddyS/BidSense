// Mirrors the backend Pydantic models. Kept narrow on purpose: the UI reads
// only what it renders, so a backend field rename fails at the point of use
// rather than silently rendering blank.

export type CheckStatus =
  | "match"
  | "partial"
  | "missing"
  | "manual_check"
  | "not_assessable";

export type Severity = "disqualifying" | "action_needed" | "review" | "info";

export type Verdict =
  | "compliant"
  | "needs_review"
  | "not_compliant"
  // Nothing could be checked: extraction produced no requirements. Distinct
  // from "compliant", which would otherwise be reported on an empty run.
  | "not_checked";

export interface Provenance {
  clause_ref: string | null;
  source_page: number | null;
  source_snippet: string | null;
  extraction_confidence: number | null;
}

export interface GapItem {
  conditional_on: string | null;
  requirement: string;
  kind: "document" | "numeric" | "boolean" | "format_rule";
  status: CheckStatus;
  severity: Severity;
  required_value: string | null;
  found_value: string | null;
  explanation: string;
  is_mandatory: boolean;
  match_method: string | null;
  match_score: number | null;
  notification_provenance: Provenance | null;
  submission_provenance: Provenance | null;
}

export interface ScorePreviewItem {
  factor: string;
  weightage: number;
  status: CheckStatus;
  provenance: Provenance | null;
}

export interface ScorePreview {
  available: boolean;
  items: ScorePreviewItem[];
  total_weightage: number | null;
  unavailable_reason: string | null;
}

export type ActionGroup = "hard_fail" | "upload" | "clarify" | "verify";

export interface ActionItem {
  action: string;
  severity: Severity;
  group: ActionGroup;
  requirement: string;
  clause_ref: string | null;
  /** Non-null when the item binds only some bidders (a JV agreement, an MSME
   *  concession). The UI groups these apart so a sole proprietor is not handed
   *  six to-dos they neither have nor need. */
  applies_only_if: string | null;
}

export interface GapReport {
  tender_id: string;
  vendor_id: string;
  vendor_name: string | null;
  items: GapItem[];
  score_preview: ScorePreview;
  action_list: ActionItem[];
}

/** A count of mandatory requirements met. Explicitly NOT a score: `caveat`
 *  travels with the number and must be rendered beside it, never dropped. */
export interface Completion {
  satisfied: number;
  total: number;
  undetermined: number;
  label: string;
  caveat: string;
}

export interface ValidationFinding {
  field: string;
  severity: "error" | "warning";
  message: string;
  value: string | null;
  affects_confidence: boolean;
  source: "notification" | "bid";
}

/** How far the figures can be trusted. Separate from the verdict: one answers
 *  "does this bid meet the tender", the other "how good was our reading". */
export interface DataQuality {
  providers?: Record<string, string | null>;
  ok: boolean;
  banner: string | null;
  findings: ValidationFinding[];
}

/** Section 5.6 — the tender moved, this report has not. */
export interface Staleness {
  stale: boolean;
  banner: string | null;
  corrigendum_id: string | null;
  issued_date: string | null;
  changed_fields: string[];
  last_checked_at: string | null;
}

/** Content hashes for opening a citation on its source page. Null when the
 *  document predates the store — the UI then shows page and clause without a
 *  page image rather than a broken link. */
export interface SourceDocuments {
  notification: string | null;
  bid: string | null;
}

export interface GapReportResponse {
  report: GapReport;
  verdict: Verdict;
  counts: Record<string, number>;
  staleness: Staleness;
  data_quality: DataQuality;
  completion: Completion;
  action_counts: { blocking: number; to_check: number; conditional: number };
  sources: SourceDocuments;
}

export interface ChangedField {
  field_path: string;
  label: string;
  old_value: string | null;
  new_value: string | null;
  clause_ref: string | null;
  source_page: number | null;
}

export interface Corrigendum {
  corrigendum_id: string;
  parent_tender_id: string;
  issued_date: string | null;
  source_file: string | null;
  uploaded_at: string;
  changed_fields: ChangedField[];
}

export interface Citation {
  index: number;
  text: string;
  source_file: string | null;
  source_page: number | null;
  clause_ref: string | null;
  doc_kind: string;
  score: number;
  label: string;
}

/** How well retrieval matched the question. `none` means the model was never
 *  called: handing it loosely related passages invites an answer stitched from
 *  whatever it was given, and every citation in that answer would be real. */
export type Confidence = "high" | "low" | "none";

export interface GroundedAnswer {
  provider?: string | null;
  question: string;
  answer: string;
  citations: Citation[];
  retrieved: Citation[];
  invented_citations: number[];
  answered: boolean;
  confidence: Confidence;
  caveat: string | null;
}

export interface AskResponse {
  data_quality?: DataQuality | null;
  answer: GroundedAnswer;
  grounded: boolean;
  confidence: Confidence;
  sources: SourceDocuments;
}

export interface NotificationSummary {
  tender_id: string;
  title: string;
  issuing_authority: string | null;
  sector: string | null;
  submission_deadline: string | null;
  emd_amount_inr: string | null;
  eligibility_count: number;
  document_count: number;
  submission_count: number;
  created_at: string;
}

export interface VendorSubmissionSummary {
  vendor_id: string;
  vendor_name: string;
  status: string;
  is_blacklisted: boolean;
  elimination_reason: string | null;
}

export interface Level1Result {
  vendor_id: string;
  vendor_name: string;
  status: "eliminated" | "pending";
  elimination_reason: string | null;
  clause_ref: string | null;
  source_page: number | null;
  /** Present on the read model; merged locally when the evaluation response omits it. */
  is_blacklisted?: boolean;
}

export interface ReviewLevel1Response {
  tender_id: string;
  total: number;
  eliminated: number;
  pending: number;
  results: Level1Result[];
}

export interface PerformanceSummary {
  completed_jobs: number;
  median_seconds: number | null;
  p95_seconds: number | null;
  cache_reuse_percent: number;
  pages_per_second: number | null;
}

export interface ShortlistCandidate {
  vendor_id: string;
  vendor_name: string;
  status: "shortlisted";
  summary: string;
  evidence: string[];
}

export interface ReviewLevel2Response {
  tender_id: string;
  eligible: number;
  shortlisted: number;
  requested: number;
  factors: string[];
  candidates: ShortlistCandidate[];
  caveat: string;
}

export interface PoolQueryResponse {
  route: "structured" | "comparative" | "qualitative" | "hybrid" | "audit";
  answer: string;
  citations: { vendor_id: string | null; source_file: string | null; source_page: number | null; clause_ref: string | null; snippet: string }[];
  caveat: string;
}

export interface JobAccepted {
  job_id: string;
  status: string;
  file_name: string;
  poll_url: string;
}

export interface JobStatus {
  job_id: string;
  kind: "notification" | "submission" | "corrigendum";
  status: "queued" | "running" | "succeeded" | "partial" | "failed";
  stage: string | null;
  progress: number;
  steps_done: number;
  steps_total: number | null;
  file_name: string;
  tender_id: string | null;
  vendor_id: string | null;
  result: IngestResponse | null;
  error: string | null;
  seconds_elapsed: number | null;
}

export interface Page {
  total: number;
  limit: number;
  offset: number;
}

export interface NotificationList {
  items: NotificationSummary[];
  page: Page;
}

export interface MoneyAmount {
  raw_text: string | null;
  amount_inr: string | null;
}

export interface EligibilityCriterion {
  criterion: string;
  type: "numeric" | "boolean" | "document";
  threshold_raw: string | null;
  threshold_amount: MoneyAmount | null;
  threshold_number: number | null;
  unit: string | null;
  is_mandatory: boolean;
  provenance: Provenance;
}

export interface MandatoryDocument {
  doc_name: string;
  aliases: string[];
  provenance: Provenance;
}

/** Full extracted notification — the Section 6 schema as the API returns it. */
export interface TenderDetail {
  tender_id: string;
  title: string;
  issuing_authority: string | null;
  sector: string | null;
  submission_deadline: string | null;
  pre_bid_query_deadline: string | null;
  eligibility_criteria: EligibilityCriterion[];
  mandatory_documents: MandatoryDocument[];
  evaluation_criteria: { factor: string; weightage_if_stated: number | null }[];
  technical_requirements: { requirement: string; provenance: Provenance }[];
  submission_format_rules: { rule: string; provenance: Provenance }[];
  emd_amount: MoneyAmount | null;
  contract_value_estimate: MoneyAmount | null;
}

export interface IngestResponse {
  ok: boolean;
  file_name: string;
  identifier: string | null;
  pages: number;
  ocr_pages: number;
  chunks_indexed: number;
  parse_warnings: string[];
  extraction_errors: string[];
  seconds: number;
  /** Which provider and model produced it. A run served by the local fallback
   *  is a different run, and nothing else in the report says which. */
  extracted_by?: string | null;
  from_cache?: boolean;
  content_hash?: string | null;
  timing?: { parse: number; extract: number; persist: number; index: number };
  node_timings?: Record<string, number>;
  index_state?: "pending" | "ready" | "failed";
  index_error?: string | null;
  validation_summary?: string | null;
  validation?: { field: string; severity: string; message: string }[];
}

export interface Health {
  status: string;
  postgres: boolean;
  qdrant: boolean;
  embeddings: boolean;
  llm_provider: string;
  llm_reachable: boolean;
  ocr_available: boolean;
  ocr_missing: string[];
}
