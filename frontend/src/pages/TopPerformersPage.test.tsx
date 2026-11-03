import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { filterOptions, source } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { GroupRanking, RankedPerson, TopPerformersResponse } from '../types';
import { TopPerformersPage } from './TopPerformersPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchTeamTop: vi.fn(),
}));

const fetchTeamTop = vi.mocked(api.fetchTeamTop);
const lastQuery = () => fetchTeamTop.mock.calls.at(-1)![0] as URLSearchParams;

const person = (name: string, scope: number, nsla: number, rank: number | null, reason: string | null = null, other: string[] = []): RankedPerson => ({
  name, sites_in_scope: scope, sites_reported: scope, nsla_sites: nsla, nsla_pct: Math.round((1000 * nsla) / scope) / 10,
  eligible: reason === null, reason, rank, other_assignments: other,
});
const ranking = (status: GroupRanking['status'], top: string[], people: RankedPerson[], reason: string | null = null): GroupRanking => ({
  status, reason, top, people_total: people.length, people_eligible: people.filter((p) => p.eligible).length, ranking: people,
});

const nsla = (count: number, scope: number) => ({ sites_reported: scope, nsla_sites: count, nsla_pct: Math.round((10000 * count) / scope) / 100, no_value: 0 });

// The backend ranks; the page only shows its answer.
const response: TopPerformersResponse = {
  reporting_date: '2026-10-20',
  months_available: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30' },
    { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-20' },
  ],
  reporting_month: '2026-10',
  month: { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-20' },
  months: [
    { key: '2026-09', label: 'Sep-26', kind: 'month', start: '2026-09-01', end: '2026-09-30' },
    { key: '2026-10', label: 'Oct-26 MTD', kind: 'mtd', start: '2026-10-01', end: '2026-10-20' },
  ],
  previous_mtd: { key: '2026-09-mtd', label: 'Sep-26 MTD', kind: 'previous_mtd', start: '2026-09-01', end: '2026-09-20', available: true, reason: null },
  projects: [{ report_type: 'LWE', sites_in_scope: 312, nsla: { '2026-09': nsla(222, 312), '2026-10': nsla(112, 312), '2026-09-mtd': nsla(15, 62) } }],
  rules: { min_sites: 10, min_people: 2, nsla_threshold_pct: 98.5 },
  circles: [
    {
      report_type: 'LWE', circle: 'AP', sites_in_scope: 62, nsla_rank: 1,
      nsla: { '2026-09': nsla(21, 62), '2026-10': nsla(11, 62), '2026-09-mtd': nsla(15, 62) },
      ci: ranking('insufficient', [], [person('Krishna Sundaram', 62, 11, 1)], '1 of 1 eligible; at least 2 are needed to compare.'),
      ie: ranking('ranked', ['Naidana Ashok'], [person('Naidana Ashok', 14, 1, 1), person('Other IE', 20, 5, 2), person('Tiny IE', 3, 0, null, 'Fewer than 10 assigned sites; too small to compare fairly.')]),
    },
    {
      report_type: 'LWE', circle: 'BH', sites_in_scope: 250, nsla_rank: 2,
      nsla: { '2026-09': nsla(201, 250), '2026-10': nsla(101, 250), '2026-09-mtd': null },
      ci: ranking('ranked', ['Gaurav Kumar'], [person('Gaurav Kumar', 105, 36, 1, null, ['JH LWE']), person('BH-TBD', 145, 65, 2)]),
      ie: ranking('tie', ['Md. Mazhar Imam', 'Yugesh Kumar Singh'], [person('Md. Mazhar Imam', 12, 0, 1), person('Yugesh Kumar Singh', 12, 0, 1), person('Third', 30, 6, 3)]),
    },
  ],
  source,
};

beforeEach(() => {
  vi.mocked(api.fetchFilterOptions).mockResolvedValue(filterOptions);
  fetchTeamTop.mockReset().mockResolvedValue(response);
});

const circleRow = async (circle: string) => {
  const table = await screen.findByRole('region', { name: 'Top performers by circle' });
  return within(table).getByRole('rowheader', { name: `${circle} LWE` }).closest('tr') as HTMLElement;
};

describe('TopPerformersPage', () => {
  it('shows the top CI and IE of each circle, insufficient data and ties as given by the backend', async () => {
    renderWithWorkbook(<TopPerformersPage />, { url: '/teams/top' });
    const ap = await circleRow('AP');
    expect(ap).toHaveTextContent('Insufficient data');
    expect(ap).toHaveTextContent('1 of 1 eligible');
    expect(within(ap).queryByRole('link', { name: 'Krishna Sundaram' })).not.toBeInTheDocument();
    expect(within(ap).getByRole('link', { name: 'Naidana Ashok' })).toHaveAttribute('href', expect.stringContaining('/teams/ci-ie?report_type=LWE&circle=AP'));
    expect(ap).toHaveTextContent('1 of 14 sites NSLA');

    const bh = await circleRow('BH');
    expect(bh).toHaveTextContent('Tie · 2');
    expect(within(bh).getByRole('link', { name: 'Md. Mazhar Imam' })).toBeInTheDocument();
    expect(within(bh).getByRole('link', { name: 'Yugesh Kumar Singh' })).toBeInTheDocument();
    expect(lastQuery().get('scope')).toBe('om_start');
    expect(lastQuery().has('month')).toBe(false);
  });

  it('does not render CI and IE ranking tables on the page', async () => {
    renderWithWorkbook(<TopPerformersPage />, { url: '/teams/top' });
    await circleRow('AP');
    expect(screen.queryByRole('region', { name: /CI ranking table/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /IE ranking table/i })).not.toBeInTheDocument();
  });

  it('makes individual circle rows clickable while project total is not', async () => {
    renderWithWorkbook(<TopPerformersPage />, { url: '/teams/top' });
    const table = await screen.findByRole('region', { name: 'Circle-wise NSLA by month' });
    const apHeader = within(table).getByRole('rowheader', { name: /AP/i });
    const apRow = apHeader.closest('tr')!;
    expect(apRow).toHaveClass('cursor-pointer');
    expect(within(apRow).getByText('AP')).toBeInTheDocument();

    // Total row is NOT clickable
    const totalHeader = within(table).getByRole('rowheader', { name: /LWE total/i });
    const totalRow = totalHeader.closest('tr')!;
    expect(totalRow).not.toHaveClass('cursor-pointer');
  });

  it('shows circle-wise NSLA by month with the project total and the rank from the backend', async () => {
    renderWithWorkbook(<TopPerformersPage />, { url: '/teams/top' });
    const table = await screen.findByRole('region', { name: 'Circle-wise NSLA by month' });
    const rows = within(table).getAllByRole('row');
    expect(rows[0]).toHaveTextContent('NSLA · Oct-26 MTD');
    expect(rows[0]).toHaveTextContent('Sep-26');
    expect(rows[1]).toHaveTextContent('LWE total');
    expect(rows[1]).toHaveTextContent('112');
    expect(rows[1]).toHaveTextContent('35.9%');
    expect(rows[2]).toHaveTextContent('AP');
    expect(rows[2]).toHaveTextContent('17.7%');
    expect(rows[2]).toHaveTextContent('21');
    expect(rows[3]).toHaveTextContent('BH');
    // Sep-26 MTD beside the month to date; a circle without September daily data shows "—", not 0.
    const headers = within(rows[0]).getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers.indexOf('Sep-26 MTD')).toBe(headers.indexOf('Rank') + 1);
    const sepMtd = (row: HTMLElement) => within(row).getAllByRole('cell')[headers.indexOf('Sep-26 MTD') - 1].textContent;
    expect(sepMtd(rows[2])).toBe('1524%');
    expect(sepMtd(rows[3])).toBe('—');
  });

  it('requests an earlier reporting month', async () => {
    renderWithWorkbook(<TopPerformersPage />, { url: '/teams/top?month=2026-09&report_type=LWE' });
    await waitFor(() => expect(lastQuery().get('month')).toBe('2026-09'));
    expect(lastQuery().get('report_type')).toBe('LWE');
  });

  it('shows an empty state', async () => {
    fetchTeamTop.mockResolvedValue({ ...response, circles: [] });
    renderWithWorkbook(<TopPerformersPage />, { url: '/teams/top' });
    expect(await screen.findByText('No circle has sites assigned to a CI or IE for the selected filters.')).toBeInTheDocument();
  });
});
