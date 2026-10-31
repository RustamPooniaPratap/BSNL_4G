import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '../components/Sidebar';
import * as api from '../services/api';
import { asThresholdResponse, filterOptions, records, thresholds } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { ThresholdResponse, ThresholdValue } from '../types';
import { ThresholdPage } from './ThresholdPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchThresholds: vi.fn(),
  fetchRecords: vi.fn(),
  fetchPeriod: vi.fn(),
}));

const fetchThresholds = vi.mocked(api.fetchThresholds);
const fetchRecords = vi.mocked(api.fetchRecords);
const lastRecords = () => fetchRecords.mock.calls.at(-1)![0] as URLSearchParams;

/**
 * The backend's response for the requested date, period and comparison (resolved as the backend does); MTD to
 * 1 Oct (the previous date) differs so changes can be checked.
 */
function thresholdsFor(params: URLSearchParams, previousMtd: ThresholdValue = null): ThresholdResponse {
  const date = params.get('reporting_date') ?? '2026-10-02';
  const share = (count: number) => ({ count, pct: count * 20 });  // 5 sites in scope
  const total = date !== '2026-10-01' ? thresholds.total : { ...thresholds.total, values: { ...thresholds.total.values, mtd: {
    sites_reported: 5, gte_98_5: share(2), lt_60: share(2), '60_90': share(1), '90_97': share(0), '97_98_5': share(0), below_98_5: share(3), no_value: share(0),
  } } };
  return asThresholdResponse({ ...thresholds, reporting_date: date, total }, params, previousMtd);
}

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

const renderPage = (url = '/thresholds?date=2026-10-02') => renderWithWorkbook(
  <><Routes><Route path="*" element={<ThresholdPage />} /></Routes><Location /></>, { url },
);
const unified = () => screen.getByRole('region', { name: 'Uptime threshold analysis and monthly comparison' });
const findUnified = () => screen.findByRole('region', { name: 'Uptime threshold analysis and monthly comparison' });
const bucketRow = (label: string) => within(unified()).getByRole('row', { name: `${label}: show line chart` });
const cells = (row: HTMLElement) => [...row.querySelectorAll('td')].map((c) => c.textContent);
const headers = () => within(unified()).getAllByRole('columnheader').map((h) => h.textContent);
const kpi = () => screen.getByRole('group', { name: 'Uptime Threshold Summary' });
/** The backend's previous-month MTD over the same days (1–2 Sep): 4 below 60%, 1 in 60-90%, of 5 sites. */
const s = (count: number) => ({ count, pct: count * 20 });
const SEP_MTD = { sites_reported: 5, lt_60: s(4), '60_90': s(1), '90_97': s(0), '97_98_5': s(0), gte_98_5: s(0), below_98_5: s(5), no_value: s(0) } as ThresholdValue;
const periodTable = () => screen.getByRole('table', { name: /by circle and period/ });

beforeEach(() => {
  vi.mocked(api.fetchFilterOptions).mockResolvedValue(filterOptions);
  fetchThresholds.mockReset().mockImplementation(async (params) => thresholdsFor(params));
  fetchRecords.mockReset().mockResolvedValue(records(0));
});

describe('Threshold analysis: one unified table', () => {
  it('defaults to the O&M Start population used by the workbook and passes filters through', async () => {
    renderPage('/thresholds?circle=MP&date=2026-10-02');
    await findUnified();
    const current = fetchThresholds.mock.calls.map((c) => Object.fromEntries(c[0] as URLSearchParams));
    expect(current).toContainEqual(expect.objectContaining({ scope: 'om_start', circle: 'MP', reporting_date: '2026-10-02' }));
    expect(screen.queryByRole('region', { name: 'Bucket comparison' })).not.toBeInTheDocument();  // the two tables are now one
    expect(screen.queryByRole('region', { name: 'Monthly comparison' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('table')).toHaveLength(1);
  });

  it('shows full months, both MTD periods with their dates, MTD shares, the MTD change and Analyse, in that order', async () => {
    renderPage();
    await findUnified();
    expect(screen.getByText('Uptime Threshold Analysis & Monthly Comparison')).toBeInTheDocument();
    expect(headers()).toEqual(['Uptime bucket', 'Sep-26full month', 'Sep-26 MTD01–02 Sep', 'Oct-26 MTD01 Oct–02 Oct',
      '% · Oct-26 MTDof sites in scope', '% · Sep-26 MTDof sites in scope', 'Changesites, MTD vs MTD', 'Analyse']);
    // First data row: the aggregate, then the five buckets.
    const labels = within(unified()).getAllByRole('row').slice(1).map((r) => r.getAttribute('aria-label'));
    expect(labels).toEqual(['Below 98.5% — Total: show line chart', 'Below 60%: show line chart', '60% to <90%: show line chart',
      '90% to <97%: show line chart', '97% to <98.5%: show line chart', '98.5% and above: show line chart']);
    expect(within(unified()).queryByRole('row', { name: 'Grand Total' })).not.toBeInTheDocument();
    // No Sep daily data in this fixture: Sep MTD and the MTD change are not available (never the full month instead).
    expect(cells(bucketRow('Below 98.5% — Total'))).toEqual(['Below 98.5% — Total', '3', '—', '2', '—', '—', '—', '']);
    expect(cells(bucketRow('Below 60%'))).toEqual(['Below 60%', '2', '—', '1', '—', '—', '—', '']);
    expect(bucketRow('Below 60%').querySelector('td')).toHaveAttribute('title', 'uptime < 60%');  // the rule is the row's tooltip
    expect(cells(bucketRow('98.5% and above')).slice(0, 4)).toEqual(['98.5% and above', '1', '—', '3']);
    expect(within(bucketRow('Below 98.5% — Total')).queryByRole('button')).not.toBeInTheDocument();  // the aggregate has no Analyse
    expect(within(unified()).getByRole('list', { name: 'Unavailable columns' })).toHaveTextContent(
      'Sep-26 MTD: Sep-26 has no daily data in the source for days 1–2, so its MTD cannot be computed.');
    expect(api.fetchPeriod).not.toHaveBeenCalled();  // every column comes from thresholds/ (the backend)
  });

  it('compares the month to date with the same days of the previous month, as computed by the backend', async () => {
    fetchThresholds.mockImplementation(async (params) => thresholdsFor(params, SEP_MTD));
    renderPage();
    await findUnified();
    // Oct MTD 2 (40%) vs Sep 1–2: 5 (100%); the full month (3) stays in its own column and is not the comparison.
    expect(cells(bucketRow('Below 98.5% — Total')).slice(1, 7)).toEqual(['3', '5', '2', '40.00%', '100.00%', '-3']);
    expect(cells(bucketRow('Below 60%')).slice(1, 7)).toEqual(['2', '4', '1', '20.00%', '80.00%', '-3']);
    expect(cells(bucketRow('98.5% and above')).slice(1, 7)).toEqual(['1', '0', '3', '60.00%', '0.00%', '+3']);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();  // same reporting population in both periods
  });

  it('warns when the two MTD periods cover different reporting populations', async () => {
    fetchThresholds.mockImplementation(async (params) => thresholdsFor(params, { ...SEP_MTD, sites_reported: 3, lt_60: s(2), no_value: s(2), below_98_5: s(3) } as ThresholdValue));
    renderPage();
    await findUnified();
    expect(screen.getByRole('note')).toHaveTextContent('5 sites reported in Oct-26 MTD 01 Oct–02 Oct but 3 in Sep-26 MTD 01–02 Sep');
    expect(within(unified()).queryByRole('row', { name: 'Grand Total' })).not.toBeInTheDocument();
  });

  it('switches the period columns between counts and percentages', async () => {
    const user = userEvent.setup();
    renderPage();
    await findUnified();
    await user.click(screen.getByRole('button', { name: 'Percentage' }));
    expect(cells(bucketRow('Below 60%')).slice(1, 4)).toEqual(['40.0%', '—', '20.0%']);
  });

  it('offers MTD, months, weeks and dates; the selected period drives the KPI and is sent to the backend', async () => {
    const user = userEvent.setup();
    renderPage();
    await findUnified();
    await user.click(screen.getByRole('combobox', { name: 'Period' }));
    expect((await screen.findAllByRole('option')).map((o) => o.textContent)).toEqual([
      'MTD · 01 Oct–02 Oct (2 days)', 'Month · Sep-26 (30 days)', 'Week · Wk-1 (01 Oct–07 Oct, 2 days so far)', 'Date · 02 Oct 2026', 'Date · 01 Oct 2026',
    ]);  // Wk-2 has no reported day yet
    await user.click(screen.getByRole('option', { name: 'Date · 02 Oct 2026' }));
    expect(screen.getByTestId('location')).toHaveTextContent('period=2026-10-02');
    await waitFor(() => expect(Object.fromEntries(fetchThresholds.mock.calls.at(-1)![0] as URLSearchParams)).toMatchObject({ period: '2026-10-02' }));
    // 2 Oct: 1 in 60-90%, 0 below 60% = 1 below 98.5% (20%).
    expect(await within(kpi()).findByText('02 Oct')).toBeInTheDocument();
    expect(within(kpi()).getByText('20.0%')).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Compare with' }));
    await user.click(await screen.findByRole('option', { name: /^Week · Wk-1/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('vs=w1');
    await waitFor(() => expect(Object.fromEntries(fetchThresholds.mock.calls.at(-1)![0] as URLSearchParams)).toMatchObject({ period: '2026-10-02', vs: 'w1' }));
  });

  it('shows an unavailable state when the API fails', async () => {
    fetchThresholds.mockRejectedValue(new api.ApiError('No data has been reported for 2026-10-20.', 400));
    renderPage();
    expect(await screen.findByText('Threshold analysis unavailable')).toBeInTheDocument();
  });
});

describe('Threshold analysis: uptime threshold summary', () => {
  it('shows meeting and below-threshold counts that reconcile with the site scope and bucket totals', async () => {
    renderPage();
    await findUnified();
    // MTD to 2 Oct, all 5 sites are classified: 3 meeting + 2 below, with the below count matching the four bucket totals.
    expect(within(kpi()).getByText('3')).toHaveClass('text-emerald-700');
    expect(within(kpi()).getByText('60.0%')).toBeInTheDocument();
    expect(within(kpi()).getByText('2')).toHaveClass('text-red-700');
    expect(within(kpi()).getByText('40.0%')).toBeInTheDocument();
    expect(within(kpi()).getByText('MTD to 02 Oct')).toBeInTheDocument();
    expect(within(kpi()).getByText('5 O&M Start sites')).toBeInTheDocument();
    expect(within(kpi()).getByRole('img')).toHaveAttribute('aria-label',
      'Threshold distribution: 3 meeting and 2 below out of 5 sites in scope');
    expect(within(kpi()).getByText('All sites classified')).toBeInTheDocument();
    const cards = within(screen.getByRole('group', { name: 'Below 98.5% by bucket' })).getAllByRole('button').map((b) => b.getAttribute('aria-label'));
    expect(cards).toEqual(['Below 60%: 1 sites, open analysis', '60% to <90%: 1 sites, open analysis', '90% to <97%: 0 sites, open analysis', '97% to <98.5%: 0 sites, open analysis']);
    expect(cells(bucketRow('Below 98.5% — Total'))[3]).toBe('2');  // Oct MTD = the KPI
  });

  it('shows the backend aggregate of all four buckets and leaves sites with no value out of every bucket', async () => {
    const counts = { lt_60: 1, '60_90': 2, '90_97': 3, '97_98_5': 4, gte_98_5: 10 };
    const pct = (n: number) => Math.round((10000 * n) / 22) / 100;
    const v = { sites_reported: 20, ...Object.fromEntries(Object.entries(counts).map(([k, n]) => [k, { count: n, pct: pct(n) }])),
      below_98_5: { count: 10, pct: pct(10) }, no_value: { count: 2, pct: pct(2) } } as unknown as ThresholdValue;
    fetchThresholds.mockImplementation(async (params) => {
      const base = thresholdsFor(params);
      return asThresholdResponse({ ...base, total: { ...base.total, sites_in_scope: 22, values: { ...base.total.values, mtd: v } } }, params);
    });
    renderPage();
    await findUnified();
    const summaryCounts = within(kpi()).getAllByText('10');
    expect(summaryCounts).toHaveLength(2);
    expect(summaryCounts[0]).toHaveClass('text-emerald-700');
    expect(summaryCounts[1]).toHaveClass('text-red-700');
    expect(within(kpi()).getAllByText('45.5%')).toHaveLength(2);
    expect(within(kpi()).getByText('2 unclassified · 2 no value')).toBeInTheDocument();
    expect(cells(bucketRow('Below 98.5% — Total'))[3]).toBe('10');
  });

  it('opens a bucket from its breakdown card or Analyse, and a row (also the aggregate) opens its line chart', async () => {
    const user = userEvent.setup();
    renderPage();
    await findUnified();
    expect(screen.getByText('Select an uptime bucket above to see its line chart.')).toBeInTheDocument();
    await user.click(bucketRow('Below 98.5% — Total'));
    expect(screen.getByRole('region', { name: 'Below 98.5% — Total by month' })).toBeInTheDocument();
    await user.click(bucketRow('98.5% and above'));
    expect(screen.getByRole('region', { name: '98.5% and above by month' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Below 98.5% — Total by month' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '60% to <90%: 1 sites, open analysis' }));
    expect(screen.getByTestId('location')).toHaveTextContent('view=60_90');
  });
});

describe('Threshold analysis: bucket detail', () => {
  it('opens a bucket from its row and returns to all buckets with the filters kept', async () => {
    const user = userEvent.setup();
    renderPage('/thresholds?date=2026-10-02&circle=MP');
    await findUnified();
    await user.click(within(unified()).getByRole('button', { name: 'Analyse Below 60%' }));
    expect(await screen.findByRole('heading', { name: /Critical low uptime: below 60%/ })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('view=lt_60');
    expect(screen.getByTestId('location')).toHaveTextContent('circle=MP');
    await user.click(screen.getByRole('button', { name: /All buckets/ }));
    expect(await findUnified()).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('circle=MP');
    expect(screen.getByTestId('location')).not.toHaveTextContent('view=');
  });

  it('shows the bucket definition, summary, trend and period table for a middle bucket, not labelled critical', async () => {
    renderPage('/thresholds?date=2026-10-02&view=60_90');
    const heading = await screen.findByRole('heading', { name: /Uptime 60% to below 90%/ });
    expect(heading.parentElement).toHaveTextContent('rule: 60% ≤ uptime < 90% (workbook label ">60 To <90")');
    const summary = screen.getByRole('region', { name: 'Bucket summary' });
    expect(summary).toHaveTextContent('Sites · MTD to 02 Oct1');
    expect(summary).toHaveTextContent('20.00% of sites in scope');
    expect(screen.queryByText('Critical')).not.toBeInTheDocument();
    const total = within(periodTable()).getByRole('rowheader', { name: 'Grand Total' }).closest('tr')!;
    // 60-90%: Sep 1, MTD 1, Wk-1 1, Wk-2 —, 01 Oct 0, 02 Oct 1
    expect(cells(total)).toEqual(['5', '1', '1', '1', '—', '0', '1']);
    expect(within(total).getAllByRole('link')[0].className).toContain('text-primary');
  });

  it('keeps the critical analysis for below 60% and the high-availability analysis for 98.5%+', async () => {
    const view = renderPage('/thresholds?date=2026-10-02&view=lt_60');
    expect(await screen.findByRole('heading', { name: /Critical low uptime: below 60%/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open in Site Explorer/ })).toHaveAttribute('href', '/?scope=om_start&date=2026-10-02&bucket=lt_60');
    const mp = within(periodTable()).getByRole('rowheader', { name: 'MP · 4G' }).closest('tr')!;
    const day = within(mp).getAllByRole('link').find((a) => a.getAttribute('href')?.includes('date=2026-10-01'))!;
    expect(day).toHaveAttribute('href', '/?scope=om_start&date=2026-10-01&bucket=lt_60&report_type=4G+Saturation&circle=MP&bucket_basis=daily');
    expect(day.className).toContain('text-destructive');
    view.unmount();
    renderPage('/thresholds?date=2026-10-02&view=gte_98_5');
    expect(await screen.findByRole('heading', { name: /High availability: 98.5% and above/ })).toBeInTheDocument();
  });

  it('lists the affected sites for the bucket and narrows them to a circle picked in the detail', async () => {
    const user = userEvent.setup();
    renderPage('/thresholds?date=2026-10-02&view=60_90');
    await screen.findByRole('heading', { name: /Uptime 60% to below 90%/ });
    await waitFor(() => expect(fetchRecords).toHaveBeenCalled());
    expect(Object.fromEntries(lastRecords())).toMatchObject({ bucket: '60_90', scope: 'om_start', reporting_date: '2026-10-02' });
    expect(lastRecords().has('bucket_basis')).toBe(false);  // MTD
    const byCircle = screen.getByRole('region', { name: 'Circle comparison for the bucket' });
    await user.click(within(byCircle).getByRole('row', { name: /OD · LWE: list its sites/ }));
    await waitFor(() => expect(Object.fromEntries(lastRecords())).toMatchObject({ circle: 'OD', report_type: 'LWE', bucket: '60_90' }));
    expect(screen.getByTestId('location')).not.toHaveTextContent('circle=');  // the global filter is unchanged
  });

  it('lists the sites bucketed on the chosen date when the period is a date', async () => {
    renderPage('/thresholds?date=2026-10-02&period=2026-10-01&view=lt_60');
    await screen.findByRole('heading', { name: /Critical low uptime/ });
    await waitFor(() => expect(fetchRecords).toHaveBeenCalled());
    expect(Object.fromEntries(lastRecords())).toMatchObject({ bucket: 'lt_60', bucket_basis: 'daily', reporting_date: '2026-10-01' });
    expect(screen.getByRole('link', { name: /Open in Site Explorer/ })).toHaveAttribute('href', '/?scope=om_start&date=2026-10-01&bucket=lt_60&bucket_basis=daily');
    expect(screen.getByRole('region', { name: 'Bucket summary' })).toHaveTextContent('Sites · 01 Oct');
  });

  it('switches the detail tables between counts and percentages', async () => {
    const user = userEvent.setup();
    renderPage('/thresholds?date=2026-10-02&view=gte_98_5');
    await screen.findByRole('heading', { name: /High availability/ });
    await user.click(screen.getByRole('button', { name: 'Percentage' }));
    expect(screen.getByTestId('location')).toHaveTextContent('show=pct');
    const total = within(periodTable()).getByRole('rowheader', { name: 'Grand Total' }).closest('tr')!;
    expect(total.querySelectorAll('td')[2]).toHaveTextContent('60.0%');  // MTD 3 of 5
  });

  it('sorts circles by a period column', async () => {
    const user = userEvent.setup();
    renderPage('/thresholds?date=2026-10-02&view=gte_98_5');
    await screen.findByRole('heading', { name: /High availability/ });
    const order = () => within(periodTable()).getAllByRole('rowheader').map((h) => h.textContent);
    expect(order()).toEqual(['MP · 4G', 'OD · LWE', 'Grand Total']);
    await user.click(within(periodTable()).getByRole('button', { name: /Entity/ }));
    await user.click(within(periodTable()).getByRole('button', { name: /Entity/ }));
    expect(order()).toEqual(['OD · LWE', 'MP · 4G', 'Grand Total']);  // Grand Total stays last
  });
});

describe('Sidebar', () => {
  it('lists Threshold Analysis between LWE and Team Performance and highlights it when active', () => {
    renderWithWorkbook(<Sidebar />, { url: '/thresholds' });
    const links = within(screen.getByRole('navigation', { name: 'Main' })).getAllByRole('link').map((a) => a.textContent);
    // On its page the Threshold Analysis group is open, showing its subpage.
    expect(links.slice(4, 8)).toEqual(['LWE', 'Threshold Analysis', 'Uptime Buckets & Site Details', 'Team Performance']);
    expect(screen.getByRole('link', { name: 'Threshold Analysis' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current');
  });
});

describe('Site Explorer drill-down', () => {
  it('filters the site table by uptime on the reporting date', async () => {
    const { SiteTable } = await import('../components/dashboard/SiteTable');
    renderWithWorkbook(
      <SiteTable params={new URLSearchParams({ scope: 'om_start', reporting_date: '2026-10-01' })} version="v1"
        bucket="lt_60" bucketBasis="daily" onBucketChange={vi.fn()} onSelectSite={vi.fn()} />,
    );
    await waitFor(() => expect(fetchRecords).toHaveBeenCalled());
    expect([lastRecords().get('bucket'), lastRecords().get('bucket_basis')]).toEqual(['lt_60', 'daily']);
    expect(screen.getByText(/Below 60% on 01 Oct 2026/)).toBeInTheDocument();
  });
});
