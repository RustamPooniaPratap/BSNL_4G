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
