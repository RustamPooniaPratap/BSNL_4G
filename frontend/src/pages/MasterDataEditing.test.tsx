import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { ApiError } from '../services/api';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { MasterDatasets, MasterPermissions } from '../types/masterData';
import { MasterDataPage } from './MasterDataPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchMasterDatasets: vi.fn(), fetchMasterOptions: vi.fn(), fetchMasterRecords: vi.fn(), saveMasterData: vi.fn(), revertMasterOverrides: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 30000 });

const col = (key: string, label: string, kind = 'text') => ({ key, label, kind, hidden: false }) as MasterDatasets['datasets'][0]['columns'][0];
const READER: MasterPermissions = { view: true, export: false, edit: false, add: false, editable: [], addable: [], required: [] };
/** Daily Performance: changes are authorized corrections and need a reason. */
const EDITOR: MasterPermissions = { view: true, export: false, edit: true, add: true, editable: ['availability_pct', 'outage_minutes'],
  addable: ['project', 'circle', 'site_id', 'date', 'availability_pct', 'outage_minutes'], required: ['site_id', 'date'], reason_required: true };
const SITE_EDITOR: MasterPermissions = {
  view: true, export: true, edit: true, add: false,
  editable: ['site_name', 'oa', 'on_air', 'on_air_date', 'latitude'], addable: [], required: [],
};
const ESCALATION_EDITOR: MasterPermissions = {
  view: true, export: true, edit: true, add: false,
  editable: ['ci_name', 'commissioning_date'], addable: [], required: [],
};
const RCA_EDITOR: MasterPermissions = {
  view: true, export: true, edit: true, add: true,
  editable: ['final_bucket', 'rca_text'], addable: ['reporting_date', 'project', 'circle', 'site_id', 'rca_text', 'final_bucket'],
  required: ['reporting_date', 'project', 'circle', 'site_id', 'rca_text'],
};
/** A viewer without an Edit grant sees Site Master in its default read-only mode. */
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
  const input = screen.getByLabelText(label);
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

  it('edits text, dropdown, boolean, date and numeric Site Master cells and saves them together', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue({
      page_sizes: [25, 50], weeks: [],
      datasets: [{
        key: 'uptime_sites', label: 'Site Master', description: 'Manual overrides persist across matrix imports.', time: false,
        columns: [col('site_id', 'Site ID'), col('site_name', 'Site name'), col('oa', 'OA'), col('on_air', 'On-Air', 'bool'),
          col('on_air_date', 'On-Air date', 'date'), col('latitude', 'Latitude', 'number')],
        filters: { site: true, choices: [] }, permissions: SITE_EDITOR,
      }],
    });
    m.fetchMasterOptions.mockResolvedValue({ projects: ['4G Saturation'], circles: ['MP'], choices: { oa: ['Sehore', 'Bhopal'] } });
    m.fetchMasterRecords.mockResolvedValue({
      total: 1, page: 1, page_size: 50, pages: 1, manual_overrides: {},
      rows: [{ _id: 7, updated_at: '2026-11-16T09:30:00+00:00', site_id: 'UVMP1', site_name: 'Alpha', oa: 'Sehore',
        on_air: false, on_air_date: '2026-10-01', latitude: 23.2 }],
    });
    m.saveMasterData.mockResolvedValue({ saved: true, updated: 1, added: 0, ids: [7] });
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await screen.findByRole('region', { name: 'Site Master' });
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
    expect(screen.getByText('EDIT MODE')).toBeInTheDocument();

    await user.dblClick(screen.getByRole('cell', { name: /Site name of record 7/ }));
    const name = screen.getByRole('textbox', { name: 'Site name of record 7' });
    await user.clear(name);
    await user.type(name, 'Manual Alpha{Enter}');

    await user.dblClick(screen.getByRole('cell', { name: /OA of record 7/ }));
    const oa = screen.getByRole('combobox', { name: 'OA of record 7' });
    await user.selectOptions(oa, 'Bhopal');
    await user.keyboard('{Enter}');

    await user.dblClick(screen.getByRole('cell', { name: /On-Air of record 7/ }));
    const onAir = screen.getByRole('combobox', { name: 'On-Air of record 7' });
    await user.selectOptions(onAir, 'Yes');
    await user.keyboard('{Enter}');

    await user.dblClick(screen.getByRole('cell', { name: /On-Air date of record 7/ }));
    const date = screen.getByLabelText('On-Air date of record 7');
    fireEvent.change(date, { target: { value: '2026-11-10' } });
    fireEvent.keyDown(date, { key: 'Enter', code: 'Enter' });

    await user.dblClick(screen.getByRole('cell', { name: /Latitude of record 7/ }));
    const latitude = screen.getByRole('spinbutton', { name: 'Latitude of record 7' });
    await user.clear(latitude);
    await user.type(latitude, '24.5{Enter}');

    expect(screen.getByRole('region', { name: 'Unsaved changes' })).toHaveTextContent('5 changed cells in 1 row');
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    await waitFor(() => expect(m.saveMasterData).toHaveBeenCalledWith('uptime_sites', {
      changes: [{ id: 7, values: { site_name: 'Manual Alpha', oa: 'Bhopal', on_air: 'Yes', on_air_date: '2026-11-10', latitude: '24.5' },
        updated_at: '2026-11-16T09:30:00+00:00' }],
      additions: [],
    }));
  });

  it('shows CI-wise Edit Mode and saves only the authorized matrix fields', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue({
      page_sizes: [25, 50], weeks: [],
      datasets: [{
        key: 'escalation', label: 'CI-wise Consolidation & Escalation Matrix', description: 'Matrix overrides persist across imports.',
        time: false, columns: [col('site_id', 'BSNL Site ID'), col('ci_name', 'CI'), col('commissioning_date', 'Commissioning', 'date')],
        filters: { site: true, choices: [] }, permissions: ESCALATION_EDITOR,
      }],
    });
    m.fetchMasterRecords.mockResolvedValue({
      total: 1, page: 1, page_size: 50, pages: 1, manual_overrides: {},
      rows: [{ _id: 12, updated_at: '2026-11-16T09:30:00+00:00', site_id: 'UVMP12', ci_name: 'CI East', commissioning_date: '2025-01-01' }],
    });
    m.saveMasterData.mockResolvedValue({ saved: true, updated: 1, added: 0, ids: [12] });
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data/escalation' });
    const region = await screen.findByRole('region', { name: 'CI-wise Consolidation & Escalation Matrix' });
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
    await user.dblClick(screen.getByRole('cell', { name: /CI of record 12/ }));
    const input = screen.getByRole('textbox', { name: 'CI of record 12' });
    await user.clear(input);
    await user.type(input, 'Manual CI{Enter}');
    await user.dblClick(screen.getByRole('cell', { name: /Commissioning of record 12/ }));
    const date = screen.getByLabelText('Commissioning of record 12');
    fireEvent.change(date, { target: { value: '2025-02-01' } });
    fireEvent.keyDown(date, { key: 'Enter', code: 'Enter' });
    expect(screen.getByRole('region', { name: 'Unsaved changes' })).toHaveTextContent('2 changed cells in 1 row');
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    await waitFor(() => expect(m.saveMasterData).toHaveBeenCalledWith('escalation', {
      changes: [{ id: 12, values: { ci_name: 'Manual CI', commissioning_date: '2025-02-01' }, updated_at: '2026-11-16T09:30:00+00:00' }], additions: [],
    }));
    expect(await screen.findByText('Saved to the database: 1 record updated, 0 added.')).toBeInTheDocument();
  });

  it('keeps RCA Data Edit Mode and saving behavior intact', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue({
      page_sizes: [25, 50], weeks: [],
      datasets: [{
        key: 'rca', label: 'RCA Data', description: 'RCA records.', time: true,
        columns: [col('final_bucket', 'Final Bucket'), col('rca_text', 'RCA')],
        filters: { site: true, choices: [] }, permissions: RCA_EDITOR,
      }],
    });
    m.fetchMasterOptions.mockResolvedValue({ projects: [], circles: [], months: [], choices: {} });
    m.fetchMasterRecords.mockResolvedValue({
      total: 1, page: 1, page_size: 50, pages: 1,
      rows: [{ _id: 3, final_bucket: 'TCS', rca_text: 'Power issue' }],
    });
    m.saveMasterData.mockResolvedValue({ saved: true, updated: 1, added: 0, ids: [3] });
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data/rca' });
    const region = await screen.findByRole('region', { name: 'RCA Data' });
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
    await user.dblClick(screen.getByRole('cell', { name: /RCA of record 3/ }));
    const input = screen.getByRole('textbox', { name: 'RCA of record 3' });
    await user.clear(input);
    await user.type(input, 'Fiber cut{Enter}');
    await user.click(screen.getByRole('button', { name: /Save Changes/ }));
    await waitFor(() => expect(m.saveMasterData).toHaveBeenCalledWith('rca', {
      changes: [{ id: 3, values: { rca_text: 'Fiber cut' } }], additions: [],
    }));
  });

  it('uses Enter, Tab and Shift+Tab for cell navigation, and Discard restores the server value', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue({
      page_sizes: [25, 50], weeks: [],
      datasets: [{ key: 'uptime_sites', label: 'Site Master', description: 'Sites.', time: false,
        columns: [col('site_id', 'Site ID'), col('site_name', 'Site name'), col('oa', 'OA')],
        filters: { site: true, choices: [] }, permissions: SITE_EDITOR }],
    });
    m.fetchMasterOptions.mockResolvedValue({ projects: [], circles: [], choices: { oa: ['Sehore'] } });
    m.fetchMasterRecords.mockResolvedValue({ total: 1, page: 1, page_size: 50, pages: 1,
      rows: [{ _id: 1, site_id: 'UVMP1', site_name: 'Alpha', oa: 'Sehore', project: '4G Saturation', circle: 'MP' }] });
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const region = await screen.findByRole('region', { name: 'Site Master' });
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
    const nameCell = screen.getByRole('cell', { name: /Site name of record 1/ });
    nameCell.focus();
    await user.keyboard('{Enter}');
    const name = screen.getByRole('textbox', { name: 'Site name of record 1' });
    await user.clear(name);
    await user.type(name, 'Draft{Tab}');
    await waitFor(() => expect(document.activeElement).toHaveAttribute('aria-label', 'OA of record 1: Sehore'));
    await user.keyboard('{Enter}');
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    await waitFor(() => expect(document.activeElement).toHaveAttribute('aria-label', 'Site name of record 1: Draft'));
    await user.click(screen.getByRole('button', { name: /Discard Changes/ }));
    expect(screen.getByRole('cell', { name: 'Site name of record 1: Alpha' })).toBeInTheDocument();
    expect(m.saveMasterData).not.toHaveBeenCalled();
  });

  it('corrects several values with a mandatory reason, saves them together and reloads from the database', async () => {
    const user = userEvent.setup();
    m.fetchMasterDatasets.mockResolvedValue(meta(EDITOR));
    m.saveMasterData.mockResolvedValue({ saved: true, updated: 2, added: 0, ids: [1, 2] });
    renderWithWorkbook(<MasterDataPage />, { url: URL_DAILY });
    const region = await grid();
    await within(region).findByText('Alpha');
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
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
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
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
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
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
    await user.click(within(region).getByRole('button', { name: 'Edit Mode' }));
    await typeInto(user, 'Availability of record 1', '42');
    // Switching the Uptime Master view would reload the table: the page asks first.
    await user.click(screen.getByRole('button', { name: 'Site Master' }));
    const dialog = await screen.findByRole('dialog', { name: 'Unsaved changes' });
    await user.click(within(dialog).getByRole('button', { name: 'Stay' }));
    expect(screen.getByRole('cell', { name: /Availability of record 1/ })).toHaveTextContent('42');  // still there
  });
});
