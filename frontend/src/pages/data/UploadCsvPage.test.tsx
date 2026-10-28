import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { CI_USER, authValue, renderWithWorkbook, workbookValue } from '../../test/renderWithWorkbook';
import type { RawRowsPage, RawUpload, RawUploadOptions } from '../../types/rawUpload';
import { UploadCsvPage } from './UploadCsvPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRawUploadOptions: vi.fn(), fetchRawUploads: vi.fn(), fetchRawUpload: vi.fn(), fetchRawUploadRows: vi.fn(),
  previewRawUpload: vi.fn(), commitRawUpload: vi.fn(), discardRawUpload: vi.fn(), uploadDataFile: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });

const OPTIONS: RawUploadOptions = {
  projects: [
    { value: '4G Saturation', configured: true, availability_column: 'Nw Avail (4G TCS)', circles: ['OD'] },
    { value: 'LWE', configured: false, availability_column: 'Nw Avail (4G TCS)', circles: ['OD'] },
  ],
  assigned_circles: ['OD'], max_bytes: 25 * 1024 * 1024, formula: 'outage minutes = 1440 × (1 − availability / 100)',
};
const ROWS: RawRowsPage = {
  count: 3, page: 1, pages: 1, rows: [
    { line: 2, raw_id: 'UVOR001', site_id: 'UVOR001', site_name: 'Karla', circle: 'OR', report_date: '13-10-2026', raw_availability: '95.5',
      availability: 95.5, outage_minutes: 64.8, status: 'ready', code: 'ready', label: 'Ready to import', message: '', note: '' },
    { line: 3, raw_id: 'ZZOR999', site_id: null, site_name: '', circle: 'OR', report_date: '13-10-2026', raw_availability: '99',
      availability: null, outage_minutes: null, status: 'out_of_scope', code: 'unknown_site', label: 'Not in the approved site master (outside the project scope)',
      message: 'ZZOR999 is not in the approved 4G Saturation site master (outside the project scope).', note: '' },
    { line: 4, raw_id: 'UVOR003', site_id: 'UVOR003', site_name: 'Pardi', circle: 'OR', report_date: '13-10-2026', raw_availability: '',
      availability: null, outage_minutes: null, status: 'availability', code: 'missing_availability', label: 'Availability missing',
      message: 'Nw Avail (4G TCS) is blank: not read as 0% or as 0 outage minutes.', note: '' },
  ],
};
const PREVIEW: RawUpload = {
  id: 7, status: 'previewed', status_label: 'Previewed', file: 'nw_aval_day.csv', checksum: 'abc', project: '4G Saturation', circle: 'OD',
  reporting_date: '2026-10-13', remarks: null, uploaded_by: 'ravi.ci', uploaded_at: '2026-10-29T10:00:00Z', committed_at: null, error: null,
  summary: { total_rows: 3, valid_in_scope: 1, ready_to_import: 1, identical_skipped: 0, out_of_scope: 1, unresolved_or_ambiguous: 0,
    availability_problems: 1, duplicates_or_conflicts: 0, date_mismatches: 0, project_or_circle_mismatches: 0, other_invalid: 0,
    by_code: { ready: 1, unknown_site: 1, missing_availability: 1 } },
  daily: null, rejected_count: 2, skipped_count: 0, file_issues: [], blocked: false,
  file_info: { encoding: 'utf-8-sig', header_line: 2, preamble: ['Network availability report'], blank_lines: 0, columns: {}, unused_columns: 50,
    report_dates: ['2026-10-13'], circles_in_file: { OD: 3 } },
  availability_rule: { column: 'Nw Avail (4G TCS)', confirmed: true, formula: 'outage minutes = 1440 × (1 − availability / 100)' },
  resolver: { project: '4G Saturation', configured: true },
  master_scope: { sites: 4, sites_in_file: 2, missing_from_file: 2, missing_examples: ['UVOR002', 'UVOR004'] },
  already_imported: null, rows: ROWS,
};
const CI_OD = { ...CI_USER, circles: ['OD'] };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRawUploadOptions.mockResolvedValue(OPTIONS);
  m.fetchRawUploads.mockResolvedValue({ uploads: [] });
  m.fetchRawUploadRows.mockResolvedValue(ROWS);
});

describe('Upload CSV', () => {
  it('validates on the server, shows the preview and imports only after explicit confirmation', async () => {
    const user = userEvent.setup();
    const refresh = vi.fn();
    m.previewRawUpload.mockResolvedValue(PREVIEW);
    m.commitRawUpload.mockResolvedValue({ ...PREVIEW, status: 'committed', status_label: 'Committed', committed_at: '2026-10-29T10:01:00Z',
      daily: { inserted: 1, filled: 0, skipped_identical: 0, skipped_repeats: 0, rejected: 2 } });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }), workbook: workbookValue({ refresh }) });
    const circle = await screen.findByLabelText('Circle (assigned)');
    expect(circle).toHaveValue('OD');
    expect(circle).toHaveAttribute('readonly');
    const validate = screen.getByRole('button', { name: 'Validate on server' });
    expect(validate).toBeDisabled();
    await user.type(screen.getByLabelText('Reporting date'), '2026-10-13');
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['BTS IP ID,Circle,Report Date\n'], 'nw_aval_day.csv', { type: 'text/csv' }));
    expect(screen.getByText('nw_aval_day.csv')).toBeInTheDocument();
    await user.click(validate);
    expect(m.previewRawUpload).toHaveBeenCalledWith(expect.any(File), { project: '4G Saturation', circle: 'OD', reporting_date: '2026-10-13', remarks: '' });

    const preview = await screen.findByLabelText('Validation preview');
    expect(within(preview).getByText(/nothing saved yet/)).toBeInTheDocument();
    expect(within(preview).getByText(/header on line 2 \(above it: “Network availability report”\)/)).toBeInTheDocument();
    const tile = (label: string) => within(preview).getByText(label, { selector: 'dt' }).nextSibling?.textContent;
    expect([tile('Rows in file'), tile('Ready to import'), tile('Out of scope'), tile('Missing / invalid availability')]).toEqual(['3', '1', '1', '1']);
    expect(within(preview).getByText(/2 approved 4G Saturation sites of OD have no row in this file/)).toBeInTheDocument();
    const rows = within(within(preview).getByRole('table', { name: 'Rows' })).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('UVOR001');
    expect(rows[1]).toHaveTextContent('64.8');
    expect(rows[2]).toHaveTextContent('not in the approved 4G Saturation site master');
    expect(rows[3]).toHaveTextContent('blank');
    expect(within(preview).getByRole('link', { name: /Validation report/ })).toHaveAttribute('href', expect.stringContaining('/raw-uploads/7/issues.csv'));

    await user.click(within(preview).getByRole('button', { name: 'Import 1 records…' }));
    expect(m.commitRawUpload).not.toHaveBeenCalled();  // a second, explicit confirmation
    await user.click(within(preview).getByRole('button', { name: 'Yes, import' }));
    expect(m.commitRawUpload).toHaveBeenCalledWith(7);
    const result = await screen.findByLabelText('Import result');
    expect(within(result).getByText(/1 daily records inserted/)).toBeInTheDocument();
    expect(within(result).getByText(/the dashboard data source setting is unchanged/)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalled();  // database-backed pages reload
    expect(m.uploadDataFile).not.toHaveBeenCalled();
  });

  it('shows file-level problems and offers no import for a blocked file', async () => {
    const user = userEvent.setup();
    m.previewRawUpload.mockResolvedValue({ ...PREVIEW, status: 'rejected', status_label: 'Rejected (cannot be imported)', blocked: true,
      summary: { ...PREVIEW.summary!, ready_to_import: 0 },
      file_issues: [{ code: 'date_mismatch', message: 'The file is for 13-10-2026, not the entered reporting date 14-10-2026.' }] });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await user.type(await screen.findByLabelText('Reporting date'), '2026-10-14');
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['x'], 'day.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Validate on server' }));
    expect(await screen.findByText(/not the entered reporting date 14-10-2026/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Import/ })).not.toBeInTheDocument();
  });

  it('refuses non-CSV files in the browser and explains an unassigned account', async () => {
    const user = userEvent.setup({ applyAccept: false });
    m.fetchRawUploadOptions.mockResolvedValue({ ...OPTIONS, assigned_circles: [], projects: OPTIONS.projects.map((p) => ({ ...p, circles: [] })) });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_USER }) });
    expect(await screen.findByText('No circle is assigned to your account')).toBeInTheDocument();
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['x'], 'data.xlsx'));
    expect(screen.getByText(/choose the CSV file exported from CNMC/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Validate on server' })).toBeDisabled();
    expect(m.previewRawUpload).not.toHaveBeenCalled();
  });

  it('links the consolidated export to the chosen filters', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await screen.findByLabelText('Export: project');
    expect(screen.getByText('Choose the dates to export.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('From'), '2026-10-01');
    await user.type(screen.getByLabelText('To'), '2026-10-31');
    expect(screen.getByRole('link', { name: /Excel/ })).toHaveAttribute('href',
      expect.stringContaining('/raw-uploads/export/?project=4G+Saturation&date_from=2026-10-01&date_to=2026-10-31&output=xlsx'));
  });
});
