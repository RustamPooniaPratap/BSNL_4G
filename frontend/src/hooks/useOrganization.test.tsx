import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import type { OrganizationCatalog } from '../types/organization';
import { activeCirclesOf, invalidateOrganization, useOrganization } from './useOrganization';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchOrganizationCatalog: vi.fn(),
}));

const catalog = (circles: string[]): OrganizationCatalog => ({
  projects: [{ key: 'LWE', code: 'LWE', name: 'LWE', is_active: true }],
  circles: circles.map((code) => ({ code, name: code, is_active: true })),
  associations: circles.map((circle) => ({ project: 'LWE', circle, is_active: circle !== 'OD' })),
});

function LweCircles() {
  const { data } = useOrganization();
  return <p data-testid="circles">{activeCirclesOf(data, 'LWE').join(',')}</p>;
}

describe('useOrganization', () => {
  it('reloads every mounted selector after an Organization change, and offers active associations only', async () => {
    vi.mocked(api.fetchOrganizationCatalog).mockResolvedValueOnce(catalog(['BH', 'OD'])).mockResolvedValueOnce(catalog(['BH', 'KL', 'OD']));
    render(<LweCircles />);
    expect(await screen.findByText('BH')).toBeInTheDocument();  // OD's association is inactive: not offered
    act(() => invalidateOrganization());  // e.g. KL associated with LWE on the Organization page
    expect(await screen.findByText('BH,KL')).toBeInTheDocument();
    expect(api.fetchOrganizationCatalog).toHaveBeenCalledTimes(2);
  });
});
