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
}

export interface GapReport {
  tender_id: string;
  vendor_id: string;
  vendor_name: string | null;
  items: GapItem[];
  score_preview: ScorePreview;
  action_list: ActionItem[];
}

export interface GapReportResponse {
  report: GapReport;
  verdict: Verdict;
  counts: Record<string, number>;
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

export interface GroundedAnswer {
  question: string;
  answer: string;
  citations: Citation[];
  retrieved: Citation[];
  invented_citations: number[];
  answered: boolean;
}

export interface AskResponse {
  answer: GroundedAnswer;
  grounded: boolean;
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

export interface JobAccepted {
  job_id: string;
  status: string;
  file_name: string;
  poll_url: string;
}

export interface JobStatus {
  job_id: string;
  kind: "notification" | "submission";
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
