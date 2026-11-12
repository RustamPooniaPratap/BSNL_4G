/**
 * The global site population (On-Air or O&M Start). One selection drives every site-based figure of the portal; the
 * backend receives it as the ``scope`` query parameter (missing = On-Air). "All sites" is not a population.
 */
export type Population = 'on_air' | 'om_start';

export const POPULATIONS: Population[] = ['on_air', 'om_start'];
export const DEFAULT_POPULATION: Population = 'on_air';
/** URL query parameter and localStorage key of the selection. */
export const POPULATION_PARAM = 'scope';
export const POPULATION_STORAGE_KEY = 'portal.population';

const LABELS: Record<Population, string> = { on_air: 'On-Air', om_start: 'O&M Start' };

export const isPopulation = (value: unknown): value is Population => value === 'on_air' || value === 'om_start';
export const parsePopulation = (value: string | null | undefined): Population | null => (isPopulation(value) ? value : null);

/** "On-Air" / "O&M Start". */
export const populationLabel = (scope: Population) => LABELS[scope];
/** "On-Air sites" / "O&M Start sites". */
export const populationSites = (scope: Population) => `${LABELS[scope]} sites`;

/** The population label of an API response (``population: {scope, label}``), falling back to the selection's own label. */
export function responseLabel(response: unknown, scope: Population): string {
  const population = (response as { population?: { label?: unknown } } | null | undefined)?.population;
  return typeof population?.label === 'string' && population.label ? population.label : populationLabel(scope);
}

/** A copy of ``params`` with the population set (every site-metric request sends it). */
export function withScope(params: URLSearchParams | undefined, scope: Population): URLSearchParams {
  const next = new URLSearchParams(params);
  next.set(POPULATION_PARAM, scope);
  return next;
}

export function readStoredPopulation(): Population | null {
  try {
    return parsePopulation(window.localStorage.getItem(POPULATION_STORAGE_KEY));
  } catch {
    return null;  // storage blocked (private mode, policies)
  }
}

export function storePopulation(scope: Population) {
  try {
    window.localStorage.setItem(POPULATION_STORAGE_KEY, scope);
  } catch {
    // Storage blocked: the URL still carries the selection.
  }
}
