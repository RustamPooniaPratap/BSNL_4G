/** Master Data (database explorer): dataset definitions and pages of records, all from the API. */
export type MasterColumnKind = 'text' | 'number' | 'pct' | 'date' | 'datetime' | 'bool' | 'minutes' | 'month';

export interface MasterColumn { key: string; label: string; kind: MasterColumnKind; hidden: boolean; sortable?: boolean }

export interface MasterDataset {
  key: string;
  label: string;
  description: string;
  /** Time-based: offers the Daily / Weekly / Monthly / Overall period views. */
  time: boolean;
  columns: MasterColumn[];
  filters: { site: boolean; choices: { key: string; label: string }[] };
  /** What this user may do here (Users & Roles › Data Panel · dataset); the server checks every request again. No delete. */
  permissions: MasterPermissions;
}

export interface MasterPermissions {
  view: boolean; add: boolean; edit: boolean; export: boolean;
  /** Columns that can be changed on existing rows / filled in on new rows; required on new rows. */
  editable: string[]; addable: string[]; required: string[];
}

/** One Data Panel save: changed cells of existing rows and new rows, written together or not at all. */
export interface MasterSaveRequest {
  changes: { id: number; values: Record<string, string> }[];
  additions: { values: Record<string, string> }[];
}
export interface MasterSaveResult { saved: true; updated: number; added: number; ids: number[] }
/** 400 details: errors per row id (changes) or new-row index (additions), per column ('_row' for the whole row). */
export interface MasterSaveErrors { changes: Record<string, Record<string, string>>; additions: Record<string, Record<string, string>> }

export interface MasterDatasets { datasets: MasterDataset[]; page_sizes: number[]; weeks: { value: number; label: string }[] }

export interface MasterOptions {
  projects: string[];
  circles: string[];
  months?: { year: number; month: number }[];
  dates?: string[];
  choices: Record<string, string[]>;
}

export type MasterRow = Record<string, string | number | boolean | null> & { _id: number };

export interface MasterPage { total: number; page: number; page_size: number; pages: number; rows: MasterRow[] }
