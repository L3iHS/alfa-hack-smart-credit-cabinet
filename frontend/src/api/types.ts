export type ProductCode = "working_capital" | "equipment";
export interface User {
  id: string;
  role: "client" | "staff";
  company_id: string | null;
  display_name: string;
}
export interface Company {
  id: string;
  inn: string;
  name: string;
  industry: string;
  registered_at: string;
}
export interface Product {
  code: ProductCode;
  name: string;
  purpose_description: string;
  min_amount_kopecks: number;
  max_amount_kopecks: number;
  min_term_months: number;
  max_term_months: number;
  annual_rate_bps: number;
  required_document_types: ("financial_statement" | "equipment_invoice")[];
}
export interface Catalog {
  catalog_version: string;
  items: Product[];
}
export interface DraftFields {
  product_code: ProductCode;
  purpose: string | null;
  description: string | null;
  amount_kopecks: number | null;
  term_months: number | null;
  period_start: string | null;
  period_end: string | null;
  revenue_kopecks: number | null;
  operating_expenses_kopecks: number | null;
  existing_debt_payments_kopecks: number | null;
}
export interface Application extends DraftFields {
  id: string;
  version: number;
  status: ApplicationStatus;
  updated_at: string;
  catalog_version: string;
  public_reasons: string[];
  processing_status: ProcessingStatus | null;
  information_requests: InformationRequest[];
  offers: Offer[];
  available_actions: Action[];
}
export interface HistoryEvent {
  id: string;
  event_type: string;
  actor_type: "user" | "system";
  actor_id: string | null;
  revision_id: string | null;
  processing_run_id: string | null;
  created_at: string;
  application_version: number;
}
export interface PageResult<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface FormValues {
  product_code: ProductCode;
  purpose: string;
  description: string;
  amount_kopecks: string;
  term_months: string;
  period_start: string;
  period_end: string;
  revenue_kopecks: string;
  operating_expenses_kopecks: string;
  existing_debt_payments_kopecks: string;
}
export interface Recovery {
  owner: string;
  path: string;
  values: FormValues;
  application: Application | null;
}

export interface CsrfBinding {
  csrf_token: string;
  user_id: string | null;
}

export type DocumentType = "financial_statement" | "equipment_invoice";
export interface ApplicationDocument {
  id: string;
  document_type: DocumentType;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}
export interface SubmissionPolicy {
  consent_version: string;
  data_confirmation_text: string;
  bki_consent_text: string;
  max_file_size_bytes: number;
  accepted_content_types: string[];
}
export interface SubmitBody {
  expected_version: number;
  data_confirmed: boolean;
  bki_consent: boolean;
  consent_version: string;
}
export interface SubmitResult {
  application_id: string;
  version: number;
  status: "submitted";
  revision_id: string;
  processing_run_id: string;
}

export type ApplicationStatus =
  | "draft"
  | "submitted"
  | "processing"
  | "needs_info"
  | "manual_review"
  | "counteroffer"
  | "approved"
  | "rejected";
export type ProcessingStatus =
  "pending" | "running" | "succeeded" | "failed" | "interrupted";
export type Action =
  | "edit_draft"
  | "upload_document"
  | "submit"
  | "respond_information"
  | "accept_offer"
  | "decline_offer"
  | "request_information"
  | "make_offer"
  | "approve"
  | "reject"
  | "retry_processing";
export interface InformationRequest {
  id: string;
  revision_id: string;
  application_version: number;
  status: "open" | "answered";
  message: string;
  requested_fields: string[];
  requested_document_types: DocumentType[];
  created_at: string;
  response_message: string | null;
  responded_by: string | null;
  responded_at: string | null;
  response_revision_id: string | null;
}
export interface Offer {
  id: string;
  version: number;
  revision_id: string;
  application_version: number;
  status: "active" | "accepted" | "declined" | "superseded";
  product_code: ProductCode;
  amount_kopecks: number;
  term_months: number;
  monthly_payment_kopecks: number;
  total_payment_kopecks: number;
  annual_rate_bps: number;
  reason: string;
  created_at: string;
}
export interface CommandResult {
  application_id: string;
  version: number;
  status: ApplicationStatus;
  revision_id: string;
}
export interface RiskFactor {
  feature_name: string;
  label: string;
  contribution: number;
}
export interface RiskAssessment {
  assessment_id: string;
  revision_id: string;
  processing_run_id: string;
  status: "succeeded" | "failed" | "not_applicable";
  reason_code: string | null;
  scorer_kind: string;
  scorer_version: string | null;
  feature_schema_version: string | null;
  target_event: string;
  horizon_months: number;
  data_kind: string;
  prediction_scope: "requested_terms" | "offered_terms";
  offer_version: number | null;
  terms_fingerprint: string;
  terms: {
    product_code: string;
    amount_kopecks: number;
    term_months: number;
    annual_rate_bps: number;
  };
  probability: number | null;
  risk_band: "low" | "elevated" | "high" | null;
  explanation_method: string | null;
  explanation_scale: string | null;
  base_value: number | null;
  raw_prediction: number | null;
  contributions: RiskFactor[];
  top_increasing_factors: RiskFactor[];
  top_decreasing_factors: RiskFactor[];
}
export interface Assessment {
  application_id: string;
  revision_id: string | null;
  risk_assessment: RiskAssessment | null;
  runs: {
    id: string;
    revision_id: string;
    status: ProcessingStatus;
    catalog_version: string;
    policy_version: string;
    source_version: string;
    scorer_version: string | null;
    risk_assessments: RiskAssessment[];
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
    error_code: string | null;
    checks: {
      id: string;
      kind: "registry" | "tax" | "bki";
      source_version: string;
      status: "succeeded";
      data:
        | { registered_at: string; liquidated: boolean }
        | { expected_monthly_revenue_kopecks: number | null }
        | { overdue_days: number };
      created_at: string;
    }[];
    calculation: {
      months: number;
      monthly_revenue_kopecks: string;
      monthly_operating_expenses_kopecks: string;
      monthly_debt_kopecks: string;
      available_flow_kopecks: string;
      monthly_payment_kopecks: number;
      coverage_ratio: string | null;
      policy_version: string;
    } | null;
    decision: {
      id: string;
      outcome:
        | "needs_info"
        | "manual_review"
        | "counteroffer"
        | "approved"
        | "rejected";
      public_reason_codes: string[];
      public_reasons: string[];
      internal_reason: string;
      created_at: string;
    } | null;
  }[];
}

export interface InformationRequestBody {
  expected_version: number;
  message: string;
  requested_fields: Exclude<keyof DraftFields, "product_code">[];
  requested_document_types: DocumentType[];
}
export interface InformationResponseBody extends SubmitBody {
  request_id: string;
  message: string;
}
export interface CreateOfferBody {
  risk_acknowledged: boolean;
  expected_version: number;
  amount_kopecks: number;
  term_months: number;
  reason: string;
}
export interface DecisionBody {
  risk_acknowledged: boolean;
  expected_version: number;
  outcome: "approved" | "rejected";
  reason: string;
}
export interface OfferActionBody {
  expected_version: number;
  offer_version: number;
}
