import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAdmin } from '../components/auth/Guards';
import { Sidebar } from '../components/Sidebar';
import * as api from '../services/api';
import { authValue, CI_USER, renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import type { LweMappingBatch, MatrixImportBatch, NewLayerUpload, UnmatchedReport, UptimeImportBatch } from '../types/matrixImport';
import type { CoverageThresholdResponse, MonthFinalization, ReportingUnit } from '../types/reporting';
import { DatabaseImportPage } from './DatabaseImportPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchNewLayerUploads: vi.fn(), fetchMonthlyResults: vi.fn(), finalizeMonth: vi.fn(), reopenMonth: vi.fn(),
  fetchReportingUnits: vi.fn(), createReportingUnit: vi.fn(), updateReportingUnit: vi.fn(), fetchCoverageThreshold: vi.fn(), changeCoverageThreshold: vi.fn(),
  previewLweMapping: vi.fn(), commitLweMapping: vi.fn(), discardLweMapping: vi.fn(),
  fetchUnmatchedSites: vi.fn(), refreshUnmatchedDetails: vi.fn(), mapAlternateIdentifier: vi.fn(), processPendingRecords: vi.fn(),
  previewMatrixImport: vi.fn(), commitMatrixImport: vi.fn(), discardMatrixImport: vi.fn(),
  previewSitedataUptime: vi.fn(), commitSitedataUptime: vi.fn(), discardSitedataUptime: vi.fn(),
}));
const m = vi.mocked(api);
const UPTIME_PREVIEW: UptimeImportBatch = {
  id: 8, kind: 'uptime_master', technology: '4G Saturation', file: 'RJ, MP & OD - Uptime Report- Nov-26.xlsx', status: 'previewed',
  validation_status: 'passed_with_warnings', uploaded_at: '2026-11-07T09:00:00Z', committed_at: null, uploaded_by: 'admin', error: null, can_commit: true,
  counts: { received: 12174, accepted: 12170, rejected: 0, duplicate: 0, unmatched: 4, conflict: 0, superseded: 0 },
  report: { format: 'up_time_report', months_in_scope: ['2026-09', '2026-10', '2026-11'], months_in_file: ['2026-11'], not_reported_site_days: 124146,
    sites_not_in_site_master: ['UVRJJPR00057', 'UVRJUPR00612'], sites_not_in_site_master_count: 2,
    warnings: ['2 site(s) of the workbook are not in the site master and were not imported.'],
    already_imported: null },
};
const MATRIX_PREVIEW: MatrixImportBatch = {
  id: 5, kind: 'consolidation_matrix', file: 'matrix.xlsx', status: 'previewed', validation_status: 'passed_with_warnings', uploaded_at: '2026-11-05T10:00:00Z',
  committed_at: null, uploaded_by: 'admin', error: null, can_commit: true,
  report: {
    sheet: 'Raw Data', columns_not_in_file: ['bts_id_b1', 'bts_id_b28', 'master_bts_id', 'smps_make'],
    preview: { total_rows: 6764, new_sites: 1, updated_sites: 6762, unchanged_sites: 0, rejected_rows: 1, duplicate_site_ids: 0, conflicting_mappings: 0,
      missing_mandatory: 0, invalid_circle_or_technology: 1, effective_date_issues: 3, effective_date_changes: 2, blank_values_kept: 4, sites_not_in_file: 0 },
    rejected_by_reason: { unknown_circle: { rows: 1, reason: 'Circle Name is not a known circle (Organization > Code Mapping)' } },
    rejected: [{ row: 9, site_id: 'LWEXX01', entity: 'LWE', circle: 'Atlantis', code: 'unknown_circle', reason: 'Circle Name is not a known circle (Organization > Code Mapping): "Atlantis"' }],
    effective_date_review: { om_start_date_missing: 3 }, effective_date_review_rows: [], effective_date_changes: [], warnings: ['1 row(s) are rejected and not imported (see the rejected rows).'],
  },
};

const LWE_PREVIEW: LweMappingBatch = {
  id: 12, kind: 'lwe_band_mapping', technology: 'LWE', file: 'LWE Band ID mapping.xlsx', status: 'previewed', validation_status: 'passed_with_warnings',
  uploaded_at: '2026-11-08T09:00:00Z', committed_at: null, uploaded_by: 'admin', error: null, can_commit: true,
  counts: { received: 2410, accepted: 2400, rejected: 10, duplicate: 0, unmatched: 4, conflict: 0, superseded: 0 },
  report: { sheet: 'Sheet1', rows: 2410, rejected_by_reason: { unknown_master_id: 4, circle_mismatch: 6 },
    changes: { added: 2400, changed: 0, unchanged: 0, kept_new_row_rejected: 0, not_in_this_workbook_kept: 0 },
    lwe_sites_mapped_after_import: 2400, lwe_sites_without_mapping: 15, warnings: ['10 row(s) rejected.'] },
};
const HISTORY: NewLayerUpload[] = [
  { id: 41, kind: 'uptime_master', technology: '4G Saturation', file: 'RJ, MP & OD - Uptime Report- Nov-26.xlsx', status: 'committed',
    uploaded_at: '2026-11-07T09:00:00Z', committed_at: '2026-11-07T09:02:00Z', uploaded_by: 'pratap.admin',
    counts: { received: 12174, accepted: 12170, rejected: 0, duplicate: 0, unmatched: 4, conflict: 0, superseded: 0 } },
  { id: 22, kind: 'consolidation_matrix', technology: null, file: "Consolidated Escalation Matrix - Nov'26.xlsx", status: 'committed',
    uploaded_at: '2026-11-05T07:22:28Z', committed_at: '2026-11-05T07:23:31Z', uploaded_by: 'pratap.admin',
    counts: { received: 6764, accepted: 6764, rejected: 0, duplicate: 0, unmatched: 0, conflict: 0, superseded: 0 } },
  { id: 12, kind: 'lwe_band_mapping', technology: 'LWE', file: 'LWE Band ID mapping.xlsx', status: 'committed',
    uploaded_at: '2026-11-04T07:22:28Z', committed_at: '2026-11-04T07:23:31Z', uploaded_by: 'pratap.admin',
    counts: { received: 2410, accepted: 2400, rejected: 10, duplicate: 0, unmatched: 4, conflict: 0, superseded: 0 } },
];
// Every request the page makes outside the mocked calls: the removed legacy APIs (/imports/, /data-source/, workbook upload) must never be one of them.
const fetchSpy = vi.spyOn(globalThis, 'fetch');
const legacyImportCalls = () => fetchSpy.mock.calls.filter(([u, init]) => /\/api\/(imports|data-source)\//.test(String(u))
  || (/\/dashboard\/workbook\//.test(String(u)) && init?.method === 'POST'));

const RJ_PENDING: UnmatchedReport = {
  uploads_without_detail: [], pending_sites: 2, ready_sites: 0,
  sites: ['UVRJJPR00057', 'UVRJUPR00612'].map((id) => ({
    site_id: id, project: '4G Saturation', circle: 'RJ', uploads: [5, 41], first_date: '2026-10-01', last_date: '2026-11-03', pending_site_days: 33,
    processed_site_days: 0, reason: 'Not in the Consolidation Matrix site master', status: 'pending' as const, resolved_to: null, resolved_by: null })),
};
const NO_UNMATCHED: UnmatchedReport = { sites: [], uploads_without_detail: [], pending_sites: 0, ready_sites: 0 };

const LWE_OD: ReportingUnit = {
  id: 3, technology: 'LWE', circle: 'OD', active_from: '2026-09-01', active_until: null, notes: '',
  changes: [{ action: 'created', before: {}, after: { technology: 'LWE', circle: 'OD', active_from: '2026-09-01', active_until: null, notes: '' },
    reason: 'Programme start', user: 'pratap.admin', at: '2026-09-01T09:00:00Z' }],
};
const THRESHOLD: CoverageThresholdResponse = {
  current_pct: 90, availability_threshold_pct: 98.5,
  history: [{ value_pct: 90, previous_value_pct: 95, effective_from: '2026-10-01', reason: 'Approved rule B-6', changed_by: 'pratap.admin', changed_at: '2026-09-30T10:00:00Z' }],
};
const INCOMPLETE: MonthFinalization = {
  revision: 1, status: 'incomplete_missing_data', status_label: 'Incomplete — Missing Data',
  missing: [{ technology: 'LWE', circle: 'OD', dates: ['2026-10-03', '2026-10-04'] }],
  finalized_at: '2026-11-02T10:00:00Z', finalized_by: 'pratap.admin', reopened_at: null, reopened_by: null, reopen_reason: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchUnmatchedSites.mockResolvedValue(NO_UNMATCHED);
  fetchSpy.mockResolvedValue(new Response('{}', { status: 404 }));
  m.fetchNewLayerUploads.mockResolvedValue(HISTORY);
  m.fetchReportingUnits.mockResolvedValue({ units: [LWE_OD] });
  m.fetchCoverageThreshold.mockResolvedValue(THRESHOLD);
  m.fetchMonthlyResults.mockResolvedValue({ months: [
    { month: '2026-11-01', records: 6700, finalized: false, calculated_at: '2026-11-08T10:00:00Z' },
    { month: '2026-10-01', records: 6690, finalized: true, calculated_at: '2026-11-01T10:00:00Z' },
  ] });
});
afterEach(() => expect(legacyImportCalls()).toEqual([]));

describe('Data Source: data layer imports', () => {
  it('offers no data source switch and no Master workbook upload: only the data layer status and its imports', async () => {
    renderWithWorkbook(<DatabaseImportPage />);
    expect(await screen.findByRole('region', { name: 'Reporting data' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Import a workbook' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Dashboard data source' })).not.toBeInTheDocument();
    expect(screen.queryByRole('radiogroup', { name: 'Data source' })).not.toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /PostgreSQL database|Excel workbook/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Upload consolidated workbook')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Choose Master workbook')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Switch source/ })).not.toBeInTheDocument();
  });

  it('requires the workbook type before a file can be chosen, and each type uses its own importer', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    expect(screen.getByRole('note')).toHaveTextContent('Select the workbook type before choosing a file.');
    expect(screen.queryByLabelText(/Up-Time Report workbook \(\.xlsx\)/)).toBeNull();
    expect(screen.queryByLabelText(/Consolidated Escalation Matrix \(\.xlsx\)/)).toBeNull();
    await user.click(screen.getByRole('radio', { name: /^Up-Time Report/ }));
    expect(screen.getByLabelText(/Up-Time Report workbook \(\.xlsx\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /^Consolidation Matrix/ }));
    expect(screen.queryByLabelText(/Up-Time Report workbook \(\.xlsx\)/)).toBeNull();
    fireEvent.change(screen.getByLabelText(/Consolidated Escalation Matrix \(\.xlsx\)/), { target: { files: [new File(['m'], 'matrix.xlsx')] } });
    await user.click(screen.getByRole('button', { name: /Preview matrix import/ }));
    expect(m.previewMatrixImport).toHaveBeenCalledTimes(1);
    expect(m.previewSitedataUptime).not.toHaveBeenCalled();  // routed to the Consolidation Matrix importer only
  });

  it('shows the matrix preview, needs confirmation, then commits and summarises the import', async () => {
    const user = userEvent.setup();
    m.previewMatrixImport.mockResolvedValue(MATRIX_PREVIEW);
    m.commitMatrixImport.mockResolvedValue({ ...MATRIX_PREVIEW, status: 'committed', can_commit: false,
      report: { ...MATRIX_PREVIEW.report, committed: { inserted: 1, updated: 6762, unchanged: 0, no_longer_in_matrix: 0 } } });
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    await user.click(screen.getByRole('radio', { name: /^Consolidation Matrix/ }));
    const file = new File(['m'], 'matrix.xlsx');
    fireEvent.change(screen.getByLabelText(/Consolidated Escalation Matrix \(\.xlsx\)/), { target: { files: [file] } });
    await user.click(screen.getByRole('button', { name: /Preview matrix import/ }));
    expect(m.previewMatrixImport).toHaveBeenCalledWith(file);
    const preview = await screen.findByRole('region', { name: 'Matrix import preview' });
    const counts = within(preview).getByLabelText('Preview counts');
    expect(counts).toHaveTextContent('Rows detected6,764');
    expect(counts).toHaveTextContent('New sites1');
    expect(counts).toHaveTextContent('Rejected rows1');
    expect(within(preview).getByLabelText('Rejected rows')).toHaveTextContent('Circle Name is not a known circle (Organization > Code Mapping): "Atlantis"');
    expect(preview).toHaveTextContent('Columns not in this file, stored values kept: bts id b1, bts id b28, master bts id, smps make.');
    const confirm = screen.getByRole('button', { name: /Confirm matrix import/ });
    expect(confirm).toBeDisabled();  // explicit confirmation first
    await user.click(screen.getByRole('checkbox', { name: /I have reviewed the preview/ }));
    await user.click(confirm);
    expect(m.commitMatrixImport).toHaveBeenCalledWith(5);
    expect(await screen.findByText('Consolidation Matrix #5 imported')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1 new sites, 6,762 updated, 0 unchanged. 1 rejected rows were not imported.');
  });

  it('imports an Up-Time Report only into the new data layer: no destination choice, no legacy importer', async () => {
    const user = userEvent.setup();
    m.previewSitedataUptime.mockResolvedValue(UPTIME_PREVIEW);
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    await user.click(screen.getByRole('radio', { name: /^Up-Time Report/ }));
    expect(screen.queryByRole('group', { name: 'Destination' })).toBeNull();
    expect(screen.queryByRole('radio', { name: /Legacy tables|New data layer/ })).toBeNull();
    expect(document.body).not.toHaveTextContent(/Legacy tables|uptimedb/);
    const file = new File(['x'], 'RJ, MP & OD - Uptime Report- Nov-26.xlsx');
    fireEvent.change(screen.getByLabelText(/Up-Time Report workbook \(\.xlsx\)/), { target: { files: [file] } });
    await user.selectOptions(screen.getByLabelText(/Project, if the sheet has no Project column/), '4G Saturation');
    await user.click(screen.getByRole('button', { name: /Preview import into the new data layer/ }));
    expect(m.previewSitedataUptime).toHaveBeenCalledWith(file, '4G Saturation');  // the sitedata API, always
    const preview = await screen.findByRole('region', { name: 'New data layer import preview' });
    expect(preview).not.toHaveTextContent(/legacy/i);
    expect(preview).not.toHaveTextContent('already imported into the new data layer');
    expect(within(preview).getByLabelText('Preview counts')).toHaveTextContent('New records12,170');
    expect(preview).toHaveTextContent('Months in the file: 2026-11 · imported months: 2026-09, 2026-10, 2026-11');
  });

  it('confirms before committing into the new data layer and reports a repeat as already imported there', async () => {
    const user = userEvent.setup();
    m.previewSitedataUptime.mockResolvedValueOnce(UPTIME_PREVIEW)
      .mockResolvedValueOnce({ ...UPTIME_PREVIEW, id: 9, counts: { ...UPTIME_PREVIEW.counts, accepted: 0, duplicate: 12170 },
        report: { ...UPTIME_PREVIEW.report, already_imported: { batch: 8, committed_at: '2026-11-07T10:00:00Z' } } });
    m.commitSitedataUptime.mockResolvedValue({ ...UPTIME_PREVIEW, status: 'committed', can_commit: false });
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    await user.click(screen.getByRole('radio', { name: /^Up-Time Report/ }));
    const input = screen.getByLabelText(/Up-Time Report workbook \(\.xlsx\)/);
    fireEvent.change(input, { target: { files: [new File(['x'], 'nov.xlsx')] } });
    await user.click(screen.getByRole('button', { name: /Preview import into the new data layer/ }));
    const confirm = await screen.findByRole('button', { name: /Confirm import/ });
    expect(confirm).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /I have reviewed the preview/ }));
    await user.click(confirm);
    expect(m.commitSitedataUptime).toHaveBeenCalledWith(8);
    expect(await screen.findByText('Up-Time Report #8 imported into the new data layer')).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [new File(['x'], 'nov.xlsx')] } });
    await user.click(screen.getByRole('button', { name: /Preview import into the new data layer/ }));
    expect(await screen.findByText('This exact file was already imported into the new data layer')).toBeInTheDocument();
  });

  it('lists the data layer uploads of every workbook type with their error reports', async () => {
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    const history = await screen.findByRole('region', { name: 'Import history' });
    const rows = within(history).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('41Up-Time Report · 4G SaturationRJ, MP & OD - Uptime Report- Nov-26.xlsxcommittedpratap.admin');
    expect(rows[1]).toHaveTextContent("22Consolidation MatrixConsolidated Escalation Matrix - Nov'26.xlsx");
    expect(within(history).getByRole('link', { name: 'Error report of upload 41' })).toHaveAttribute('href', expect.stringContaining('/sitedata/uptime/41/issues.csv'));
    expect(within(history).getByRole('link', { name: 'Error report of upload 22' })).toHaveAttribute('href', expect.stringContaining('/sitedata/matrix/22/issues.csv'));
    expect(rows[2]).toHaveTextContent('12LWE Band ID mapping · LWE');
    expect(within(history).getByRole('link', { name: 'Error report of upload 12' })).toHaveAttribute('href', expect.stringContaining('/sitedata/lwe-mapping/12/issues.csv'));
  });

  it('reports sites missing from the site master and resolves them only through explicit Admin actions', async () => {
    const user = userEvent.setup();
    m.fetchUnmatchedSites.mockResolvedValueOnce(RJ_PENDING).mockResolvedValue({
      ...RJ_PENDING, pending_sites: 1, ready_sites: 1,
      sites: [{ ...RJ_PENDING.sites[0], status: 'ready', resolved_to: 'UVRJJPR00056', resolved_by: 'alternate_identifier' }, RJ_PENDING.sites[1]] });
    m.mapAlternateIdentifier.mockResolvedValue(RJ_PENDING);
    m.processPendingRecords.mockResolvedValue({ ...NO_UNMATCHED, counts: { accepted: 33 } });
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    const card = await screen.findByRole('region', { name: 'Sites not in the site master' });
    const rows = within(card).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('UVRJJPR00057');
    expect(rows[0]).toHaveTextContent('4G SaturationRJ');
    expect(rows[0]).toHaveTextContent('33Not in the Consolidation Matrix site masterPending: not in the site master');
    expect(within(card).queryByRole('button', { name: /Process pending records/ })).toBeNull();  // nothing is resolved yet
    const form = within(card).getByRole('form', { name: 'Map an approved alternate identifier' });
    const submit = within(form).getByRole('button', { name: /Map identifier/ });
    await user.selectOptions(within(form).getByLabelText('Unmatched site ID'), 'UVRJJPR00057');
    await user.type(within(form).getByLabelText('Existing master BSNL Site ID'), 'UVRJJPR00056');
    expect(submit).toBeDisabled();  // evidence is required
    await user.type(within(form).getByLabelText('Evidence / reason'), 'Circle letter 7 Nov');
    await user.click(submit);
    expect(m.mapAlternateIdentifier).toHaveBeenCalledWith('UVRJJPR00057', 'UVRJJPR00056', 'Circle letter 7 Nov');
    const process = await within(card).findByRole('button', { name: /Process pending records/ });
    expect(process).toBeDisabled();  // explicit confirmation first
    await user.click(within(card).getByRole('checkbox', { name: /Process the pending records of the 1 resolved site/ }));
    await user.click(process);
    expect(m.processPendingRecords).toHaveBeenCalledTimes(1);
    expect(await within(card).findByText('33 daily records added.')).toBeInTheDocument();
  });

  it('previews the LWE Band ID mapping, needs confirmation, then commits it', async () => {
    const user = userEvent.setup();
    const workbook = workbookValue();
    m.previewLweMapping.mockResolvedValue(LWE_PREVIEW);
    m.commitLweMapping.mockResolvedValue({ ...LWE_PREVIEW, status: 'committed', can_commit: false, committed_at: '2026-11-08T09:05:00Z',
      report: { ...LWE_PREVIEW.report, identifiers_created: 4800 } });
    renderWithWorkbook(<DatabaseImportPage />, { workbook });
    await screen.findByRole('region', { name: 'Import a workbook' });
    await user.click(screen.getByRole('radio', { name: /^LWE Band ID mapping/ }));
    const file = new File(['l'], 'LWE Band ID mapping.xlsx');
    fireEvent.change(screen.getByLabelText(/LWE Band ID mapping \(\.xlsx\)/), { target: { files: [file] } });
    await user.click(screen.getByRole('button', { name: /Preview mapping import/ }));
    expect(m.previewLweMapping).toHaveBeenCalledWith(file);
    expect(m.previewMatrixImport).not.toHaveBeenCalled();
    const preview = await screen.findByRole('region', { name: 'LWE mapping preview' });
    const counts = within(preview).getByLabelText('Preview counts');
    expect(counts).toHaveTextContent('Rows detected2,410');
    expect(counts).toHaveTextContent('Rejected rows10');
    expect(counts).toHaveTextContent('LWE sites without mapping15');
    expect(within(preview).getByLabelText('Rejected rows')).toHaveTextContent('unknown master id: 4');
    expect(within(preview).getByRole('link', { name: /Rejected rows and review items/ })).toHaveAttribute('href', expect.stringContaining('/sitedata/lwe-mapping/12/issues.csv'));
    const confirm = screen.getByRole('button', { name: /Confirm mapping import/ });
    expect(confirm).toBeDisabled();
    await user.click(within(preview).getByRole('checkbox', { name: /I have reviewed the preview/ }));
    await user.click(confirm);
    expect(m.commitLweMapping).toHaveBeenCalledWith(12);
    expect(await screen.findByText('LWE Band ID mapping #12 imported')).toBeInTheDocument();
    expect(screen.getByText(/2,400 rows applied, 4,800 identifiers added, 10 rejected rows not imported/)).toBeInTheDocument();
    expect(workbook.refresh).toHaveBeenCalled();
  });

  it('discards an LWE mapping preview without committing', async () => {
    const user = userEvent.setup();
    m.previewLweMapping.mockResolvedValue(LWE_PREVIEW);
    m.discardLweMapping.mockResolvedValue({ ...LWE_PREVIEW, status: 'discarded', can_commit: false });
    renderWithWorkbook(<DatabaseImportPage />);
    await screen.findByRole('region', { name: 'Import a workbook' });
    await user.click(screen.getByRole('radio', { name: /^LWE Band ID mapping/ }));
    fireEvent.change(screen.getByLabelText(/LWE Band ID mapping \(\.xlsx\)/), { target: { files: [new File(['l'], 'map.xlsx')] } });
    await user.click(screen.getByRole('button', { name: /Preview mapping import/ }));
    await user.click(await screen.findByRole('button', { name: 'Discard preview' }));
    expect(m.discardLweMapping).toHaveBeenCalledWith(12);
    expect(m.commitLweMapping).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'LWE mapping preview' })).not.toBeInTheDocument();
  });

  it('lists the monthly results and finalizes a month only after confirming', async () => {
    const user = userEvent.setup();
    m.finalizeMonth.mockResolvedValue({ month: '2026-11-01', finalized_records: 6700 });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Monthly results' });
    const rows = await within(card).findAllByRole('row');
    expect(rows[1]).toHaveTextContent('6,700');
    expect(rows[1]).toHaveTextContent('Open');
    expect(rows[2]).toHaveTextContent('Finalized');
    expect(within(rows[2]).queryByRole('button')).toBeNull();  // a finalized month cannot be finalized again
    await user.click(within(rows[1]).getByRole('button', { name: /^Finalize/ }));
    expect(m.finalizeMonth).not.toHaveBeenCalled();  // the confirmation comes first
    const dialog = within(card).getByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Yes, finalize' }));
    expect(m.finalizeMonth).toHaveBeenCalledWith('2026-11-01', '');
    expect(await within(card).findByText(/6,700 monthly site results are final/)).toBeInTheDocument();
  });

  it('is an Admin page: a CI sees no menu entry and is refused on the URL', () => {
    const auth = authValue({ user: CI_USER });
    renderWithWorkbook(<><Sidebar /><Routes><Route path="/workbook" element={<RequireAdmin><DatabaseImportPage /></RequireAdmin>} /></Routes></>, { url: '/workbook', auth });
    expect(screen.queryByRole('link', { name: 'Data Source', hidden: true })).not.toBeInTheDocument();
    expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
    expect(m.fetchNewLayerUploads).not.toHaveBeenCalled();
  });
});

describe('Data Source: reporting configuration', () => {
  it('adds a reporting unit with a reason', async () => {
    const user = userEvent.setup();
    m.createReportingUnit.mockResolvedValue({ unit: { ...LWE_OD, id: 4, technology: '4G Saturation', circle: 'MP', active_from: '2026-11-01' } });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Reporting units' });
    const row = await within(card).findByRole('row', { name: 'LWE OD' });
    expect(row).toHaveTextContent(/LWEOD01 Sept? 2026Active/);
    expect(row).toHaveTextContent('Created · pratap.admin');
    await user.click(within(card).getByRole('button', { name: 'Add reporting unit' }));
    const form = within(card).getByRole('form', { name: 'Add reporting unit' });
    const submit = within(form).getByRole('button', { name: /Add unit/ });
    await user.selectOptions(within(form).getByLabelText('Technology'), '4G Saturation');
    await user.type(within(form).getByLabelText('Circle'), 'mp');
    fireEvent.change(within(form).getByLabelText('Active from'), { target: { value: '2026-11-01' } });
    expect(submit).toBeDisabled();  // the reason is required
    await user.type(within(form).getByLabelText('Reason (required)'), 'New circle in the programme');
    await user.click(submit);
    expect(m.createReportingUnit).toHaveBeenCalledWith({ technology: '4G Saturation', circle: 'MP', active_from: '2026-11-01', reason: 'New circle in the programme' });
    expect(await within(card).findByText('4G Saturation MP added, active from 01 Nov 2026')).toBeInTheDocument();
    expect(m.fetchReportingUnits).toHaveBeenCalledTimes(2);  // reloaded
  });

  it('shows the field message of a refused unit', async () => {
    const user = userEvent.setup();
    m.createReportingUnit.mockRejectedValue(new api.ApiError('Invalid request parameters.', 400, { circle: 'XX is not set up in the Organization.' }));
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Reporting units' });
    await user.click(await within(card).findByRole('button', { name: 'Add reporting unit' }));
    const form = within(card).getByRole('form', { name: 'Add reporting unit' });
    await user.selectOptions(within(form).getByLabelText('Technology'), 'LWE');
    await user.type(within(form).getByLabelText('Circle'), 'XX');
    fireEvent.change(within(form).getByLabelText('Active from'), { target: { value: '2026-11-01' } });
    await user.type(within(form).getByLabelText('Reason (required)'), 'Test');
    await user.click(within(form).getByRole('button', { name: /Add unit/ }));
    expect(await within(form).findByText('XX is not set up in the Organization.')).toBeInTheDocument();
  });

  it('deactivates a unit only with a reason and shows its change history', async () => {
    const user = userEvent.setup();
    const deactivated: ReportingUnit = { ...LWE_OD, active_until: '2026-11-30', changes: [
      { action: 'deactivated', before: { active_until: null }, after: { active_until: '2026-11-30' }, reason: 'Circle handed over', user: 'pratap.admin', at: '2026-11-10T09:00:00Z' },
      ...LWE_OD.changes] };
    m.updateReportingUnit.mockResolvedValue({ unit: deactivated });
    m.fetchReportingUnits.mockResolvedValueOnce({ units: [LWE_OD] }).mockResolvedValue({ units: [deactivated] });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Reporting units' });
    await user.click(await within(card).findByRole('button', { name: 'Deactivate LWE OD' }));
    const form = within(card).getByRole('form', { name: 'Deactivate LWE OD' });
    fireEvent.change(within(form).getByLabelText('Active until (deactivation date)'), { target: { value: '2026-11-30' } });
    const submit = within(form).getByRole('button', { name: /Deactivate unit/ });
    expect(submit).toBeDisabled();
    await user.type(within(form).getByLabelText('Reason (required)'), 'Circle handed over');
    await user.click(submit);
    expect(m.updateReportingUnit).toHaveBeenCalledWith(3, { active_until: '2026-11-30', reason: 'Circle handed over' });
    expect(await within(card).findByText('LWE OD deactivated from 30 Nov 2026')).toBeInTheDocument();
    const row = await within(card).findByRole('row', { name: 'LWE OD' });
    expect(row).toHaveTextContent('Inactive from 30 Nov 2026');
    expect(within(row).getByRole('button', { name: 'Reactivate LWE OD' })).toBeInTheDocument();
    await user.click(within(row).getByRole('button', { name: 'Change history of LWE OD' }));
    const history = within(card).getByRole('list', { name: 'Changes of LWE OD' });
    expect(history).toHaveTextContent('Deactivated · pratap.admin');
    expect(history).toHaveTextContent('Active until: — → 30 Nov 2026');
    expect(history).toHaveTextContent('Reason: Circle handed over');
  });

  it('reactivates a unit with a reason (active_until cleared)', async () => {
    const user = userEvent.setup();
    m.fetchReportingUnits.mockResolvedValue({ units: [{ ...LWE_OD, active_until: '2026-10-31' }] });
    m.updateReportingUnit.mockResolvedValue({ unit: LWE_OD });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Reporting units' });
    await user.click(await within(card).findByRole('button', { name: 'Reactivate LWE OD' }));
    const form = within(card).getByRole('form', { name: 'Reactivate LWE OD' });
    await user.type(within(form).getByLabelText('Reason (required)'), 'Back in scope');
    await user.click(within(form).getByRole('button', { name: /Reactivate unit/ }));
    expect(m.updateReportingUnit).toHaveBeenCalledWith(3, { active_until: null, reason: 'Back in scope' });
  });

  it('shows the coverage threshold apart from the availability threshold and asks to confirm a retroactive change', async () => {
    const user = userEvent.setup();
    m.changeCoverageThreshold
      .mockRejectedValueOnce(new api.ApiError('Invalid request parameters.', 400,
        { confirm_retroactive: '02 Oct 2026 is in the past: the statuses of earlier non-finalized dates will change. Confirm with confirm_retroactive: true.' }))
      .mockResolvedValueOnce({ value_pct: 85, previous_value_pct: 90, effective_from: '2026-10-02' });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Coverage threshold' });
    expect(await within(card).findByLabelText('Current coverage threshold')).toHaveTextContent('90 %');
    expect(card).toHaveTextContent('Availability threshold (separate rule)98.5 %');
    const history = within(card).getByRole('table', { name: 'Coverage threshold history' });
    expect(within(history).getAllByRole('row')[1]).toHaveTextContent('01 Oct 202690 %95 %pratap.admin');
    const form = within(card).getByRole('form', { name: 'Change coverage threshold' });
    await user.type(within(form).getByLabelText('New value (%)'), '85');
    fireEvent.change(within(form).getByLabelText('Effective from'), { target: { value: '2026-10-02' } });
    const save = within(form).getByRole('button', { name: /Save threshold/ });
    expect(save).toBeDisabled();  // reason required
    await user.type(within(form).getByLabelText('Reason (required)'), 'Approved by the programme office');
    await user.click(save);
    expect(m.changeCoverageThreshold).toHaveBeenLastCalledWith({ value_pct: 85, effective_from: '2026-10-02', reason: 'Approved by the programme office' });
    const dialog = await within(form).findByRole('alertdialog', { name: 'Confirm retroactive change' });
    expect(dialog).toHaveTextContent('02 Oct 2026 is in the past');
    await user.click(within(dialog).getByRole('button', { name: /Yes, apply retroactively/ }));
    expect(m.changeCoverageThreshold).toHaveBeenLastCalledWith({ value_pct: 85, effective_from: '2026-10-02', reason: 'Approved by the programme office', confirm_retroactive: true });
    expect(await within(card).findByText('Coverage threshold set to 85 % from 02 Oct 2026 (was 90 %).')).toBeInTheDocument();
    expect(m.fetchCoverageThreshold).toHaveBeenCalledTimes(2);
  });

  it('refuses a threshold date inside a finalized month with the field message', async () => {
    const user = userEvent.setup();
    m.changeCoverageThreshold.mockRejectedValue(new api.ApiError('Invalid request parameters.', 400,
      { effective_from: ['Finalized months cannot be re-evaluated: choose a date after Sep 2026 (or reopen those months first).'] }));
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Coverage threshold' });
    const form = within(card).getByRole('form', { name: 'Change coverage threshold' });
    await user.type(within(form).getByLabelText('New value (%)'), '85');
    fireEvent.change(within(form).getByLabelText('Effective from'), { target: { value: '2026-09-15' } });
    await user.type(within(form).getByLabelText('Reason (required)'), 'x');
    await user.click(within(form).getByRole('button', { name: /Save threshold/ }));
    expect(await within(form).findByText(/Finalized months cannot be re-evaluated/)).toBeInTheDocument();
    expect(within(form).queryByRole('alertdialog')).toBeNull();
  });

  it("finalizes a month with missing data and marks it 'Incomplete — Missing Data'", async () => {
    const user = userEvent.setup();
    m.fetchMonthlyResults.mockResolvedValueOnce({ months: [
      { month: '2026-10-01', records: 6690, finalized: false, calculated_at: '2026-11-01T10:00:00Z', finalization_status: 'open', finalization_label: 'Not finalized', finalization: null },
    ] }).mockResolvedValue({ months: [
      { month: '2026-10-01', records: 6690, finalized: true, calculated_at: '2026-11-01T10:00:00Z', finalization_status: 'incomplete_missing_data',
        finalization_label: 'Incomplete — Missing Data', finalization: INCOMPLETE },
    ] });
    m.finalizeMonth.mockResolvedValue({ month: '2026-10-01', finalized_records: 6690, finalization: INCOMPLETE });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Monthly results' });
    const rows = await within(card).findAllByRole('row');
    expect(rows[1]).toHaveTextContent('Open');
    await user.click(within(rows[1]).getByRole('button', { name: /^Finalize/ }));
    const dialog = within(card).getByRole('alertdialog');
    expect(dialog).toHaveTextContent("marked ‘Incomplete — Missing Data’");
    await user.click(within(dialog).getByRole('button', { name: 'Yes, finalize' }));
    expect(m.finalizeMonth).toHaveBeenCalledWith('2026-10-01', '');
    const done = await within(card).findByRole('status');
    expect(done).toHaveTextContent('finalized: Incomplete — Missing Data');
    expect(done).toHaveTextContent('Missing: LWE OD (2 days)');
    const row = (await within(card).findAllByRole('row'))[1];
    await waitFor(() => expect(within(row).getByText('Incomplete — Missing Data')).toBeInTheDocument());
    expect(within(row).getByText('Finalized')).toBeInTheDocument();
    expect(within(row).getByLabelText('Missing data of Oct 2026')).toHaveTextContent('LWE OD: 2 days (03 Oct, 04 Oct)');
    expect(within(row).queryByRole('button', { name: /^Finalize/ })).toBeNull();
    expect(within(row).getByRole('button', { name: /^Reopen/ })).toBeInTheDocument();
  });

  it('reopens a finalized month only with a reason', async () => {
    const user = userEvent.setup();
    m.fetchMonthlyResults.mockResolvedValueOnce({ months: [
      { month: '2026-10-01', records: 6690, finalized: true, calculated_at: '2026-11-01T10:00:00Z', finalization_status: 'incomplete_missing_data',
        finalization_label: 'Incomplete — Missing Data', finalization: INCOMPLETE },
    ] }).mockResolvedValue({ months: [
      { month: '2026-10-01', records: 6690, finalized: false, calculated_at: '2026-11-01T10:00:00Z', finalization_status: 'reopened', finalization_label: 'Reopened',
        finalization: { ...INCOMPLETE, reopened_at: '2026-11-12T08:00:00Z', reopened_by: 'pratap.admin', reopen_reason: 'LWE OD data received late' } },
    ] });
    m.reopenMonth.mockResolvedValue({ month: '2026-10-01', finalization: { ...INCOMPLETE, reopened_at: '2026-11-12T08:00:00Z', reopened_by: 'pratap.admin', reopen_reason: 'LWE OD data received late' } });
    renderWithWorkbook(<DatabaseImportPage />);
    const card = await screen.findByRole('region', { name: 'Monthly results' });
    const row = (await within(card).findAllByRole('row'))[1];
    await user.click(within(row).getByRole('button', { name: 'Reopen Oct 2026' }));
    const form = within(card).getByRole('form', { name: 'Reopen Oct 2026' });
    const submit = within(form).getByRole('button', { name: /Reopen month/ });
    expect(submit).toBeDisabled();
    await user.type(within(form).getByLabelText('Reason for reopening'), 'LWE OD data received late');
    await user.click(submit);
    expect(m.reopenMonth).toHaveBeenCalledWith('2026-10-01', 'LWE OD data received late');
    expect(await within(card).findByText('Oct 2026 reopened')).toBeInTheDocument();
    const after = (await within(card).findAllByRole('row'))[1];
    await waitFor(() => expect(after).toHaveTextContent('Reopened by pratap.admin'));
    expect(after).toHaveTextContent('LWE OD data received late');
    expect(within(after).getByRole('button', { name: /^Finalize/ })).toBeInTheDocument();  // finalize again afterwards
  });
});
