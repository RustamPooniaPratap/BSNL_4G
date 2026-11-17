import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CI_PERMISSIONS, CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import { Sidebar } from '../../components/Sidebar';
import * as api from './api';
import { AllKpisPage } from './AllKpisPage';
import type { KpiFilterOptions, KpiHierarchy, KpiSummary, KpiTrendPoint, KpiValues } from './types';

vi.mock('./api', () => ({
  fetchKpiFilters: vi.fn(), fetchKpiSummary: vi.fn(), fetchKpiTrends: vi.fn(), fetchKpiHierarchy: vi.fn(), fetchKpiSites: vi.fn(), fetchKpiRca: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });

const values = (over: Partial<KpiValues> = {}): KpiValues => ({
  total_sites: 120, on_air_sites: 110, om_start_sites: null, availability_pct: 98.7452, outage_minutes: 24573, outage_hours: 409.56,
  usd_sites: null, nsla_sites: null, above_98_5_sites: 90, below_98_5_sites: 18, below_60_sites: 2, sites_with_values: 108,
  buckets: {}, missing_site_days: 2, expected_site_days: 110, reported_site_days: 108, coverage_pct: 98.2, sites_missing_any_day: 2, sites_without_any_value: 2, ...over,
});
const SUMMARY: KpiSummary = {
  period: { start: '2026-11-01', end: '2026-11-01', label: '01 Nov 2026', days_with_data: 1, days_in_period: 1 },
  previous_period: { start: '2026-10-31', end: '2026-10-31', label: '31 Oct 2026', days_with_data: 1 },
  current: values(), previous: values({ om_start_sites: 100, usd_sites: 40, nsla_sites: 20 }),
  om_start: { months: ['2026-11'], missing_months: ['Nov 2026'], available: false, complete: false },
  pending: { rca_ownership: 'Responsibility classification uses the current Final Bucket mapping.' },
};
const OPTIONS: KpiFilterOptions = {
  dates: ['2026-10-31', '2026-11-01'], default_period: { start: '2026-11-01', end: '2026-11-01' }, projects: ['4G Saturation', 'LWE'], circles: ['MP', 'RJ'],
  cis: [{ key: 'RJ::Guddu Singh', label: 'Guddu Singh', circle: 'RJ' }], ies: [], sites: [], site_count: 120,
  buckets: [{ key: 'lt_60', label: 'Below 60%' }, { key: '60_90', label: '60% to 90%' }, { key: 'gte_98_5', label: '98.5% and above' }],
  final_buckets: ['TCS', 'Not mapped'],
  responsibilities: ['Own', 'Customer', 'Third party', 'Pending', 'Unclassified'].map((key) => ({ key, label: key })),
};
const row = (circle: string, over: Partial<KpiValues> = {}) => ({ ...values(over), key: circle, project: '4G Saturation', circle });
// Six circles, so the ranking shades the three lowest.
const CIRCLES: KpiHierarchy = { level: 'circle', rows: [
  row('RJ'), row('MP', { availability_pct: 99.5, outage_minutes: 600, outage_hours: 10 }), row('OD', { availability_pct: 97.1, outage_minutes: 4800, outage_hours: 80 }), row('BH', { availability_pct: 95.2, outage_minutes: 7200, outage_hours: 120 }),
  row('UP', { availability_pct: 99.9, outage_minutes: 120, outage_hours: 2 }), row('KL', { availability_pct: 58.4, outage_minutes: 30000, outage_hours: 500, below_60_sites: 9 }),
] };
const PREVIOUS: KpiHierarchy = { level: 'circle', rows: [row('RJ', { availability_pct: 99.9 }), row('MP', { availability_pct: 98.0 })] };
const point = (key: string, label: string, over: Partial<KpiTrendPoint> = {}): KpiTrendPoint => ({
  key, label, start: '2026-10-01', end: '2026-10-31', days: 31, availability_pct: 98.9, outage_minutes: 1000, outage_hours: 16.7, usd_sites: 12, nsla_sites: 4,
  below_98_5_sites: 10, below_60_sites: 1, coverage_pct: 99, missing_site_days: 3, ...over,
});
const Location = () => { const l = useLocation(); return <p data-testid="location">{l.search}</p>; };
const isPrevious = (p: URLSearchParams) => p.get('date_from') === '2026-10-31';

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchKpiFilters.mockResolvedValue(OPTIONS);
  m.fetchKpiSummary.mockResolvedValue(SUMMARY);
  m.fetchKpiTrends.mockResolvedValue({ granularity: 'day', points: [] });
  m.fetchKpiHierarchy.mockImplementation(async (p: URLSearchParams) => (isPrevious(p) ? PREVIOUS : CIRCLES));
  m.fetchKpiSites.mockResolvedValue({ total: 0, page: 1, pages: 1, rows: [] });
  m.fetchKpiRca.mockResolvedValue({
    records: 0, buckets: [], ownership: { configured: true, message: 'Responsibility classification uses the current Final Bucket mapping.',
      buckets: ['Own', 'Customer', 'Third party', 'Pending', 'Unclassified'].map((bucket) => ({
        bucket, label: bucket === 'Third party' ? 'Third Party' : bucket, records: 0, outage_minutes: 0, share_pct: null,
      })) },
  });
});

describe("All KPI's", () => {
  it('shows backend KPIs and marks O&M-dependent values Not available', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    const usd = await screen.findByRole('group', { name: 'USD Sites' });
    expect(usd).toHaveTextContent('Not available');
    expect(screen.queryByText(/O&M Start data is not available/)).not.toBeInTheDocument();  // On-Air population: nothing depends on it here
    expect(screen.queryByText(/handover/i)).not.toBeInTheDocument();  // not a project concept: no card, label or placeholder
    expect(screen.getByRole('group', { name: 'Availability (selected period)' })).toHaveTextContent('98.75%');
    expect(screen.getByRole('group', { name: 'Outage minutes' })).toHaveTextContent('24,573 min');  // minutes from outage_minutes, never hours
    expect(screen.queryByRole('group', { name: 'Outage hours' })).not.toBeInTheDocument();
  });

  it('shows the overview KPIs in one grid, without the banner, Site Portfolio or Data Completeness', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    const grid = await screen.findByRole('region', { name: 'Key indicators' });
    const tiles = within(grid).getAllByRole('group').map((g) => g.getAttribute('aria-label'));
    expect(tiles).toEqual(['Availability (selected period)', 'Daily availability', 'Weekly availability', 'Monthly availability', 'Outage minutes',
      'USD Sites', 'NSLA Sites (< 98.5%)', 'Sites ≥ 98.5% (period)', 'Sites < 60% (period)']);  // Sites < 98.5% = NSLA Sites: one tile
    expect(new Set(tiles).size).toBe(tiles.length);  // no duplicates
    expect(screen.queryByText(/4G & LWE Site Performance/)).not.toBeInTheDocument();  // the banner
    expect(screen.queryByRole('region', { name: 'Site Portfolio' })).not.toBeInTheDocument();
    for (const gone of ['Total sites', 'On-Air sites', 'O&M Start sites', 'Reporting coverage', 'Missing availability (site-days)', 'Sites missing a day', 'Sites without any value'])
      expect(screen.queryByRole('group', { name: gone })).not.toBeInTheDocument();
    expect(screen.queryByText(/Data Completeness/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'View title' })).not.toBeInTheDocument();  // no heading card on the overview
    for (const gone of [/coverage/i, /missing site-days/i]) expect(screen.queryByText(gone)).not.toBeInTheDocument();
  });

  it('names the period of each availability tile: selected period, latest day / week of it, latest calendar month', async () => {
    m.fetchKpiTrends.mockImplementation(async (p: URLSearchParams) => {
      const g = p.get('granularity') as 'day' | 'week' | 'month';
      const label = { day: '01 Nov', week: 'W1 Nov 2026', month: 'Nov 2026 (MTD)' }[g];
      return { granularity: g, points: [point('k', label, { availability_pct: 97.25 })] };
    });
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    const grid = await screen.findByRole('region', { name: 'Key indicators' });
    expect(within(grid).getByRole('group', { name: 'Availability (selected period)' })).toHaveTextContent('01 Nov 2026 · outage-weighted');
    expect(await within(grid).findByText('Latest day of the selected period: 01 Nov')).toBeInTheDocument();
    expect(within(grid).getByText('Latest week of the selected period: W1 Nov 2026')).toBeInTheDocument();
    expect(within(grid).getByText(/Latest month with data: Nov 2026 \(MTD\), a calendar month \(not limited to the selected period\)/)).toBeInTheDocument();
    expect(within(grid).queryByRole('group', { name: 'Sites < 98.5% (period)' })).not.toBeInTheDocument();
  });

  it('has no heading card on any view: the KPI views keep their definition line and the O&M Start data check', async () => {
    for (const tab of ['trends', 'availability', 'usd', 'below_60', 'ranking', 'drilldown']) {
      const { unmount } = renderWithWorkbook(<AllKpisPage />, { url: `/all-kpis?tab=${tab}&scope=om_start` });
      expect(await screen.findByText(/O&M Start data is not available for Nov 2026/)).toBeInTheDocument();
      expect(screen.queryByRole('region', { name: 'View title' })).not.toBeInTheDocument();
      unmount();
    }
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis?tab=availability' });
    expect(await screen.findByLabelText('How Availability is calculated')).toHaveTextContent('Outage-weighted availability');
  });

  it('shows the overview data check without a heading card for the O&M Start population', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis?scope=om_start' });
    expect(await screen.findByText(/O&M Start data is not available for Nov 2026/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'View title' })).not.toBeInTheDocument();
  });

  it('keeps every filter in the compact filter bar, with Reset at its end', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    const bar = await screen.findByRole('search', { name: "All KPI's filters" });
    for (const name of ['From', 'To', 'Population']) expect(within(bar).getByLabelText(name)).toBeInTheDocument();
    for (const name of [/^Project:/, /^Circle:/, /^CI \/ Cluster:/, /^IE:/, /^Site:/, /^Availability bucket:/]) expect(within(bar).getByRole('button', { name })).toBeInTheDocument();
    const buttons = within(bar).getAllByRole('button');
    expect(buttons.at(-1)).toHaveAccessibleName('Reset filters');
  });

  it('opens the overview for a link to the removed Data Completeness view', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis?tab=completeness' });
    expect(await screen.findByRole('region', { name: 'Key indicators' })).toBeInTheDocument();
  });

  it('labels the existing USD metric as USD Sites, never USD Events, and removes the reference report tools', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    expect(await screen.findByRole('group', { name: 'USD Sites' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: "All KPI's sections" })).not.toBeInTheDocument();
    expect(screen.queryByText(/USD events/i)).not.toBeInTheDocument();
    for (const tool of [/Upload Excel/i, /Sample data/i, /Input format/i, /Export to Excel/i, /Print/i, /Settings/i, /letter/i, /email/i, /MTTR/i, /score/i])
      expect(screen.queryByRole('button', { name: tool })).not.toBeInTheDocument();
  });

  it('ranks the circles by the existing availability, with the previous rank, the total of the filters and the three lowest shaded', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    const table = await screen.findByRole('region', { name: 'Ranking · Circle-wise table' });
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(8));  // header, 6 circles, total
    const names = within(table).getAllByRole('button', { name: /^Open Circle/ }).map((b) => b.textContent);
    expect(names).toEqual(['UP', 'MP', 'RJ', 'OD', 'BH', 'KL']);  // highest availability first, as the API reports it
    const rj = within(table).getByRole('button', { name: 'Open Circle RJ (4G)' }).closest('tr')!;
    expect(rj).toHaveTextContent('98.75%');
    await waitFor(() => expect(rj).toHaveTextContent('▼ 2'));  // rank 1 → 3 against the previous period
    expect(within(table).getByRole('button', { name: 'Open Circle KL (4G)' }).closest('tr')).toHaveClass('bottom');
    expect(within(table).getByRole('row', { name: 'Total of the selected filters' })).toHaveTextContent('98.75%');
    // The previous ranks come from the same endpoint with the summary's comparison period.
    expect(m.fetchKpiHierarchy.mock.calls.some(([p]) => isPrevious(p as URLSearchParams) && (p as URLSearchParams).get('date_to') === '2026-10-31')).toBe(true);
  });

  it('opens a KPI view from the menu with this period against the previous and the units ranked by it', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><AllKpisPage /><Location /></>, { url: '/all-kpis' });
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Outage Minutes' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('tab=outage'));
    const strip = await screen.findByRole('group', { name: 'Outage minutes: this period against the previous' });
    expect(strip).toHaveTextContent('24,573 min');  // canonical outage minutes (display rounding only)
    expect(strip).not.toHaveTextContent(/\d h\b/);
    const table = await screen.findByRole('region', { name: 'Circle-wise · Outage minutes table' });
    await waitFor(() => expect(within(table).getAllByRole('button', { name: /^Open Circle/ }).map((b) => b.textContent)).toEqual(['UP', 'MP', 'OD', 'BH', 'RJ', 'KL']));  // lowest outage first
    expect(screen.getByRole('img', { name: /Outage minutes: weakest/ })).toBeInTheDocument();
  });

  it('lists the sites of a threshold KPI through the existing bucket filter', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis?tab=below_60' });
    expect(await screen.findByRole('region', { name: 'Site list – Sites < 60%' })).toBeInTheDocument();
    await waitFor(() => expect(m.fetchKpiSites.mock.calls.some(([p]) => (p as URLSearchParams).get('bucket') === 'lt_60')).toBe(true));
  });

  it('shows the month-wise trend of every KPI from the trends endpoint', async () => {
    m.fetchKpiTrends.mockResolvedValue({ granularity: 'month', points: [point('2026-09', 'Sep 26', { availability_pct: 98.2 }), point('2026-10', 'Oct 26', { status: 'Provisional' })] });
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis?tab=trends' });
    const table = await screen.findByRole('region', { name: 'KPI trend table' });
    expect(within(table).getByRole('columnheader', { name: 'Oct 26*' })).toBeInTheDocument();
    expect(within(table).getByRole('row', { name: /^Availability/ })).toHaveTextContent('98.20%');
    expect(within(table).getByRole('row', { name: /^USD Sites/ })).toBeInTheDocument();
    expect(m.fetchKpiTrends.mock.calls.some(([p]) => (p as URLSearchParams).get('granularity') === 'month')).toBe(true);
  });

  it('removes the horizontal KPI navigation without changing the displayed section data', async () => {
    renderWithWorkbook(<><Sidebar /><AllKpisPage /></>, { url: '/all-kpis?tab=availability' });
    expect(screen.queryByRole('navigation', { name: "All KPI's sections" })).not.toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Availability' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('group', { name: 'Availability: this period against the previous' })).toHaveTextContent('98.75%');
  });

  it('drills from a circle to its CIs, keeping the filters in the URL', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><AllKpisPage /><Location /></>, { url: '/all-kpis?tab=drilldown' });
    await user.click(await screen.findByRole('button', { name: 'Open Circle RJ (4G)' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('level=ci'));
    expect(screen.getByTestId('location')).toHaveTextContent('circle=RJ');
    expect(Object.fromEntries(m.fetchKpiHierarchy.mock.calls.at(-1)![0] as URLSearchParams)).toMatchObject({ level: 'ci', circle: 'RJ', project: '4G Saturation' });
    await user.click(screen.getByRole('button', { name: /Back/ }));
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('level='));
  });

  it('shows the RCA view only with RCA Summary View and current responsibility totals', async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithWorkbook(<><Sidebar /><AllKpisPage /></>, { url: '/all-kpis', auth: authValue({ user: CI_USER }) });
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(within(nav).queryByRole('link', { name: 'RCA' })).not.toBeInTheDocument();
    unmount();
    renderWithWorkbook(<><Sidebar /><AllKpisPage /></>, { url: '/all-kpis', auth: authValue({ user: { ...CI_USER, permissions: { ...CI_PERMISSIONS, rca_summary: ['view'] } } }) });
    await user.click(within(await screen.findByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'RCA' }));
    for (const g of ['Own', 'Customer', 'Third Party', 'Pending', 'Unclassified']) expect(await screen.findByRole('group', { name: g })).toHaveTextContent('0');
    expect(screen.getByText('Configured')).toBeInTheDocument();
  });
});
