import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { CI_USER, authValue, renderWithWorkbook, workbookValue } from '../../test/renderWithWorkbook';
import type { RawRowsPage, RawUpload, RawUploadOptions } from '../../types/rawUpload';
import { UploadCsvPage } from './UploadCsvPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRawUploadOptions: vi.fn(), fetchRawUploads: vi.fn(), fetchRawUpload: vi.fn(), fetchRawUploadRows: vi.fn(),
  previewRawUpload: vi.fn(), commitRawUpload: vi.fn(), discardRawUpload: vi.fn(),
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
      availability: null, outage_minutes: null, status: 'out_of_scope', code: 'outside_scope', label: 'Outside the dashboard reporting scope',
      message: 'ZZOR999 is not in the approved 4G Saturation site master (outside the project scope).', note: '' },
    { line: 4, raw_id: 'UVOR003', site_id: 'UVOR003', site_name: 'Pardi', circle: 'OR', report_date: '13-10-2026', raw_availability: '',
      availability: null, outage_minutes: null, status: 'availability', code: 'not_reported', label: 'Availability blank: not reported (never 0)',
      message: 'Nw Avail (4G TCS) is blank: not read as 0% or as 0 outage minutes.', note: '' },
  ],
};
const PREVIEW: RawUpload = {
  id: 7, status: 'previewed', status_label: 'Previewed', file: 'nw_aval_day.csv', checksum: 'abc', project: '4G Saturation', circle: 'OD',
  reporting_date: '2026-10-13', remarks: null, uploaded_by: 'ravi.ci', uploaded_at: '2026-10-29T10:00:00Z', committed_at: null, error: null,
  summary: { total_rows: 3, valid_in_scope: 1, ready_to_import: 1, identical_skipped: 0, out_of_scope: 1, unresolved_or_ambiguous: 0,
    availability_problems: 1, duplicates_or_conflicts: 0, date_mismatches: 0, project_or_circle_mismatches: 0, other_invalid: 0,
    by_code: { ready: 1, outside_scope: 1, not_reported: 1 }, by_status: { ready: 1, out_of_scope: 1, availability: 1 } },
  daily: null, rejected_count: 2, skipped_count: 0, file_issues: [], blocked: false,
  file_info: { encoding: 'utf-8-sig', header_line: 2, preamble: ['Network availability report'], blank_lines: 0, columns: {}, unused_columns: 50,
    report_dates: ['2026-10-13'], circles_in_file: { OD: 3 } },
  availability_rule: { column: 'Nw Avail (4G TCS)', confirmed: true, formula: 'outage minutes = 1440 × (1 − availability / 100)' },
  resolver: { project: '4G Saturation', configured: true },
  master_scope: { sites: 4, sites_in_file: 2, missing_from_file: 2, missing_examples: ['UVOR002', 'UVOR004'] },
  already_imported: null, rows: ROWS,
};
const CI_OD = { ...CI_USER, circles: ['OD'] };
/** Each workflow step as "label: state", from the indicator's data-state (what the server reported). */
const steps = () => within(screen.getByRole('list', { name: 'Upload progress' })).getAllByRole('listitem')
  .map((li) => `${li.textContent!.replace(/\s*\(.*\)$/, '').replace(/^\d/, '')}: ${li.getAttribute('data-state')}`);

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
      daily: { inserted: 1, filled: 0, skipped_identical: 3, skipped_repeats: 0, rejected: 2, conflicts: 4, pending: 5 } });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }), workbook: workbookValue({ refresh }) });
    const circle = await screen.findByLabelText('Circle (assigned)');
    expect(circle).toHaveValue('OD');
    expect(circle).toHaveAttribute('readonly');
    const validate = screen.getByRole('button', { name: 'Validate CSV' });
    expect(validate).toBeDisabled();
    expect(screen.getByText('Still needed: reporting date, CSV file.')).toBeInTheDocument();
    expect(steps()).toEqual(['Upload: current', 'Validate & Preview: todo', 'Confirm Import: todo', 'Results: todo']);
    await user.type(screen.getByLabelText('Reporting date'), '2026-10-13');
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['BTS IP ID,Circle,Report Date\n'], 'nw_aval_day.csv', { type: 'text/csv' }));
    expect(screen.getByText('nw_aval_day.csv')).toBeInTheDocument();
    await user.click(validate);
    expect(m.previewRawUpload).toHaveBeenCalledWith(expect.any(File), { project: '4G Saturation', circle: 'OD', reporting_date: '2026-10-13', remarks: '' });

    const preview = await screen.findByLabelText('Validation preview');
    expect(steps()).toEqual(['Upload: done', 'Validate & Preview: done', 'Confirm Import: current', 'Results: todo']);
    expect(within(screen.getByLabelText('Selected file')).getByText('Validation passed')).toBeInTheDocument();
    expect(within(preview).getByText(/Validation preview — nothing saved yet/)).toBeInTheDocument();
    expect(within(preview).queryByText(/Saved to the reporting data/)).not.toBeInTheDocument();  // no success banner before the commit
    // Row filter counts come from the server's by_status.
    const filters = within(preview).getByRole('group', { name: 'Show rows' });
    expect(within(filters).getByRole('button', { name: 'Out of scope (1)' })).toBeInTheDocument();
    expect(within(filters).getByRole('button', { name: 'Availability problem (1)' })).toBeInTheDocument();
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

    await user.click(within(preview).getByRole('button', { name: 'Import 1 record…' }));
    expect(m.commitRawUpload).not.toHaveBeenCalled();  // a second, explicit confirmation
    await user.click(within(preview).getByRole('button', { name: 'Yes, import' }));
    expect(m.commitRawUpload).toHaveBeenCalledWith(7);
    const result = await screen.findByLabelText('Import result');
    expect(within(result).getByRole('status')).toHaveTextContent(
      'Saved to the reporting data: 1 new daily records, 3 already stored, 4 conflicting values kept (higher-precedence values stay), 5 rows pending (unmatched programme sites, not yet in the site master), 2 rejected.');
    expect(within(result).queryByText(/data source setting/)).not.toBeInTheDocument();
    expect(refresh).toHaveBeenCalled();  // every page reloads from the reporting data
    expect(steps()).toEqual(['Upload: done', 'Validate & Preview: done', 'Confirm Import: done', 'Results: done']);
  });

  it('shows file-level problems and offers no import for a blocked file', async () => {
    const user = userEvent.setup();
    m.previewRawUpload.mockResolvedValue({ ...PREVIEW, status: 'rejected', status_label: 'Rejected (cannot be imported)', blocked: true,
      summary: { ...PREVIEW.summary!, ready_to_import: 0 },
      file_issues: [{ code: 'date_mismatch', message: 'The file is for 13-10-2026, not the entered reporting date 14-10-2026.' }] });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await user.type(await screen.findByLabelText('Reporting date'), '2026-10-14');
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['x'], 'day.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Validate CSV' }));
    expect(await screen.findByText(/not the entered reporting date 14-10-2026/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Import/ })).not.toBeInTheDocument();
    expect(steps()).toEqual(['Upload: done', 'Validate & Preview: failed', 'Confirm Import: todo', 'Results: todo']);  // never shown as passed
    expect(screen.queryByText(/Saved to the reporting data/)).not.toBeInTheDocument();
    expect(within(screen.getByLabelText('Selected file')).getByText('Blocked — see the preview')).toBeInTheDocument();
  });

  it('refuses non-CSV files in the browser and explains an unassigned account', async () => {
    const user = userEvent.setup({ applyAccept: false });
    m.fetchRawUploadOptions.mockResolvedValue({ ...OPTIONS, assigned_circles: [], projects: OPTIONS.projects.map((p) => ({ ...p, circles: [] })) });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_USER }) });
    expect(await screen.findByText('No circle is assigned to your account')).toBeInTheDocument();
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['x'], 'data.xlsx'));
    expect(screen.getByText(/choose the CSV file exported from CNMC/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Validate CSV' })).toBeDisabled();
    expect(m.previewRawUpload).not.toHaveBeenCalled();
  });

  it('selects a file by drag and drop, and Replace / Remove clear a stale preview', async () => {
    const user = userEvent.setup();
    m.previewRawUpload.mockResolvedValue(PREVIEW);
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    const zone = (await screen.findByText('Upload your daily CSV file')).closest('div')!;
    const dropped = new File(['BTS IP ID,Circle,Report Date\n'], 'dropped.csv', { type: 'text/csv' });
    fireEvent.dragOver(zone, { dataTransfer: { files: [dropped] } });
    expect(screen.getByText('Drop the CSV to select it')).toBeInTheDocument();
    fireEvent.drop(zone, { dataTransfer: { files: [dropped] } });
    const selected = screen.getByLabelText('Selected file');
    expect(selected).toHaveTextContent('dropped.csv');
    expect(selected).toHaveTextContent('Ready to validate');
    fireEvent.drop(zone, { dataTransfer: { files: [dropped, dropped] } });
    expect(screen.getByText('Drop one CSV file at a time.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Selected file')).not.toBeInTheDocument();
    fireEvent.drop(zone, { dataTransfer: { files: [dropped] } });
    await user.type(screen.getByLabelText('Reporting date'), '2026-10-13');
    await user.click(screen.getByRole('button', { name: 'Validate CSV' }));
    expect(await screen.findByLabelText('Validation preview')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove file' }));
    expect(screen.queryByLabelText('Validation preview')).not.toBeInTheDocument();  // a stale preview cannot be imported
    expect(screen.getByRole('button', { name: 'Validate CSV' })).toBeDisabled();
    expect(screen.getByText('Still needed: CSV file.')).toBeInTheDocument();
  });

  it('explains why validation failed next to the file and keeps the import steps open', async () => {
    const user = userEvent.setup();
    m.previewRawUpload.mockRejectedValue(new api.ApiError('This is the monthly summary dump (MONTH and YEAR columns, no Report Date).', 400));
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await user.type(await screen.findByLabelText('Reporting date'), '2026-10-13');
    await user.upload(screen.getByLabelText('Raw daily CSV file'), new File(['x'], 'monthly.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Validate CSV' }));
    expect(await screen.findByText('The file could not be validated')).toBeInTheDocument();
    expect(screen.getByText(/monthly summary dump/)).toBeInTheDocument();
    expect(within(screen.getByLabelText('Selected file')).getByText('Validation failed')).toBeInTheDocument();
    expect(steps()).toEqual(['Upload: current', 'Validate & Preview: failed', 'Confirm Import: todo', 'Results: todo']);
  });

  it('shows no success banner for a discarded or failed upload, and lists pending sites', async () => {
    const user = userEvent.setup();
    m.fetchRawUploads.mockResolvedValue({ uploads: [{ ...PREVIEW, id: 8, status: 'failed', status_label: 'Failed', error: 'Database error' }] });
    m.fetchRawUpload.mockResolvedValue({ ...PREVIEW, id: 8, status: 'failed', status_label: 'Failed', error: 'Database error', pending_sites: ['XXOR1', 'XXOR2'],
      daily: null });
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await user.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Database error', { selector: '[data-slot="alert-description"]' })).toBeInTheDocument();
    expect(screen.getByLabelText('Pending sites')).toHaveTextContent('XXOR1, XXOR2');
    expect(screen.queryByText(/Saved to the reporting data/)).not.toBeInTheDocument();
  });

  it('notes that LWE rows cannot be imported only while the LWE mapping is missing', async () => {
    const lwe = (configured: boolean) => ({ ...OPTIONS, projects: [{ ...OPTIONS.projects[1], configured }] });
    m.fetchRawUploadOptions.mockResolvedValue(lwe(false));
    const first = renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    expect(await screen.findByText(/LWE rows cannot be imported yet/)).toBeInTheDocument();
    first.unmount();
    m.fetchRawUploadOptions.mockResolvedValue(lwe(true));  // the LWE Band ID mapping exists: LWE is importable
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await screen.findByLabelText('Circle (assigned)');
    expect(screen.queryByText(/LWE rows cannot be imported yet/)).not.toBeInTheDocument();
  });

  it('shows the programme classification tiles and does not present outside-programme rows as pending', async () => {
    const user = userEvent.setup();
    const classified: RawUpload = {
      ...PREVIEW, summary: { ...PREVIEW.summary!, total_rows: 10, classification: { matched: 5, unmatched_programme: 2, outside_programme: 2, invalid: 1 } },
      pending_sites: ['UVOR777', 'UVOR778'],
      rows: null,
    };
    const rows: RawRowsPage = { ...ROWS, rows: ROWS.rows.map((r) => ({ ...r, category: r.status === 'ready' ? 'matched' as const : r.status === 'out_of_scope' ? 'outside_programme' as const : 'invalid' as const })) };
    m.fetchRawUploadRows.mockResolvedValue(rows);
    m.fetchRawUploads.mockResolvedValue({ uploads: [classified] });
    m.fetchRawUpload.mockResolvedValue(classified);
    renderWithWorkbook(<UploadCsvPage />, { url: '/data/upload-csv', auth: authValue({ user: CI_OD }) });
    await user.click(await screen.findByRole('button', { name: 'View' }));
    const tiles = await screen.findByLabelText('Row classification');
    expect(tiles).toHaveTextContent('Matched5');
    expect(tiles).toHaveTextContent('Unmatched programme2');
    expect(tiles).toHaveTextContent('Outside programme scope2');
    expect(tiles).toHaveTextContent('Invalid1');
    expect(tiles).toHaveTextContent('Outside programme scope (not in the Consolidation Matrix; not counted as unmatched)');
    // Only the genuine unmatched programme IDs are pending: the outside-programme raw ID is not.
    const pending = screen.getByLabelText('Pending sites');
    expect(pending).toHaveTextContent('UVOR777, UVOR778');
    expect(pending).not.toHaveTextContent('ZZOR999');
    // The row table shows the category, and a category filter sits next to the status filter.
    const table = screen.getByRole('table', { name: 'Rows' });
    expect(await within(table).findByText('Outside programme scope')).toBeInTheDocument();
    const filter = screen.getByRole('group', { name: 'Show category' });
    expect(screen.getByRole('group', { name: 'Show rows' })).toBeInTheDocument();
    await user.click(within(filter).getByRole('button', { name: 'Outside programme scope (2)' }));
    expect(m.fetchRawUploadRows).toHaveBeenLastCalledWith(7, '', 1, expect.anything(), 'outside_programme');
  });
});
