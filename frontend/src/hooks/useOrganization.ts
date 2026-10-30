import { useEffect, useState } from 'react';
import { fetchOrganizationCatalog } from '../services/api';
import type { OrganizationCatalog } from '../types/organization';
import { useApiQuery } from './useApiQuery';

/** Broadcast after any Organization change, so every selector reloads the catalog. */
const CHANGED = 'organization-changed';
let version = 0;

export function invalidateOrganization() {
  version += 1;
  window.dispatchEvent(new Event(CHANGED));
}

/**
 * Projects, circles and their associations from the server (Administration > Organization), the single source for
 * project and circle selectors. Nothing here decides access: the server checks every request.
 */
export function useOrganization() {
  const [current, setCurrent] = useState(version);
  useEffect(() => {
    const onChange = () => setCurrent(version);
    window.addEventListener(CHANGED, onChange);
    return () => window.removeEventListener(CHANGED, onChange);
  }, []);
  return useApiQuery<OrganizationCatalog>(`organization-catalog|${current}`, fetchOrganizationCatalog);
}

/** Active circles of a project, in code order (the selectors' list). */
export const activeCirclesOf = (catalog: OrganizationCatalog | null, project: string) =>
  (catalog?.associations ?? []).filter((a) => a.project === project && a.is_active).map((a) => a.circle).sort();

/** The project's short label (e.g. "4G"), or the key itself when unknown. */
export const projectCode = (catalog: OrganizationCatalog | null, key: string) => catalog?.projects.find((p) => p.key === key)?.code ?? key;
