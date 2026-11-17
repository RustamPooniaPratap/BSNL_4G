import { request } from '../../services/api';
import type { ApiEndpointDetail, ApiEndpointRow, EndpointStatus, RegistryOverview, SyncResult } from './types';

/** API Master administration calls (Admins only). The shared request helper adds the session, CSRF token and errors. */
const BASE = '/api-master';
const post = <T,>(path: string, body: unknown = {}) =>
  request<T>(`${BASE}${path}`, undefined, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });

export const fetchRegistryOverview = (signal?: AbortSignal) => request<RegistryOverview>(`${BASE}/overview/`, undefined, { signal });
export const fetchEndpoints = (params: URLSearchParams, signal?: AbortSignal) =>
  request<{ count: number; results: ApiEndpointRow[] }>(`${BASE}/endpoints/`, params, { signal });
export const fetchEndpoint = (id: number, signal?: AbortSignal) => request<ApiEndpointDetail>(`${BASE}/endpoints/${id}/`, undefined, { signal });
export const reviewEndpoint = (id: number, review: { status: EndpointStatus; note: string; fields_reviewed: boolean }) =>
  post<ApiEndpointDetail>(`/endpoints/${id}/review/`, review);
export const syncRegistry = () => post<SyncResult>('/endpoints/sync/');
