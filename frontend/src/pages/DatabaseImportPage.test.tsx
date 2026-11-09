import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAdmin } from '../components/auth/Guards';
import { Sidebar } from '../components/Sidebar';
import * as api from '../services/api';
import { authValue, CI_USER, renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import type { DatabaseCompleteness, DataSourceState } from '../types';
import type { MatrixImportBatch, NewLayerUpload, UnmatchedReport, UptimeImportBatch } from '../types/matrixImport';
import { DatabaseImportPage } from './DatabaseImportPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchDataSource: vi.fn(), setDataSource: vi.fn(), fetchNewLayerUploads: vi.fn(),
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
    already_imported: null, legacy_imports: [{ batch: 36, committed_at: '2026-11-05T07:34:15Z' }] },
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

const DB: DatabaseCompleteness = {
  sites: 6726, monthly_records: 87438, daily_records: 134520, months: ['2026-09', '2026-10'],
  daily_months: { '2026-10': { label: 'Oct-26', first: '2026-10-01', last: '2026-10-20', days: 20, gaps: [] } },
  previous_month_daily: false, last_import: { batch: 1, file: 'master.xlsx', committed_at: '2026-10-24T17:09:26' }, empty: false,
  warnings: ['Sep-26 daily history is missing (only its monthly totals are imported).'],
};
const STATE: DataSourceState = { active: 'excel', label: 'Excel workbook', options: [{ value: 'excel', label: 'Excel workbook' }, { value: 'database', label: 'PostgreSQL database' }], database: DB };
const HISTORY: NewLayerUpload[] = [
  { id: 41, kind: 'uptime_master', technology: '4G Saturation', file: 'RJ, MP & OD - Uptime Report- Nov-26.xlsx', status: 'committed',
    uploaded_at: '2026-11-07T09:00:00Z', committed_at: '2026-11-07T09:02:00Z', uploaded_by: 'pratap.admin',
    counts: { received: 12174, accepted: 12170, rejected: 0, duplicate: 0, unmatched: 4, conflict: 0, superseded: 0 } },
  { id: 22, kind: 'consolidation_matrix', technology: null, file: "Consolidated Escalation Matrix - Nov'26.xlsx", status: 'committed',
    uploaded_at: '2026-11-05T07:22:28Z', committed_at: '2026-11-05T07:23:31Z', uploaded_by: 'pratap.admin',
    counts: { received: 6764, accepted: 6764, rejected: 0, duplicate: 0, unmatched: 0, conflict: 0, superseded: 0 } },
];
// Every request the page makes outside the mocked calls: the legacy import API (/imports/) must never be one of them.
const fetchSpy = vi.spyOn(globalThis, 'fetch');
const legacyImportCalls = () => fetchSpy.mock.calls.filter(([u]) => /\/api\/imports\//.test(String(u)));

const RJ_PENDING: UnmatchedReport = {
  uploads_without_detail: [], pending_sites: 2, ready_sites: 0,
  sites: ['UVRJJPR00057', 'UVRJUPR00612'].map((id) => ({
    site_id: id, project: '4G Saturation', circle: 'RJ', uploads: [5, 41], first_date: '2026-10-01', last_date: '2026-11-03', pending_site_days: 33,
    processed_site_days: 0, reason: 'Not in the Consolidation Matrix site master', status: 'pending' as const, resolved_to: null, resolved_by: null })),
};
const NO_UNMATCHED: UnmatchedReport = { sites: [], uploads_without_detail: [], pending_sites: 0, ready_sites: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchUnmatchedSites.mockResolvedValue(NO_UNMATCHED);
  fetchSpy.mockResolvedValue(new Response('{}', { status: 404 }));
  m.fetchDataSource.mockResolvedValue(STATE);
  m.fetchNewLayerUploads.mockResolvedValue(HISTORY);
  m.setDataSource.mockResolvedValue({ ...STATE, active: 'database' });
});
afterEach(() => expect(legacyImportCalls()).toEqual([]));

describe('Data source & database import', () => {
  it('shows the workbook upload for Excel, the in-use source, and the import tools when PostgreSQL is picked', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<DatabaseImportPage />);
    const selector = await screen.findByRole('region', { name: 'Dashboard data source' });
    expect(within(selector).getByRole('radio', { name: /Excel workbook/ })).toHaveTextContent('In use by the dashboard');
    expect(screen.getByText('Upload consolidated workbook')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Import into PostgreSQL' })).not.toBeInTheDocument();
    await user.click(within(selector).getByRole('radio', { name: /PostgreSQL database/ }));
    expect(screen.getByRole('region', { name: 'Import into PostgreSQL' })).toBeInTheDocument();
    expect(screen.queryByText('Upload consolidated workbook')).not.toBeInTheDocument();
    expect(m.setDataSource).not.toHaveBeenCalled();  // picking a tile only asks; it does not switch
    await user.click(screen.getByRole('button', { name: 'Keep Excel workbook' }));
    expect(screen.getByText('Upload consolidated workbook')).toBeInTheDocument();
  });

  it('lets an empty database be filled before it can be used', async () => {
    const user = userEvent.setup();
    m.fetchDataSource.mockResolvedValue({ ...STATE, database: { ...DB, empty: true, sites: 0, warnings: ['The database has no imported sites yet.'] } });
    renderWithWorkbook(<DatabaseImportPage />);
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
    expect(screen.getByText(/The database is empty. Import the Master workbook below/)).toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Import into PostgreSQL' })).toBeInTheDocument();
  });

  it('requires the workbook type before a file can be chosen, and each type uses its own importer', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<DatabaseImportPage />);
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
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
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
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
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
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
    // The legacy import of the same file is information only: it does not count as imported here.
    expect(preview).toHaveTextContent('Imported before into the legacy tables only');
    expect(preview).toHaveTextContent('Legacy import #36 stored this file in the old tables');
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
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
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

  it('lists the new data layer uploads of both workbook types with their error reports', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<DatabaseImportPage />);
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
    const history = await screen.findByRole('region', { name: 'Import history' });
    const rows = within(history).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('41Up-Time Report · 4G SaturationRJ, MP & OD - Uptime Report- Nov-26.xlsxcommittedpratap.admin');
    expect(rows[1]).toHaveTextContent("22Consolidation MatrixConsolidated Escalation Matrix - Nov'26.xlsx");
    expect(within(history).getByRole('link', { name: 'Error report of upload 41' })).toHaveAttribute('href', expect.stringContaining('/sitedata/uptime/41/issues.csv'));
    expect(within(history).getByRole('link', { name: 'Error report of upload 22' })).toHaveAttribute('href', expect.stringContaining('/sitedata/matrix/22/issues.csv'));
  });

  it('reports sites missing from the site master and resolves them only through explicit Admin actions', async () => {
    const user = userEvent.setup();
    m.fetchUnmatchedSites.mockResolvedValueOnce(RJ_PENDING).mockResolvedValue({
      ...RJ_PENDING, pending_sites: 1, ready_sites: 1,
      sites: [{ ...RJ_PENDING.sites[0], status: 'ready', resolved_to: 'UVRJJPR00056', resolved_by: 'alternate_identifier' }, RJ_PENDING.sites[1]] });
    m.mapAlternateIdentifier.mockResolvedValue(RJ_PENDING);
    m.processPendingRecords.mockResolvedValue({ ...NO_UNMATCHED, counts: { accepted: 33 } });
    renderWithWorkbook(<DatabaseImportPage />);
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
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

  it('switches the dashboard source only after confirming, acknowledging missing data', async () => {
    const user = userEvent.setup();
    const workbook = workbookValue();
    renderWithWorkbook(<DatabaseImportPage />, { workbook });
    const selector = await screen.findByRole('region', { name: 'Dashboard data source' });
    expect(within(selector).getByRole('radio', { name: /Excel workbook/ })).toHaveAttribute('aria-checked', 'true');
    await user.click(within(selector).getByRole('radio', { name: /PostgreSQL database/ }));
    const confirm = screen.getByRole('alertdialog', { name: 'Confirm data source change' });
    expect(confirm).toHaveTextContent('Sep-26 daily history is missing');
    expect(within(confirm).getByRole('button', { name: /Switch source/ })).toBeDisabled();
    await user.click(within(confirm).getByRole('checkbox'));
    await user.click(within(confirm).getByRole('button', { name: /Switch source/ }));
    expect(m.setDataSource).toHaveBeenCalledWith('database', true);
    expect(workbook.refresh).toHaveBeenCalled();  // every page reloads from the new source
  });

  it('is an Admin page: a CI sees no menu entry and is refused on the URL', () => {
    const auth = authValue({ user: CI_USER });
    renderWithWorkbook(<><Sidebar /><Routes><Route path="/workbook" element={<RequireAdmin><DatabaseImportPage /></RequireAdmin>} /></Routes></>, { url: '/workbook', auth });
    expect(screen.queryByRole('link', { name: 'Data Source', hidden: true })).not.toBeInTheDocument();
    expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
    expect(m.fetchDataSource).not.toHaveBeenCalled();
  });
});
