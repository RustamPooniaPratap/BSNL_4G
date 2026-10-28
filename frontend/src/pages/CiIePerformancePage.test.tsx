import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { filterOptions, source } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { NslaValue, TeamMonthlyResponse } from '../types';
import { CiIePerformancePage } from './CiIePerformancePage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchTeamMonthly: vi.fn(),
}));

const fetchTeamMonthly = vi.mocked(api.fetchTeamMonthly);
const lastQuery = () => fetchTeamMonthly.mock.calls.at(-1)![0] as URLSearchParams;
const nsla = (nsla_sites: number, sites: number, no_value = 0): NslaValue => ({
  sites_reported: sites - no_value, nsla_sites, nsla_pct: Math.round((10000 * nsla_sites) / sites) / 100, no_value,
});

// Values as the backend returns them (it does every calculation); rows in name order.
const response: TeamMonthlyResponse = {
  group: 'ci',
  reporting_date: '2026-10-21',
  months_available: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30' },
    { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-21' },
  ],
  reporting_month: '2026-10',
  months: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30' },
    { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-21' },
  ],
  totals: { people: 2, sites_in_scope: 14, months: { '2026-09': nsla(9, 14), '2026-10': nsla(5, 14) } },
  rows: [
    { report_type: '4G Saturation', circle: 'MP', name: 'Abhay Tiwari', sites_in_scope: 10, months: { '2026-09': nsla(8, 10), '2026-10': nsla(2, 10) } },
    { report_type: 'LWE', circle: 'OD', name: 'Amit Dash', sites_in_scope: 3, months: { '2026-09': nsla(1, 3), '2026-10': nsla(3, 3) } },
    { report_type: '4G Saturation', circle: 'RJ', name: 'Unassigned', sites_in_scope: 1, months: { '2026-09': null, '2026-10': null } },
  ],
  unsupported: [{ field: 'RCA-wise columns', reason: 'The source has no RCA per site and month.' }],
  source,
};

beforeEach(() => {
  vi.mocked(api.fetchFilterOptions).mockResolvedValue(filterOptions);
  fetchTeamMonthly.mockReset().mockResolvedValue(response);
});

const bodyRows = async () => {
  const table = await screen.findByRole('region', { name: 'CI-wise NSLA table' });
  return within(table).getAllByRole('row').slice(1, -1);  // header and totals excluded
};

describe('CiIePerformancePage', () => {
  it('shows the backend values per person in name order, with no rank', async () => {
    renderWithWorkbook(<CiIePerformancePage />, { url: '/teams/ci-ie' });
    const rows = await bodyRows();
    expect(rows.map((r) => within(r).getAllByRole('rowheader')[0].textContent)).toEqual(['Abhay Tiwari', 'Amit Dash', 'Unassigned']);
    expect(rows[0]).toHaveTextContent('MP4G102' + '20.0%' + '8 (80.0%)');
    expect(rows[2]).toHaveTextContent('—');  // no site reported: not zero
    expect(screen.queryByText('#')).not.toBeInTheDocument();
    expect(screen.getByText(/RCA-wise columns/)).toBeInTheDocument();
    expect(lastQuery().get('group')).toBe('ci');
    expect(lastQuery().get('scope')).toBe('om_start');
    expect(lastQuery().has('month')).toBe(false);
  });

  it('sorts a numeric column on request, keeping missing values last, and searches by name', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<CiIePerformancePage />, { url: '/teams/ci-ie' });
    await bodyRows();
    await user.click(screen.getByRole('button', { name: 'NSLA %' }));
    expect((await bodyRows()).map((r) => within(r).getAllByRole('rowheader')[0].textContent)).toEqual(['Amit Dash', 'Abhay Tiwari', 'Unassigned']);

    await user.type(screen.getByRole('searchbox', { name: 'Search CIs by name' }), 'abhay');
    expect(await bodyRows()).toHaveLength(1);
    await user.clear(screen.getByRole('searchbox', { name: 'Search CIs by name' }));
    await user.type(screen.getByRole('searchbox', { name: 'Search CIs by name' }), 'nobody');
    expect(await screen.findByText('No CI matches “nobody”.')).toBeInTheDocument();
  });

  it('requests IEs and an earlier reporting month', async () => {
    renderWithWorkbook(<CiIePerformancePage />, { url: '/teams/ci-ie?group=ie&month=2026-09' });
    await waitFor(() => expect(lastQuery().get('group')).toBe('ie'));
    expect(lastQuery().get('month')).toBe('2026-09');
  });

  it('shows an empty state when no one is assigned', async () => {
    fetchTeamMonthly.mockResolvedValue({ ...response, rows: [] });
    renderWithWorkbook(<CiIePerformancePage />, { url: '/teams/ci-ie' });
    expect(await screen.findByText('No CIs are assigned to sites in the selected filters.')).toBeInTheDocument();
  });
});
