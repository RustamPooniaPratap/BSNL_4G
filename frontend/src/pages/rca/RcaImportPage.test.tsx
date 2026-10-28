import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequirePage } from '../../components/auth/Guards';
import * as api from '../../services/api';
import { CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { AuthUser } from '../../types';
import type { RcaImportBatch, RcaImportReport } from '../../types/rca';
import { RcaImportPage } from './RcaImportPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRcaImports: vi.fn(), fetchRcaImport: vi.fn(), previewRcaImport: vi.fn(), commitRcaImport: vi.fn(), discardRcaImport: vi.fn(),
}));
const m = vi.mocked(api);
const NOC: AuthUser = { username: 'noc.lead', name: 'NOC Lead', role: 'noc_lead', role_label: 'NOC Lead', must_change_password: false };

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

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRcaImports.mockResolvedValue({ imports: [], records: 1819, all: false });
});

describe('Upload RCA Data', () => {
  it('takes the report details and the workbook, shows the validation and imports only after explicit confirmation', async () => {
    const user = userEvent.setup();
    m.previewRcaImport.mockResolvedValue(PREVIEW);
    m.commitRcaImport.mockResolvedValue(DONE);
    renderWithWorkbook(<RcaImportPage />, { url: '/rca/import', auth: authValue({ user: NOC }) });
    expect(await screen.findByText(/uploaded as noc\.lead/)).toBeInTheDocument();  // the uploader is the signed-in account
    const validate = screen.getByRole('button', { name: 'Validate workbook' });
    expect(validate).toBeDisabled();
    await user.type(screen.getByLabelText(/Report name/), 'October 2026 RCA Report');
    await user.type(screen.getByLabelText(/Reporting date/), '2026-10-21');
    await user.type(screen.getByLabelText(/Remarks/), 'Corrected OD outage');
    await user.upload(screen.getByLabelText('RCA workbook'), new File(['x'], 'Oct_RCA.xlsx'));
    await user.click(validate);
    expect(m.previewRcaImport).toHaveBeenCalledWith(expect.any(File), {
      report_name: 'October 2026 RCA Report', period_start: '2026-10-21', period_end: '', project_scope: 'both', remarks: 'Corrected OD outage' });
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
    renderWithWorkbook(<RcaImportPage />, { url: '/rca/import', auth: authValue({ user: NOC }) });
    const mine = await screen.findByLabelText('My uploads');
    const row = (await within(mine).findAllByRole('row'))[1];
    expect(row).toHaveTextContent('October 2026 RCA Report21 Oct 2026Oct_RCA.xlsx');
    expect(row).toHaveTextContent('4 · 1 · 0 · 1');
    await user.click(within(row).getByRole('button', { name: 'View' }));
    expect(m.fetchRcaImport).toHaveBeenCalledWith(20);
    expect(await screen.findByLabelText('Upload summary')).toBeInTheDocument();
    expect(m.fetchRcaImports).toHaveBeenCalledWith(expect.anything());  // own uploads only, never ?all
  });

  it('is open to Admins and NOC Leads, not to CI users', () => {
    renderWithWorkbook(<Routes><Route path="/rca/import" element={<RequirePage><RcaImportPage /></RequirePage>} /></Routes>,
      { url: '/rca/import', auth: authValue({ user: CI_USER }) });
    expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
    expect(m.fetchRcaImports).not.toHaveBeenCalled();
  });
});
