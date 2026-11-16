import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAdmin } from '../../components/auth/Guards';
import { Sidebar } from '../../components/Sidebar';
import * as api from '../../services/api';
import { CI_PERMISSIONS, CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { AuthUser } from '../../types';
import type { RcaBreakdown, RcaCauses, RcaOptions, RcaOverviewResponse, RcaPage, RcaRecord, RcaRecordDetail, RcaSummary } from '../../types/rca';
import { RcaMappingPage } from './RcaMappingPage';
import { RcaRegisterPage } from './RcaRegisterPage';
import { RcaSummaryPage } from './RcaSummaryPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRcaOptions: vi.fn(), fetchRcaRecords: vi.fn(), fetchRcaRecord: vi.fn(), updateRcaWorkflow: vi.fn(), fetchRcaSummary: vi.fn(),
  fetchRcaCauses: vi.fn(), mapRcaCauses: vi.fn(), createRcaCategory: vi.fn(), fetchRcaOverview: vi.fn(),
}));
const m = vi.mocked(api);

const OPTIONS: RcaOptions = {
  dates: ['2026-10-21'], months: [{ month: '2026-10', dates_with_records: 1 }], projects: ['4G Saturation', 'LWE'],
  circles: [{ project: '4G Saturation', circle: 'OD', circle_raw: 'Odisha' }, { project: 'LWE', circle: 'BH', circle_raw: 'Bihar' }],
  final_buckets: [{ value: 'other media', label: 'Other Media', unclassified: false }],
  bucket_2: [{ value: 'bsnl media', label: 'BSNL Media', unclassified: false }, { value: '__unclassified__', label: 'Unclassified (blank or "-")', unclassified: true }],
  categories: [], statuses: [{ value: 'investigation', label: 'Investigation' }], total_records: 2,
};
const REC: RcaRecord = {
  id: 1, reporting_date: '2026-10-21', project: '4G Saturation', project_raw: '4G Satu', circle: 'OD', circle_raw: 'Odisha', site_id: 'OD0001',
  site_name: 'Bravo', oa: 'KORAPUT', ba: 'KORAPUT', om_start_raw: 'YES', om_start: true, outage_minutes: 1442.55, final_bucket: 'BSNL OFC',
  final_bucket_unclassified: false, bucket_2: '-', bucket_2_unclassified: true, rca_text: 'SSA OFC Break', rca_unclassified: false, rca_applicable: true,
  category: null, source: 'import', status: null, status_label: null,
};
const PAGE: RcaPage = { count: 2, page: 1, page_size: 25, pages: 1, results: [REC, { ...REC, id: 2, site_id: 'LWEBH0063', project: 'LWE', project_raw: 'LWE', circle: 'BH', outage_minutes: 20.6, bucket_2: 'BSNL Media', bucket_2_unclassified: false, rca_text: 'Media Flacuatation' }] };
const DETAIL: RcaRecordDetail = { ...REC, source_file: 'Book1_RCA_Rustam.xlsx', source_row: 7, batch: 1, created_by: null, created_at: '2026-10-26T09:05:00', workflow: null, comments: [], history: [], other_records: [] };
const BREAKDOWN_LABELS = [
  'IaasP Power', 'IaasP Others', 'IaasP Battery', 'IaasP OFC', 'BSNL OFC',
  'BSNL Media', 'Others', 'TCS', 'DMW', 'HFCL',
];
const counts = (values: Record<string, number>, empty = false) =>
  Object.fromEntries(BREAKDOWN_LABELS.map((l) => [l, empty ? null : (values[l] ?? 0)]));
const BREAKDOWN: RcaBreakdown = {
  through: '2026-10-26',
  columns: BREAKDOWN_LABELS.map((label) => ({ label, pending: false, final_buckets: [label] })),
  rows: [
    { circle: 'AP', has_records: false, counts: counts({}, true), grand_total: null, not_mapped: null },
    { circle: 'MP', has_records: true, counts: counts({ 'BSNL OFC': 30, Others: 10 }), grand_total: 40, not_mapped: 5 },
    { circle: 'OD', has_records: true, counts: counts({ 'BSNL OFC': 20, TCS: 40 }), grand_total: 60, not_mapped: 0 },
  ],
  totals: counts({ 'BSNL OFC': 50, TCS: 40, Others: 10 }),
  grand_total: 100,
  percent_of_total: Object.fromEntries(BREAKDOWN_LABELS.map((l) => [l, ({ 'BSNL OFC': 50, TCS: 40, Others: 10 } as Record<string, number>)[l] ?? 0])),
  not_mapped: { records: 5, values: [{ final_bucket: 'BB', records: 5 }] },
  records: 105,
  all_rca_records: 105,
  nsla_rca_records: 80,
  missing_availability: {
    count: 3,
    by_circle: { MP: 2, OD: 1 },
    sample: [{ site_id: 'UVMP999', circle: 'MP' }],
  },
  empty: false,
  sites: {
    period: { label: 'Month to date', first: '2026-10-01', last: '2026-10-26', days_reported: 26 },
    rows: {
      AP: { total_sites: 12, om_start_sites: 12, usd_sites: 11, nsla_sites: 4, days_reported: 26 },
      MP: { total_sites: 120, om_start_sites: 115, usd_sites: 100, nsla_sites: 60, days_reported: 26 },
      OD: { total_sites: 80, om_start_sites: 75, usd_sites: 70, nsla_sites: 30, days_reported: 26 },
    },
    total: { total_sites: 212, om_start_sites: 202, usd_sites: 181, nsla_sites: 94, days_reported: 26 },
  },
};
const SUMMARY: RcaSummary = {
  breakdown: BREAKDOWN,
  kpis: { records: 1819, affected_sites: 1819, outage_minutes: 632278.77, records_with_minutes: 1819, incomplete_records: 223, incomplete_by_field: { final_bucket: 0, bucket_2: 223, rca: 0 },
    missing_label: 'RCA Required — Missing Information', rca_applicable_records: 743, completeness_pct: 70,
    rca_not_applicable: { label: 'Other Media — RCA Not Applicable', final_buckets: ['Other Media'], records: 1076, outage_minutes: 155583.67, blank_bucket_2: 120 } },
  dates: [{ date: '2026-10-21', records: 1819 }],
  final_buckets: [
    { key: 'other media', label: 'Other Media', unclassified: false, rca_not_applicable: true, records: 1076, outage_minutes: 155583.67, variants: ['Other Media'] },
    { key: 'bbnl ofc', label: 'BBNL OFC', unclassified: false, rca_not_applicable: false, records: 99, outage_minutes: 131085.66, variants: ['BBNL OFC'] },
    { key: 'bsnl ofc', label: 'BSNL OFC', unclassified: false, rca_not_applicable: false, records: 222, outage_minutes: 123628.98, variants: ['BSNL OFC'] },
  ],
  bucket_2: [
    { key: 'bsnl media', label: 'BSNL Media', unclassified: false, rca_not_applicable: false, records: 610, outage_minutes: 1000, variants: ['BSNL MEDIA', 'BSNL Media'] },
    { key: '__unclassified__', label: 'Unclassified (blank or "-")', unclassified: true, rca_not_applicable: false, records: 223, outage_minutes: 500, variants: [] },
  ],
  circles: [
    { project: '4G Saturation', circle: 'OD', records: 522, outage_minutes: 1000, affected_sites: 522, portfolio_sites: 1603, records_per_100_sites: 32.6, minutes_per_portfolio_site: 0.6 },
    { project: 'LWE', circle: 'UP', records: 39, outage_minutes: 100, affected_sites: 39, portfolio_sites: 78, records_per_100_sites: 50, minutes_per_portfolio_site: 1.3 },
  ],
  projects: [
    { project: '4G Saturation', records: 1346, outage_minutes: 509459.16, affected_sites: 1346, rca_not_applicable: 700, incomplete_records: 150 },
    { project: 'LWE', records: 473, outage_minutes: 122819.61, affected_sites: 473, rca_not_applicable: 376, incomplete_records: 73 },
  ],
  cycle: {
    id: 4, name: 'October 2026 RCA Report', period_start: '2026-10-21', period_end: '2026-10-21', period_label: '21 Oct 2026', matches_filter: false,
    notes: null, created_by: 'noc-lead', created_at: '2026-10-22T09:00:00', records: 1819, uploads_summary: { total: 1, imported: 1, with_rejected_rows: 0, awaiting_confirmation: 0, validation_failed: 0, corrections: 0, last_upload_at: '2026-10-22T10:00:00Z' },
    status: { code: 'partial', label: 'Partially received', required: 3, received: 1, complete: false, final_version: null, can_finalize: false,
      upload_awaiting_confirmation: false, records_checksum: 'x',
      outstanding: [{ project: '4G Saturation', circle: 'RJ', status: 'pending', status_label: 'Pending — no accepted records' }, { project: 'LWE', circle: 'BH', status: 'pending', status_label: 'Pending — no accepted records' }] },
  },
  population_source: "Sites per circle in the dashboard's current Master data",
  categories: { mapped: [], unreviewed: { records: 1819, outage_minutes: 632278.77, descriptions: 394 }, no_description: { records: 0, outage_minutes: null } },
  top_records: [REC],
};

const OVERVIEW_MOCK: RcaOverviewResponse = {
  tab: 'circle',
  kpis: {
    own: { records: 280, outage_minutes: 31000, share_pct: 15.5 },
    customer: { records: 1100, outage_minutes: 117000, share_pct: 58.5 },
    third_party: { records: 130, outage_minutes: 40000, share_pct: 20.0 },
    pending: { records: 180, outage_minutes: 12000, share_pct: 6.0 },
    total_records: 1690,
    total_minutes: 200000,
  },
  count: 3,
  page: 1,
  page_size: 25,
  pages: 1,
  rows: [
    {
      id: 'OD',
      name: 'OD',
      detail: 'Odisha',
      site_count: 80,
      om_start_sites: 75,
      uptime_pct: 90.49,
      target: '> 98.5%',
      gap: -8.01,
      outage_min: 67962,
      status: 'Not Meeting SLA',
      split: { own: 23, customer: 41, third_party: 33, pending: 3 },
    },
    {
      id: 'AP',
      name: 'AP',
      detail: 'Andhra Pradesh',
      site_count: 12,
      om_start_sites: 12,
      uptime_pct: 99.11,
      target: '> 98.5%',
      gap: 0.61,
      outage_min: 198,
      status: 'Meeting SLA',
      split: { own: 0, customer: 83, third_party: 0, pending: 17 },
    },
    {
      id: 'EX',
      name: 'EX',
      detail: 'Exact Target',
      site_count: 10,
      om_start_sites: 10,
      uptime_pct: 98.50,
      target: '> 98.5%',
      gap: 0.00,
      outage_min: 500,
      status: 'Not Meeting SLA',
      split: null,
    },
  ],
  total_row: {
    id: 'TOTAL',
    name: 'Total',
    detail: '3 circle records',
    site_count: 102,
    om_start_sites: 97,
    uptime_pct: 95.80,
    target: '> 98.5%',
    gap: -2.70,
    outage_min: 68660,
    status: 'Not Meeting SLA',
    split: { own: 22, customer: 42, third_party: 33, pending: 3 },
  },
};

const NOC_LEAD: AuthUser = { username: 'noc.lead', name: 'NOC Lead', role: 'noc_lead', role_label: 'NOC Lead', must_change_password: false, permissions: CI_PERMISSIONS };
const Location = () => { const l = useLocation(); return <p data-testid="location">{l.pathname + l.search}</p>; };
const bars = (name: string) => within(screen.getByRole('list', { name })).getAllByRole('listitem').map((li) => li.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRcaOptions.mockResolvedValue(OPTIONS);
  m.fetchRcaRecords.mockResolvedValue(PAGE);
  m.fetchRcaRecord.mockResolvedValue(DETAIL);
  m.fetchRcaSummary.mockResolvedValue(SUMMARY);
  m.fetchRcaOverview.mockResolvedValue(OVERVIEW_MOCK);
});

describe('RCA Register', () => {
  it('lists records with source values, unclassified placeholders and no invented follow-up', async () => {
    renderWithWorkbook(<RcaRegisterPage />, { url: '/rca' });
    expect(await screen.findByText('2 RCA records')).toBeInTheDocument();
    const row = screen.getByRole('button', { name: 'OD0001' }).closest('tr')!;
    expect(within(row).getByText('1,443 min')).toBeInTheDocument();
    expect(within(row).getByText('Unclassified (-)')).toBeInTheDocument();  // Bucket - 2 "-" is not a cause
    expect(within(row).getByText('Not recorded')).toBeInTheDocument();  // no status until someone records one
    expect(within(row).getByText('Unreviewed')).toBeInTheDocument();
    expect(screen.getByText(/RCA data for 21 Oct 2026/)).toBeInTheDocument();
  });

  it('sends the filters and search to the API and keeps them in the URL', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><RcaRegisterPage /><Location /></>, { url: '/rca?project=LWE&bucket_2=__unclassified__' });
    await screen.findByText('2 RCA records');
    const params = m.fetchRcaRecords.mock.calls.at(-1)![0] as URLSearchParams;
    expect(Object.fromEntries(params)).toMatchObject({ project: 'LWE', bucket_2: '__unclassified__', page_size: '25' });
    await user.type(screen.getByLabelText('Search'), 'OFC');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('q=OFC'));
    expect(Object.fromEntries(m.fetchRcaRecords.mock.calls.at(-1)![0] as URLSearchParams)).toMatchObject({ q: 'OFC', project: 'LWE' });
  });

  it('opens a record with its read-only source facts and saves follow-up', async () => {
    const user = userEvent.setup();
    m.updateRcaWorkflow.mockResolvedValue({ ...DETAIL, status: 'investigation', status_label: 'Investigation',
      workflow: { status: 'investigation', status_label: 'Investigation', review_status: null, review_status_label: null, corrective_action: null, owner: 'OD O&M',
        target_date: null, completed_date: null, verification: null, verification_label: null, reviewer: null, reviewed_at: null, updated_by: 'ravi.ci', updated_at: '2026-10-26T10:00:00' } });
    renderWithWorkbook(<RcaRegisterPage />, { url: '/rca?record=1', auth: authValue({ user: CI_USER }) });
    const sheet = await screen.findByRole('dialog');
    expect(await within(sheet).findByText(/Book1_RCA_Rustam.xlsx, Excel row 7/)).toBeInTheDocument();
    expect(within(sheet).getByText(/source: “4G Satu”/)).toBeInTheDocument();
    expect(within(sheet).getByText(/Nothing has been recorded yet/)).toBeInTheDocument();
    // A CI cannot record the root-cause review or the verification.
    expect(within(sheet).getByRole('combobox', { name: /Root-cause review/ })).toBeDisabled();
    expect(within(sheet).getByRole('combobox', { name: /Verification outcome/ })).toBeDisabled();
    await user.type(within(sheet).getByLabelText(/Assigned owner/), 'OD O&M');
    await user.click(within(sheet).getByRole('button', { name: 'Save follow-up' }));
    expect(m.updateRcaWorkflow).toHaveBeenCalledWith(1, expect.objectContaining({ owner: 'OD O&M', status: '' }));
    expect(await within(sheet).findByText('Follow-up saved.')).toBeInTheDocument();
  });
});

describe('RCA Summary', () => {
  it('shows the 4 KPI cards, 4 tabs, and 8-column RCA overview table with SLA status', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<RcaSummaryPage />, { url: '/rca/summary' });
    expect(await screen.findByText(/Single-date snapshot: 21 Oct 2026/)).toBeInTheDocument();

    // 4 KPI Cards above the table: Own, Customer, Third Party, Pending
    const kpiRegion = screen.getByRole('region', { name: 'RCA attribution KPIs' });
    expect(within(kpiRegion).getByRole('group', { name: 'Own' })).toBeInTheDocument();
    expect(within(kpiRegion).getByRole('group', { name: 'Customer' })).toBeInTheDocument();
    expect(within(kpiRegion).getByRole('group', { name: 'Third Party' })).toBeInTheDocument();
    expect(within(kpiRegion).getByRole('group', { name: 'Pending' })).toBeInTheDocument();

    // 4 Tabs
    const tabNav = screen.getByRole('navigation', { name: 'RCA breakdown tabs' });
    expect(within(tabNav).getByRole('button', { name: 'Circle-wise' })).toBeInTheDocument();
    expect(within(tabNav).getByRole('button', { name: 'CI-wise' })).toBeInTheDocument();
    expect(within(tabNav).getByRole('button', { name: 'IE-wise' })).toBeInTheDocument();
    expect(within(tabNav).getByRole('button', { name: 'Site-wise' })).toBeInTheDocument();

    // 8 Exact Table Columns
    expect(screen.getByRole('columnheader', { name: 'Circle' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Site Count' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'O&M Start Sites' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Uptime %' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Target' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Gap' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Outage Min' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Split' })).toBeInTheDocument();

    // Verify unrequested columns are removed
    expect(screen.queryByRole('columnheader', { name: /Gross Uptime/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Net Uptime/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Customer %/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Own H/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Pending H/i })).not.toBeInTheDocument();

    // Verify SLA status: AP (>98.5%) is Meeting SLA; OD and EX (<=98.5%) are Not Meeting SLA
    const apRow = screen.getByRole('cell', { name: /Andhra Pradesh/i }).closest('tr')!;
    expect(within(apRow).getByText('Meeting SLA')).toBeInTheDocument();
    expect(within(apRow).getByText('+0.61%')).toBeInTheDocument();

    const exRow = screen.getByRole('cell', { name: /Exact Target/i }).closest('tr')!;
    expect(within(exRow).getByText('Not Meeting SLA')).toBeInTheDocument(); // exactly 98.5% is Not Meeting SLA
    expect(within(exRow).getByText('0.00%')).toBeInTheDocument();

    const odRow = screen.getByRole('cell', { name: /Odisha/i }).closest('tr')!;
    expect(within(odRow).getByText('Not Meeting SLA')).toBeInTheDocument();
    expect(within(odRow).getByText('-8.01%')).toBeInTheDocument();

    await user.click(within(screen.getByRole('navigation', { name: 'RCA Summary pages' })).getByRole('link', { name: 'Root Cause Analysis' }));
    const title = 'RCA classification: Final Bucket';
    // Technical causes are ranked; Other Media follows, labelled as not applicable, even though it has the most records.
    expect(bars(title).map((t) => t!.split(/\d/)[0])).toEqual(['BSNL OFC', 'BBNL OFC', 'Other Media — RCA not applicable']);
    // By outage minutes the order changes: 99 long BBNL outages outrank 222 BSNL ones.
    await user.click(within(screen.getByRole('group', { name: `${title} measure` })).getByRole('button', { name: 'Outage minutes' }));
    expect(bars(title).map((t) => t!.split(/\d/)[0])).toEqual(['BBNL OFC', 'BSNL OFC', 'Other Media — RCA not applicable']);
    expect(bars(title)[0]).toContain('1,31,086 min');
    expect(screen.getByText(/RCA-applicable records only: the 1,076 Other Media — RCA Not Applicable records are not included/)).toBeInTheDocument();
    // Bucket - 2: the "-" placeholder is listed last as unclassified, not ranked as a cause.
    expect(bars('Secondary classification: Bucket - 2 (per Final Bucket)').at(-1)).toMatch(/^Unclassified/);
  });

  it('compares circles by raw counts and outage minutes', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<RcaSummaryPage />, { url: '/rca/summary/circles' });
    await screen.findByText(/Single-date snapshot/);
    expect(bars('RCA by circle').map((t) => t!.slice(0, 2))).toEqual(['OD', 'UP']);  // raw incidents
    expect(screen.queryByRole('button', { name: 'Per 100 sites' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Outage min' }));
    await user.click(within(screen.getByRole('group', { name: 'Network' })).getByRole('button', { name: 'LWE' }));
    expect(bars('RCA by circle')).toHaveLength(1);
  });

  it('points to the review queue while no cause category has been approved, and opens records from the attention table', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<RcaSummaryPage />, { url: '/rca/summary/root-causes' });
    expect(await screen.findByRole('heading', { name: 'RCA Summary · Root Cause Analysis' })).toBeInTheDocument();
    expect(screen.queryByText('Standardised cause categories')).not.toBeInTheDocument();
    await user.click(within(screen.getByRole('navigation', { name: 'RCA Summary pages' })).getByRole('link', { name: 'Project & Circle Analysis' }));
    expect(await screen.findByRole('link', { name: 'OD0001' })).toHaveAttribute('href', '/rca?record=1');
  });

  it('shows the circle-wise root cause breakdown below the KPIs, reconciled and refreshed with the period', async () => {
    const user = userEvent.setup();
    m.fetchRcaOptions.mockResolvedValue({ ...OPTIONS, dates: ['2026-10-21', '2026-10-22'], months: [] });
    renderWithWorkbook(<RcaSummaryPage />, { url: '/rca/summary/breakdown' });
    const table = await screen.findByRole('region', { name: 'Circle-wise Root Cause Breakdown' });
    expect(screen.queryByRole('region', { name: 'RCA summary KPIs' })).not.toBeInTheDocument();  // its own page
    expect(within(table).getByText('Through 26 Oct 2026 · Final Bucket, filtered as above')).toBeInTheDocument();
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual(['Circle', 'Total Sites', 'O&M Start Sites', 'USD Sites', 'NSLA Sites (<98.5%)', ...BREAKDOWN_LABELS, 'Grand Total', 'Not mapped']);
    expect(headers).not.toContain('BSNL-Link');  // out of scope: removed
    expect(headers).not.toContain('PTPL-Techn');
    const row = (name: string) => within(table).getByRole('row', { name }).querySelectorAll('th, td');
    const at = (name: string, label: string) => row(name)[headers.indexOf(label)].textContent;
    expect([at('RCA % of Total', 'BSNL OFC'), at('RCA % of Total', 'TCS'), at('RCA % of Total', 'Grand Total')]).toEqual(['50%', '40%', '100%']);
    expect([at('Total', 'BSNL OFC'), at('Total', 'Grand Total'), at('Total', 'Not mapped')]).toEqual(['50', '100', '5']);
    expect([at('Circle MP', 'BSNL OFC'), at('Circle MP', 'Grand Total')]).toEqual(['30', '40']);
    expect([at('Circle AP', 'BSNL OFC'), at('Circle AP', 'Grand Total')]).toEqual(['', '']);  // no records: empty, not 0
    // Site columns (Site Master and performance) are filled even for a circle without RCA records.
    expect(['Total Sites', 'O&M Start Sites', 'USD Sites', 'NSLA Sites (<98.5%)'].map((l) => at('Circle AP', l))).toEqual(['12', '12', '11', '4']);
    expect(['Total Sites', 'O&M Start Sites', 'USD Sites', 'NSLA Sites (<98.5%)'].map((l) => at('Total', l))).toEqual(['212', '202', '181', '94']);
    expect(at('RCA % of Total', 'Total Sites')).toBe('');
    expect(within(table).getByText(/Not mapped \(outside the Grand Total\): BB 5\./)).toBeInTheDocument();

    // Missing availability notice
    expect(screen.getByRole('status', { name: 'Missing availability notification' })).toBeInTheDocument();
    expect(screen.getByText(/Availability Data Notice: 3 O&M Start sites have missing daily availability/)).toBeInTheDocument();

    // RCA Scope toggle
    const toggleGroup = screen.getByRole('group', { name: 'RCA incident scope toggle' });
    const allBtn = within(toggleGroup).getByRole('button', { name: /All RCA/ });
    const nslaBtn = within(toggleGroup).getByRole('button', { name: /NSLA RCA/ });
    expect(allBtn).toHaveAttribute('aria-pressed', 'true');
    expect(nslaBtn).toHaveAttribute('aria-pressed', 'false');
    await user.click(nslaBtn);
    expect(m.fetchRcaSummary).toHaveBeenLastCalledWith(new URLSearchParams({ rca_scope: 'nsla' }), 'on_air', expect.anything());
    await user.click(allBtn);
    expect(m.fetchRcaSummary).toHaveBeenLastCalledWith(new URLSearchParams(), 'on_air', expect.anything());
    m.fetchRcaSummary.mockResolvedValue({ ...SUMMARY, breakdown: { ...BREAKDOWN, through: '2026-10-22', rows: [], totals: counts({}), grand_total: 0, records: 0, empty: true,
      percent_of_total: counts({}, true), not_mapped: { records: 0, values: [] } } });
    await user.click(screen.getByRole('combobox', { name: 'Reporting date' }));
    await user.click(await screen.findByRole('option', { name: '22 Oct 2026' }));
    expect(m.fetchRcaSummary).toHaveBeenLastCalledWith(new URLSearchParams({ date_from: '2026-10-22', date_to: '2026-10-22' }), 'on_air', expect.anything());
    const updated = await screen.findByRole('region', { name: 'Circle-wise Root Cause Breakdown' });
    expect(await within(updated).findByText('No RCA records match these filters.')).toBeInTheDocument();
    expect(within(updated).getByText(/^Through 22 Oct 2026/)).toBeInTheDocument();
  });

  it('keeps the filters on every RCA Summary page and falls back to the Overview for unknown pages', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><RcaSummaryPage /><Location /></>, { url: '/rca/summary/trends?project=LWE&date_from=2026-10-21&date_to=2026-10-21' });
    expect(await screen.findByText('Daily: RCA records per reporting date')).toBeInTheDocument();
    expect(m.fetchRcaSummary).toHaveBeenLastCalledWith(new URLSearchParams({ date_from: '2026-10-21', date_to: '2026-10-21', project: 'LWE' }), 'on_air', expect.anything());
    const tabs = within(screen.getByRole('navigation', { name: 'RCA Summary pages' }));
    expect(tabs.getAllByRole('link').map((l) => l.textContent)).toEqual(['Overview', 'Circle-wise RCA Breakdown', 'Root Cause Analysis', 'Project & Circle Analysis', 'Daily & Monthly Trends']);
    expect(tabs.getByRole('link', { name: 'Daily & Monthly Trends' })).toHaveAttribute('aria-current', 'page');
    await user.click(tabs.getByRole('link', { name: 'Circle-wise RCA Breakdown' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/rca/summary/breakdown?project=LWE&date_from=2026-10-21&date_to=2026-10-21');
    expect(await screen.findByRole('region', { name: 'Circle-wise Root Cause Breakdown' })).toBeInTheDocument();
    await user.click(within(screen.getByRole('navigation', { name: 'RCA Summary pages' })).getByRole('link', { name: 'Overview' }));
    expect(await screen.findByRole('region', { name: 'RCA attribution KPIs' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/rca/summary?project=LWE&date_from=2026-10-21&date_to=2026-10-21');
  });

  it('opens the Overview, with the filters, for an unknown RCA Summary page', async () => {
    renderWithWorkbook(<><RcaSummaryPage /><Location /></>, { url: '/rca/summary/no-such-page?project=LWE' });
    expect(await screen.findByRole('region', { name: 'RCA attribution KPIs' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/rca\/summary\?project=LWE$/);
  });

  it('lists only reporting dates with records in the daily and monthly trends', async () => {
    m.fetchRcaSummary.mockResolvedValue({ ...SUMMARY, dates: [{ date: '2026-09-30', records: 4 }, { date: '2026-10-21', records: 10 }, { date: '2026-10-23', records: 6 }] });
    renderWithWorkbook(<RcaSummaryPage />, { url: '/rca/summary/trends' });
    const daily = within(await screen.findByRole('table', { name: 'RCA records per reporting date' })).getAllByRole('row').slice(1).map((r) => r.textContent);
    expect(daily).toEqual(['30 Sept 20264', '21 Oct 202610', '23 Oct 20266']);  // 22 Oct has no records: not listed as 0
    const monthly = within(screen.getByRole('table', { name: 'RCA records per month' })).getAllByRole('row').slice(1).map((r) => r.textContent);
    expect(monthly).toHaveLength(2);  // Sep and Oct; 22 Oct (no records) is not a zero
    expect(monthly).toEqual(['Sept 202641', 'Oct 2026162']);  // records, then reporting dates with records
  });

  it('selects one reporting date or a month aggregated from the dates with records', async () => {
    const user = userEvent.setup();
    m.fetchRcaOptions.mockResolvedValue({ ...OPTIONS, dates: ['2026-10-21', '2026-10-22'], months: [{ month: '2026-10', dates_with_records: 2 }] });
    renderWithWorkbook(<><RcaSummaryPage /><Location /></>, { url: '/rca/summary' });
    expect(await screen.findByText(/^Showing every reporting date · /)).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Reporting date' }));
    const choices = (await screen.findAllByRole('option')).map((o) => o.textContent);
    expect(choices).toEqual(['All reporting dates', '22 Oct 2026', '21 Oct 2026', 'Oct 2026 — month (2 reporting dates with records)']);
    await user.click(screen.getByRole('option', { name: '22 Oct 2026' }));
    expect(screen.getByTestId('location')).toHaveTextContent('date_from=2026-10-22&date_to=2026-10-22');
    expect(await screen.findByText(/^Showing 22 Oct 2026 · /)).toBeInTheDocument();
    expect(m.fetchRcaSummary).toHaveBeenLastCalledWith(new URLSearchParams({ date_from: '2026-10-22', date_to: '2026-10-22' }), 'on_air', expect.anything());
    await user.click(screen.getByRole('combobox', { name: 'Reporting date' }));
    await user.click(await screen.findByRole('option', { name: /Oct 2026 — month/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('date_from=2026-10-01&date_to=2026-10-31');
    expect(await screen.findByText(/^Showing Oct 2026: the sum of 2 reporting dates with records · /)).toBeInTheDocument();
  });

  it('is an Admin page: a CI is refused', () => {
    renderWithWorkbook(<Routes><Route path="/rca/summary" element={<RequireAdmin><RcaSummaryPage /></RequireAdmin>} /></Routes>,
      { url: '/rca/summary', auth: authValue({ user: CI_USER }) });
    expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
    expect(m.fetchRcaSummary).not.toHaveBeenCalled();
  });
});

describe('RCA cause mapping', () => {
  const CAUSES: RcaCauses = {
    categories: [{ id: 3, name: 'Media fluctuation', description: '', descriptions: 0 }],
    queue: [
      { key: 'media fluctuation', text: 'Media Fluctuation', spellings: ['Media Fluctuation', 'Media fluctuation'], records: 183, outage_minutes: 100, category: null, reviewed_by: null, reviewed_at: null },
      { key: 'media flactuation', text: 'Media Flactuation', spellings: ['Media Flactuation'], records: 305, outage_minutes: 200, category: null, reviewed_by: null, reviewed_at: null },
    ],
    mapped: [], stats: { descriptions: 2, mapped_descriptions: 0, records: 488, mapped_records: 0, no_description_records: 0 },
  };

  it('maps only the selected descriptions to the chosen category', async () => {
    const user = userEvent.setup();
    m.fetchRcaCauses.mockResolvedValue(CAUSES);
    m.mapRcaCauses.mockResolvedValue({ ...CAUSES, queue: [CAUSES.queue[1]], mapped: [{ ...CAUSES.queue[0], category: { id: 3, name: 'Media fluctuation' } }] });
    renderWithWorkbook(<RcaMappingPage />, { url: '/rca/mappings' });
    expect(await screen.findByText(/Also written: “Media fluctuation”/)).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Select "Media Fluctuation"' }));
    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    await user.click(await screen.findByRole('option', { name: 'Media fluctuation (0)' }));
    await user.click(screen.getByRole('button', { name: 'Approve mapping' }));
    expect(m.mapRcaCauses).toHaveBeenCalledWith(['media fluctuation'], 3);  // the similar "Media Flactuation" is not included
    expect(await screen.findByText('Mapped 1 description (183 records).')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review queue (1)' })).toBeInTheDocument();
  });
});

describe('RCA in the sidebar', () => {
  it('lists RCA as its own section; a CI sees the RCA Register (and circle upload when granted), a NOC Lead the circle upload, an Admin every RCA page but Cause Mapping', async () => {
    const view = renderWithWorkbook(<Sidebar />, { url: '/rca', auth: authValue({ user: { ...CI_USER, permissions: { ...CI_PERMISSIONS, rca_upload: [] }, rca_upload: { circle: false, consolidated: false } } }) });
    const nav = () => screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav()).getByText('RCA')).toHaveClass('uppercase');  // a section heading, like Data
    expect(within(nav()).queryByRole('button', { name: 'RCA' })).not.toBeInTheDocument();
    expect(within(nav()).getByRole('link', { name: 'RCA Register' })).toHaveAttribute('aria-current', 'page');
    for (const name of ['RCA Summary', 'RCA Submissions', 'Cause Mapping', 'Upload Circle RCA', 'Upload Consolidated RCA']) {
      expect(within(nav()).queryByRole('link', { name, hidden: true })).not.toBeInTheDocument();
    }
    view.unmount();
    const granted = renderWithWorkbook(<Sidebar />, { url: '/rca', auth: authValue({ user: { ...CI_USER, rca_upload: { circle: true, consolidated: false } } }) });
    expect(within(nav()).getByRole('link', { name: 'Upload Circle RCA' })).toHaveAttribute('href', '/rca/import');
    expect(within(nav()).queryByRole('link', { name: 'Upload Consolidated RCA', hidden: true })).not.toBeInTheDocument();
    granted.unmount();
    const noc = renderWithWorkbook(<Sidebar />, { url: '/rca', auth: authValue({ user: { ...NOC_LEAD, rca_upload: { circle: true, consolidated: false } } }) });
    expect(within(nav()).getByRole('link', { name: 'Upload Circle RCA' })).toHaveAttribute('href', '/rca/import');
    expect(within(nav()).queryByRole('link', { name: 'Upload Consolidated RCA', hidden: true })).not.toBeInTheDocument();  // not in the group
    for (const name of ['RCA Summary', 'RCA Submissions', 'Cause Mapping', 'Team Performance', 'CSV Arrival Tracking', 'Users & Roles']) {
      expect(within(nav()).queryByRole('link', { name, hidden: true })).not.toBeInTheDocument();
    }
    noc.unmount();
    renderWithWorkbook(<Sidebar />, { url: '/portfolio', auth: authValue({ user: { ...authValue().user!, rca_upload: { circle: true, consolidated: true } } }) });
    expect(['RCA Register', 'RCA Summary', 'RCA Submissions', 'Upload Circle RCA', 'Upload Consolidated RCA'].map((n) => within(nav()).getByRole('link', { name: n }).getAttribute('href')))
      .toEqual(['/rca', '/rca/summary', '/rca/submissions', '/rca/import', '/rca/import/consolidated']);
    // Cause Mapping is out of the navigation; its page and data are kept.
    expect(within(nav()).queryByRole('link', { name: 'Cause Mapping', hidden: true })).not.toBeInTheDocument();
  });
});

describe('RCA Site Scope', () => {
  it('is not on the RCA Summary: Population is its one site control, on every tab, and an old site_scope URL never filters', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><RcaSummaryPage /><Location /></>, { url: '/rca/summary?site_scope=om_start&circle=RJ', population: true });
    const population = await screen.findByRole('combobox', { name: 'Population' });
    expect(screen.queryByRole('combobox', { name: 'Site Scope' })).not.toBeInTheDocument();
    expect(population).toHaveTextContent('On-Air');
    await waitFor(() => expect(m.fetchRcaSummary).toHaveBeenCalled());
    const sent = () => m.fetchRcaSummary.mock.calls.at(-1)!;
    expect((sent()[0] as URLSearchParams).get('circle')).toBe('RJ');  // the other filters are kept
    expect(Object.fromEntries(sent()[0] as URLSearchParams)).not.toHaveProperty('site_scope');
    expect(sent()[1]).toBe('on_air');
    await waitFor(() => expect(m.fetchRcaOverview.mock.calls.at(-1)?.[1]).toBe('on_air'));
    expect(Object.fromEntries(m.fetchRcaOverview.mock.calls.at(-1)![0] as URLSearchParams)).not.toHaveProperty('site_scope');
    // Changing the Population refetches the summary (every analysis tab) and the Overview table with it.
    await user.click(population);
    await user.click(await screen.findByRole('option', { name: 'O&M Start' }));
    await waitFor(() => expect(sent()[1]).toBe('om_start'));
    await waitFor(() => expect(m.fetchRcaOverview.mock.calls.at(-1)?.[1]).toBe('om_start'));
    for (const tab of ['Circle-wise RCA Breakdown', 'Root Cause Analysis', 'Project & Circle Analysis', 'Daily & Monthly Trends']) {
      await user.click(screen.getByRole('link', { name: tab }));
      expect(screen.getByRole('combobox', { name: 'Population' })).toHaveTextContent('O&M Start');
      expect(screen.queryByRole('combobox', { name: 'Site Scope' })).not.toBeInTheDocument();
      expect(sent()[1]).toBe('om_start');
      expect(Object.fromEntries(sent()[0] as URLSearchParams)).not.toHaveProperty('site_scope');
    }
    expect(screen.queryByText(/^Site Scope:/)).not.toBeInTheDocument();
  });

  it('is on the RCA Register too and narrows its records on the server', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<RcaRegisterPage />, { url: '/rca' });
    await user.click(await screen.findByRole('combobox', { name: 'Site Scope' }));
    await user.click(await screen.findByRole('option', { name: 'O&M Not Started Sites' }));
    await waitFor(() => expect((m.fetchRcaRecords.mock.calls.at(-1)![0] as URLSearchParams).get('site_scope')).toBe('om_not_started'));
  });
});
