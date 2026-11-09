/**
 * Site Portfolio on the new data layer (backend apps/sitedata/portfolio.py, /api/site-portfolio/). The same requests and
 * responses as the dashboard endpoints the page used before; the data comes from the Consolidation Matrix and the new
 * daily records. Used only by the Site Portfolio page.
 */
import type { BreakdownResponse, ConversionActivity, FilterOptions, PeriodSummary, SummaryResponse } from '../types';
import { request } from './api';

/** Continuity of the reporting month: MTD ends at the last continuous date with data. */
export interface PortfolioContinuity {
  dates_with_data: string[];
  continuous_until: string | null;
  excluded_after_gap: string[];
}

export type PortfolioFilterOptions = FilterOptions & { source: FilterOptions['source'] & { data_layer?: string; continuity?: PortfolioContinuity } };

type Fetcher<T> = (params: URLSearchParams, signal?: AbortSignal) => Promise<T>;
const portfolio = <T,>(path: string): Fetcher<T> => (params, signal) => request<T>(`/site-portfolio/${path}`, params, { signal });

export const fetchPortfolioFilters = (signal?: AbortSignal) => request<PortfolioFilterOptions>('/site-portfolio/filters/', undefined, { signal });
export const fetchPortfolioSummary = portfolio<SummaryResponse>('summary/');
export const fetchPortfolioBreakdowns = portfolio<BreakdownResponse>('breakdowns/');
export const fetchPortfolioPeriod = portfolio<PeriodSummary>('period/');
export const fetchPortfolioActivity = portfolio<ConversionActivity>('conversion-activity/');
