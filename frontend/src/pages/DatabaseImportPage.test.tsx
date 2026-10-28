import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAdmin } from '../components/auth/Guards';
import { Sidebar } from '../components/Sidebar';
import * as api from '../services/api';
import { authValue, CI_USER, renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import type { DatabaseCompleteness, DataSourceState, ImportBatch } from '../types';
import { DatabaseImportPage } from './DatabaseImportPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchDataSource: vi.fn(), setDataSource: vi.fn(), fetchImports: vi.fn(), previewImport: vi.fn(), commitImport: vi.fn(), discardImport: vi.fn(),
}));
const m = vi.mocked(api);

const DB: DatabaseCompleteness = {
  sites: 6726, monthly_records: 87438, daily_records: 134520, months: ['2026-09', '2026-10'],
  daily_months: { '2026-10': { label: 'Oct-26', first: '2026-10-01', last: '2026-10-20', days: 20, gaps: [] } },
  previous_month_daily: false, last_import: { batch: 1, file: 'master.xlsx', committed_at: '2026-10-24T17:09:26' }, empty: false,
  warnings: ['Sep-26 daily history is missing (only its monthly totals are imported).'],
};
const STATE: DataSourceState = { active: 'excel', label: 'Excel workbook', options: [{ value: 'excel', label: 'Excel workbook' }, { value: 'database', label: 'PostgreSQL database' }], database: DB };
const SUMMARY = {
  filename: 'master.xlsx', checksum: 'abc', sheet: 'Up-Time Report', has_project_column: true, data_rows: 6726, sites: 6726, distinct_site_ids: 6726,
  by_project: { '4G Saturation': 4544, LWE: 2182 }, by_circle: { '4G Saturation|MP': 1483 }, months: { '2026-09': { label: 'Sep-26', sites_with_values: 6725 } },
  daily: { '2026-10': { outage_columns: 'BT:CX', uptime_columns: 'DG:EK', dates: [], reported_dates: ['2026-10-01', '2026-10-20'], missing_values: {}, site_day_values: 134520 } },
  skipped: {}, rejected: 0, flagged: 0, issues: {},
};
const PREVIEW: ImportBatch = {
  id: 7, status: 'previewed', file: 'master.xlsx', checksum: 'abc', sheet: 'Up-Time Report', reconciliation_file: 'rj.xlsx', conflict_source: null,
  uploaded_at: '2026-10-24T17:00:00', committed_at: null, imported_by: 'asha.admin', via: 'api', counts: {}, rejected: 0, skipped: 0, error: null,
  report: {
    primary: SUMMARY, reconciliation: { ...SUMMARY, filename: 'rj.xlsx', has_project_column: false },
    comparison: { primary: 'master.xlsx', reconciliation: 'rj.xlsx', overlapping_sites: 4544, only_in_primary: 0, only_in_reconciliation: 0, sites_with_differences: 4544,
      differences: { 'monthly.May-26.ff_count': { count: 1941, examples: [{ circle: 'MP', site_id: 'UVMPBLG00003', where: 'May-26', primary: 15, reconciliation: 16 }] } },
      dates_only_in_reconciliation: ['2026-10-21'] },
    database_effect: { sites_in_database: 0, new_sites: 6726, existing_sites: 0, database_sites_not_in_file: 0 },
  },
};
const COUNTS = { inserted: 6726, updated: 0, unchanged: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchDataSource.mockResolvedValue(STATE);
  m.fetchImports.mockResolvedValue({ imports: [], database: DB });
  m.previewImport.mockResolvedValue(PREVIEW);
  m.commitImport.mockResolvedValue({ ...PREVIEW, status: 'committed', counts: { sites: COUNTS, monthly: COUNTS, daily: COUNTS }, database: DB });
  m.setDataSource.mockResolvedValue({ ...STATE, active: 'database' });
});

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

  it('sends the project and the daily-values-only option, and shows what a daily import will add', async () => {
    const user = userEvent.setup();
    m.previewImport.mockResolvedValue({ ...PREVIEW, reconciliation_file: null, report: { ...PREVIEW.report!, comparison: undefined, reconciliation: undefined,
      daily_effect: { months: ['2026-09'], sites_in_file: 4543, sites_in_database: 4543, sites_not_in_database: 0,
        monthly_total_checks: { '2026-09': { sites_compared: 4543, file_monthly_total_differs: 0, database_monthly_total_differs: 0 } } } } });
    renderWithWorkbook(<DatabaseImportPage />);
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
    const file = new File(['x'], 'sep.xlsx');
    fireEvent.change(screen.getByLabelText(/Master workbook \(consolidated/), { target: { files: [file] } });
    await user.selectOptions(screen.getByLabelText(/Project, if the sheet has no Project column/), '4G Saturation');
    await user.click(screen.getByRole('checkbox', { name: /Daily values only/ }));
    expect(screen.getByLabelText(/Second report to compare/)).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /Preview import/ }));
    expect(m.previewImport).toHaveBeenCalledWith(file, null, { project: '4G Saturation', dailyOnly: true });
    expect(await screen.findByRole('region', { name: 'Daily values only' })).toHaveTextContent('2026-09: daily values add up to the monthly total for 4,543 of 4,543 sites');
    expect(screen.getByRole('button', { name: /Commit import/ })).toBeEnabled();  // no second file, no choice needed
  });

  it('previews both files, lists their differences and commits only after a choice', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<DatabaseImportPage />);
    await user.click(await screen.findByRole('radio', { name: /PostgreSQL database/ }));
    const file = new File(['x'], 'master.xlsx');
    fireEvent.change(await screen.findByLabelText(/Master workbook \(consolidated/), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText(/Second report to compare/), { target: { files: [new File(['y'], 'rj.xlsx')] } });
    await user.click(screen.getByRole('button', { name: /Preview import/ }));
    const preview = await screen.findByRole('region', { name: 'Import preview' });
    expect(preview).toHaveTextContent('Preview #7: nothing has been written yet');
    expect(preview).toHaveTextContent('4G Saturation 4,544 · LWE 2,182');
    expect(within(preview).getByRole('region', { name: 'Differences between the two files' })).toHaveTextContent('monthly.May-26.ff_count1,941MP UVMPBLG00003 May-26: 15 vs 16');
    expect(screen.getByRole('button', { name: /Commit import/ })).toBeDisabled();  // a choice is required
    await user.click(screen.getByRole('radio', { name: /the Master workbook/ }));
    await user.click(screen.getByRole('button', { name: /Commit import/ }));
    expect(m.commitImport).toHaveBeenCalledWith(7, 'primary');
    expect(await screen.findByText('Import #7 committed')).toBeInTheDocument();
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
