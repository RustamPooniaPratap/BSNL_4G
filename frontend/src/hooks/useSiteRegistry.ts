import { useEffect, useState } from 'react';
import { normaliseSiteId } from '../lib/dataEntry';
import { fetchRecords } from '../services/api';
import type { SiteRecord } from '../types';

const PAGE_SIZE = 100;  // the records API maximum
const PARALLEL = 4;

// In-memory only, per workbook version: cleared on reload, never written to browser storage.
const cache = new Map<string, Promise<Map<string, SiteRecord>>>();

const baseQuery = (reportType: string, circle: string) =>
  new URLSearchParams({ scope: 'all', report_type: reportType, circle, sort: 'site_id', page_size: String(PAGE_SIZE) });

/** Every site of one report type and circle in the active workbook, keyed by Site ID (read-only GETs). */
export function loadSiteRegistry(version: string, reportType: string, circle: string): Promise<Map<string, SiteRecord>> {
  const cacheKey = `${version}|${reportType}|${circle}`;
  let pending = cache.get(cacheKey);
  if (!pending) {
    pending = (async () => {
      const page = (n: number) => {
        const query = baseQuery(reportType, circle);
        query.set('page', String(n));
        return fetchRecords(query);
      };
      const first = await page(1);
      const records = [...first.records];
      const rest = Array.from({ length: first.pages - 1 }, (_, i) => i + 2);
      for (let i = 0; i < rest.length; i += PARALLEL) {
        const batch = await Promise.all(rest.slice(i, i + PARALLEL).map(page));
        batch.forEach((response) => records.push(...response.records));
      }
      return new Map(records.map((r) => [normaliseSiteId(r.site_id), r]));
    })();
    pending.catch(() => cache.delete(cacheKey));  // let a failed load be retried
    cache.set(cacheKey, pending);
  }
  return pending;
}

export interface SiteRegistryState {
  sites: Map<string, SiteRecord> | null;
  loading: boolean;
  error: Error | null;
}

export function useSiteRegistry(version: string, reportType: string, circle: string): SiteRegistryState {
  const ready = Boolean(reportType && circle);
  const [state, setState] = useState<SiteRegistryState & { key: string }>({ key: '', sites: null, loading: false, error: null });
  const key = ready ? `${version}|${reportType}|${circle}` : '';

  useEffect(() => {
    if (!ready) return;
    let active = true;
    loadSiteRegistry(version, reportType, circle)
      .then((sites) => { if (active) setState({ key, sites, loading: false, error: null }); })
      .catch((error: unknown) => {
        if (active) setState({ key, sites: null, loading: false, error: error instanceof Error ? error : new Error(String(error)) });
      });
    return () => { active = false; };
  }, [ready, key, version, reportType, circle]);

  if (!ready) return { sites: null, loading: false, error: null };
  if (state.key !== key) return { sites: null, loading: true, error: null };
  return state;
}

/** Look a Site ID up across every report type and circle (exact match, read-only). */
export async function findSite(siteId: string, signal?: AbortSignal): Promise<SiteRecord | null> {
  const id = normaliseSiteId(siteId);
  const query = new URLSearchParams({ scope: 'all', search: id, page_size: String(PAGE_SIZE) });
  const response = await fetchRecords(query, signal);
  return response.records.find((r) => normaliseSiteId(r.site_id) === id) ?? null;
}
