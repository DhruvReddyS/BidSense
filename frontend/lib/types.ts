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

export type Verdict = "compliant" | "needs_review" | "not_compliant";

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

export interface ActionItem {
  action: string;
  severity: Severity;
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
