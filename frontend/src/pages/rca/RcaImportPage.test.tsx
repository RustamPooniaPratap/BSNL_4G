import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequirePage, RequireRcaConsolidated } from '../../components/auth/Guards';
import * as api from '../../services/api';
import { CI_PERMISSIONS, CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { AuthUser } from '../../types';
import type { RcaImportBatch, RcaImportReport } from '../../types/rca';
import { RcaImportPage } from './RcaImportPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRcaImports: vi.fn(), fetchRcaImport: vi.fn(), previewRcaImport: vi.fn(), commitRcaImport: vi.fn(), discardRcaImport: vi.fn(),
  fetchOrganizationCatalog: vi.fn(),
}));
const m = vi.mocked(api);
/** Each workflow step as "label: state" (from the indicator's data-state). */
const steps = () => within(screen.getByRole('list', { name: 'Upload progress' })).getAllByRole('listitem')
  .map((li) => `${li.textContent!.replace(/\s*\(.*\)$/, '').replace(/^\d/, '')}: ${li.getAttribute('data-state')}`);
const NOC: AuthUser = { username: 'noc.lead', name: 'NOC Lead', role: 'noc_lead', role_label: 'NOC Lead', must_change_password: false, permissions: CI_PERMISSIONS };

const REPORT: RcaImportReport = {
  filename: 'Oct_RCA.xlsx', sheet: 'Sheet1', rows_read: 6, valid_rows: 5, rejected_rows: 1, blank_rows: 0, unknown_columns: [], dates: { '2026-10-21': 5 },
  projects: { '4G Saturation': 3, LWE: 2 }, projects_raw: { '4G Satu': 3, LWE: 2 }, circles: { '4G Saturation|OD': 3, 'LWE|BH': 2 },
  circle_names: { 'Odisha -> OD': 3, 'Bihar -> BH': 2 }, distinct_sites: 5, outage_minutes: 1234.5, final_buckets: {}, bucket_2: {}, distinct_rca: 3,
  label_variants: {}, severity_counts: { error: 1, warning: 0, info: 0 }, issue_counts: { unknown_site: 1 },
  issues: [{ severity: 'error', code: 'unknown_site', row: 7, site_id: 'OD9999', message: 'Site ID is not in the Up-Time Report for 4G Saturation.' }],
  new_rows: 4, unchanged_rows: 0, conflict_rows: 1, already_imported: null, restored_rows: 0, missing_rows: 0, is_correction: true, earlier_uploads_for_period: 1,
  rca_not_applicable_rows: 2, missing_rca_rows: 1, earlier_date_rows: 4,
  by_date: [
    { date: '2026-10-21', rows: 4, new: 0, unchanged: 3, changed: 1, missing: 0, earlier_date: true, kind: 'earlier date: corrected' },
    { date: '2026-10-22', rows: 1, new: 1, unchanged: 0, changed: 0, missing: 0, earlier_date: false, kind: 'reporting date: new' },
  ],
  coverage: { source: 'previous period', expected: [['4G Saturation', 'OD'], ['LWE', 'BH'], ['LWE', 'OD']], present: [['4G Saturation', 'OD']],
    missing: [['LWE', 'BH'], ['LWE', 'OD']] },
  conflicts: [{ row: 3, site_id: 'OD0001', record_id: 1, differences: { outage_minutes: { database: 90, file: 95 } } }],
};
const PREVIEW: RcaImportBatch = {
  id: 20, status: 'previewed', status_label: 'Validated — awaiting confirmation', file: 'Oct_RCA.xlsx', checksum: 'abc', sheet: 'Sheet1',
  uploaded_at: '2026-10-28T10:00:00Z', committed_at: null, imported_by: 'noc.lead', report_name: 'October 2026 RCA Report', project_scope: 'both',
  remarks: 'Corrected OD outage', period_start: '2026-10-21', period_end: '2026-10-21', cycle: 4, units: [['4G Saturation', 'OD'], ['LWE', 'BH']],
  counts: { total: 6, valid: 5, rejected: 1 }, correction: true, conflict_action: null, missing_action: null, error: null, file_kept: true, report: REPORT,
};
const DONE: RcaImportBatch & { records: number; final_report: null } = {
  ...PREVIEW, status: 'committed', status_label: 'Imported with rejected rows', committed_at: '2026-10-28T10:01:00Z', records: 1823, final_report: null,
  counts: { total: 6, valid: 5, rejected: 1, inserted: 4, updated: 1, skipped: 0, withdrawn: 0, correction: true },
};

const CATALOG = {
  projects: [{ key: '4G Saturation', code: '4G', name: '4G Saturation', is_active: true }, { key: 'LWE', code: 'LWE', name: 'LWE', is_active: true }],
  circles: ['OD', 'RJ'].map((code) => ({ code, name: code, is_active: true })),
  associations: [{ project: '4G Saturation', circle: 'OD', is_active: true }, { project: '4G Saturation', circle: 'RJ', is_active: true },
    { project: 'LWE', circle: 'OD', is_active: true }],
};
const CI_OD: AuthUser = { ...CI_USER, username: 'ci.od', rca_upload: { circle: true, consolidated: false } };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRcaImports.mockResolvedValue({ imports: [], records: 1819, all: false });
  m.fetchOrganizationCatalog.mockResolvedValue(CATALOG);
});

describe('Upload RCA Data', () => {
  it('takes the report details and the workbook, shows the validation and imports only after explicit confirmation', async () => {
    const user = userEvent.setup();
    m.previewRcaImport.mockResolvedValue(PREVIEW);
    m.commitRcaImport.mockResolvedValue(DONE);
    renderWithWorkbook(<RcaImportPage mode="consolidated" />, { url: '/rca/import', auth: authValue({ user: NOC }) });
    expect(await screen.findByText(/uploaded as noc\.lead/)).toBeInTheDocument();  // the uploader is the signed-in account
    const validate = screen.getByRole('button', { name: 'Validate workbook' });
    expect(validate).toBeDisabled();
    await user.type(screen.getByLabelText(/Report name/), 'October 2026 RCA Report');
    await user.type(screen.getByLabelText(/Reporting date/), '2026-10-21');
    await user.type(screen.getByLabelText(/Remarks/), 'Corrected OD outage');
    await user.upload(screen.getByLabelText('RCA workbook'), new File(['x'], 'Oct_RCA.xlsx'));
    await user.click(validate);
    expect(m.previewRcaImport).toHaveBeenCalledWith(expect.any(File), {
      upload_type: 'consolidated', report_name: 'October 2026 RCA Report', period_start: '2026-10-21', project_scope: 'both', project: '', circle: '',
      remarks: 'Corrected OD outage' });
    const preview = await screen.findByLabelText('Import preview');
    expect(within(preview).getByText(/Correction: this period already has 1 imported upload/)).toBeInTheDocument();
    expect(within(preview).getByText('Row 7 (OD9999): Site ID is not in the Up-Time Report for 4G Saturation.')).toBeInTheDocument();
    expect(within(preview).getByText(/Other Media \(RCA not applicable\): 2 · RCA required but information missing: 1/)).toBeInTheDocument();
    expect(within(preview).getByText(/outage_minutes “90” → “95”/)).toBeInTheDocument();
    // Each date of the cumulative workbook: the earlier date is history (never withdrawn), the reporting date is new.
    const dates = within(within(preview).getByRole('table', { name: 'Rows by reporting date' })).getAllByRole('row');
    expect(dates[1]).toHaveTextContent('21 Oct 20264031— (never withdrawn)earlier date: corrected');
    expect(dates[2]).toHaveTextContent('22 Oct 202611000reporting date: new');
    expect(within(preview).getByText(/No rows for the reporting date from BH LWE, OD LWE/)).toBeInTheDocument();
    const confirm = within(preview).getByRole('button', { name: 'Confirm import of 5 valid rows' });
    expect(confirm).toBeDisabled();  // the rejected row must be acknowledged first
    await user.click(within(preview).getByRole('checkbox', { name: /Import the 5 valid rows without the 1 rejected rows/ }));
    await user.click(within(preview).getByRole('button', { name: 'Update with this workbook' }));
    await user.click(confirm);
    expect(m.commitRcaImport).toHaveBeenCalledWith(20, { conflict_action: 'overwrite', missing_action: '', accept_rejected: true });
    const summary = await screen.findByLabelText('Upload summary');
    expect(within(summary).getByText('Status: Imported with rejected rows (correction)')).toBeInTheDocument();
    const tiles = within(summary).getAllByRole('definition').map((d) => d.textContent);
    expect(tiles).toEqual(['6', '4', '1', '0', '1', '0']);
    expect(within(summary).getByText('LWE / BH')).toBeInTheDocument();
    expect(within(summary).getByRole('link', { name: /Consolidated RCA report/ })).toHaveAttribute('href', expect.stringContaining('/rca/imports/20/report.xlsx'));
  });

  it('lists the user\'s own uploads and opens the summary of one', async () => {
    const user = userEvent.setup();
    m.fetchRcaImports.mockResolvedValue({ imports: [DONE], records: 1823, all: false });
    m.fetchRcaImport.mockResolvedValue(DONE);
    renderWithWorkbook(<RcaImportPage mode="consolidated" />, { url: '/rca/import', auth: authValue({ user: NOC }) });
    const mine = await screen.findByLabelText('My uploads');
    expect(within(mine).getByText('My consolidated uploads')).toBeInTheDocument();
    const row = (await within(mine).findAllByRole('row'))[1];
    expect(row).toHaveTextContent('October 2026 RCA Report21 Oct 2026Oct_RCA.xlsx');
    expect(row).toHaveTextContent('4 · 1 · 0 · 1');
    await user.click(within(row).getByRole('button', { name: 'View' }));
    expect(m.fetchRcaImport).toHaveBeenCalledWith(20);
    expect(await screen.findByLabelText('Upload summary')).toBeInTheDocument();
    expect(m.fetchRcaImports).toHaveBeenCalledWith(expect.anything(), false, 'consolidated');  // own consolidated uploads only, never ?all
  });

  it('matches the Upload CSV layout: steps, details, drop zone, file checks, Replace / Remove and stale previews', async () => {
    const user = userEvent.setup();
    m.fetchRcaImports.mockResolvedValue({ imports: [], records: 1819, all: false, max_bytes: 50 * 1024 * 1024 });
    m.previewRcaImport.mockResolvedValue(PREVIEW);
    renderWithWorkbook(<RcaImportPage mode="consolidated" />, { url: '/rca/import', auth: authValue({ user: NOC }) });
    expect(await screen.findByText(/as \.xlsx or \.xlsm, up to 50\.0 MB/)).toBeInTheDocument();  // the server's configured limit
    expect(steps()).toEqual(['Upload: current', 'Validate & Preview: todo', 'Confirm Import: todo', 'Results: todo']);
    expect(screen.getByText('Still needed: report name, RCA workbook.')).toBeInTheDocument();  // the date is optional (latest in the workbook)
    expect(screen.getByRole('button', { name: 'Validate workbook' })).toBeDisabled();
    const zone = screen.getByText('Upload your RCA workbook').closest('div')!;
    fireEvent.drop(zone, { dataTransfer: { files: [new File(['x'], 'rca.csv')] } });  // wrong type: refused, never selected
    expect(screen.getByText('rca.csv: choose the RCA workbook (.xlsx or .xlsm).')).toBeInTheDocument();
    expect(screen.queryByLabelText('Selected file')).not.toBeInTheDocument();
    const workbook = new File(['x'], 'Oct_RCA.xlsx');
    fireEvent.dragOver(zone, { dataTransfer: { files: [workbook] } });
    expect(screen.getByText('Drop the workbook to select it')).toBeInTheDocument();
    fireEvent.drop(zone, { dataTransfer: { files: [workbook] } });
    expect(screen.getByLabelText('Selected file')).toHaveTextContent('Oct_RCA.xlsxExcel workbook');
    expect(screen.getByLabelText('Selected file')).toHaveTextContent('Ready to validate');
    await user.type(screen.getByLabelText(/Report name/), 'October 2026 RCA Report');
    await user.type(screen.getByLabelText(/Reporting date/), '2026-10-21');
    await user.click(screen.getByRole('button', { name: 'Validate workbook' }));
    expect(await screen.findByLabelText('Import preview')).toBeInTheDocument();
    expect(steps()).toEqual(['Upload: done', 'Validate & Preview: done', 'Confirm Import: current', 'Results: todo']);
    expect(screen.getByLabelText('Selected file')).toHaveTextContent('Validation passed');
    await user.type(screen.getByLabelText(/Remarks/), ' x');  // a changed detail makes the validation stale
    expect(screen.queryByLabelText('Import preview')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove file' }));
    expect(screen.queryByLabelText('Selected file')).not.toBeInTheDocument();
    expect(screen.getByText('Still needed: RCA workbook.')).toBeInTheDocument();
  });

  it('shows a rejected workbook and a failed import as failures, and success only after the server commits', async () => {
    const user = userEvent.setup();
    m.previewRcaImport.mockRejectedValueOnce(new api.ApiError('Oct_RCA.xlsx: no sheet has the RCA columns.', 400));
    renderWithWorkbook(<RcaImportPage mode="consolidated" />, { url: '/rca/import', auth: authValue({ user: NOC }) });
    await user.type(await screen.findByLabelText(/Report name/), 'October 2026 RCA Report');
    await user.type(screen.getByLabelText(/Reporting date/), '2026-10-21');
    await user.upload(screen.getByLabelText('RCA workbook'), new File(['x'], 'Oct_RCA.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Validate workbook' }));
    expect(await screen.findByText('The workbook could not be validated')).toBeInTheDocument();
    expect(steps()).toEqual(['Upload: current', 'Validate & Preview: failed', 'Confirm Import: todo', 'Results: todo']);
    m.previewRcaImport.mockResolvedValue(PREVIEW);
    m.commitRcaImport.mockRejectedValueOnce(new api.ApiError('The database is unavailable.', 503));
    await user.click(screen.getByRole('button', { name: 'Validate workbook' }));
    const preview = await screen.findByLabelText('Import preview');
    await user.click(within(preview).getByRole('checkbox', { name: /Import the 5 valid rows/ }));
    await user.click(within(preview).getByRole('button', { name: 'Update with this workbook' }));
    await user.click(within(preview).getByRole('button', { name: 'Confirm import of 5 valid rows' }));
    expect(await screen.findByText('The import did not complete')).toBeInTheDocument();
    expect(screen.queryByText('Import complete')).not.toBeInTheDocument();
    expect(steps()).toEqual(['Upload: done', 'Validate & Preview: done', 'Confirm Import: failed', 'Results: todo']);
    m.commitRcaImport.mockResolvedValue(DONE);
    await user.click(within(screen.getByLabelText('Import preview')).getByRole('button', { name: 'Confirm import of 5 valid rows' }));
    expect(await screen.findByText('Import complete')).toBeInTheDocument();
    expect(steps()).toEqual(['Upload: done', 'Validate & Preview: done', 'Confirm Import: done', 'Results: done']);
  });

  it('opens Upload Consolidated RCA only to Admins and the RCA Consolidated Uploaders group', () => {
    const route = <Routes><Route path="/rca/import/consolidated" element={<RequireRcaConsolidated><RcaImportPage mode="consolidated" /></RequireRcaConsolidated>} /></Routes>;
    const noc = renderWithWorkbook(route, { url: '/rca/import/consolidated', auth: authValue({ user: { ...NOC, rca_upload: { circle: true, consolidated: false } } }) });
    expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
    expect(m.fetchRcaImports).not.toHaveBeenCalled();
    noc.unmount();
    renderWithWorkbook(route, { url: '/rca/import/consolidated', auth: authValue({ user: { ...NOC, rca_upload: { circle: true, consolidated: true } } }) });
    expect(screen.getByRole('heading', { name: 'Upload Consolidated RCA' })).toBeInTheDocument();
  });

  it('offers a CI user only their granted project and circle and sends one circle and date', async () => {
    const user = userEvent.setup();
    m.fetchRcaImports.mockResolvedValue({ imports: [], records: 0, all: false, rights: { circle: true, consolidated: false, access: [{ project: '4G Saturation', circle: 'OD' }] } });
    m.previewRcaImport.mockResolvedValue({ ...PREVIEW, upload_type: 'circle', circle: 'OD', project_scope: '4G Saturation' });
    renderWithWorkbook(<Routes><Route path="/rca/import" element={<RequirePage><RcaImportPage mode="circle" /></RequirePage>} /></Routes>,
      { url: '/rca/import', auth: authValue({ user: CI_OD }) });
    expect(await screen.findByRole('heading', { name: 'Upload Circle RCA' })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Report name/)).not.toBeInTheDocument();
    expect(await screen.findByText('Still needed: reporting date, RCA workbook.')).toBeInTheDocument();  // the only grant is preselected
    expect(screen.getByRole('combobox', { name: /Project/ })).toHaveTextContent('4G Saturation');
    expect(screen.getByRole('combobox', { name: /Circle/ })).toHaveTextContent('OD');
    await user.type(screen.getByLabelText(/Reporting date/), '2026-10-21');
    await user.upload(screen.getByLabelText('RCA workbook'), new File(['x'], 'OD_RCA.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Validate workbook' }));
    expect(m.previewRcaImport).toHaveBeenCalledWith(expect.any(File), {
      upload_type: 'circle', report_name: '', period_start: '2026-10-21', project_scope: 'both', project: '4G Saturation', circle: 'OD', remarks: '' });
    expect(m.fetchRcaImports).toHaveBeenCalledWith(expect.anything(), false, 'circle');
  });

  it('tells a CI user without a granted circle and keeps validation disabled', async () => {
    m.fetchRcaImports.mockResolvedValue({ imports: [], records: 0, all: false, rights: { circle: false, consolidated: false, access: [] } });
    renderWithWorkbook(<RcaImportPage mode="circle" />, { url: '/rca/import', auth: authValue({ user: { ...CI_USER, rca_upload: { circle: false, consolidated: false } } }) });
    expect(await screen.findByText('No circle granted')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Validate workbook' })).toBeDisabled();
  });
});
