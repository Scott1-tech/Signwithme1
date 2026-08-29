import type { ComparisonResult } from '../types/comparison';
import type { Contract, ContractDetail, ContractField, DateField } from '../types/contract';
import { api } from './client';

export const contractsApi = {
  list: (params: { status?: string; templateId?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set('status', params.status);
    if (params.templateId) query.set('template_id', params.templateId);
    const suffix = query.toString() ? `?${query}` : '';
    return api.get<Contract[]>(`/api/contracts${suffix}`);
  },

  get: (id: string) => api.get<ContractDetail>(`/api/contracts/${id}`),

  upload: (templateId: string, file: File, contractorName?: string, contractorEmail?: string) => {
    const form = new FormData();
    form.append('template_id', templateId);
    form.append('file', file);
    if (contractorName) form.append('contractor_name', contractorName);
    if (contractorEmail) form.append('contractor_email', contractorEmail);
    return api.upload<{ contract_id: string; task_id: string | null; status: string }>(
      '/api/contracts',
      form,
    );
  },

  comparison: (id: string, signal?: AbortSignal) =>
    api.get<ComparisonResult>(`/api/contracts/${id}/compare`, signal),

  rerunComparison: (id: string) => api.post<ComparisonResult>(`/api/contracts/${id}/compare`),

  fields: (id: string, page?: number) =>
    api.get<ContractField[]>(`/api/contracts/${id}/fields${page ? `?page=${page}` : ''}`),

  correctField: (
    id: string,
    fieldId: string,
    correction: { value?: string | null; selected?: string[]; checked?: boolean },
  ) =>
    api.patch<ContractField>(
      `/api/contracts/${id}/fields/${encodeURIComponent(fieldId)}`,
      correction,
    ),

  dateFields: (id: string) => api.get<DateField[]>(`/api/contracts/${id}/date-fields`),

  submitReview: (id: string, decision: 'approved' | 'rejected', notes?: string) =>
    api.post<Contract>(`/api/review/${id}`, { decision, notes }),

  reviewQueue: () => api.get<Contract[]>('/api/review/queue'),

  auditTrail: (id: string) =>
    api.get<
      {
        action: string;
        actor_email: string | null;
        actor_role: string | null;
        details: Record<string, unknown>;
        timestamp: string;
      }[]
    >(`/api/review/${id}/audit`),

  verifyFinal: (id: string) =>
    api.get<{ recorded_hash: string; current_hash: string; intact: boolean }>(
      `/api/download/${id}/verify`,
    ),
};
