import type { BBox } from './field';

export type ContractStatus =
  | 'uploaded'
  | 'parsing'
  | 'analyzed'
  | 'reviewing'
  | 'signing'
  | 'completed'
  | 'failed';

export type ReviewStatus = 'pending' | 'approved' | 'rejected';

export interface Contract {
  id: string;
  template_id: string;
  contractor_name: string | null;
  contractor_email: string | null;
  status: ContractStatus;
  review_status: ReviewStatus;
  error_message: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContractDetail extends Contract {
  extracted_data: Record<string, ExtractedValue>;
  comparison_result: Record<string, unknown>;
  final_available: boolean;
}

export interface ExtractedValue {
  value: string | null;
  normalized?: string | null;
  confidence: number;
  detected: boolean;
  status?: string;
  selected?: string[];
  checked?: boolean;
  has_signature?: boolean;
  rows?: string[][];
}

export interface ContractField {
  template_field_id: string;
  field_type: string;
  status: 'empty' | 'filled' | 'invalid' | 'verified';
  raw_value: string | null;
  normalized_value: string | null;
  confidence_score: number | null;
  is_required: boolean;
  is_valid: boolean | null;
  validation_error: string | null;
  bbox: BBox | null;
  page_number: number | null;
  extra: Record<string, unknown>;
}

export interface DateField {
  field_id: string;
  label: string | null;
  page: number | null;
  bbox: BBox;
  required: boolean;
  paired_signature_field_id: string | null;
  current_value: string | null;
}

export interface Signature {
  id: string;
  contract_id: string;
  signer_name: string | null;
  signer_email: string | null;
  signer_role: 'contractor' | 'company_rep';
  page_number: number;
  bbox: BBox;
  field_id: string | null;
  signed_at: string;
}
