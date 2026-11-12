import { usePopulation } from '../context/population';
import { useWorkbook } from '../context/workbook';
import { fetchFilterOptions } from '../services/api';
import { useApiQuery } from './useApiQuery';

/** The dashboard filter options for the active workbook and the global population (refetched when either changes). */
export function useFilterOptions() {
  const { active, version } = useWorkbook();
  const { scope } = usePopulation();
  return useApiQuery(active ? `${version}|filters|${scope}` : null, (signal) => fetchFilterOptions(signal, scope));
}
