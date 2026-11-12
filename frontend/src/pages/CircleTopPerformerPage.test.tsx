import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { filterOptions, source } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import { Route, Routes } from 'react-router-dom';
import { CircleTopPerformerPage } from './CircleTopPerformerPage';
import type { GroupRanking, RankedPerson, TopPerformersResponse } from '../types';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchTeamTop: vi.fn(),
}));

const fetchTeamTop = vi.mocked(api.fetchTeamTop);
const lastQuery = () => fetchTeamTop.mock.calls.at(-1)![0] as URLSearchParams;

const person = (name: string, scope: number, nsla: number, rank: number | null, reason: string | null = null): RankedPerson => ({
  name, sites_in_scope: scope, sites_reported: scope, nsla_sites: nsla, nsla_pct: Math.round((1000 * nsla) / scope) / 10,
  eligible: reason === null, reason, rank, other_assignments: [],
});

const ranking = (status: GroupRanking['status'], top: string[], people: RankedPerson[], reason: string | null = null): GroupRanking => ({
  status, reason, top, people_total: people.length, people_eligible: people.filter((p) => p.eligible).length, ranking: people,
});

const testFilterOptions = {
  ...filterOptions,
  circles: [
    { value: 'BH', label: 'Bihar', report_types: ['LWE'], site_count: 1 },
    { value: 'MP', label: 'Madhya Pradesh', report_types: ['4G Saturation', 'LWE'], site_count: 4 },
    { value: 'OD', label: 'Odisha', report_types: ['4G Saturation', 'LWE'], site_count: 3 },
    { value: 'RJ', label: 'Rajasthan', report_types: ['4G Saturation'], site_count: 1 },
  ],
};

const topResponse: TopPerformersResponse = {
  reporting_date: '2026-10-27',
  months_available: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30' },
    { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-27' },
  ],
  reporting_month: '2026-10',
  month: { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-27' },
  months: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30' },
    { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-27' },
  ],
  projects: [
    { report_type: '4G Saturation', sites_in_scope: 3175, nsla: { '2026-10': { sites_reported: 3175, nsla_sites: 11, nsla_pct: 0.35, no_value: 0 } } },
    { report_type: 'LWE', sites_in_scope: 500, nsla: { '2026-10': { sites_reported: 500, nsla_sites: 5, nsla_pct: 1.0, no_value: 0 } } },
  ],
  previous_mtd: null,
  rules: { min_sites: 10, min_people: 2, nsla_threshold_pct: 98.0 },
  circles: [
    {
      report_type: '4G Saturation',
      circle: 'RJ',
      sites_in_scope: 1316,
      nsla_rank: 1,
      nsla: { '2026-10': { sites_reported: 1316, nsla_sites: 1, nsla_pct: 0.1, no_value: 0 } },
      ci: ranking('ranked', ['Rajveer Singh Shekhawat'], [person('Rajveer Singh Shekhawat', 110, 1, 1), person('CI Second', 120, 5, 2)]),
      ie: ranking('tie', ['Amit punia', 'Balveer Singh'], [person('Amit punia', 15, 0, 1), person('Balveer Singh', 15, 0, 1), person('IE Third', 20, 2, 3)]),
    },
    {
      report_type: '4G Saturation',
      circle: 'OD',
      sites_in_scope: 1859,
      nsla_rank: 2,
      nsla: { '2026-10': { sites_reported: 1859, nsla_sites: 10, nsla_pct: 0.5, no_value: 0 } },
      ci: ranking('ranked', ['OD Top CI'], [person('OD Top CI', 100, 1, 1)]),
      ie: ranking('ranked', ['OD Top IE'], [person('OD Top IE', 25, 0, 1)]),
    },
    {
      report_type: 'LWE',
      circle: 'MP',
      sites_in_scope: 500,
      nsla_rank: 1,
      nsla: { '2026-10': { sites_reported: 500, nsla_sites: 5, nsla_pct: 1.0, no_value: 0 } },
      ci: ranking('ranked', ['MP LWE CI'], [person('MP LWE CI', 80, 1, 1)]),
      ie: ranking('ranked', ['MP LWE IE'], [person('MP LWE IE', 20, 0, 1)]),
    },
  ],
  source,
};

describe('CircleTopPerformerPage', () => {
  beforeEach(() => {
    vi.mocked(api.fetchFilterOptions).mockResolvedValue(testFilterOptions);
    fetchTeamTop.mockReset().mockResolvedValue(topResponse);
  });

  const renderCirclePage = (url: string) => {
    return renderWithWorkbook(
      <Routes>
        <Route path="/teams/top/circle/:circleId" element={<CircleTopPerformerPage />} />
        <Route path="/teams/circle/:circleId" element={<CircleTopPerformerPage />} />
        <Route path="/team-performance/circle/:circleId" element={<CircleTopPerformerPage />} />
      </Routes>,
      { url }
    );
  };

  it('renders breadcrumb and displays circle name in header', async () => {
    renderCirclePage('/teams/top/circle/MP?report_type=4G+Saturation');

    const breadcrumb = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(breadcrumb).toBeInTheDocument();
    expect(breadcrumb).toHaveTextContent('Circle-wise Top Performers');
    expect(breadcrumb).toHaveTextContent('Madhya Pradesh');

    const backLink = screen.getByRole('link', { name: 'Circle-wise Top Performers' });
    expect(backLink).toHaveAttribute('href', expect.stringContaining('/teams/top'));
    expect(backLink).toHaveAttribute('href', expect.stringContaining('report_type=4G+Saturation'));
  });

  it('renders CI and IE ranking tables with data for RJ', async () => {
    renderCirclePage('/teams/top/circle/RJ?report_type=4G+Saturation&circle=RJ');

    // Breadcrumb
    const breadcrumb = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(breadcrumb).toHaveTextContent('Rajasthan');

    // Both CI and IE ranking tables must be rendered
    const ciTable = await screen.findByRole('region', { name: /CI ranking table/i });
    expect(ciTable).toBeInTheDocument();
    expect(within(ciTable).getByRole('link', { name: 'Rajveer Singh Shekhawat' })).toBeInTheDocument();

    const ieTable = await screen.findByRole('region', { name: /IE ranking table/i });
    expect(ieTable).toBeInTheDocument();
    expect(within(ieTable).getByRole('link', { name: 'Amit punia' })).toBeInTheDocument();
    expect(within(ieTable).getByRole('link', { name: 'Balveer Singh' })).toBeInTheDocument();
    expect(screen.getByText(/Tie · 2 IEs share the top rank/i)).toBeInTheDocument();

    // API must be queried with circle RJ and the global population
    expect(lastQuery().get('circle')).toBe('RJ');
    expect(lastQuery().get('scope')).toBe('on_air');  // the global population (On-Air by default), no page default
    expect(lastQuery().get('report_type')).toBe('4G Saturation');
  });

  it('handles affected URL /teams/top/circle/R?report_type=4G+Saturation&circle=RJ by falling back to query param', async () => {
    renderCirclePage('/teams/top/circle/R?report_type=4G+Saturation&circle=RJ');

    const breadcrumb = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(breadcrumb).toHaveTextContent('Rajasthan');

    const ciTable = await screen.findByRole('region', { name: /CI ranking table/i });
    expect(ciTable).toBeInTheDocument();
    expect(within(ciTable).getByRole('link', { name: 'Rajveer Singh Shekhawat' })).toBeInTheDocument();
  });

  it('renders ranking data for another circle (OD)', async () => {
    renderCirclePage('/teams/top/circle/OD?report_type=4G+Saturation');

    const breadcrumb = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(breadcrumb).toHaveTextContent('Odisha');

    const ciTable = await screen.findByRole('region', { name: /CI ranking table/i });
    expect(within(ciTable).getByRole('link', { name: 'OD Top CI' })).toBeInTheDocument();

    const ieTable = await screen.findByRole('region', { name: /IE ranking table/i });
    expect(within(ieTable).getByRole('link', { name: 'OD Top IE' })).toBeInTheDocument();
  });

  it('renders ranking data for another project (LWE)', async () => {
    renderCirclePage('/teams/top/circle/MP?report_type=LWE');

    const breadcrumb = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(breadcrumb).toHaveTextContent('Madhya Pradesh');

    const ciTable = await screen.findByRole('region', { name: /CI ranking table/i });
    expect(within(ciTable).getByRole('link', { name: 'MP LWE CI' })).toBeInTheDocument();
  });

  it('preserves and passes different reporting month', async () => {
    renderCirclePage('/teams/top/circle/OD?report_type=4G+Saturation&scope=om_start&month=2026-09');

    await screen.findByRole('region', { name: /CI ranking table/i });
    expect(lastQuery().get('month')).toBe('2026-09');
    expect(lastQuery().get('circle')).toBe('OD');
  });

  it('shows an alert when circle is outside active project available circles', async () => {
    // RJ is only 4G Saturation; navigating under LWE should show the mismatch alert
    renderCirclePage('/teams/top/circle/RJ?report_type=LWE');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Circle unavailable under selected project');
    expect(alert).toHaveTextContent('Rajasthan');
    expect(alert).toHaveTextContent('LWE');
  });

  it('works via alternative routing convention paths (/teams/circle/:id and /team-performance/circle/:id)', async () => {
    renderCirclePage('/teams/circle/MP');
    expect(await screen.findByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Madhya Pradesh');
  });
});
