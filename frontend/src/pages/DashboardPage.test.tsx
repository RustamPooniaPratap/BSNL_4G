import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { ApiError } from '../services/api';
import { breakdown, filterOptions, monthly, period, records, summary, teams, trend } from '../test/fixtures';
import { renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import type { TrendResponse } from '../types';
import { WorkbookContext } from '../context/workbook';
import { BucketsSitesPage } from './BucketsSitesPage';
import { DashboardPage } from './DashboardPage';

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>();
  return {
    ...actual,
    fetchFilterOptions: vi.fn(),
    fetchMonthly: vi.fn(),
    fetchTeams: vi.fn(),
    fetchSummary: vi.fn(),
    fetchTrends: vi.fn(),
    fetchBreakdowns: vi.fn(),
    fetchRecords: vi.fn(),
    fetchSiteDetail: vi.fn(),
    fetchPeriod: vi.fn(),
  };
});

const mocked = vi.mocked(api);

const Location = () => { const l = useLocation(); return <p data-testid="location">{l.pathname + l.search}</p>; };
/** Both pages are routed, so the redirect of bucket links and the links between them are exercised. */
function renderPage(url = '/', workbook = workbookValue()) {
  return renderWithWorkbook(
    <>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/thresholds/buckets" element={<BucketsSitesPage />} />
      </Routes>
      <Location />
    </>,
    { url, workbook },
  );
}

const lastParams = (fn: (...args: never[]) => unknown) => {
  const calls = vi.mocked(fn).mock.calls;
  return calls[calls.length - 1][0] as unknown as URLSearchParams;
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchFilterOptions.mockResolvedValue(filterOptions);
  mocked.fetchMonthly.mockResolvedValue(monthly);
  mocked.fetchTeams.mockResolvedValue(teams);
  mocked.fetchSummary.mockResolvedValue(summary);
  mocked.fetchTrends.mockResolvedValue(trend);
  mocked.fetchBreakdowns.mockResolvedValue(breakdown);
  mocked.fetchRecords.mockResolvedValue(records(3));
  mocked.fetchPeriod.mockResolvedValue(period);
});

describe('DashboardPage', () => {
  it('renders KPIs from the summary endpoint for the latest date by default', async () => {
    renderPage();
    const kpis = await screen.findByRole('region', { name: 'Key indicators' });
    // Five cards in order: MTD uptime (unchanged), Not meeting SLA, Unique sites down, Below 60% MTD, Outage minutes.
    expect(within(kpis).getAllByRole('group').filter((g) => g.dataset.slot === 'card').map((g) => g.getAttribute('aria-label')))
      .toEqual(['MTD uptime', 'Not meeting SLA', 'Unique sites down', 'Below 60% MTD', 'Outage minutes']);
    expect(within(kpis).getByText('93.07%')).toBeInTheDocument();
    const card = (name: string) => within(kpis).getByRole('group', { name });
    expect(card('Not meeting SLA')).toHaveTextContent('240.0%');  // 2 of 5 sites with MTD data
    // USD: distinct active sites with outage > 0 at least once in the selected reporting period, of every active site.
    expect(await within(kpis).findByText('Outage > 0 at least once · 01 Oct – 03 Oct · of 5 active sites')).toBeInTheDocument();
    expect(card('Unique sites down')).toHaveTextContent('360.0%');
    expect(lastParams(mocked.fetchPeriod).get('scope')).toBe('on_air');  // the same filters as every KPI
    expect(card('Below 60% MTD')).toHaveTextContent('240.0%');
    expect(within(kpis).queryByText('Daily uptime')).not.toBeInTheDocument();  // replaced
    // Outage minutes: MTD by default (more minutes than the same days of September: red, up); Day: fewer (green, down).
    const outage = card('Outage minutes');
    expect(outage).toHaveTextContent('+25%vs 01 Sep – 03 Sep');
    expect(within(outage).getByText('+25%').className).toContain('text-destructive');
    await userEvent.click(within(outage).getByRole('button', { name: 'Day' }));
    expect(within(outage).getByText('-20%').className).toContain('text-emerald-700');
    await userEvent.click(within(outage).getByRole('button', { name: 'Month' }));
    expect(outage).toHaveTextContent('October is not complete yet.');  // no misleading change

    const params = lastParams(mocked.fetchSummary);
    expect(params.get('reporting_date')).toBe('2026-10-03');
    expect(params.get('scope')).toBe('on_air');
    expect(params.has('circle')).toBe(false); // All circles: no hardcoded default
  });

  it('builds filter options from the API, not hardcoded values', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('combobox', { name: 'Circle' }));
    const options = screen.getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['All circles', 'BH', 'MP', 'RJ']);
  });

  it('applies combined filters from the URL to every request', async () => {
    renderPage('/?report_type=LWE&circle=MP&scope=om_start&date=2026-10-02&from=2026-10-01&to=2026-10-02');
    await screen.findByRole('region', { name: 'Key indicators' });
    for (const fn of [mocked.fetchSummary, mocked.fetchBreakdowns]) {
      const params = lastParams(fn);
      expect(params.get('report_type')).toBe('LWE');
      expect(params.get('circle')).toBe('MP');
      expect(params.get('scope')).toBe('om_start');
      expect(params.get('reporting_date')).toBe('2026-10-02');
    }
    const trendParams = lastParams(mocked.fetchTrends);
    expect(trendParams.get('start_date')).toBe('2026-10-01');
    expect(trendParams.get('end_date')).toBe('2026-10-02');
  });

  it('ignores filter values the workbook does not offer', async () => {
    renderPage('/?circle=XX&report_type=Bogus&date=2026-12-01');
    await screen.findByRole('region', { name: 'Key indicators' });
    const params = lastParams(mocked.fetchSummary);
    expect(params.has('circle')).toBe(false);
    expect(params.has('report_type')).toBe(false);
    expect(params.get('reporting_date')).toBe('2026-10-03');
  });

  it('shows the page title and the filters in one compact card, with "Project" for the report type', async () => {
    renderPage();
    const title = await screen.findByRole('heading', { name: 'Network uptime overview' });
    expect(title.closest('[data-slot="card"]')).toContainElement(screen.getByRole('search', { name: 'Dashboard filters' }));
    expect(screen.getByRole('combobox', { name: 'Project' })).toHaveTextContent('All projects');
    expect(screen.getByRole('button', { name: 'Reset filters' })).toBeInTheDocument();
  });

  it('drops a circle that does not belong to the newly selected report type', async () => {
    const user = userEvent.setup();
    renderPage('/?circle=RJ');
    await user.click(await screen.findByRole('combobox', { name: 'Project' }));
    await user.click(screen.getByRole('option', { name: 'LWE' }));
    await waitFor(() => expect(lastParams(mocked.fetchSummary).get('report_type')).toBe('LWE'));
    expect(lastParams(mocked.fetchSummary).has('circle')).toBe(false);
  });

  it('resets filters to defaults', async () => {
    const user = userEvent.setup();
    renderPage('/?report_type=LWE');
    await screen.findByRole('region', { name: 'Key indicators' });
    await user.click(screen.getByRole('button', { name: /reset filters/i }));
    await waitFor(() => expect(lastParams(mocked.fetchSummary).has('report_type')).toBe(false));
  });

  it('asks for an upload and fetches nothing when no workbook is loaded', async () => {
    renderPage('/', workbookValue({ active: null, version: 'none', message: 'No Master workbook has been uploaded yet.' }));
    expect(await screen.findByText('No reporting data loaded')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /import data/i })).toHaveAttribute('href', '/workbook');
    expect(mocked.fetchFilterOptions).not.toHaveBeenCalled();
    expect(mocked.fetchSummary).not.toHaveBeenCalled();
  });

  it('refetches every panel when a new workbook becomes active', async () => {
    const view = renderPage();
    await screen.findByRole('region', { name: 'Key indicators' });
    const before = { summary: mocked.fetchSummary.mock.calls.length, filters: mocked.fetchFilterOptions.mock.calls.length };
    view.rerender(
      <MemoryRouter>
        <WorkbookContext.Provider value={workbookValue({ version: 'v2' })}>
          <DashboardPage />
        </WorkbookContext.Provider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(mocked.fetchSummary.mock.calls.length).toBeGreaterThan(before.summary));
    expect(mocked.fetchFilterOptions.mock.calls.length).toBeGreaterThan(before.filters);
  });

  it('switches the trend between daily, weekly and monthly views', async () => {
    const user = userEvent.setup();
    renderPage();
    const group = await screen.findByRole('group', { name: 'Trend period' });
    expect(within(group).getByRole('button', { name: 'Daily' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(within(group).getByRole('button', { name: 'Weekly' }));
    const weeks = await screen.findByLabelText('Weekly uptime and change');
    expect(within(weeks).getByText('95.00%')).toBeInTheDocument();
    expect(within(weeks).getByText('Not reported')).toBeInTheDocument();

    await user.click(within(group).getByRole('button', { name: 'Monthly' }));
    expect(await screen.findByText(/Overall · Sep-26 to 03 Oct 2026 · 2 months/)).toBeInTheDocument();
    expect(screen.getByText('94.60%')).toBeInTheDocument();
    expect(screen.getByText('4G 93.80% · LWE 96.40%')).toBeInTheDocument();
    expect(screen.getByTitle('-2.00 pts vs previous month')).toBeInTheDocument();
  });

  it('leaves team performance, uptime buckets and the site table to their own pages', async () => {
    renderPage('/?report_type=LWE');
    await screen.findByRole('region', { name: 'Key indicators' });
    expect(await screen.findByText('Circle comparison')).toBeInTheDocument();
    for (const moved of ['Site uptime buckets', 'Site detail', 'Team performance']) {
      expect(screen.queryByText(moved)).not.toBeInTheDocument();
    }
    expect(mocked.fetchTeams).not.toHaveBeenCalled();
    expect(mocked.fetchRecords).not.toHaveBeenCalled();
  });

  it('links to the buckets page with the same project, circle, scope and date (not the chart-only settings)', async () => {
    renderPage('/?report_type=LWE&circle=MP&date=2026-10-02&uptime_view=heatmap&trend=weekly');
    const link = await screen.findByRole('link', { name: /Uptime buckets & site details/ });
    expect(link).toHaveAttribute('href', '/thresholds/buckets?report_type=LWE&circle=MP&date=2026-10-02');
  });

  it('shows an explicit error and no sample data when the workbook is unavailable', async () => {
    mocked.fetchFilterOptions.mockRejectedValue(new ApiError('No Master workbook (.xlsx) was found in Data/reference.', 503));
    renderPage();
    expect(await screen.findByText('Reporting data is unavailable')).toBeInTheDocument();
    expect(screen.getByText(/No Master workbook/)).toBeInTheDocument();
    expect(mocked.fetchSummary).not.toHaveBeenCalled();
  });

  it('keeps other panels working when one endpoint fails', async () => {
    mocked.fetchTrends.mockRejectedValue(new ApiError('Trend failed', 500));
    renderPage();
    // Both panels that use the trend endpoint report the failure; the others still render.
    expect(await screen.findAllByText('Trend failed')).toHaveLength(2);
    expect(await screen.findByRole('region', { name: 'Key indicators' })).toBeInTheDocument();
  });

  it('shows unreported days as not reported, not as 100%', async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText(/1 day not reported \(shown as gaps\)/)).toBeInTheDocument();
    await user.click(within(screen.getByRole('group', { name: 'Trend period' })).getByRole('button', { name: 'Weekly' }));
    const week2 = await screen.findByText(/Week 2 ·/);
    expect(within(week2.closest('div')!).getByText('Not reported')).toBeInTheDocument();
  });

  it('shows outage minutes for the same view as the uptime trend, per report type and combined', async () => {
    const user = userEvent.setup();
    renderPage();
    const card = (await screen.findByText('Outage minutes')).closest('[data-slot="card"]') as HTMLElement;
    const table = () => within(card).getByRole('table', { hidden: true });
    const headers = () => within(table()).getAllByRole('columnheader', { hidden: true }).map((h) => h.textContent);
    const firstRow = () => within(table()).getAllByRole('row', { hidden: true })[1].textContent;
    await within(card).findByRole('table', { hidden: true });  // the title shows before the data arrives
    expect(headers()).toEqual(['Date', 'Combined', '4G Saturation', 'LWE']);
    expect(firstRow()).toBe('01 Oct 2026360 min250 min110 min');

    // Switching either chart switches both.
    await user.click(within(card).getByRole('button', { name: 'Weekly' }));
    expect(within(screen.getByRole('group', { name: 'Trend period' })).getByRole('button', { name: 'Weekly' })).toHaveAttribute('aria-pressed', 'true');
    expect(headers()[0]).toBe('Week');
    expect(firstRow()).toBe('Week 1 (01 Oct–07 Oct), 1 of 7 days360 min250 min110 min');

    await user.click(within(card).getByRole('button', { name: 'Monthly' }));
    expect(headers()).toEqual(['Month', 'Combined', '4G Saturation', 'LWE']);
    expect(within(table()).getAllByRole('row', { hidden: true }).map((r) => r.textContent).slice(1)).toEqual([
      'Sep-2610,800 min7,800 min3,000 min',
      'Oct-26 MTD (3 days)1,512 min1,100 min412 min',
    ]);
  });

  it('shows an empty state when no sites match', async () => {
    mocked.fetchRecords.mockResolvedValue({ ...records(0), records: [] });
    renderPage('/thresholds/buckets');
    expect(await screen.findByText('No sites match the selected filters.')).toBeInTheDocument();
  });

  it('opens an old bucket link (header alerts, Site Portfolio: /?bucket=lt_60) on the buckets page, keeping every parameter', async () => {
    renderPage('/?bucket=lt_60&bucket_basis=daily&report_type=LWE&date=2026-10-02');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(
      '/thresholds/buckets?bucket=lt_60&bucket_basis=daily&report_type=LWE&date=2026-10-02'));
    await waitFor(() => expect(lastParams(mocked.fetchRecords).get('bucket')).toBe('lt_60'));
    const params = lastParams(mocked.fetchRecords);
    expect([params.get('bucket_basis'), params.get('report_type'), params.get('reporting_date')]).toEqual(['daily', 'LWE', '2026-10-02']);
    expect(mocked.fetchSummary).not.toHaveBeenCalled();  // the Overview did not render on the way
  });

  it('ignores an unknown bucket in the URL', async () => {
    renderPage('/thresholds/buckets?bucket=everything');
    await waitFor(() => expect(mocked.fetchRecords).toHaveBeenCalled());
    expect(lastParams(mocked.fetchRecords).has('bucket')).toBe(false);
  });

  it('opens the bucket drill-down from the "List sites" KPI action', async () => {
    const user = userEvent.setup();
    renderPage('/?report_type=LWE');
    await user.click(await screen.findByRole('button', { name: 'List sites' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/thresholds/buckets?report_type=LWE&bucket=lt_60');
    await waitFor(() => expect(lastParams(mocked.fetchRecords).get('bucket')).toBe('lt_60'));
  });
});

describe('Uptime Buckets & Site Details page', () => {
  it('shows the bucket chart above the site table, for the filters in the URL', async () => {
    renderPage('/thresholds/buckets?report_type=LWE&circle=MP&scope=om_start&date=2026-10-02');
    const chart = await screen.findByText('Site uptime buckets');
    const table = await screen.findByText('Site detail');
    expect(chart.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const fn of [mocked.fetchBreakdowns, mocked.fetchRecords]) {
      const params = lastParams(fn);
      expect([params.get('report_type'), params.get('circle'), params.get('scope'), params.get('reporting_date')]).toEqual(['LWE', 'MP', 'om_start', '2026-10-02']);
    }
    expect(mocked.fetchTrends).not.toHaveBeenCalled();  // no trend charts on this page
  });

  it('keeps the Month to date / Selected day toggle and lists a bucket in the table', async () => {
    const user = userEvent.setup();
    renderPage('/thresholds/buckets');
    await screen.findByText(/Sites grouped by month-to-date uptime/);
    await user.click(screen.getByRole('button', { name: /Below 60%/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('bucket=lt_60');
    await waitFor(() => expect(lastParams(mocked.fetchRecords).get('bucket')).toBe('lt_60'));
    await user.click(screen.getByRole('button', { name: 'Selected day' }));
    expect(screen.getByText(/Sites grouped by their uptime on/)).toBeInTheDocument();
  });

  it('refreshes the chart and the table when the reporting date changes', async () => {
    renderPage('/thresholds/buckets?date=2026-10-02');
    await screen.findByText('Site detail');
    await waitFor(() => expect(lastParams(mocked.fetchRecords).get('reporting_date')).toBe('2026-10-02'));
    expect(lastParams(mocked.fetchBreakdowns).get('reporting_date')).toBe('2026-10-02');
  });
});

describe('Trend period', () => {
  it('shows only hand-picked dates and requests the span they cover', async () => {
    renderPage('/?days=2026-10-01,2026-10-03,bogus');
    expect(await screen.findByText(/on 2 selected dates/)).toBeInTheDocument();
    const params = lastParams(mocked.fetchTrends);
    expect([params.get('start_date'), params.get('end_date')]).toEqual(['2026-10-01', '2026-10-03']);
    expect(screen.getByRole('button', { name: 'Trend period' })).toHaveTextContent('Dates · 01 Oct, 03 Oct');
  });

  it('compares only the picked weeks', async () => {
    renderPage('/?trend=weekly&weeks=1');
    expect(await screen.findByText(/weeks 1 of Oct-26/)).toBeInTheDocument();
    const cards = await screen.findByLabelText('Weekly uptime and change');
    expect(within(cards).getByText(/Week 1/)).toBeInTheDocument();
    expect(within(cards).queryByText(/Week 2/)).not.toBeInTheDocument();
  });

  it('sends picked months to the monthly endpoint', async () => {
    renderPage('/?trend=monthly&months=2026-10,2026-09,1999-01');
    await screen.findByText(/by selected month/);
    expect(lastParams(mocked.fetchMonthly).get('months')).toBe('2026-09,2026-10');
    expect(screen.getByRole('button', { name: 'Trend period' })).toHaveTextContent('Months · Sep-26, Oct-26 MTD');
  });

  it('switches the chart to months and picks a month from the period picker', async () => {
    const user = userEvent.setup();
    renderPage();
    const picker = await screen.findByRole('button', { name: 'Trend period' });
    expect(picker).toHaveTextContent('01 Oct – 03 Oct');
    await user.click(picker);
    await user.click(screen.getByRole('tab', { name: 'Months' }));
    expect(await screen.findByText(/by month\. Recomputed/)).toBeInTheDocument();
    await user.click(within(screen.getByRole('group', { name: 'Months' })).getByRole('button', { name: /Sep-26/ }));
    await waitFor(() => expect(lastParams(mocked.fetchMonthly).get('months')).toBe('2026-09'));

    await user.click(screen.getByRole('tab', { name: 'Specific dates' }));
    await user.click(screen.getByRole('button', { name: '02 Oct 2026' }));
    await waitFor(() => expect(lastParams(mocked.fetchTrends).get('end_date')).toBe('2026-10-02'));
  });
});

describe('Trend period KPI', () => {
  it('is not shown on the Overview', async () => {
    renderPage();
    await screen.findByRole('region', { name: 'Key indicators' });
    expect(screen.queryByRole('region', { name: 'Trend period indicators' })).not.toBeInTheDocument();
    expect(mocked.fetchPeriod).toHaveBeenCalled();  // its data only: Unique sites down counts over the reporting period
  });

  it('shows the period figures on the 4G Saturation and LWE pages', async () => {
    for (const type of ['4G+Saturation', 'LWE']) {
      const view = renderPage(`/?report_type=${type}`);
      const card = await screen.findByRole('region', { name: 'Trend period indicators' });
      expect(within(card).getByText('01 Oct – 03 Oct')).toBeInTheDocument();
      expect(within(card).getByText('94.10%')).toBeInTheDocument();
      expect(within(card).getByText('2,880 min')).toBeInTheDocument();
      const params = lastParams(mocked.fetchPeriod);
      expect([params.get('report_type'), params.get('period'), params.get('start_date'), params.get('end_date')])
        .toEqual([type.replace('+', ' '), 'range', '2026-10-01', '2026-10-03']);
      view.unmount();
    }
  });

  it('follows every kind of trend period while the reporting-date cards stay put', async () => {
    const cases: [string, Record<string, string>][] = [
      ['/?days=2026-10-01,2026-10-03', { period: 'days', days: '2026-10-01,2026-10-03' }],
      ['/?trend=weekly&weeks=1,2', { period: 'weeks', weeks: '1,2' }],
      ['/?trend=monthly&months=2026-09,2026-10', { period: 'months', months: '2026-09,2026-10' }],
      ['/?trend=monthly', { period: 'months' }],
    ];
    for (const [url, expected] of cases) {
      const view = renderPage(`${url}&report_type=LWE&circle=MP`);
      await screen.findByRole('region', { name: 'Trend period indicators' });
      const params = lastParams(mocked.fetchPeriod);
      expect(Object.fromEntries([...params].filter(([k]) => !['scope', 'circle', 'report_type'].includes(k)))).toEqual(expected);
      expect(params.get('circle')).toBe('MP');
      expect(lastParams(mocked.fetchSummary).get('reporting_date')).toBe('2026-10-03');
      view.unmount();
    }
  });
});

/** Trend data with circle series, as the API returns them; LWE|BH has no value on 1 Oct (null, not 0). */
function circleTrend(reportType: string | null): TrendResponse {
  const all = [
    { key: '4G Saturation|MP', report_type: '4G Saturation', circle: 'MP', sites: 3, up: 93.5, out: 200 },
    { key: '4G Saturation|RJ', report_type: '4G Saturation', circle: 'RJ', sites: 1, up: 95.2, out: 50 },
    { key: 'LWE|BH', report_type: 'LWE', circle: 'BH', sites: 1, up: null, out: null },
    { key: 'LWE|MP', report_type: 'LWE', circle: 'MP', sites: 1, up: 96.1, out: 110 },
    { key: 'LWE|OD', report_type: 'LWE', circle: 'OD', sites: 1, up: 97.4, out: 30 },
    { key: 'LWE|TL', report_type: 'LWE', circle: 'TL', sites: 1, up: 99.0, out: 10 },
  ].filter((c) => !reportType || c.report_type === reportType);
  const values = (pick: (c: (typeof all)[number]) => number | null, reported: boolean) => Object.fromEntries(all.map((c) => [c.key, reported ? pick(c) : null]));
  return {
    ...trend,
    report_types: reportType ? [reportType] : trend.report_types,
    circles: all.map(({ key, report_type, circle, sites }) => ({ key, report_type, circle, sites })),
    series: trend.series.map((p) => ({ ...p, by_circle: values((c) => c.up, p.reported), outage_by_circle: values((c) => c.out, p.reported) })),
    weeks: trend.weeks.map((w) => ({ ...w, by_circle: values((c) => c.up, w.days_reported > 0), outage_by_circle: values((c) => c.out, w.days_reported > 0) })),
  };
}

describe('Overview charts: overall, by circle, heatmap', () => {
  beforeEach(() => {
    mocked.fetchTrends.mockImplementation(async (params) => circleTrend(params.get('report_type')));
    // Lowest MTD first: OD, MP 4G, BH, MP LWE, TL (RJ has no value).
    const c = (report_type: string, circle: string, mtd: number | null) => ({ ...breakdown.circles[0], report_type, circle, mtd_uptime_pct: mtd });
    mocked.fetchBreakdowns.mockResolvedValue({ ...breakdown, circles: [c('4G Saturation', 'MP', 92), c('4G Saturation', 'RJ', null), c('LWE', 'BH', 93),
      c('LWE', 'MP', 94), c('LWE', 'OD', 90), c('LWE', 'TL', 99)] });
  });
  const uptimeTable = () => screen.getByRole('table', { name: 'Daily uptime data' });
  const columns = () => within(uptimeTable()).getAllByRole('columnheader').map((h) => h.textContent);
  const viewSwitch = () => screen.getByRole('group', { name: 'Uptime chart' });

  it('opens on the overall lines only: Combined, 4G and LWE, with no circle picker', async () => {
    renderPage();
    await screen.findByRole('group', { name: 'Uptime chart' });
    expect(within(viewSwitch()).getByRole('button', { name: 'Overall' })).toHaveAttribute('aria-pressed', 'true');
    expect(columns()).toEqual(['Date', 'Combined', '4G Saturation', 'LWE', 'Sites reported']);
    expect(screen.queryByRole('group', { name: 'Circle comparison' })).not.toBeInTheDocument();
  });

  it('by circle: starts with the four lowest-MTD circles; searchable; one circle, several or a whole network', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(within(await screen.findByRole('group', { name: 'Uptime chart' })).getByRole('button', { name: 'By circle' }));
    expect(columns()).toEqual(['Date', 'MP · 4G', 'BH · LWE', 'MP · LWE', 'OD · LWE', 'Sites reported']);
    // BH has no value on 1 Oct: shown as "—" (no data), never as 0.
    const firstDay = [...within(uptimeTable()).getAllByRole('row')[1].querySelectorAll('td')].map((c) => c.textContent);
    expect(firstDay.slice(1, 5)).toEqual(['93.50%', '—', '96.10%', '97.40%']);
    await user.click(screen.getByRole('button', { name: /Compare circles/ }));
    expect(screen.getByText('4 of 6 selected')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /OD · LWE/ }));
    await user.click(screen.getByRole('checkbox', { name: /TL · LWE/ }));
    expect(columns()).toEqual(['Date', 'MP · 4G', 'BH · LWE', 'MP · LWE', 'TL · LWE', 'Sites reported']);
    // A whole network at once: all LWE circles, beyond four lines.
    const allLwe = screen.getByRole('checkbox', { name: 'All LWE circles' }) as HTMLInputElement;
    expect([allLwe.checked, allLwe.indeterminate]).toEqual([false, true]);
    await user.click(allLwe);
    expect(columns()).toEqual(['Date', 'MP · 4G', 'BH · LWE', 'MP · LWE', 'OD · LWE', 'TL · LWE', 'Sites reported']);
    expect(screen.getByText(/5 lines: the Heatmap view is easier to read/)).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /MP · 4G/ }));
    expect(screen.getByRole('button', { name: 'Compare circles: All LWE circles' })).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Search circles' }), 'rj');
    const picker = screen.getByRole('textbox', { name: 'Search circles' }).closest('[data-slot="popover-content"]') as HTMLElement;
    expect(within(picker).getAllByRole('checkbox').map((c) => c.closest('label')!.textContent)).toEqual(['All 4G0/2', 'RJ · 4G1 sites']);
    await user.click(screen.getByRole('button', { name: 'Clear circle selection' }));
    expect(screen.getByText('Choose up to four circles to draw.')).toBeInTheDocument();
  });

  it('heatmap: every circle by date, missing values hatched (not 0); a row opens that circle', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(within(await screen.findByRole('group', { name: 'Uptime chart' })).getByRole('button', { name: 'Heatmap' }));
    const heatmap = screen.getByRole('region', { name: 'Uptime heatmap' });
    expect(within(heatmap).getAllByRole('row', { name: /: open its trend/ })).toHaveLength(6);
    expect(within(heatmap).getByTitle('BH · LWE · 01 Oct 2026: no data')).toHaveTextContent('');
    expect(within(heatmap).getByTitle('OD · LWE · 01 Oct 2026: 97.40%')).toHaveTextContent('97.4');
    await user.click(within(heatmap).getByRole('row', { name: 'TL · LWE: open its trend' }));
    expect(within(viewSwitch()).getByRole('button', { name: 'By circle' })).toHaveAttribute('aria-pressed', 'true');
    expect(columns()).toEqual(['Date', 'TL · LWE', 'Sites reported']);
  });

  it('outage: 4G and LWE by default (combined on request); by circle ranks outage per site', async () => {
    const user = userEvent.setup();
    renderPage();
    const toggle = await screen.findByRole('checkbox', { name: 'Show combined total' });
    expect(toggle).not.toBeChecked();
    await user.click(within(screen.getByRole('group', { name: 'Outage chart' })).getByRole('button', { name: 'By circle' }));
    const rows = within(screen.getByRole('table', { name: /Outage per site by circle/ })).getAllByRole('row').slice(1)
      .map((r) => [...r.querySelectorAll('td')].map((c) => c.textContent));
    // MP 4G: 200 min over 3 sites = 66.7 per site, ahead of LWE MP 110 over 1 site? No: 110 per site is higher.
    expect(rows.map((r) => r[0])).toEqual(['MP · LWE', 'MP · 4G', 'RJ · 4G', 'OD · LWE', 'TL · LWE', 'BH · LWE']);
    expect(rows[0]).toEqual(['MP · LWE', '1', '110 min', '110 min', '1']);
    expect(rows[1].slice(1, 4)).toEqual(['3', '200 min', '67 min']);
    expect(rows.at(-1)).toEqual(['BH · LWE', '1', 'Not reported', 'No data', '2']);  // no value: not ranked as 0
  });

  it('keeps the date filter and only the page network circles', async () => {
    renderPage('/?report_type=LWE&from=2026-10-01&to=2026-10-02&uptime_view=heatmap');
    const heatmap = await screen.findByRole('region', { name: 'Uptime heatmap' });
    const params = lastParams(mocked.fetchTrends);
    expect([params.get('start_date'), params.get('end_date'), params.get('report_type')]).toEqual(['2026-10-01', '2026-10-02', 'LWE']);
    expect(within(heatmap).getAllByRole('row', { name: /: open its trend/ }).map((r) => r.getAttribute('aria-label'))).toEqual([
      'BH · LWE: open its trend', 'MP · LWE: open its trend', 'OD · LWE: open its trend', 'TL · LWE: open its trend',
    ]);
  });

  it('shows a Provisional banner listing the missing units when the month to date is Provisional', async () => {
    mocked.fetchSummary.mockResolvedValue({ ...summary, source: { ...summary.source, continuity: {
      dates_with_data: ['2026-10-01', '2026-10-02', '2026-10-03'], continuous_until: '2026-10-03', excluded_after_gap: [],
      incomplete_dates: ['2026-10-03'], mtd_status: 'Provisional',
      date_status: [{ date: '2026-10-03', status: 'Provisional', missing_units: ['LWE OD'] }],
      missing: [{ date: '2026-10-03', units: ['LWE OD'] }] } } });
    renderPage();
    const banner = await screen.findByRole('status', { name: 'Provisional figures' });
    expect(banner).toHaveTextContent('Provisional — awaiting LWE OD for 03 Oct');
  });

  it('shows no Provisional banner for a Complete month to date or an older response', async () => {
    renderPage();
    await screen.findByRole('region', { name: 'Key indicators' });
    expect(screen.queryByRole('status', { name: 'Provisional figures' })).not.toBeInTheDocument();
  });

  it('shows an incomplete week with its value and a Provisional badge listing the missing units', async () => {
    const user = userEvent.setup();
    mocked.fetchTrends.mockResolvedValue({ ...trend, weeks: [
      { ...trend.weeks[0], complete: false, status: 'Provisional', missing: [{ date: '2026-10-03', units: ['LWE OD'] }] },
      { ...trend.weeks[1], label: 'Week 2', days_reported: 7, complete: true, uptime_pct: 97.5, status: 'Complete', missing: [] },
    ] });
    mocked.fetchMonthly.mockResolvedValue({ ...monthly, months: [
      { ...monthly.months[0], status: 'Complete', finalization_status: 'incomplete_missing_data' },
      { ...monthly.months[1], status: 'Provisional', missing: [{ date: '2026-10-03', units: ['LWE OD'] }] },
    ] });
    renderPage();
    const group = await screen.findByRole('group', { name: 'Trend period' });
    await user.click(within(group).getByRole('button', { name: 'Weekly' }));
    const weeks = await screen.findByLabelText('Weekly uptime and change');
    expect(within(weeks).getByText('95.00%')).toBeInTheDocument();  // the incomplete week has a value
    const provisional = within(weeks).getByText('Provisional');
    expect(provisional).toHaveAttribute('title', 'Missing: LWE OD for 03 Oct');
    expect(within(weeks).getByText('97.50%')).toBeInTheDocument();
    expect(within(weeks).getByText('Complete')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Weekly uptime' })).toHaveTextContent('Provisional (missing LWE OD for 03 Oct)');

    await user.click(within(group).getByRole('button', { name: 'Monthly' }));
    await screen.findByText(/Overall · Sep-26 to 03 Oct 2026/);
    expect(screen.getAllByText('Provisional')[0]).toHaveAttribute('title', 'Missing: LWE OD for 03 Oct');
    expect(screen.getByRole('table', { name: 'Monthly uptime' })).toHaveTextContent('Incomplete — Missing Data');
  });
});

describe('Global population on the dashboard', () => {
  const scopesOf = (fn: (...args: never[]) => unknown) => vi.mocked(fn).mock.calls.map((c) => (c[0] as unknown as URLSearchParams).get('scope'));

  it('labels the selector "Population", offers only On-Air and O&M Start, and refetches every panel with the new scope', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Routes><Route path="/" element={<DashboardPage />} /></Routes><Location /></>, { url: '/', population: true });
    await screen.findByRole('region', { name: 'Key indicators' });
    await waitFor(() => expect(mocked.fetchPeriod).toHaveBeenCalled());
    for (const fn of [mocked.fetchSummary, mocked.fetchBreakdowns, mocked.fetchTrends, mocked.fetchMonthly, mocked.fetchPeriod]) {
      expect(new Set(scopesOf(fn))).toEqual(new Set(['on_air']));
    }
    expect(mocked.fetchFilterOptions).toHaveBeenLastCalledWith(expect.anything(), 'on_air');
    vi.clearAllMocks();
    mocked.fetchFilterOptions.mockResolvedValue(filterOptions);
    mocked.fetchSummary.mockResolvedValue(summary);
    mocked.fetchBreakdowns.mockResolvedValue(breakdown);
    mocked.fetchTrends.mockResolvedValue(trend);
    mocked.fetchMonthly.mockResolvedValue(monthly);
    mocked.fetchPeriod.mockResolvedValue(period);

    await user.click(screen.getByRole('combobox', { name: 'Population' }));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['On-Air', 'O&M Start']);
    await user.click(screen.getByRole('option', { name: 'O&M Start' }));
    await waitFor(() => expect(mocked.fetchPeriod).toHaveBeenCalled());
    // Every request of the page uses the new population: no stale or mixed scopes.
    for (const fn of [mocked.fetchSummary, mocked.fetchBreakdowns, mocked.fetchTrends, mocked.fetchMonthly, mocked.fetchPeriod]) {
      expect(new Set(scopesOf(fn))).toEqual(new Set(['om_start']));
    }
    expect(mocked.fetchFilterOptions).toHaveBeenLastCalledWith(expect.anything(), 'om_start');
    expect(screen.getByTestId('location')).toHaveTextContent('scope=om_start');
    expect(screen.getAllByText(/Population: O&M Start sites/).length).toBeGreaterThan(0);
  });
});
