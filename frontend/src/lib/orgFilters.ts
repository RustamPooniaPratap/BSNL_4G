/** List filters of the Organization tabs. */
export type ActiveFilter = 'all' | 'active' | 'inactive';
export const ACTIVE_FILTERS: [ActiveFilter, string][] = [['all', 'All'], ['active', 'Active'], ['inactive', 'Inactive']];
export const matchesActive = (filter: ActiveFilter, active: boolean) => filter === 'all' || (filter === 'active') === active;
export const matchesText = (query: string, ...values: (string | null | undefined)[]) =>
  !query.trim() || values.some((v) => (v ?? '').toLowerCase().includes(query.trim().toLowerCase()));
