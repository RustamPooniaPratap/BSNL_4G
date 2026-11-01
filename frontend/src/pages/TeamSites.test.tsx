import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { breakdown, filterOptions, records, source } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { TeamMonthlyResponse } from '../types';
import { BucketsSitesPage } from './BucketsSitesPage';
import { CiIePerformancePage } from './CiIePerformancePage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(), fetchTeamMonthly: vi.fn(), fetchBreakdowns: vi.fn(), fetchRecords: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });
const month = { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd' as const, start: '2026-10-01', end: '2026-10-03' };
const nsla = { sites_reported: 2, nsla_sites: 1, nsla_pct: 50, no_value: 0 };
// The same name in two circles: two rows, two different people.
const TEAM: TeamMonthlyResponse = {
  group: 'ci', reporting_date: '2026-10-03', months_available: [month], reporting_month: '2026-10', months: [month],
  totals: { people: 1, sites_in_scope: 4, months: { '2026-10': nsla } },
  rows: [
    { report_type: '4G Saturation', circle: 'MP', name: 'CI East', sites_in_scope: 2, months: { '2026-10': nsla } },
    { report_type: 'LWE', circle: 'MP', name: 'CI East', sites_in_scope: 2, months: { '2026-10': nsla } },
  ],
  unsupported: [], source,
};
const Location = () => { const l = useLocation(); return <p data-testid="location">{l.pathname + l.search}</p>; };
const render = (url: string) => renderWithWorkbook(
  <><Routes><Route path="/teams/ci-ie" element={<CiIePerformancePage />} /><Route path="/thresholds/buckets" element={<BucketsSitesPage />} /></Routes><Location /></>,
  { url });
const lastRecords = () => m.fetchRecords.mock.calls.at(-1)![0] as URLSearchParams;

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchFilterOptions.mockResolvedValue(filterOptions);
  m.fetchTeamMonthly.mockResolvedValue(TEAM);
  m.fetchBreakdowns.mockResolvedValue(breakdown);
  m.fetchRecords.mockResolvedValue(records(2));
});

describe('Uptime Buckets & Site Details', () => {
  it('Flow A: the normal page sends no CI / IE filter and shows no CI / IE controls', async () => {
    render('/thresholds/buckets');
    await waitFor(() => expect(m.fetchRecords).toHaveBeenCalled());
    for (const key of ['team_group', 'team', 'team_project', 'team_circle', 'below_sla']) expect(lastRecords().has(key)).toBe(false);
    expect(Object.fromEntries(m.fetchBreakdowns.mock.calls.at(-1)![0] as URLSearchParams)).not.toHaveProperty('team');
    expect(screen.queryByRole('region', { name: 'CI / IE sites' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Back to CI/ })).not.toBeInTheDocument();
  });

  it('Flow B: a CI name opens that person\'s sites (name, project and circle), with NSLA and Back', async () => {
    const user = userEvent.setup();
    render('/teams/ci-ie?scope=om_start');
    const table = await screen.findByRole('region', { name: 'CI-wise NSLA table' });
    await user.click(within(table).getByRole('link', { name: 'Sites of CI East (LWE MP)' }));  // not the 4G MP CI East
    const banner = await screen.findByRole('region', { name: 'CI / IE sites' });
    expect(banner).toHaveTextContent('CI: CI East· LWE · MP · assigned sites only');
    await waitFor(() => expect(Object.fromEntries(lastRecords())).toMatchObject(
      { team_group: 'ci', team: 'CI East', team_project: 'LWE', team_circle: 'MP', report_type: 'LWE', circle: 'MP', scope: 'om_start' }));
    expect(lastRecords().has('below_sla')).toBe(false);  // every assigned site by default
    expect(Object.fromEntries(m.fetchBreakdowns.mock.calls.at(-1)![0] as URLSearchParams)).toMatchObject({ team: 'CI East', team_circle: 'MP' });

    await user.click(within(banner).getByRole('button', { name: 'NSLA (< 98.5% MTD)' }));
    await waitFor(() => expect(lastRecords().get('below_sla')).toBe('true'));

    // Resetting the page filters keeps the person.
    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    await waitFor(() => expect(lastRecords().get('report_type')).toBeNull());
    expect(Object.fromEntries(lastRecords())).toMatchObject({ team: 'CI East', team_project: 'LWE', team_circle: 'MP' });

    await user.click(within(screen.getByRole('region', { name: 'CI / IE sites' })).getByRole('link', { name: /Back to CI & IE Performance/ }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/teams\/ci-ie\?scope=om_start$/);
    expect(await screen.findByRole('region', { name: 'CI-wise NSLA table' })).toBeInTheDocument();
  });

  it('Flow B: a back address outside CI & IE Performance is not followed', async () => {
    render('/thresholds/buckets?team_group=ie&team=IE%20MP&team_project=4G%20Saturation&team_circle=MP&back=https%3A%2F%2Fevil.example');
    const banner = await screen.findByRole('region', { name: 'CI / IE sites' });
    expect(within(banner).getByRole('link', { name: /Back to CI & IE Performance/ })).toHaveAttribute('href', '/teams/ci-ie');
  });
});
