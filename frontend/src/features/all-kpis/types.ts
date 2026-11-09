/** All KPI's: responses of /api/all-kpis/ (backend: apps/allkpis/services.py). */
export interface KpiOmStatus { months: string[]; missing_months: string[]; available: boolean; complete: boolean }

/** KPIs of a group of sites; null = not available (no data, or no O&M Start data for the period). */
export interface KpiValues {
  total_sites: number; on_air_sites: number; om_start_sites: number | null;
  availability_pct: number | null; outage_minutes: number | null; outage_hours: number | null;
  usd_sites: number | null; nsla_sites: number | null;
  above_98_5_sites: number; below_98_5_sites: number; below_60_sites: number; sites_with_values: number;
  buckets: Record<string, number>;
  missing_site_days: number; expected_site_days: number; reported_site_days: number; coverage_pct: number | null;
  sites_missing_any_day: number; sites_without_any_value: number;
}

export interface KpiPeriod { start: string; end: string; label: string; days_with_data?: number; days_in_period?: number }

export interface KpiSummary {
  period: KpiPeriod | null; previous_period?: KpiPeriod;
  current: KpiValues | null; previous: KpiValues | null;
  om_start?: KpiOmStatus; previous_om_start?: KpiOmStatus;
  pending?: { rca_ownership: string };
  notes?: string[];
}

export type Granularity = 'day' | 'week' | 'month';
export interface KpiTrendPoint {
  key: string; label: string; start: string; end: string; days: number;
  availability_pct: number | null; outage_minutes: number | null; outage_hours: number | null; usd_sites: number | null; nsla_sites: number | null;
  below_98_5_sites: number; below_60_sites: number; coverage_pct: number | null; missing_site_days: number;
}
export interface KpiTrends { granularity: Granularity; points: KpiTrendPoint[] }

export type HierarchyLevel = 'circle' | 'ci' | 'ie';
export interface KpiGroupRow extends KpiValues { key: string; project: string; circle: string; ci?: string; ie?: string }
export interface KpiHierarchy { level: HierarchyLevel; rows: KpiGroupRow[]; om_start?: KpiOmStatus }

export interface KpiSiteRow {
  site_id: string; site_name: string; project: string; circle: string; ci: string; ie: string; oa: string; on_air: boolean;
  om_start: boolean | null; availability_pct: number | null; outage_minutes: number | null; outage_hours: number | null;
  days_reported: number; days_expected: number; bucket: string | null; bucket_label: string | null; usd: boolean | null; nsla: boolean | null;
}
export interface KpiSites { total: number; page: number; page_size?: number; pages: number; rows: KpiSiteRow[]; om_start?: KpiOmStatus }

export interface KpiRca {
  period?: KpiPeriod; records: number;
  buckets: { bucket: string; records: number; outage_minutes: number; share_pct: number | null }[];
  not_mapped?: { records: number; values: { final_bucket: string; records: number }[] };
  by_circle?: { circle: string; records: number; buckets: Record<string, number> }[];
  ownership?: { configured: boolean; message: string };
}

export interface KpiFilterOptions {
  dates: string[]; default_period: { start: string; end: string } | null;
  projects: string[]; circles: string[];
  cis: { key: string; label: string; circle: string }[];
  ies: { key: string; label: string; ci: string; circle: string }[];
  sites: { key: string; label: string }[]; site_count: number;
  buckets: { key: string; label: string }[]; final_buckets: string[];
}
