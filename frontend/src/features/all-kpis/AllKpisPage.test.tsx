import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CI_PERMISSIONS, CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import * as api from './api';
import { AllKpisPage } from './AllKpisPage';
import type { KpiFilterOptions, KpiHierarchy, KpiSummary, KpiValues } from './types';

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
  pending: { site_handover_status: 'Pending clarification', rca_ownership: 'Not configured' },
};
const OPTIONS: KpiFilterOptions = {
  dates: ['2026-10-31', '2026-11-01'], default_period: { start: '2026-11-01', end: '2026-11-01' }, projects: ['4G Saturation', 'LWE'], circles: ['MP', 'RJ'],
  cis: [{ key: 'RJ::Guddu Singh', label: 'Guddu Singh', circle: 'RJ' }], ies: [], sites: [], site_count: 120,
  buckets: [{ key: 'lt_60', label: 'Below 60%' }], final_buckets: ['TCS', 'Not mapped'],
};
const CIRCLES: KpiHierarchy = { level: 'circle', rows: [{ ...values(), key: 'RJ', project: '4G Saturation', circle: 'RJ' }] };
const Location = () => { const l = useLocation(); return <p data-testid="location">{l.search}</p>; };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchKpiFilters.mockResolvedValue(OPTIONS);
  m.fetchKpiSummary.mockResolvedValue(SUMMARY);
  m.fetchKpiTrends.mockResolvedValue({ granularity: 'day', points: [] });
  m.fetchKpiHierarchy.mockResolvedValue(CIRCLES);
  m.fetchKpiSites.mockResolvedValue({ total: 0, page: 1, pages: 1, rows: [] });
  m.fetchKpiRca.mockResolvedValue({ records: 0, buckets: [], ownership: { configured: false, message: 'Not configured: no approved mapping.' } });
});

describe("All KPI's", () => {
  it('shows backend KPIs, marks O&M-dependent values Not available and lists the pending items', async () => {
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis' });
    const usd = await screen.findByRole('group', { name: 'USD sites' });
    expect(usd).toHaveTextContent('Not available');
    expect(screen.getByRole('group', { name: 'O&M Start sites' })).toHaveTextContent('Not available');
    expect(screen.getByRole('status')).toHaveTextContent('O&M Start data is not available for Nov 2026');
    expect(screen.getByRole('group', { name: 'Site Handover Status' })).toHaveTextContent('Pending clarification');
    expect(screen.getByRole('group', { name: 'Availability (selected period)' })).toHaveTextContent('98.745%');
    expect(screen.getByRole('group', { name: 'Missing availability (site-days)' })).toHaveTextContent('2');
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

  it('shows the RCA tab only with RCA Summary View, with ownership Not Configured', async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis', auth: authValue({ user: CI_USER }) });
    const nav = await screen.findByRole('navigation', { name: "All KPI's sections" });
    expect(within(nav).queryByRole('button', { name: 'RCA' })).not.toBeInTheDocument();
    unmount();
    renderWithWorkbook(<AllKpisPage />, { url: '/all-kpis', auth: authValue({ user: { ...CI_USER, permissions: { ...CI_PERMISSIONS, rca_summary: ['view'] } } }) });
    await user.click(within(await screen.findByRole('navigation', { name: "All KPI's sections" })).getByRole('button', { name: 'RCA' }));
    for (const g of ['Own', 'Customer', 'Third Party', 'Pending']) expect(await screen.findByRole('group', { name: g })).toHaveTextContent('Not Configured');
  });
});
