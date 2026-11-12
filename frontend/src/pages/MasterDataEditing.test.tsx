import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { ApiError } from '../services/api';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { MasterDatasets, MasterPermissions } from '../types/masterData';
import { MasterDataPage } from './MasterDataPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchMasterDatasets: vi.fn(), fetchMasterOptions: vi.fn(), fetchMasterRecords: vi.fn(), saveMasterData: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 30000 });

const col = (key: string, label: string, kind = 'text') => ({ key, label, kind, hidden: false }) as MasterDatasets['datasets'][0]['columns'][0];
const READER: MasterPermissions = { view: true, export: false, edit: false, add: false, editable: [], addable: [], required: [] };
/** Daily Performance: changes are authorized corrections and need a reason. */
const EDITOR: MasterPermissions = { view: true, export: false, edit: true, add: true, editable: ['availability_pct', 'outage_minutes'],
  addable: ['project', 'circle', 'site_id', 'date', 'availability_pct', 'outage_minutes'], required: ['site_id', 'date'], reason_required: true };
/** Site Master: read-only (the Consolidation Matrix is authoritative). */
const sitesMeta = (permissions: MasterPermissions): MasterDatasets => ({
  page_sizes: [25, 50], weeks: [],
  datasets: [{ key: 'uptime_sites', label: 'Site Master', description: 'Sites.', time: false,
    columns: [col('project', 'Project'), col('circle', 'Circle'), col('site_id', 'Site ID'), col('site_name', 'Site name')],
    filters: { site: true, choices: [] }, permissions }],
});
const meta = (permissions: MasterPermissions): MasterDatasets => ({
  page_sizes: [25, 50], weeks: [],
  datasets: [
    { key: 'uptime_sites', label: 'Site Master', description: 'Sites.', time: false, columns: [col('site_id', 'Site ID')],
      filters: { site: true, choices: [] }, permissions: READER },
    { key: 'uptime_daily', label: 'Daily Performance', description: 'Daily.', time: true,
      columns: [col('date', 'Reporting date', 'date'), col('site_id', 'Site ID'), col('site_name', 'Site name'),
        col('availability_pct', 'Availability', 'pct'), col('outage_minutes', 'Outage minutes', 'minutes')],
      filters: { site: true, choices: [] }, permissions },
  ],
});
const URL_DAILY = '/master-data?view=performance';

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchMasterOptions.mockResolvedValue({ projects: ['4G Saturation'], circles: ['MP', 'RJ'], choices: {} });
  m.fetchMasterRecords.mockResolvedValue({ total: 2, page: 1, page_size: 50, pages: 1, rows: [
    { _id: 1, date: '2026-10-01', site_id: 'UVMP1', site_name: 'Alpha', availability_pct: 99, outage_minutes: 14.4 },
    { _id: 2, date: '2026-10-01', site_id: 'UVRJ1', site_name: 'Delta', availability_pct: 100, outage_minutes: 0 },
  ] });
});

const grid = async () => screen.findByRole('region', { name: 'Daily Performance' });
/** Double-click a cell, type a new value and press Enter (as in a spreadsheet). */
const typeInto = async (user: ReturnType<typeof userEvent.setup>, label: string, value: string) => {
  await user.dblClick(screen.getByRole('cell', { name: new RegExp(`^${label}`) }));
  const input = screen.getByRole('textbox', { name: label });
  await user.clear(input);
  await user.type(input, `${value}{Enter}`);
};
const reasonBox = () => screen.getByRole('textbox', { name: /Reason for the correction/ });

describe('Master Data editing', () => {
  it('shows no editing or export controls on a read-only dataset', async () => {
    m.fetchMasterDatasets.mockResolvedValue(sitesMeta(READER));
    m.fetchMasterRecords.mockResolvedValue({ total: 1, page: 1, page_size: 50, pages: 1,
      rows: [{ _id: 1, project: '4G Saturation', circle: 'MP', site_id: 'UVMP1', site_name: 'Alpha' }] });
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await screen.findByRole('region', { name: 'Site Master' });
    await within(region).findByText('Alpha');
    expect(within(region).queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument();
    expect(within(region).queryByRole('link', { name: /CSV|Excel/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('corrects several values with a mandatory reason, saves them together and reloads from the database', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    m.saveMasterData.mockResolvedValue({ saved: true, updated: 2, added: 0, ids: [1, 2] });
    renderWithWorkbook(<MasterDataPage />, { url: URL_DAILY });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Availability of record 1', '99.5');
    await typeInto(user, 'Outage minutes of record 2', '30');
    expect(screen.getByRole('cell', { name: /Availability of record 1/ }).className).toContain('bg-amber-100');  // unsaved
    expect(screen.getByRole('region', { name: 'Unsaved changes' })).toHaveTextContent('2 changed cells in 2 rows');
    expect(within(region).queryByRole('cell', { name: /Site name of record 1/ })).not.toBeInTheDocument();  // not editable here
    expect(screen.getByRole('button', { name: /Save Changes/ })).toBeDisabled();  // no reason yet
    await user.type(reasonBox(), 'Ticket 4711');
    const loads = m.fetchMasterRecords.mock.calls.length;
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    await waitFor(() => expect(m.saveMasterData).toHaveBeenCalledWith('uptime_daily', {
      changes: [{ id: 1, values: { availability_pct: '99.5' } }, { id: 2, values: { outage_minutes: '30' } }], additions: [], reason: 'Ticket 4711' }));
    expect(await screen.findByText('Saved to the database: 2 records updated, 0 added.')).toBeInTheDocument();
    await waitFor(() => expect(m.fetchMasterRecords.mock.calls.length).toBeGreaterThan(loads));  // values as stored
    expect(reasonBox()).toHaveValue('');  // one reason per save
  });

  it("shows the server's errors on their cells and rows, saves nothing, and Discard restores the stored values", async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    m.saveMasterData.mockRejectedValue(new ApiError('Nothing was saved: correct the highlighted cells.', 400, {
      changes: { 1: { _row: 'Oct 2026 is finalized; only an Admin can correct it, explicitly.' } },
      additions: { 0: { site_id: 'UVXX1 is not a Site Master site.' } } }));
    renderWithWorkbook(<MasterDataPage />, { url: URL_DAILY });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Availability of record 1', '50');
    await user.click(screen.getByRole('button', { name: /Add row/ }));
    await typeInto(user, 'New record 1: Site ID', 'UVXX1');
    await user.type(reasonBox(), 'Ticket 1');
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    const cell = await screen.findByRole('cell', { name: /New record 1: Site ID/ });
    await waitFor(() => expect(cell).toHaveAttribute('aria-invalid', 'true'));
    expect(cell).toHaveAttribute('title', 'UVXX1 is not a Site Master site.');
    expect(screen.getByRole('alert')).toHaveTextContent('Nothing was saved');
    expect(screen.getByRole('alert')).toHaveTextContent('Oct 2026 is finalized');  // a whole-row problem is listed
    await user.click(screen.getByRole('button', { name: /Discard/ }));
    expect(within(region).getByText('Alpha')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: 'New record 1' })).not.toBeInTheDocument();
  });

  it("shows the server's reason error", async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    m.saveMasterData.mockRejectedValue(new ApiError('Give the reason for this correction (it is kept with every changed value).', 400, { reason: 'Required.' }));
    renderWithWorkbook(<MasterDataPage />, { url: URL_DAILY });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Availability of record 1', '50');
    await user.type(reasonBox(), 'x');
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Give the reason for this correction');
    expect(reasonBox()).toHaveAttribute('aria-invalid', 'true');
  });

  it('asks before a filter change would lose unsaved changes', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    renderWithWorkbook(<MasterDataPage />, { url: URL_DAILY });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Availability of record 1', '42');
    // Switching the Uptime Master view would reload the table: the page asks first.
    await user.click(screen.getByRole('button', { name: 'Site Master' }));
    const dialog = await screen.findByRole('dialog', { name: 'Unsaved changes' });
    await user.click(within(dialog).getByRole('button', { name: 'Stay' }));
    expect(screen.getByRole('cell', { name: /Availability of record 1/ })).toHaveTextContent('42');  // still there
  });
});
