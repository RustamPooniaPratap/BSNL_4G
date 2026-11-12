/* eslint-disable react-refresh/only-export-components -- the provider and its hook belong together */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  DEFAULT_POPULATION, POPULATION_PARAM, parsePopulation, populationLabel, populationSites, readStoredPopulation, storePopulation, type Population,
} from '../lib/population';

export interface PopulationContextValue {
  /** The selected population, sent as ``scope`` with every site-metric request. */
  scope: Population;
  /** "On-Air" / "O&M Start". */
  label: string;
  /** "On-Air sites" / "O&M Start sites". */
  sitesLabel: string;
  setScope: (scope: Population) => void;
}

const PopulationContext = createContext<PopulationContextValue | null>(null);

/**
 * The one source of truth of the site population. Initialised from the URL ``scope`` parameter, else localStorage,
 * else On-Air; every change is saved to localStorage and mirrored into the URL of every page, so links are shareable
 * and a reload keeps the selection. A valid ``scope`` in the URL (a shared link, back / forward) always wins.
 */
export function PopulationProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlScope = parsePopulation(searchParams.get(POPULATION_PARAM));
  const [stored, setStored] = useState<Population>(() => urlScope ?? readStoredPopulation() ?? DEFAULT_POPULATION);
  const scope = urlScope ?? stored;

  useEffect(() => {
    if (scope !== stored) setStored(scope);
    storePopulation(scope);
  }, [scope, stored]);

  // Mirror the selection into the URL of every page (also after a page resets its own filters).
  useEffect(() => {
    if (urlScope) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set(POPULATION_PARAM, scope);
      return next;
    }, { replace: true });
  }, [urlScope, scope, setSearchParams]);

  const setScope = useCallback((next: Population) => {
    setStored(next);
    setSearchParams((current) => {
      const params = new URLSearchParams(current);
      params.set(POPULATION_PARAM, next);
      return params;
    }, { replace: true });
  }, [setSearchParams]);

  const value = useMemo<PopulationContextValue>(
    () => ({ scope, label: populationLabel(scope), sitesLabel: populationSites(scope), setScope }),
    [scope, setScope],
  );
  return <PopulationContext.Provider value={value}>{children}</PopulationContext.Provider>;
}

/**
 * The global population. Outside a PopulationProvider (isolated component tests) it reads and writes the URL
 * ``scope`` parameter only, with On-Air as the default.
 */
export function usePopulation(): PopulationContextValue {
  const context = useContext(PopulationContext);
  const [searchParams, setSearchParams] = useSearchParams();
  const fallbackScope = parsePopulation(searchParams.get(POPULATION_PARAM)) ?? DEFAULT_POPULATION;
  const setFallback = useCallback((next: Population) => {
    setSearchParams((current) => {
      const params = new URLSearchParams(current);
      params.set(POPULATION_PARAM, next);
      return params;
    }, { replace: true });
  }, [setSearchParams]);
  const fallback = useMemo<PopulationContextValue>(
    () => ({ scope: fallbackScope, label: populationLabel(fallbackScope), sitesLabel: populationSites(fallbackScope), setScope: setFallback }),
    [fallbackScope, setFallback],
  );
  return context ?? fallback;
}
