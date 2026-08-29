import type { BBox } from '../types/field';
import type { Signature } from '../types/contract';
import { api } from './client';

export interface DatePlacementInput {
  page: number;
  field_id?: string | null;
  bbox?: BBox | null;
  value: string;
}

export const signaturesApi = {
  list: (contractId: string) => api.get<Signature[]>(`/api/contracts/${contractId}/signatures`),

  place: (
    contractId: string,
    placement: {
      page: number;
      bbox: BBox;
      field_id?: string | null;
      signer_name?: string;
      signer_role?: 'contractor' | 'company_rep';
      image_data: string;
    },
  ) => api.post<Signature>(`/api/contracts/${contractId}/signatures`, placement),

  remove: (contractId: string, signatureId: string) =>
    api.del<{ removed: boolean }>(`/api/contracts/${contractId}/signatures/${signatureId}`),

  finalize: (
    contractId: string,
    payload: {
      contract_date?: string;
      dates?: DatePlacementInput[];
      apply_paired_dates?: boolean;
    },
  ) =>
    api.post<{ contract_id: string; status: string; file_hash: string; download_url: string }>(
      `/api/contracts/${contractId}/finalize`,
      payload,
    ),
};
