export type ProductCode = "working_capital" | "equipment" | "overdraft" | "credit_line" | "investment" | "tender_guarantee";
export type PaymentKind = "annuity" | "revolving" | "guarantee";
export type DocumentType = "financial_statement" | "equipment_invoice" | "bank_statement" | "business_plan" | "tender_document";
export type ProductField = "tender_number" | "beneficiary_name" | "project_description";
export interface PaymentTerms {
  payment_kind: PaymentKind;
  amount_kopecks: number;
  term_months: number;
  annual_rate_bps: number | null;
  annual_commission_bps: number;
  monthly_payment_kopecks: number | null;
  upfront_fee_kopecks: number;
  principal_due_at_end_kopecks: number;
  last_payment_kopecks: number;
  total_payment_kopecks: number;
  total_cost_kopecks: number;
  assessment_monthly_burden_kopecks: number | null;
  contingent_liability_kopecks: number;
  assumptions: string[];
}
export interface FinancialGate {
  allowed: boolean;
  reason_code: string;
  coverage_ratio: string | null;
  guarantee_fee_affordable: boolean | null;
  guarantee_liability_within_limit: boolean | null;
  available_after_debt_kopecks: string;
  guarantee_liability_limit_kopecks: string | null;
}
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
  annual_rate_bps: number | null;
  payment_kind: PaymentKind;
  upfront_fee_bps: number;
  annual_commission_bps: number;
  required_document_types: DocumentType[];
  required_application_fields: ProductField[];
}
export interface Catalog {
  catalog_version: string;
  items: Product[];
}
export type RecommendationPurpose =
  | "working_capital"
  | "cash_gap"
  | "equipment"
  | "investment"
  | "real_estate"
  | "tender_guarantee";
export type RecommendationCollateral =
  | "real_estate"
  | "equipment"
  | "vehicle"
  | "none";
export interface RecommendationRequest {
  purpose: RecommendationPurpose;
  amount_kopecks: number;
  term_months: number;
  revenue_total_kopecks?: number | null;
  expenses_total_kopecks?: number | null;
  existing_debt_payments_kopecks?: number | null;
  period_start?: string | null;
  period_end?: string | null;
  period_months?: number | null;
}
export interface RecommendationOption {
  code: string;
  label: string;
}
export interface RecommendationOptions {
  purposes: { code: RecommendationPurpose; label: string }[];
  config_version: string;
}
export interface RecommendationAction {
  kind: "request_field" | "apply_recommendation" | "change_amount";
  label: string;
  field: "revenue_total_kopecks" | "expenses_total_kopecks" | "existing_debt_payments_kopecks" | "period_months" | "amount_kopecks" | null;
  product_code: ProductCode | null;
  recommendation_id: string | null;
}
export interface RecommendationItem {
  recommendation_id: string;
  product_code: ProductCode;
  product_name: string;
  rank: number;
  purpose_match: boolean;
  recommended_amount_kopecks: number;
  term_months: number;
  payment_terms: PaymentTerms;
  financial_gate: FinancialGate;
  client_reasons: string[];
  reason_codes: string[];
  required_application_fields: ProductField[];
  required_document_types: DocumentType[];
}
export type RecommendationStatus =
  | "ok"
  | "adjusted"
  | "request_data"
  | "no_match";
export interface RecommendationResponse {
  status: RecommendationStatus;
  message: string;
  items: RecommendationItem[];
  missing_fields: RecommendationAction["field"][];
  actions: RecommendationAction[];
  config_version: string;
  trace_id: string;
  catalog_version: string;
  staff_trace: Record<string, unknown>[] | null;
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
  tender_number: string | null;
  beneficiary_name: string | null;
  project_description: string | null;
}
export interface Application extends DraftFields {
  id: string;
  display_number: string;
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
  tender_number: string;
  beneficiary_name: string;
  project_description: string;
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
  responded_at: string | null;
  decline_reason: DeclineReason | null;
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
  payment_terms: PaymentTerms;
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
  target_event: string | null;
  horizon_months: number | null;
  data_kind: string;
  prediction_scope: "requested_terms" | "offered_terms";
  offer_version: number | null;
  terms_fingerprint: string;
  terms: {
    product_code: string;
    amount_kopecks: number;
    term_months: number;
    annual_rate_bps: number | null;
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
      payment_terms: PaymentTerms | null;
      financial_gate: FinancialGate | null;
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
export interface DeclineOfferBody extends OfferActionBody { decline_reason?: DeclineReason | null }

export type DeclineReason = 'insufficient_amount' | 'high_payment' | 'unsuitable_term' | 'no_longer_needed' | 'other';
export type OfferOutcome = 'accepted' | 'declined' | 'superseded' | 'no_response' | 'awaiting_response' | 'not_viewed';
export type FormStep = 'terms' | 'finances' | 'documents' | 'review';
export type AnalyticsEvent = {event_id: string} & (
  | {kind: 'form_opened'; journey_id: string; product_code: ProductCode}
  | {kind: 'form_step_viewed'; journey_id: string; step: FormStep}
  | {kind: 'draft_linked'; journey_id: string; application_id: string}
  | {kind: 'offer_viewed'; offer_id: string; offer_version: number}
);
export interface ObservationCount {count: number; base: number; share: number | null}
export interface FunnelStage {
  key: 'opened' | 'draft_saved' | 'submitted' | 'issued' | 'viewed' | 'responded' | 'accepted';
  count: number; base_from_first: number; base_from_previous: number;
  share_from_first: number | null; share_from_previous: number | null;
}
export interface ReportMetadata {
  date_from: string; date_to: string; timezone: 'Europe/Moscow'; generated_at: string;
  outcomes_as_of: string; product_code: ProductCode | null; no_response_hours: 72;
}
export interface AnalyticsSummary {
  metadata: ReportMetadata; form_funnel: FunnelStage[]; offer_funnel: FunnelStage[];
  last_steps: (ObservationCount & {step: FormStep | 'not_observed'})[];
  offer_outcomes: (ObservationCount & {outcome: OfferOutcome})[];
  declined_after_view: ObservationCount;
  response_coverage: {responses_without_prior_view: number; response_without_registered_view: number; response_viewed_after_response: number; response_time_unknown: number};
  decline_reasons: (ObservationCount & {reason: DeclineReason | null})[];
  condition_changes: {change: 'amount_only' | 'term_only' | 'amount_and_term' | 'unchanged'; count: number; accepted: number; acceptance_share: number | null}[];
}
export interface CounterofferRow {
  id: string; application_id: string; revision_id: string; company_name: string;
  product_code: ProductCode; created_at: string; original_amount_kopecks: number;
  original_term_months: number; original_monthly_payment_kopecks: number | null;
  amount_kopecks: number; term_months: number; payment_terms: PaymentTerms;
  amount_delta_kopecks: number; amount_delta_rubles: string; amount_delta_percent: number | null;
  term_delta_months: number; first_viewed_at: string | null; responded_at: string | null;
  outcome: OfferOutcome; decline_reason: DeclineReason | null;
}
export interface CounterofferPage {metadata: ReportMetadata; items: CounterofferRow[]; total: number; page: number; page_size: number}
