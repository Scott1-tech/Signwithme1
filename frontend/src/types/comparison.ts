import type { BBox, FieldType } from './field';

export type Severity = 'critical' | 'warning';

export interface MissingField {
  field_id: string;
  label: string;
  page: number | null;
  type: FieldType | null;
  /** Present so the highlighter can draw the box. A label alone is not enough. */
  bbox: BBox | null;
  severity: Severity;
}

/**
 * One shape for both cross-field mismatches and per-field format problems, so
 * the sidebar renders them with a single component.
 */
export interface Inconsistency {
  type: string;
  issue: string;
  values: Record<string, unknown>;
  /** Pages stated explicitly; the UI never parses them out of field-id prefixes. */
  pages: number[];
  field_id?: string | null;
  severity: Severity;
}

export interface FmcsaViolation {
  rule: string;
  issue: string;
  page: number | null;
  field_ids: string[];
  severity: Severity;
}

export interface ComparisonResult {
  contract_id: string | null;
  completion_percentage: number;
  missing_required: MissingField[];
  inconsistencies: Inconsistency[];
  fmcsa_violations: FmcsaViolation[];
  warnings: Inconsistency[];
  can_sign: boolean;
  field_count: number;
  filled_count: number;
}

export type IssueKind = 'missing' | 'inconsistency' | 'fmcsa' | 'warning';

/** A page-anchored issue, normalised from all four buckets for rendering. */
export interface PageIssue {
  kind: IssueKind;
  key: string;
  label: string;
  detail: string;
  severity: Severity;
  page: number | null;
  fieldId: string | null;
  bbox: BBox | null;
}
