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
const meta = (permissions: MasterPermissions): MasterDatasets => ({
  page_sizes: [25, 50], weeks: [],
  datasets: [{ key: 'uptime_sites', label: 'Site Master', description: 'Sites.', time: false,
    columns: [col('project', 'Project'), col('circle', 'Circle'), col('site_id', 'Site ID'), col('site_name', 'Site name')],
    filters: { site: true, choices: [] }, permissions }],
});
const EDITOR: MasterPermissions = { view: true, export: false, edit: true, add: true, editable: ['site_name'],
  addable: ['project', 'circle', 'site_id', 'site_name'], required: ['project', 'circle', 'site_id'] };
const READER: MasterPermissions = { view: true, export: false, edit: false, add: false, editable: [], addable: [], required: [] };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchMasterOptions.mockResolvedValue({ projects: ['4G Saturation'], circles: ['MP', 'RJ'], choices: {} });
  m.fetchMasterRecords.mockResolvedValue({ total: 2, page: 1, page_size: 50, pages: 1, rows: [
    { _id: 1, project: '4G Saturation', circle: 'MP', site_id: 'UVMP1', site_name: 'Alpha' },
    { _id: 2, project: '4G Saturation', circle: 'RJ', site_id: 'UVRJ1', site_name: 'Delta' },
  ] });
});

const grid = async () => screen.findByRole('region', { name: 'Site Master' });
/** Double-click a cell, type a new value and press Enter (as in a spreadsheet). */
const typeInto = async (user: ReturnType<typeof userEvent.setup>, label: string, value: string) => {
  await user.dblClick(screen.getByRole('cell', { name: new RegExp(`^${label}`) }));
  const input = screen.getByRole('textbox', { name: label });
  await user.clear(input);
  await user.type(input, `${value}{Enter}`);
};

describe('Master Data editing', () => {
  it('shows no editing or export controls without those permissions', async () => {
    m.fetchMasterDatasets.mockResolvedValue(meta(READER));
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await grid();
    await within(region).findByText('Alpha');
    expect(within(region).queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument();
    expect(within(region).queryByRole('link', { name: /CSV|Excel/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('edits several cells, highlights them, saves them together and reloads from the database', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    m.saveMasterData.mockResolvedValue({ saved: true, updated: 2, added: 0, ids: [1, 2] });
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Site name of record 1', 'Alpha North');
    await typeInto(user, 'Site name of record 2', 'Delta East');
    expect(screen.getByRole('cell', { name: /Site name of record 1/ }).className).toContain('bg-amber-100');  // unsaved
    expect(screen.getByRole('region', { name: 'Unsaved changes' })).toHaveTextContent('2 changed cells in 2 rows');
    expect(within(region).queryByRole('cell', { name: /Site ID of record 1/ })).not.toBeInTheDocument();  // not editable here
    const loads = m.fetchMasterRecords.mock.calls.length;
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    await waitFor(() => expect(m.saveMasterData).toHaveBeenCalledWith('uptime_sites', {
      changes: [{ id: 1, values: { site_name: 'Alpha North' } }, { id: 2, values: { site_name: 'Delta East' } }], additions: [] }));
    expect(await screen.findByText('Saved to the database: 2 records updated, 0 added.')).toBeInTheDocument();
    await waitFor(() => expect(m.fetchMasterRecords.mock.calls.length).toBeGreaterThan(loads));  // values as stored
  });

  it('shows the server\'s errors on their cells, saves nothing, and Discard restores the stored values', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    m.saveMasterData.mockRejectedValue(new ApiError('Nothing was saved: correct the highlighted cells.', 400,
      { changes: {}, additions: { 0: { site_id: 'A record with the same identity already exists (each must be unique).' } } }));
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Site name of record 1', 'Changed');
    await user.click(screen.getByRole('button', { name: /Add row/ }));
    await typeInto(user, 'New record 1: Site ID', 'UVMP1');
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    const cell = await screen.findByRole('cell', { name: /New record 1: Site ID/ });
    await waitFor(() => expect(cell).toHaveAttribute('aria-invalid', 'true'));
    expect(cell).toHaveAttribute('title', 'A record with the same identity already exists (each must be unique).');
    expect(screen.getByRole('alert')).toHaveTextContent('Nothing was saved');
    await user.click(screen.getByRole('button', { name: /Discard/ }));
    expect(within(region).getByText('Alpha')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: 'New record 1' })).not.toBeInTheDocument();
  });

  it('asks before a filter change would lose unsaved changes', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit' }));
    await typeInto(user, 'Site name of record 1', 'Pending');
    // Switching the Uptime Master view would reload the table: the page asks first.
    await user.click(screen.getByRole('button', { name: 'Daily Performance' }));
    const dialog = await screen.findByRole('dialog', { name: 'Unsaved changes' });
    await user.click(within(dialog).getByRole('button', { name: 'Stay' }));
    expect(screen.getByRole('cell', { name: /Site name of record 1/ })).toHaveTextContent('Pending');  // still there
  });
});
