import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '../components/Sidebar';
import { TrackingProvider } from '../context/TrackingProvider';
import { landsOnPortfolio } from '../lib/portfolio';
import * as api from '../services/api';
import { breakdown, filterOptions, period, source, summary, trend } from '../test/fixtures';
import { renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import type { ConversionActivity, PeriodSummary, SummaryResponse } from '../types';
import { PortfolioPage } from './PortfolioPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(), fetchSummary: vi.fn(), fetchBreakdowns: vi.fn(), fetchTrends: vi.fn(), fetchAlerts: vi.fn(), fetchPeriod: vi.fn(),
}));
// Conversion activity has no legacy endpoint any more: only the Site Portfolio API (/site-portfolio/conversion-activity/).
const fetchActivity = vi.hoisted(() => vi.fn());
// The page reads the new data layer through services/sitePortfolioApi; its calls are routed to the same mocks.
vi.mock('../services/sitePortfolioApi', async () => {
  const mocked = await import('../services/api');
  return {
    fetchPortfolioFilters: (signal?: AbortSignal) => mocked.fetchFilterOptions(signal),
    fetchPortfolioSummary: (params: URLSearchParams, signal?: AbortSignal) => mocked.fetchSummary(params, signal),
    fetchPortfolioBreakdowns: (params: URLSearchParams, signal?: AbortSignal) => mocked.fetchBreakdowns(params, signal),
    fetchPortfolioPeriod: (params: URLSearchParams, signal?: AbortSignal) => mocked.fetchPeriod(params, signal),
    fetchPortfolioActivity: (params: URLSearchParams, signal?: AbortSignal) => fetchActivity(params, signal),
  };
});
const m = vi.mocked(api);

function activityFor(monthKey: string, lastOnAir: number | null, lastOmStart: number | null,
  thisOnAir: number | null, thisOmStart: number | null): ConversionActivity {
  const [year, month] = monthKey.split('-').map(Number);
  const current = new Date(year, month - 1, 1);
  const previous = new Date(year, month - 2, 1);
  const label = (d: Date) => `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()]}-${String(d.getFullYear()).slice(-2)}`;
  const period = (count: number | null) => ({ count, covered_to: null, complete: false });
  return {
    source: 'matrix.xlsx', sites: 6724,
    month: { key: monthKey, label: label(current) },
    previous_month: { key: `${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, '0')}`, label: label(previous) },
    on_air: { this_month: period(thisOnAir), last_month: period(lastOnAir), change: null, latest_date: null },
    om_start: { this_month: period(thisOmStart), last_month: period(lastOmStart), change: null, latest_date: null },
  };
}

/** Each scope / date / report type gets distinguishable figures, so the page must use the right one. */
function fakeSummary(params: URLSearchParams): SummaryResponse {
  const scope = params.get('scope');
  const type = params.get('report_type');
  const previous = params.get('reporting_date') === '2026-10-02';
  const base = type === 'LWE' ? 300 : type === '4G Saturation' ? 400 : 700;
  return {
    ...summary,
    reporting_date: params.get('reporting_date') ?? '2026-10-03',
    metrics: {
      ...summary.metrics,
      sites_total: base,
      sites_converted: base - 100,  // fewer than the O&M Start count: both flags must be Yes on the same site
      sites_in_scope: scope === 'om_start' ? base - 80 : base - 50,
      sites_below_60_mtd: previous ? 12 : scope === 'om_start' ? 7 : 10,
      mtd_uptime_pct: previous ? 92.5 : type === 'LWE' ? 95 : 93,
      coverage_pct: 100,
    },
    previous_month_conversion: { label: 'Sep-26', sites_converted: base - 300 },
  };
}
/** Period figures that differ by period, so the right one must be shown: Sep 95%, Aug 94%, dates 93%. */
function fakePeriod(params: URLSearchParams): PeriodSummary {
  const months = params.get('months');
  const days = (params.get('days') ?? '').split(',').filter(Boolean);
  const om = params.get('scope') === 'om_start';
  const uptime = (months === '2026-09' ? 95 : months === '2026-08' ? 94 : 93) + (om ? 1 : 0);
  return {
    ...period, kind: months ? 'months' : 'dates', label: months ?? days.join(','), days_reported: months ? 0 : days.length,
    first_date: months ? null : days[0] ?? null, last_date: months ? null : days.at(-1) ?? null, uptime_pct: uptime,
    sites_in_scope: 650, sites_reported: 640, sites_below_60: months === '2026-08' ? 12 : 10, sites_at_or_above_98_5: 300,
    buckets: { lt_60: 10, '60_90': 30, '90_97': 100, '97_98_5': 200, gte_98_5: 300 },
  };
}
const periodCalls = () => m.fetchPeriod.mock.calls.map((c) => Object.fromEntries(c[0] as URLSearchParams));
const calls = () => m.fetchSummary.mock.calls.map((c) => Object.fromEntries(c[0] as URLSearchParams));

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchFilterOptions.mockResolvedValue(filterOptions);
  m.fetchSummary.mockImplementation(async (params) => fakeSummary(params));
  m.fetchBreakdowns.mockResolvedValue(breakdown);
  m.fetchTrends.mockResolvedValue(trend);
  m.fetchAlerts.mockResolvedValue({ alerts: [], counts: { critical: 0, warning: 0, info: 0 }, source });
  m.fetchPeriod.mockImplementation(async (params) => fakePeriod(params));
  // The endpoint returns the requested month and its previous month.
  fetchActivity.mockImplementation(async (params) => {
    const month = (params as URLSearchParams).get('month');
    if (month === '2026-09') return activityFor(month, 18, 36, 27, 54);
    if (month === '2026-11') return activityFor(month, 17, 100, null, null);
    return activityFor('2026-10', 27, 54, null, 12);
  });
});

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

const renderPage = (url = '/portfolio') => renderWithWorkbook(<TrackingProvider><PortfolioPage /></TrackingProvider>, { url });
const kpi = (label: string) => screen.getByRole('link', { name: label }).closest('[data-slot="card"]') as HTMLElement;

describe('Site Portfolio', () => {
  it('shows KPI cards from the right scope of the API figures, with the period and the change in the right unit', async () => {
    renderPage();
    expect(await screen.findByText('Site Portfolio — Summary')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Site status: total, On-Air & O&M Start' })).getByText('700')).toBeInTheDocument();
    // The default breakdown mock (2 sites) does not add up to the totals, so no project split is shown.
    expect(screen.queryByLabelText('Total sites by project')).not.toBeInTheDocument();
    expect(within(kpi('Sites below 60%')).getByText('10')).toBeInTheDocument();
    expect(within(kpi('Sites below 60%')).getByText('MTD 01–03 Oct')).toBeInTheDocument();
    expect(screen.queryByText('On-Air MTD uptime')).not.toBeInTheDocument();  // the Uptime section was removed
    expect(within(kpi('Sites below 60%')).getByText('-2 (-16.7%)')).toBeInTheDocument();       // counts: absolute and %
    expect(screen.getByRole('group', { name: 'Reporting period' }).querySelector('#period-vs-date')).toHaveValue('2026-10-02');
    expect(screen.queryByLabelText('Reporting periods')).not.toBeInTheDocument();  // the period summary box was removed
  });

  it('shows the portfolio KPIs first: total sites, On-Air and O&M Start in one card, then conversion progress', async () => {
    // Circle-wise breakdowns per scope that add up to the summary totals (700 / 650 / 620).
    // Every circle carries its total sites (site status, whatever the population): 400 + 300 = 700.
    const circles = (fourG: number, lwe: number) => ({ ...breakdown, circles: [
      { ...breakdown.circles[0], report_type: '4G Saturation', circle: 'MP', sites_in_scope: fourG, sites_total: 400 },
      { ...breakdown.circles[0], report_type: 'LWE', circle: 'JH', sites_in_scope: lwe, sites_total: 300 },
    ] });
    m.fetchBreakdowns.mockImplementation(async (params) => {
      const scope = (params as URLSearchParams).get('scope');
      return scope === 'om_start' ? circles(340, 280) : circles(360, 290);
    });
    renderPage();
    await screen.findByText('Site Portfolio — Summary');
    const sections = [...document.querySelectorAll('section[aria-label]')].map((e) => e.getAttribute('aria-label'));
    expect(sections.slice(0, 2)).toEqual(['Site status (not filtered by population)', 'Uptime buckets (MTD) · Population: On-Air sites']);
    const top = screen.getByRole('region', { name: 'Site status (not filtered by population)' });
    const cards = [...top.querySelectorAll(':scope > div > [data-slot="card"]')];
    expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual(['Site status: total, On-Air & O&M Start', 'Site Conversion Progress']);
    expect(top.querySelector(':scope > div')).toHaveClass('items-stretch');
    expect(cards.every((card) => card.classList.contains('h-full'))).toBe(true);
    // 1. One status card: total sites with the split by network, On-Air 650, O&M Start 620, difference 650 − 620 = 30.
    const merged = screen.getByRole('region', { name: 'Site status: total, On-Air & O&M Start' });
    expect([...within(merged).getAllByRole('term')].map((t) => t.textContent)).toEqual(['Total sites', 'On-Air sites', 'O&M Start sites', 'Difference']);
    expect([...merged.querySelectorAll('dd[class~="text-[22px]"]')].map((d) => d.textContent)).toEqual(['700', '650', '620', '30']);
    // Achievement against total scope: On-Air 650 / 700, O&M Start 620 / 700.
    expect(within(merged).getByText('92.9%')).toHaveClass('text-sky-700');
    expect(within(merged).getByText('88.6%')).toHaveClass('text-emerald-700');
    expect(within(merged).getByText('30')).toHaveClass('text-red-600');  // outstanding work is red
    // Remaining sites against total scope in red: 700 − 650 = 50 not On-Air, 700 − 620 = 80 remaining for O&M Start.
    const conv = screen.getByRole('region', { name: 'Site Conversion Progress' });
    expect(within(conv).getByText((_, el) => el?.textContent === '50 not On-Air')).toHaveClass('text-red-600');
    expect(within(conv).getByText((_, el) => el?.textContent === '80 remaining')).toHaveClass('text-red-600');
    expect(within(merged).getByText('On-Air, not yet O&M Start')).toBeInTheDocument();
    // 4G Saturation / LWE under every KPI, adding up to its total; Difference per project = On-Air − O&M Start, in red.
    const splitOf = async (kpi: string) => [...(await within(merged).findByLabelText(`${kpi} by project`)).children].map((r) => r.textContent);
    expect(await splitOf('Total sites')).toEqual(['4G Saturation400', 'LWE300']);
    expect(await splitOf('On-Air sites')).toEqual(['4G Saturation360', 'LWE290']);
    expect(await splitOf('O&M Start sites')).toEqual(['4G Saturation340', 'LWE280']);
    expect(await splitOf('Difference')).toEqual(['4G Saturation20', 'LWE10']);
    expect(within(within(merged).getByLabelText('Difference by project')).getByText('20')).toHaveClass('text-red-600');
    expect(within(merged).queryByRole('link')).not.toBeInTheDocument();
    // 2. Conversion progress against total scope (700): On-Air 650 (92.9%, 50 not On-Air), O&M Start 620 (88.6%, 80 remaining).
    const conversion = screen.getByRole('region', { name: 'Site Conversion Progress' });
    expect(within(conversion).getByText('700')).toBeInTheDocument();
    expect(within(conversion).getByRole('img', { name: 'On-Air: 92.9% of total site scope' })).toBeInTheDocument();
    expect(within(conversion).getByRole('img', { name: 'O&M Start: 88.6% of total site scope' })).toBeInTheDocument();
    expect(within(conversion).getByText((_, el) => el?.textContent === '· 50 not On-Air')).toBeInTheDocument();
    expect(within(conversion).getByText((_, el) => el?.textContent === '· 80 remaining')).toBeInTheDocument();
    expect(within(conversion).queryByRole('link')).not.toBeInTheDocument();
    // Monthly additions remain chronological; a month without dates is "—", not 0.
    const table = await within(conversion).findByRole('table', { name: 'Monthly additions' });
    const cells = within(table).getAllByRole('row').map((r) => [...r.querySelectorAll('th,td')].map((c) => c.textContent));
    expect(cells).toEqual([['Added in month', 'Aug-26', 'Sep-26', 'Oct-26'], ['On-Air', '18', '27', '—'], ['O&M Start', '36', '54', '12']]);
    expect(within(conversion).queryByText(/dates in the escalation matrix/)).not.toBeInTheDocument();
    expect(fetchActivity.mock.calls.map((c) => Object.fromEntries(c[0] as URLSearchParams))).toEqual([
      { month: '2026-10' }, { month: '2026-09' },
    ]);
    expect(screen.queryByText(/handover/i)).not.toBeInTheDocument();
    // Removed from this page, with no image content.
    for (const removed of ['Circles / States', 'Sites not yet On-Air', 'Network scope', 'Handover & O&M']) {
      expect(screen.queryByText(removed)).not.toBeInTheDocument();
    }
    expect(document.querySelector('main img, [role="region"] img, img')).toBeNull();
    expect(screen.queryByText(/Data as of/)).not.toBeInTheDocument();
  });

  it('uses the selected reporting month to load three consecutive activity months', async () => {
    const novemberOptions = {
      ...filterOptions,
      reporting_dates: [...filterOptions.reporting_dates, '2026-11-02'],
      default_date: '2026-11-02',
      months: [...filterOptions.months, { key: '2026-11', label: 'Nov-26 MTD' }],
      month: { label: 'Nov-26', start: '2026-11-01', end: '2026-11-30' },
    };
    m.fetchFilterOptions.mockResolvedValue(novemberOptions);
    renderPage('/portfolio?date=2026-11-02&report_type=LWE&circle=MP');

    await screen.findByText('Site Portfolio — Summary');
    const conversion = screen.getByRole('region', { name: 'Site Conversion Progress' });
    const table = await within(conversion).findByRole('table', { name: 'Monthly additions' });
    await waitFor(() => expect(within(table).getAllByRole('columnheader').map((h) => h.textContent))
      .toEqual(['Added in month', 'Sep-26', 'Oct-26', 'Nov-26']));
    expect(fetchActivity.mock.calls.map((c) => Object.fromEntries(c[0] as URLSearchParams)).sort((a, b) => String(a.month).localeCompare(String(b.month))))
      .toEqual([
        { month: '2026-10', report_type: 'LWE', circle: 'MP' },
        { month: '2026-11', report_type: 'LWE', circle: 'MP' },
      ]);
    await waitFor(() => expect(within(table).getAllByRole('row').map((r) => [...r.querySelectorAll('th,td')].map((c) => c.textContent))).toEqual([
      ['Added in month', 'Sep-26', 'Oct-26', 'Nov-26'],
      ['On-Air', '27', '17', '—'],
      ['O&M Start', '54', '100', '—'],
    ]));
  });

  it('shows its title and reporting context in the top bar, with the filters first on the page', async () => {
    const { AppLayout } = await import('../layouts/AppLayout');
    renderWithWorkbook(<TrackingProvider><AppLayout><PortfolioPage /></AppLayout></TrackingProvider>, { url: '/portfolio?report_type=LWE&circle=MP' });
    const banner = screen.getByRole('banner');
    expect(await within(banner).findByRole('heading', { name: 'Site Portfolio — Summary' })).toBeInTheDocument();
    expect(within(banner).getByText(/^Circle MP · LWE · Population: On-Air sites · 03 Oct 2026 · MTD 01–03 Oct \(3 days\)$/)).toBeInTheDocument();
    expect(within(banner).queryByText(/Latest reporting date/)).not.toBeInTheDocument();
    // The title appears once: the filters card has no title of its own.
    expect(screen.getAllByRole('heading', { name: /Site Portfolio/ })).toHaveLength(1);
    const filters = screen.getByRole('search', { name: 'Portfolio filters' });
    expect(filters.closest('[data-slot="card"]')!.querySelector('h1, h2')).toBeNull();
    expect(screen.queryByRole('combobox', { name: 'Open circle details' })).not.toBeInTheDocument();
  });

  it('applies the circle, date and report type to every request', async () => {
    renderPage('/portfolio?circle=MP&date=2026-10-03&report_type=LWE');
    await screen.findByText('Site Portfolio — Summary');
    await waitFor(() => expect(m.fetchBreakdowns).toHaveBeenCalled());
    expect(calls().every((c) => c.circle === 'MP' && c.report_type === 'LWE')).toBe(true);
    // Status On-Air and O&M Start (the On-Air one is also the selected population's), and the previous date.
    expect(calls().map((c) => c.reporting_date).sort()).toEqual(['2026-10-02', '2026-10-03', '2026-10-03']);
    expect(new Set(calls().map((c) => c.scope))).toEqual(new Set(['on_air', 'om_start']));
    expect(Object.fromEntries(m.fetchBreakdowns.mock.calls[0][0] as URLSearchParams)).toMatchObject({ circle: 'MP', report_type: 'LWE', reporting_date: '2026-10-03' });
  });

  it('drops comparisons when "No comparison" is chosen', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Site Portfolio — Summary');
    expect(await within(kpi('Sites below 60%')).findByText('-2 (-16.7%)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'No comparison' }));
    expect(screen.queryAllByText('-2 (-16.7%)')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Compare' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('links KPIs to the detailed views with filters applied', async () => {
    renderPage('/portfolio?circle=MP');
    await screen.findByText('Site Portfolio — Summary');
    expect(screen.getByRole('link', { name: 'Sites below 60%' })).toHaveAttribute('href', '/?circle=MP&date=2026-10-03&bucket=lt_60');
    expect(screen.getByRole('link', { name: 'Sites at 98.5% or above' })).toHaveAttribute('href', '/thresholds?circle=MP&date=2026-10-03');
  });

  it('no longer shows the removed sections: reporting cards, comparisons and needs attention', async () => {
    renderPage();
    await screen.findByText('Site Portfolio — Summary');
    await screen.findByRole('region', { name: 'Circle-wise Site Portfolio Breakdown' });
    for (const removed of ['Liquidity Plan', 'Reporting and operations', 'Reporting completeness', 'CSV submissions pending', 'CSV submissions late',
      'Open data alerts', 'Circle-wise comparison', 'Operational differences', 'Portfolio comparisons', '4G vs LWE',
      'Current vs previous reporting date', 'Needs attention']) {
      expect(screen.queryByText(removed)).not.toBeInTheDocument();
    }
    expect(m.fetchAlerts).not.toHaveBeenCalled();  // nothing left on the page uses alerts
  });

  it('uses only the selected population for every performance figure and refetches when it changes', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TrackingProvider><Routes><Route path="/portfolio" element={<><PortfolioPage /><Location /></>} /></Routes></TrackingProvider>,
      { url: '/portfolio', population: true });
    await screen.findByText('Site Portfolio — Summary');
    expect(within(kpi('Sites below 60%')).getByText('10')).toBeInTheDocument();  // On-Air (default)
    expect(screen.getByRole('region', { name: 'Uptime buckets (MTD) · Population: On-Air sites' })).toBeInTheDocument();
    m.fetchSummary.mockClear();
    m.fetchPeriod.mockClear();
    await user.click(screen.getByRole('combobox', { name: 'Population' }));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['On-Air', 'O&M Start']);  // 'All sites' is not offered
    await user.click(screen.getByRole('option', { name: 'O&M Start' }));
    expect(await screen.findByRole('region', { name: 'Uptime buckets (MTD) · Population: O&M Start sites' })).toBeInTheDocument();
    await waitFor(() => expect(within(kpi('Sites below 60%')).getByText('7')).toBeInTheDocument());  // the O&M Start figure
    expect(screen.getByTestId('location')).toHaveTextContent('scope=om_start');
    // The comparison date is requested for the selected population only.
    await waitFor(() => expect(calls()).toContainEqual(expect.objectContaining({ scope: 'om_start', reporting_date: '2026-10-02' })));
    expect(calls().filter((c) => c.reporting_date === '2026-10-02').every((c) => c.scope === 'om_start')).toBe(true);
    // Status counts are unchanged and still labelled as status.
    expect(within(screen.getByRole('region', { name: 'Site status: total, On-Air & O&M Start' })).getByText('700')).toBeInTheDocument();
  });

  it('requests weekly and monthly figures for the selected population only (no side-by-side populations)', async () => {
    renderWithWorkbook(<TrackingProvider><PortfolioPage /></TrackingProvider>, { url: '/portfolio?scope=om_start&view=month&month=2026-09', population: true });
    await screen.findByText('Site Portfolio — Summary');
    await waitFor(() => expect(m.fetchPeriod).toHaveBeenCalled());
    expect(new Set(periodCalls().map((c) => c.scope))).toEqual(new Set(['om_start']));
    expect(screen.queryByText('O&M Start uptime')).not.toBeInTheDocument();
    expect(screen.queryByText('On-Air uptime')).not.toBeInTheDocument();
  });

  it('shows an error and no figures when the data cannot be loaded', async () => {
    m.fetchSummary.mockRejectedValue(new api.ApiError('The workbook could not be read.', 503));
    renderPage();
    expect(await screen.findByText('Portfolio data is unavailable')).toBeInTheDocument();
    expect(screen.queryByText('Total sites')).not.toBeInTheDocument();
  });
});

describe('Circle-wise Site Portfolio Breakdown', () => {
  // Site Scope is full inventory; CI/IE assignments follow the response population.
  const teams = (ci_count: number, ie_count: number) => ({ ci_count, ie_count, sites_without_ci: 0, sites_without_ie: 0 });
  const byScope = (n: Record<string, number>, isOm = false) => ({
    ...breakdown,
    circles: [
      { ...breakdown.circles[0], report_type: '4G Saturation', circle: 'MP', sites_in_scope: n.mp4g, sites_total: 1483, om_heads: ['Mira One', 'Mira Two'], ...teams(isOm ? 9 : 10, isOm ? 88 : 91) },
      { ...breakdown.circles[0], report_type: 'LWE', circle: 'MP', sites_in_scope: n.mpLwe, sites_total: 22, om_heads: ['Ravi Head'], ...teams(1, 1) },
      { ...breakdown.circles[0], report_type: 'LWE', circle: 'BH', sites_in_scope: n.bh, sites_total: 250, om_heads: [], ...teams(3, 20) },
    ],
    team_totals: isOm
      ? { all: teams(20, 170), '4G Saturation': teams(19, 168), LWE: teams(1, 2) }
      : { all: teams(21, 180), '4G Saturation': teams(20, 178), LWE: teams(1, 4) },
  });
  beforeEach(() => {
    m.fetchBreakdowns.mockImplementation(async (params) => {
      const scope = params.get('scope');
      return scope === 'om_start'
        ? byScope({ mp4g: 1332, mpLwe: 19, bh: 250 }, true)
        : byScope({ mp4g: 1351, mpLwe: 20, bh: 250 });
    });
  });

  it('sits directly under the KPI cards, groups 4G and LWE and reconciles its totals', async () => {
    renderPage();
    const table = await screen.findByRole('region', { name: 'Circle-wise Site Portfolio Breakdown' });
    const order = [...document.querySelectorAll('section[aria-label], [role="region"], h2')].map((e) => e.getAttribute('aria-label') ?? e.textContent);
    expect(order.indexOf('Circle-wise Site Portfolio Breakdown')).toBe(order.lastIndexOf('Uptime bucket mix') + 1);  // the last KPI card
    const row = (name: string) => [...(within(table).getByRole('rowheader', { name }).closest('tr')!.querySelectorAll('td'))].map((c) => c.textContent);
    // Circle, Client, O&M Head, Site Scope, On Air, O&M Start, gaps, Remarks (MP appears once per network)
    expect(within(table).getAllByRole('rowheader', { name: 'MP' })).toHaveLength(2);
    const mp4g = within(table).getByRole('rowgroup', { name: '4G Saturation circles' });
    expect([...within(mp4g).getByRole('rowheader', { name: 'MP' }).closest('tr')!.querySelectorAll('td')].map((c) => c.textContent).slice(0, 7))
      .toEqual(['4G', 'Mira One, Mira Two', '1,483', '1,351', '1,332', '151', '19']);
    expect(row('BH').slice(2, 7)).toEqual(['250', '250', '250', '0', '0']);
    const subtotal = within(table).getByRole('row', { name: 'LWE subtotal' });
    expect([...subtotal.querySelectorAll('td')].map((c) => c.textContent).slice(0, 5)).toEqual(['272', '270', '269', '3', '1']);
    const total = within(table).getByRole('row', { name: 'Overall total' });
    expect([...total.querySelectorAll('td')].map((c) => c.textContent).slice(0, 5)).toEqual(['1,755', '1,621', '1,601', '154', '20']);
    expect(within(table).getByTestId('strip-siteScope')).toHaveTextContent('1,755');  // the strip matches the total row
    expect(within(table).getByTestId('strip-gapOnAir')).toHaveTextContent('20');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent).slice(8, 12)).toEqual(['CIs', 'IEs', 'Sites per CI', 'Sites per IE']);
  });

  it('applies the report type filter and never double-counts subtotals', async () => {
    renderPage('/portfolio?report_type=LWE');
    await screen.findByRole('region', { name: 'Circle-wise Site Portfolio Breakdown' });
    const params = m.fetchBreakdowns.mock.calls.map((c) => Object.fromEntries(c[0] as URLSearchParams));
    expect(params.every((p) => p.report_type === 'LWE')).toBe(true);
    expect(new Set(params.map((p) => p.scope))).toEqual(new Set(['on_air', 'om_start']));  // the two supported status populations
  });

  it('updates CI/IE counts and per-person ratios with the global population filter', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByRole('region', { name: 'Circle-wise Site Portfolio Breakdown' });
    const mp4gCells = () => {
      const row = within(within(table).getByRole('rowgroup', { name: '4G Saturation circles' }))
        .getByRole('rowheader', { name: 'MP' }).closest('tr')!;
      return [...row.querySelectorAll('td')].map((cell) => cell.textContent);
    };

    expect(mp4gCells().slice(7, 11)).toEqual(['10', '91', '135.1', '14.8']);
    await user.click(screen.getByRole('combobox', { name: 'Population' }));
    await user.click(screen.getByRole('option', { name: 'O&M Start' }));
    await waitFor(() => expect(mp4gCells().slice(7, 11)).toEqual(['9', '88', '148.0', '15.1']));
    // Site Scope remains the full Matrix inventory when the selected population changes.
    expect(mp4gCells()[2]).toBe('1,483');
  });

  it('shows all API-assigned O&M Heads and a dash when a circle has none', async () => {
    renderPage();
    const table = await screen.findByRole('region', { name: 'Circle-wise Site Portfolio Breakdown' });
    const omHead = (group: string, circle: string) => within(within(table).getByRole('rowgroup', { name: group }))
      .getByRole('rowheader', { name: circle }).closest('tr')!.querySelectorAll('td')[1];
    expect(omHead('4G Saturation circles', 'MP')).toHaveTextContent('Mira One, Mira Two');
    expect(omHead('LWE circles', 'MP')).toHaveTextContent('Ravi Head');
    expect(omHead('LWE circles', 'BH')).toHaveTextContent('—');
    expect(within(table).queryByRole('textbox', { name: /O&M Head/ })).not.toBeInTheDocument();
  });

  it('keeps Remarks editable in browser memory without editing O&M Head assignments', async () => {
    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByRole('region', { name: 'Circle-wise Site Portfolio Breakdown' });
    await user.click(within(table).getByRole('button', { name: 'Edit Remarks for BH LWE' }));
    await user.type(within(table).getByLabelText('Remarks for BH LWE'), 'All sites in O&M');
    await user.click(within(table).getByRole('button', { name: 'Save' }));
    const bh = within(table).getByRole('rowheader', { name: 'BH' }).closest('tr')!;
    expect(bh.querySelectorAll('td')[1]).toHaveTextContent('—');
    expect(bh).toHaveTextContent('All sites in O&M');
    expect(within(table).getByText(/held in this browser only/)).toBeInTheDocument();
  });
});

describe('navigation', () => {
  it('lists Site Portfolio first, above Overview, and highlights it', () => {
    renderWithWorkbook(<Sidebar />, { url: '/portfolio' });
    const links = within(screen.getByRole('navigation', { name: 'Main' })).getAllByRole('link').map((a) => a.textContent);
    expect(links.slice(0, 3)).toEqual(['Site Portfolio', 'Master Data', 'Overview']);
    expect(screen.getByRole('link', { name: 'Site Portfolio' })).toHaveAttribute('aria-current', 'page');
  });

  it('lands on Site Portfolio only for a plain visit to "/"', () => {
    expect(landsOnPortfolio('/', '')).toBe(true);
    expect(landsOnPortfolio('/', '?bucket=lt_60')).toBe(false);
    expect(landsOnPortfolio('/', '?report_type=LWE')).toBe(false);
    expect(landsOnPortfolio('/thresholds', '')).toBe(false);
  });
});

describe('Site Portfolio period filters', () => {
  const group = () => screen.getByRole('group', { name: 'Reporting period' });

  it('daily: compares the date with the previous date by default, or with another date, never another kind of period', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TrackingProvider><Routes><Route path="/portfolio" element={<><PortfolioPage /><Location /></>} /></Routes></TrackingProvider>,
      { url: '/portfolio' });
    await screen.findByText('Site Portfolio — Summary');
    expect(within(group()).getByRole('button', { name: 'Daily' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group()).getByLabelText('Date')).toHaveValue('2026-10-03');
    expect(within(group()).getByLabelText('Compare with date')).toHaveValue('2026-10-02');
    expect(within(group()).queryByLabelText(/week|month/i)).not.toBeInTheDocument();
    fireEvent.change(within(group()).getByLabelText('Compare with date'), { target: { value: '2026-10-01' } });
    expect(screen.getByTestId('location')).toHaveTextContent('vs=2026-10-01');
    await waitFor(() => expect(calls().some((c) => c.reporting_date === '2026-10-01')).toBe(true));
    expect(await within(kpi('Sites below 60%')).findByText('vs 01 Oct')).toBeInTheDocument();
    // A date without data is reported, not applied.
    fireEvent.change(within(group()).getByLabelText('Date'), { target: { value: '2026-09-15' } });
    expect(screen.getByRole('list', { name: 'Period notes' })).toHaveTextContent('No data for 15 Sep 2026: choose a reporting date between 01 Oct 2026 and 03 Oct 2026.');
    expect(screen.getByTestId('location')).not.toHaveTextContent('date=2026-09-15');
    await user.click(within(group()).getByRole('button', { name: 'Previous date' }));
    expect(screen.getByTestId('location')).toHaveTextContent('date=2026-10-02');
    expect(m.fetchPeriod).not.toHaveBeenCalled();
  });

  it('weekly: shows the workbook week with its dates, and explains a comparison week the workbook cannot supply', async () => {
    renderPage('/portfolio?view=week');
    await screen.findByText('Site Portfolio — Summary');
    expect(within(group()).getByRole('button', { name: 'Weekly' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group()).getByRole('combobox', { name: 'Week' })).toHaveTextContent('Wk-1 · 01–07 Oct 2026');
    expect(screen.getByRole('list', { name: 'Period notes' })).toHaveTextContent('Comparison Wk-4: Sep-26 has no daily data in the workbook.');  // Wk-4 of Sep, not substituted
    await waitFor(() => expect(periodCalls()).toContainEqual(expect.objectContaining({ scope: 'on_air', period: 'days', days: '2026-10-01,2026-10-02,2026-10-03' })));
    expect(periodCalls().every((c) => c.days !== '' && !c.months)).toBe(true);  // no request for the unavailable week
    expect(await within(kpi('Sites below 60%')).findByText('10')).toBeInTheDocument();
    expect(within(kpi('Sites below 60%')).getByText('Wk-1')).toBeInTheDocument();
    expect(screen.queryByText('On-Air uptime')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Uptime bucket mix' })).toHaveTextContent('640');
  });

  it('monthly: the month in progress is MTD only; MTD needs the same days of the comparison month', async () => {
    renderPage('/portfolio?view=month');
    await screen.findByText('Site Portfolio — Summary');
    expect(within(group()).getByRole('button', { name: 'Month: Oct-26' })).toBeInTheDocument();
    expect(within(group()).getByRole('button', { name: 'MTD' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group()).getByRole('button', { name: 'Full month' })).toBeDisabled();
    expect(screen.getByRole('list', { name: 'Period notes' })).toHaveTextContent('Comparison Sep-26 MTD: Sep-26 has no daily data in the workbook, so 01–03 Sep 2026 cannot be computed.');
    await waitFor(() => expect(periodCalls()).toContainEqual(expect.objectContaining({ period: 'days', days: '2026-10-01,2026-10-02,2026-10-03' })));
    expect(periodCalls().some((c) => c.months)).toBe(false);  // never compared with a monthly total
  });

  it('monthly: a full month is compared with the full month before, from the monthly totals', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TrackingProvider><Routes><Route path="/portfolio" element={<><PortfolioPage /><Location /></>} /></Routes></TrackingProvider>,
      { url: '/portfolio?view=month' });
    await screen.findByText('Site Portfolio — Summary');
    await user.click(within(group()).getByRole('button', { name: 'Month: Oct-26' }));
    expect(screen.getByRole('button', { name: /^Jul 2026 \(No data in the workbook\)/ })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Sep 2026' }));
    expect(screen.getByTestId('location')).toHaveTextContent('month=2026-09');
    expect(within(group()).getByRole('button', { name: 'Full month' })).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(periodCalls()).toContainEqual(expect.objectContaining({ period: 'months', months: '2026-08', scope: 'on_air' })));
    expect(await within(kpi('Sites below 60%')).findByText('-2 (-16.7%)')).toBeInTheDocument();  // Sep 10 vs Aug 12
    expect(within(kpi('Sites below 60%')).getByText('vs Aug-26')).toBeInTheDocument();
    // Sep has 30 days and Aug 31: said once, and outage minutes are not compared.
    expect(screen.getByRole('list', { name: 'Period notes' })).toHaveTextContent('The periods cover a different number of days (30 and 31)');
  });

  it('keeps the period, project and circle filters in one compact bar, with "Project" for the report type', async () => {
    const user = userEvent.setup();
    renderPage('/portfolio?report_type=LWE');
    await screen.findByText('Site Portfolio — Summary');
    const bar = screen.getByRole('search', { name: 'Portfolio filters' });
    expect(within(bar).getByRole('group', { name: 'Reporting period' })).toBeInTheDocument();
    expect(within(bar).getByRole('combobox', { name: 'Project' })).toHaveTextContent('LWE');
    expect(within(bar).getByRole('combobox', { name: 'Circle' })).toBeInTheDocument();
    expect(screen.queryByRole('search', { name: 'Dashboard filters' })).not.toBeInTheDocument();  // no second filter card
    expect(screen.queryByText(/report type/i)).not.toBeInTheDocument();
    await user.click(within(bar).getByRole('combobox', { name: 'Project' }));
    await user.click(await screen.findByRole('option', { name: 'All projects' }));
    expect(screen.getByText(/All circles · All projects/)).toBeInTheDocument();
  });

  it('switching granularity resets the comparison and keeps the choice in the URL', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TrackingProvider><Routes><Route path="/portfolio" element={<><PortfolioPage /><Location /></>} /></Routes></TrackingProvider>,
      { url: '/portfolio?vs=2026-10-01' });
    await screen.findByText('Site Portfolio — Summary');
    await user.click(within(group()).getByRole('button', { name: 'Weekly' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/portfolio?view=week');
    expect(screen.getByTestId('location')).not.toHaveTextContent('vs=');
    await user.click(within(group()).getByRole('button', { name: 'Monthly' }));
    expect(screen.getByTestId('location')).toHaveTextContent('view=month');
    expect(within(group()).queryByRole('combobox', { name: 'Week' })).not.toBeInTheDocument();
  });
});

describe('Site Portfolio on the new data layer', () => {
  it('reads the new data layer and does not depend on the old workbook status', async () => {
    renderWithWorkbook(<TrackingProvider><PortfolioPage /></TrackingProvider>, { url: '/portfolio', workbook: workbookValue({ active: null, loading: false }) });
    expect(await screen.findByText('Site Portfolio — Summary')).toBeInTheDocument();
    expect(screen.queryByText('No reporting data loaded')).not.toBeInTheDocument();
    expect(m.fetchFilterOptions).toHaveBeenCalled();  // routed through services/sitePortfolioApi
  });

  it('says where MTD stops when a reporting date has no data', async () => {
    m.fetchFilterOptions.mockResolvedValue({ ...filterOptions, source: { ...filterOptions.source,
      continuity: { dates_with_data: ['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-05'], continuous_until: '2026-10-03', excluded_after_gap: ['2026-10-05'] } } } as never);
    renderPage();
    const notice = await screen.findByText(/MTD ends on/);
    expect(notice.closest('[role="alert"]')).toHaveTextContent('05 Oct');
  });

  it('shows the reporting days used for a week or month', async () => {
    renderPage('/portfolio?view=week');
    expect(await screen.findByText(/Uptime buckets · Wk-1 · 3 reporting days/)).toBeInTheDocument();
  });
});
