import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAdmin } from '../../components/auth/Guards';
import * as api from '../../services/api';
import { CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { AuthUser } from '../../types';
import type { RcaCycleDetail, RcaImportBatch, RcaUnitState } from '../../types/rca';
import { RcaSubmissionsPage } from './RcaSubmissionsPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRcaCycles: vi.fn(), fetchRcaCycle: vi.fn(), fetchRcaImports: vi.fn(), startRcaCycle: vi.fn(),
}));
const m = vi.mocked(api);

const upload = (over: Partial<RcaImportBatch> = {}): RcaImportBatch => ({
  id: 11, status: 'committed', status_label: 'Imported', file: 'Book1_RCA.xlsx', checksum: 'abc', sheet: 'Sheet1', uploaded_at: '2026-10-22T10:00:00Z',
  committed_at: '2026-10-22T10:05:00Z', imported_by: 'noc.lead', report_name: 'October 2026 RCA Report', project_scope: 'both', remarks: null,
  period_start: '2026-10-21', period_end: '2026-10-21', cycle: 4, units: [['4G Saturation', 'OD'], ['LWE', 'BH']],
  counts: { total: 610, valid: 608, rejected: 2, inserted: 600, updated: 0, skipped: 8 }, correction: false, conflict_action: null, missing_action: null,
  error: null, file_kept: true, upload_type: 'consolidated', ...over,
});
const unit = (over: Partial<RcaUnitState>): RcaUnitState => ({
  project: '4G Saturation', circle: 'OD', status: 'received', status_label: 'Data received', data_label: 'Data available', records: 522, outage_minutes: 200973,
  source_files: ['Book1_RCA.xlsx'], submission_status: 'not_received', submission_label: 'Not received', submission: null, submissions: 0, upload_ids: [11], ...over,
});
const UNITS = [
  unit({}),
  unit({ project: 'LWE', circle: 'BH', records: 86, outage_minutes: 17530 }),
  unit({ project: 'LWE', circle: 'OD', status: 'pending', status_label: 'Pending — no accepted records', data_label: 'No data', records: 0, outage_minutes: null,
    source_files: [], upload_ids: [] }),
];
const CYCLE: RcaCycleDetail = {
  id: 4, name: 'October 2026 RCA Report', period_start: '2026-10-21', period_end: '2026-10-21', period_label: '21 Oct 2026', notes: null,
  created_by: 'noc.lead', created_at: '2026-10-22T10:05:00Z', records: 608,
  uploads_summary: { total: 2, imported: 1, with_rejected_rows: 1, awaiting_confirmation: 0, validation_failed: 1, corrections: 1, last_upload_at: '2026-10-22T10:00:00Z' },
  status: { code: 'partial', label: 'Partially received', required: 3, received: 2, complete: false, final_version: null, can_finalize: false,
    upload_awaiting_confirmation: false, records_checksum: 'x', outstanding: [{ project: 'LWE', circle: 'OD', status: 'pending', status_label: 'Pending — no accepted records' }] },
  units: UNITS, unexpected: [{ project: 'LWE', circle: 'JH', records: 293 }], uploads: [upload()], reports: [], locked: false,
};
const dataRows = (card: HTMLElement) => within(card).getAllByRole('row').slice(1);
const firstCells = (card: HTMLElement) => dataRows(card).map((r) => within(r).getAllByRole('cell')[0].textContent);

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRcaCycles.mockResolvedValue({ cycles: [CYCLE], total: 1 });
  m.fetchRcaCycle.mockResolvedValue(CYCLE);
  m.fetchRcaImports.mockResolvedValue({ imports: [upload(), upload({ id: 12, status: 'failed', status_label: 'Failed', counts: {}, cycle: null, units: [],
    error: 'The "Sheet1" sheet is missing required columns: RCA.', imported_by: 'other.lead' })], records: 608, all: true });
});

describe('RCA Submissions', () => {
  it('tracks every expected unit from the API in one table, pending first, with its latest upload', async () => {
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const coverage = await screen.findByLabelText('Expected coverage');
    const rows = dataRows(coverage);
    expect(rows).toHaveLength(3);  // every unit the API generated, none configured here
    expect(rows[0]).toHaveTextContent('ODLWENo dataNot receivedNo upload recorded0—');  // pending, no upload: still listed
    expect(rows[1]).toHaveTextContent('OD4GData availableNot receivedImportedBook1_RCA.xlsx');
    expect(rows[1]).toHaveTextContent('5222,00,973 min');
    expect(within(coverage).getByText(/outside the expected scope: JH LWE \(293\)/)).toBeInTheDocument();
  });

  it('has no manual scope selection and no separate filename sections', async () => {
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    await screen.findByLabelText('Expected coverage');
    // No reporting-period summary card (title, status, counts, download and generate buttons).
    expect(screen.queryByLabelText('Period status')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Download (draft|partial|final) report/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Generate .*final report/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Configure expected scope')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Period uploads')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('All uploads')).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'From uploaded files' })).not.toBeInTheDocument();
    expect(screen.getAllByText('Book1_RCA.xlsx', { exact: false })).toHaveLength(2);  // once per unit row that it covers, nowhere else
    expect(m.fetchRcaImports).not.toHaveBeenCalled();  // the audit history loads only when opened
  });

  it('starts a reporting period without choosing projects or circles', async () => {
    const user = userEvent.setup();
    m.startRcaCycle.mockResolvedValue({ ...CYCLE, id: 5, period_label: '25 Oct 2026' });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    await user.click(await screen.findByRole('button', { name: /Start a reporting period/ }));
    const form = screen.getByLabelText('Start a reporting period');
    await user.type(within(form).getByLabelText('Reporting date (or first day)'), '2026-10-25');
    await user.click(within(form).getByRole('button', { name: 'Start period' }));
    expect(m.startRcaCycle).toHaveBeenCalledWith({ name: '', period_start: '2026-10-25', period_end: '', notes: '' });
    expect(await screen.findByText('Reporting period 25 Oct 2026 started.')).toBeInTheDocument();
  });

  it('lists the daily reporting status: completeness beside received, failed and corrected uploads', async () => {
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const rows = dataRows(await screen.findByLabelText('Daily reporting status'));
    expect(rows[0]).toHaveTextContent('21 Oct 2026October 2026 RCA ReportPartially received2 of 3OD LWE');
    expect(rows[0]).toHaveTextContent('1 (1 with rejected rows)');
    const cells = within(rows[0]).getAllByRole('cell').map((c) => c.textContent);
    expect(cells.slice(6, 9)).toEqual(['1', '0', '1']);  // validation failed, awaiting confirmation, corrections
  });

  it('filters, searches, sorts and opens a unit with its uploads, circle file and records', async () => {
    const user = userEvent.setup();
    const circleFile = upload({ id: 21, upload_type: 'circle', circle: 'BH', project_scope: 'LWE', file: 'BH_LWE_RCA.xlsx', imported_by: 'bh.ci', uploaded_at: '2026-10-22T09:00:00Z',
      units: [['LWE', 'BH']], counts: { inserted: 86, updated: 0, skipped: 0, rejected: 0 } });
    const bh = unit({ project: 'LWE', circle: 'BH', records: 86, outage_minutes: 17530, submission_status: 'received', submission_label: 'Received', submissions: 2, upload_ids: [11, 21],
      submission: { batch: 21, file: 'BH_LWE_RCA.xlsx', reporting_date: '2026-10-21', uploaded_at: '2026-10-22T09:00:00Z', committed_at: '2026-10-22T09:05:00Z', uploaded_by: 'bh.ci' } });
    m.fetchRcaCycle.mockResolvedValue({ ...CYCLE, units: [UNITS[0], bh, UNITS[2]], uploads: [upload(), circleFile] });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const tiles = await screen.findByLabelText('Submission summary');
    const tile = (name: RegExp) => within(tiles).getByRole('button', { name });
    expect([tile(/^Expected circles/), tile(/^RCA data available/), tile(/^No RCA data/), tile(/^Circle files received/), tile(/^Circle files not received/),
      tile(/^Uploads recorded/), tile(/^Awaiting confirmation/)].map((t) => t.textContent?.match(/\d+/)?.[0])).toEqual(['3', '2', '1', '1', '2', '2', '0']);
    const coverage = screen.getByLabelText('Expected coverage');
    // A summary tile filters the table (its count equals the rows shown); selecting it again clears the filter.
    await user.click(tile(/^Circle files received/));
    expect(dataRows(coverage)).toHaveLength(1);
    expect(dataRows(coverage)[0]).toHaveTextContent('BHLWEData availableReceived');
    expect(dataRows(coverage)[0]).toHaveTextContent('Book1_RCA.xlsx · 22 Oct 2026, 03:30 pm · noc.lead · +1 more');
    await user.click(tile(/^Circle files received/));
    expect(dataRows(coverage)).toHaveLength(3);
    // Search: circle, project, file or uploader.
    await user.type(screen.getByLabelText('Search'), 'bh.ci');
    expect(firstCells(coverage)).toEqual(['BH']);
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(dataRows(coverage)).toHaveLength(3);
    await user.click(within(coverage).getByRole('button', { name: /Circle \/ State/ }));
    expect(firstCells(coverage)).toEqual(['BH', 'OD', 'OD']);
    // The row opens every upload of the unit for the period (with its validation report), its circle file and its records.
    await user.click(dataRows(coverage)[0]);
    const sheet = await screen.findByRole('dialog');
    const uploads = within(within(sheet).getByLabelText('Uploads')).getAllByRole('listitem');
    expect(uploads).toHaveLength(2);
    expect(uploads[1]).toHaveTextContent('BH_LWE_RCA.xlsx');
    expect(uploads[1]).toHaveTextContent('Upload #21 · Circle file · BH LWE');
    expect(within(uploads[1]).getByRole('link', { name: 'Validation report' })).toHaveAttribute('href', expect.stringContaining('/21/'));
    expect(within(sheet).getByText(/2 circle files confirmed for this period; the latest is shown/)).toBeInTheDocument();
    expect(within(sheet).getByRole('link', { name: /View records in the RCA Register/ }))
      .toHaveAttribute('href', '/rca?project=LWE&circle=BH&date_from=2026-10-21&date_to=2026-10-21');
  });

  it('filters the units with an upload awaiting confirmation', async () => {
    const user = userEvent.setup();
    const waiting = upload({ id: 14, status: 'previewed', status_label: 'Validated — awaiting confirmation', units: [['LWE', 'OD']] });
    m.fetchRcaCycle.mockResolvedValue({ ...CYCLE, units: [UNITS[0], UNITS[1], { ...UNITS[2], upload_ids: [14] }], uploads: [waiting, upload()] });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    await user.click(within(await screen.findByLabelText('Submission summary')).getByRole('button', { name: /^Awaiting confirmation/ }));
    const rows = dataRows(screen.getByLabelText('Expected coverage'));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('ODLWENo dataNot receivedValidated — awaiting confirmation');
  });

  it('paginates the units 20 per page', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 25 }, (_, i) => unit({ project: 'LWE', circle: `C${String(i).padStart(2, '0')}`, upload_ids: [] }));
    m.fetchRcaCycle.mockResolvedValue({ ...CYCLE, units: many });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const coverage = await screen.findByLabelText('Expected coverage');
    expect(dataRows(coverage)).toHaveLength(20);
    const pager = within(coverage).getByRole('navigation', { name: 'Table pagination' });
    expect(pager).toHaveTextContent('Page 1 of 2');
    await user.click(within(pager).getByRole('button', { name: 'Next' }));
    expect(firstCells(coverage)).toEqual(['C20', 'C21', 'C22', 'C23', 'C24']);
  });

  it('keeps the audit history of every upload in one collapsed list, loaded when opened', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const history = await screen.findByLabelText('Upload history');
    await user.click(within(history).getByText(/Upload history/));
    expect(await within(history).findByText(/missing required columns/)).toBeInTheDocument();
    expect(within(history).getByText(/other\.lead/)).toBeInTheDocument();
    expect(m.fetchRcaImports).toHaveBeenCalledWith(expect.anything(), true);
  });

  it('shows the fixed scope and the stored final report files of a finalized period', async () => {
    const v1 = { id: 1, version: 1, filename: 'RCA_Master_2026-10-21_FINAL_v1.xlsx', generated_at: '2026-10-23T10:00:00Z', generated_by: null, automatic: true,
      record_count: 608, superseded_at: null, current: true, available: true };
    m.fetchRcaCycle.mockResolvedValue({ ...CYCLE, locked: true, reports: [v1], status: { ...CYCLE.status, code: 'final', label: 'Final report generated', final_version: 1 } });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions?cycle=4' });
    expect(await screen.findByText(/scope fixed by the final report/)).toBeInTheDocument();
    expect(within(screen.getByLabelText('Final reports')).getByRole('link', { name: 'RCA_Master_2026-10-21_FINAL_v1.xlsx' }))
      .toHaveAttribute('href', expect.stringContaining('/rca/cycles/4/reports/1.xlsx'));
  });

  it('shows an error with a retry when the periods cannot be loaded', async () => {
    const user = userEvent.setup();
    m.fetchRcaCycles.mockRejectedValueOnce(new Error('Server unavailable'));
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    expect(await screen.findByText('The reporting periods could not be loaded')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByLabelText('Expected coverage')).toBeInTheDocument();
    expect(m.fetchRcaCycles).toHaveBeenCalledTimes(2);
  });

  it('says when only the latest periods are listed, and when nothing is expected', async () => {
    m.fetchRcaCycles.mockResolvedValue({ cycles: [CYCLE], total: 130 });
    m.fetchRcaCycle.mockResolvedValue({ ...CYCLE, units: [], status: { ...CYCLE.status, code: 'unconfigured', label: 'Expected scope not configured', required: 0, received: 0, outstanding: [] } });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    expect(await screen.findByText(/The latest 1 of 130 reporting periods\./)).toBeInTheDocument();
    expect(screen.getByText('No active project and circle is associated in the Organization.')).toBeInTheDocument();
  });

  it('is an Admin page: a CI or a NOC Lead is refused', () => {
    const noc: AuthUser = { username: 'noc.lead', name: 'NOC', role: 'noc_lead', role_label: 'NOC Lead', must_change_password: false };
    for (const user of [CI_USER, noc]) {
      const view = renderWithWorkbook(<Routes><Route path="/rca/submissions" element={<RequireAdmin><RcaSubmissionsPage /></RequireAdmin>} /></Routes>,
        { url: '/rca/submissions', auth: authValue({ user }) });
      expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
      view.unmount();
    }
    expect(m.fetchRcaCycles).not.toHaveBeenCalled();
  });
});
