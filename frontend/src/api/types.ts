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
  status: "draft" | "submitted";
  updated_at: string;
  catalog_version: string;
  public_reasons: string[];
  available_actions: ("edit_draft" | "upload_document" | "submit")[];
}
export interface HistoryEvent {
  id: string;
  event_type:
    | "draft_created"
    | "draft_updated"
    | "document_uploaded"
    | "document_deleted"
    | "application_submitted";
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
