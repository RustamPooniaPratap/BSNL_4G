import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '../components/Sidebar';
import * as api from '../services/api';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { MasterDatasets } from '../types/masterData';
import { MasterDataPage } from './MasterDataPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchMasterDatasets: vi.fn(), fetchMasterOptions: vi.fn(), fetchMasterRecords: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });
const col = (key: string, label: string, kind = 'text', hidden = false) => ({ key, label, kind, hidden }) as MasterDatasets['datasets'][0]['columns'][0];
const META: MasterDatasets = {
  page_sizes: [25, 50], weeks: [{ value: 1, label: 'Week 1 (days 1–7)' }, { value: 2, label: 'Week 2 (days 8–14)' }],
  datasets: [
    { key: 'uptime_sites', label: 'Site Master', description: 'Sites.', time: false, columns: [col('site_id', 'Site ID'), col('ci_contact', 'CI contact', 'text', true)],
      filters: { site: true, choices: [] } },
    { key: 'uptime_daily', label: 'Daily Performance', description: 'Daily.', time: true,
      columns: [col('date', 'Reporting date', 'date'), col('site_id', 'Site ID'), col('outage_minutes', 'Outage minutes', 'minutes')], filters: { site: true, choices: [] } },
    { key: 'escalation', label: 'CI-wise Consolidation & Escalation Matrix', description: 'Matrix.', time: false, columns: [col('site_id', 'BSNL Site ID')], filters: { site: true, choices: [] } },
    { key: 'rca', label: 'RCA Data', description: 'RCA.', time: true, columns: [col('reporting_date', 'Date', 'date')], filters: { site: true, choices: [] } },
  ],
};
const lastParams = () => m.fetchMasterRecords.mock.calls.at(-1)![1] as URLSearchParams;

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchMasterDatasets.mockResolvedValue(META);
  m.fetchMasterOptions.mockResolvedValue({ projects: ['4G Saturation', 'LWE'], circles: ['MP'], months: [{ year: 2026, month: 9 }, { year: 2026, month: 10 }],
    dates: ['2026-10-01', '2026-10-09'], choices: {} });
  m.fetchMasterRecords.mockResolvedValue({ total: 2, page: 1, page_size: 50, pages: 1,
    rows: [{ _id: 1, site_id: 'UVMP1', date: '2026-10-09', outage_minutes: null, ci_contact: null }, { _id: 2, site_id: 'UVMP2', date: '2026-10-09', outage_minutes: 12 }] });
});

describe('Master Data', () => {
  it('is one sidebar entry with dataset tabs inside the page', async () => {
    renderWithWorkbook(<><Sidebar /><MasterDataPage /></>, { url: '/master-data/escalation' });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Master Data' })).toHaveAttribute('aria-current', 'page');
    const tabs = screen.getByRole('navigation', { name: 'Master Data datasets' });
    expect(within(tabs).getAllByRole('link').map((a) => a.textContent)).toEqual(['Uptime Master', 'CI-wise Consolidation & Escalation Matrix', 'RCA Data']);
    expect(await screen.findByRole('region', { name: 'CI-wise Consolidation & Escalation Matrix' })).toBeInTheDocument();
    expect(m.fetchMasterRecords).toHaveBeenCalledWith('escalation', expect.any(URLSearchParams), expect.anything());
    expect(screen.queryByRole('group', { name: 'Period' })).not.toBeInTheDocument();  // static data: no period views
  });

  it('shows the site master, then daily records of the latest month with the period views', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<MasterDataPage />, { url: '/master-data' });
    const grid = await screen.findByRole('region', { name: 'Site Master' });
    expect(await within(grid).findByText('2 matching records')).toBeInTheDocument();
    expect(within(grid).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Site ID']);  // hidden columns off by default
    await user.click(screen.getByRole('button', { name: 'Daily Performance' }));
    expect(await screen.findByRole('region', { name: 'Daily Performance' })).toBeInTheDocument();
    await waitFor(() => expect(Object.fromEntries(lastParams())).toMatchObject({ period: 'daily', year: '2026', month: '10' }));  // the latest month with data
    expect(within(screen.getByRole('region', { name: 'Daily Performance' })).getAllByRole('row')[1]).toHaveTextContent('09 Oct 2026UVMP1—');  // blank, not 0
    await user.click(screen.getByRole('button', { name: 'Weekly' }));
    await waitFor(() => expect(Object.fromEntries(lastParams())).toMatchObject({ period: 'weekly', year: '2026', month: '10' }));
    await user.click(screen.getByRole('button', { name: 'Outage minutes' }));
    await waitFor(() => expect(lastParams().get('sort')).toBe('outage_minutes'));
    const csv = screen.getByRole('link', { name: /CSV/ });
    expect(csv.getAttribute('href')).toContain('/master-data/uptime_daily/export/?');
    expect(csv.getAttribute('href')).toContain('period=weekly');
    expect(csv.getAttribute('href')).toContain('file=csv');
  });
});
