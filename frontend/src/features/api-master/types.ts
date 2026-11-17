/** API Master (Phase 1: API Registry) — shapes returned by /api/api-master/ (apps/api_master/views.py). */
export type EndpointStatus = 'pending' | 'approved' | 'rejected' | 'deprecated';

export interface ApiEndpointRow {
  id: number;
  key: string;
  name: string;
  path: string;
  method: string;
  module: string;
  description: string;
  status: EndpointStatus;
  status_label: string;
  blocked: boolean;
  block_reason: string;
  field_review: string;
  present: boolean;
  access_type: string;
}

export interface ApiEndpointDetail extends ApiEndpointRow {
  url_name: string;
  view: string;
  permission_classes: string[];
  authentication_classes: string[];
  path_params: { name: string; type: string }[];
  review_note: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  first_seen: string;
  last_seen: string;
  external_route: string | null;
  allowed_transitions: EndpointStatus[];
}

export interface RegistryOverview {
  total: number;
  approved: number;
  pending: number;
  rejected: number;
  deprecated: number;
  blocked: number;
  field_review: number;
  reviewable: number;
  no_longer_present: number;
  methods: Record<string, number>;
  modules: { module: string; total: number; approved: number; blocked: number }[];
  last_sync: string | null;
}

export interface SyncResult {
  discovered: number;
  created: number;
  updated: number;
  no_longer_present: number;
  approvals_withdrawn: number;
  total: number;
}
