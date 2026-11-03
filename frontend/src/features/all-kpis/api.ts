import { request } from '../../services/api';
import type { KpiFilterOptions, KpiHierarchy, KpiRca, KpiSites, KpiSummary, KpiTrends } from './types';

/** All KPI's API calls (read-only). Uses the shared request helper for sessions and errors; nothing else depends on these. */
const get = <T,>(path: string, params: URLSearchParams, signal?: AbortSignal) => request<T>(`/all-kpis/${path}/`, params, { signal });

export const fetchKpiFilters = (params: URLSearchParams, signal?: AbortSignal) => get<KpiFilterOptions>('filters', params, signal);
export const fetchKpiSummary = (params: URLSearchParams, signal?: AbortSignal) => get<KpiSummary>('summary', params, signal);
export const fetchKpiTrends = (params: URLSearchParams, signal?: AbortSignal) => get<KpiTrends>('trends', params, signal);
export const fetchKpiHierarchy = (params: URLSearchParams, signal?: AbortSignal) => get<KpiHierarchy>('hierarchy', params, signal);
export const fetchKpiSites = (params: URLSearchParams, signal?: AbortSignal) => get<KpiSites>('sites', params, signal);
export const fetchKpiRca = (params: URLSearchParams, signal?: AbortSignal) => get<KpiRca>('rca', params, signal);
