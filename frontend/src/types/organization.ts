/** Administration > Organization: projects, global circles, their associations, code mapping, access and history. */

/** What every portal user may read: used by selectors across the application. */
export interface OrganizationCatalog {
  projects: { key: string; code: string; name: string; is_active: boolean }[];
  circles: { code: string; name: string; is_active: boolean }[];
  /** ``is_active``: the association, its project and its circle are all active. */
  associations: { project: string; circle: string; is_active: boolean }[];
}

/** Records referring to one project/circle (nothing is invented: zero means none stored). */
export interface OrgUsage {
  sites: number;
  on_air_sites: number;
  daily: number;
  monthly: number;
  uploads: number;
  rca: number;
  /** Expected RCA units (reporting cycles) of the project and circle. */
  rca_expected: number;
  /** Consolidated Escalation Matrix sites. */
  escalation: number;
  users: number;
}

export interface OrgProject {
  id: number;
  /** Stored on site, daily, upload and RCA records; fixed once created. */
  key: string;
  code: string;
  name: string;
  description: string;
  is_active: boolean;
  circles: { code: string; is_active: boolean }[];
  usage: OrgUsage;
  created_at: string;
  updated_at: string;
}

export interface OrgCircle {
  id: number;
  code: string;
  name: string;
  description: string;
  is_active: boolean;
  projects: { project: string; project_code: string; is_active: boolean; usage: OrgUsage }[];
  /** Data of the circle under a project it is not associated with (e.g. an RCA record). */
  unassociated_data: { project: string; usage: OrgUsage }[];
  aliases: number;
  /** Nothing refers to it (no association, alias, record or grant): it may be deleted. */
  deletable: boolean;
  created_at: string;
  updated_at: string;
}

export interface OrgAssociation {
  id: number;
  project: string;
  project_code: string;
  project_active: boolean;
  circle: string;
  circle_name: string;
  circle_active: boolean;
  is_active: boolean;
  usage: OrgUsage;
  created_at: string;
}

export interface OrgAlias {
  id: number;
  source: string;
  source_label: string;
  project: string | null;
  raw_code: string;
  circle: string;
  circle_name: string;
  is_active: boolean;
  notes: string;
  problems: string[];
  created_by: string;
  updated_at: string;
}

/** What Remove did: removed (unused), or kept inactive because records refer to the association. */
export interface OrgRemoval {
  associations: OrgAssociation[];
  outcome: 'removed' | 'deactivated' | 'kept_inactive';
  dependencies: Partial<Record<keyof OrgUsage, number>>;
}

/** How raw site identifiers resolve per project (separate from circle code aliases). */
export interface OrgSiteIdMapping {
  project: string;
  configured: boolean;
  rule: string;
}

export interface OrgAccessUser {
  id: number;
  username: string;
  name: string;
  role: string | null;
  role_label: string;
  is_active: boolean;
  /** CI users only: Admins and NOC Leads are not limited. */
  limited: boolean;
  pairs: { project: string; circle: string }[];
  /** Circle-only assignments from before project-specific access: they still apply to every project. */
  legacy_circles: string[];
  needs_review: boolean;
}

export interface OrgChange {
  id: number;
  entity_type: string;
  entity_id: string;
  entity_label: string;
  action: string;
  previous: Record<string, unknown> | null;
  new: Record<string, unknown> | null;
  actor: string;
  reason: string;
  created_at: string;
}


export interface PaginatedResult<T> {
  results: T[];
  count: number;
  num_pages: number;
  current_page: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface OperationalAreaItem {
  id: number;
  circle: number;
  circle_code: string;
  circle_name: string;
  name: string;
  normalized_name: string;
  code: string | null;
  is_active: boolean;
  alias_count: number;
  created_at: string;
  updated_at: string;
}

export interface OperationalAreaAliasItem {
  id: number;
  oa: number;
  oa_name: string;
  circle_code: string;
  raw_name: string;
  normalized_name: string;
  source: string;
  created_at: string;
}

export interface OmManagerAssignmentItem {
  id: number;
  circle: number;
  circle_code: string;
  circle_name: string;
  project: number | null;
  project_key: string | null;
  project_name: string | null;
  manager_name: string;
  employee_code: string;
  contact: string;
  email: string;
  user: number | null;
  user_username: string | null;
  is_vacant: boolean;
  is_active: boolean;
  effective_from: string;
  effective_to: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface OmManagerAssignmentAuditItem {
  id: number;
  assignment: number | null;
  actor: number | null;
  actor_username: string;
  action: string;
  timestamp: string;
  reason: string;
  effective_date: string;
  before_values: Record<string, unknown>;
  after_values: Record<string, unknown>;
  request_id: string;
}

export interface PersonnelItem {
  id: number;
  display_name: string;
  canonical_name: string;
  role_type: 'ci' | 'ie';
  employee_code: string | null;
  contact: string | null;
  email: string | null;
  user: number | null;
  user_username: string | null;
  is_active: boolean;
  merged_into: number | null;
  merged_into_name: string | null;
  merged_at: string | null;
  merge_reason: string;
  site_assignment_count: number;
  alias_count: number;
  created_at: string;
  updated_at: string;
}

export interface PersonnelAliasItem {
  id: number;
  personnel: number;
  personnel_name: string;
  role_type: 'ci' | 'ie';
  raw_name: string;
  normalized_name: string;
  source: string;
  circle: number | null;
  circle_code: string | null;
  project: number | null;
  project_key: string | null;
  created_at: string;
}

export interface PersonnelSourceMappingItem {
  id: number;
  source_system: string;
  source_dataset: string;
  source_record_key: string;
  source_role_type: 'ci' | 'ie';
  source_circle: number | null;
  circle_code: string | null;
  source_project: number | null;
  project_key: string | null;
  raw_name: string;
  raw_employee_code: string;
  personnel: number | null;
  personnel_name: string | null;
  mapping_status: 'approved' | 'unresolved' | 'rejected';
  approved_by: number | null;
  approved_by_username: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SitePersonnelAssignmentItem {
  id: number;
  site: number;
  site_id_str: string;
  site_name: string;
  circle_code: string;
  project_key: string;
  personnel: number;
  personnel_name: string;
  personnel_code: string | null;
  role_type: 'ci' | 'ie';
  parent_ci: number | null;
  parent_ci_name: string | null;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface PersonnelConflictItem {
  id: number;
  fingerprint: string;
  source_system: string;
  source_dataset: string;
  source_record_key: string;
  conflict_type: string;
  role_type: 'ci' | 'ie';
  raw_source_data: Record<string, unknown>;
  possible_matches: unknown[];
  status: 'open' | 'under_review' | 'resolved' | 'rejected';
  resolution: string;
  resolved_personnel: number | null;
  resolved_personnel_name: string | null;
  reviewed_by: number | null;
  reviewed_by_username: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersonnelMergeAuditItem {
  id: number;
  source_personnel_id: number;
  target_personnel: number;
  target_personnel_name: string;
  actor: number;
  actor_username: string;
  timestamp: string;
  reason: string;
  affected_relationship_ids: Record<string, unknown>;
  original_values: Record<string, unknown>;
  applied_changes: Record<string, unknown>;
  status: string;
  rollback_status: string;
  rollback_actor: number | null;
  rollback_actor_username: string | null;
  rollback_timestamp: string | null;
  rollback_reason: string;
}
