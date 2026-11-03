/**
 * Type definitions for the 5-Level Team Performance Hierarchy:
 * O&M Manager -> Circle -> OA -> CI -> IE -> Assigned Sites
 */

export interface HierarchyKpis {
  assigned_sites: number;
  availability_pct: number;
  nsla_sites: number;
  nsla_pct: number;
  usd: number;
  incidents: number;
  l1: number | null; // Always null / N/A until source ingested
  overall_score: number | null; // Always null / N/A until all 5 KPIs present
  rank: number | null; // Dense rank by overall score; null if overall score is N/A
}

export interface HierarchyCircleRow extends HierarchyKpis {
  circle: string;
  circle_name: string;
  om_manager: string;
  is_vacant: boolean;
  emp_code?: string;
  contact?: string;
  effective_from?: string;
}

export interface HierarchyOaRow extends HierarchyKpis {
  oa_id: string;
  oa_name: string;
  circle: string;
  circle_name: string;
  is_unassigned?: boolean;
}

export interface HierarchyCiRow extends HierarchyKpis {
  ci_id: string;
  ci_name: string;
  emp_code?: string;
  contact?: string;
  circle: string;
  oa_id: string;
  oa_name: string;
  other_oas?: string[]; // Demonstrates many-to-many CI-to-OA
}

export interface HierarchyIeRow extends HierarchyKpis {
  ie_id: string;
  ie_name: string;
  emp_code?: string;
  contact?: string;
  circle: string;
  oa_id: string;
  oa_name: string;
  ci_id: string;
  ci_name: string;
  other_cis?: string[]; // Demonstrates many-to-many IE-to-CI
}

export interface HierarchySiteRow {
  site_id: string;
  site_name: string;
  circle: string;
  oa_id?: string;
  oa_name: string;
  ci_name: string;
  ci_id: string;
  ie_name: string;
  ie_id: string;
  site_status: 'On-Air' | 'Degraded' | 'Critical';
  availability_pct: number;
  nsla_status: 'Meeting SLA' | 'Breached';
  usd_status: 'Normal' | 'Down';
  incident_count: number;
}

export interface HistoricalMonthKpiGroup {
  month_key: string;
  month_label: string;
  kind: 'month' | 'mtd';
  availability_pct: number;
  nsla_sites: number;
  nsla_pct: number;
  usd: number;
  incidents: number;
  l1: null;
  overall_score: null;
}
