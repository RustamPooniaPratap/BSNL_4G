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
}

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
