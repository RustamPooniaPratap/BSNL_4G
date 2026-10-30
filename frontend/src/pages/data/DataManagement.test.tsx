import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '../../components/Sidebar';
import * as api from '../../services/api';
import { filterOptions, site, source } from '../../test/fixtures';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { RecordsResponse, SiteRecord } from '../../types';
import { AddRowPage } from './AddRowPage';
import { AddSitePage } from './AddSitePage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchRecords: vi.fn(),
  fetchSiteDetail: vi.fn(),
  uploadWorkbook: vi.fn(),
  uploadDataFile: vi.fn(),
}));
const m = vi.mocked(api);
// These tests walk through whole forms; allow for slow runs when every test file runs in parallel.
vi.setConfig({ testTimeout: 20000 });

// Master data: MP 4G has two sites; LWE BH has one.
const MASTER: SiteRecord[] = [
  site('UVMPBPL00012', { site_name: 'Kheda' }),
  site('UVMPBPL00020', { site_name: 'Ratanpur' }),
  site('LWEBH0303', { report_type: 'LWE', circle: 'BH', site_name: 'Gaya' }),
];
const page = (records: SiteRecord[]): RecordsResponse => ({
  reporting_date: '2026-10-03', count: records.length, page: 1, page_size: 100, pages: 1, records, source,
});

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  m.fetchFilterOptions.mockResolvedValue(filterOptions);
  m.fetchRecords.mockReset().mockImplementation(async (params) => {
    const search = params.get('search');
    if (search) return page(MASTER.filter((s) => s.site_id.includes(search)));
    return page(MASTER.filter((s) => s.report_type === params.get('report_type') && s.circle === params.get('circle')));
  });
  m.fetchSiteDetail.mockReset().mockResolvedValue({
    site: {} as never, reporting_date: '2026-10-03', mtd_uptime_pct: 99, mtd_bucket: 'gte_98_5',
    daily: [{ date: '2026-10-02', reported: true, outage_minutes: 30, uptime_pct: 97.9 }], source,
  });
  // The pages may only read through the (mocked) API helpers: no network request of any kind.
  fetchSpy = vi.spyOn(globalThis, 'fetch');
});
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(m.uploadWorkbook).not.toHaveBeenCalled();
  expect(m.uploadDataFile).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

const render = (ui: React.ReactElement, url: string) =>
  renderWithWorkbook(<Routes><Route path="/data/*" element={ui} /><Route path="*" element={<p>other page</p>} /></Routes>, { url });

async function choose(user: ReturnType<typeof userEvent.setup>, label: RegExp, option: string) {
  await user.click(await screen.findByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: option }));
}

describe('Add Row', () => {
  it('requires every field and explains each problem', async () => {
    const user = userEvent.setup();
    render(<AddRowPage />, '/data/add-row');
    await user.click(await screen.findByRole('button', { name: 'Review record' }));
    expect(screen.getByText('Choose a report type.')).toBeInTheDocument();
    expect(screen.getByText('Choose a circle.')).toBeInTheDocument();
    expect(screen.getByText('Choose the reporting date.')).toBeInTheDocument();
    expect(screen.getByText('Site ID is required.')).toBeInTheDocument();
    expect(screen.getByText(/Outage minutes are required/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Site ID \/ BTS IP ID/)).toHaveAttribute('aria-invalid', 'true');
  });

  it('validates dates and numbers', async () => {
    const user = userEvent.setup();
    render(<AddRowPage />, '/data/add-row');
    const date = await screen.findByLabelText(/Reporting date/);
    fireEvent.change(date, { target: { value: '2999-01-01' } });
    await user.type(screen.getByLabelText(/Outage minutes/), '-4');
    await user.click(screen.getByRole('button', { name: 'Review record' }));
    expect(screen.getByText('The reporting date cannot be in the future.')).toBeInTheDocument();
    expect(screen.getByText('Outage minutes cannot be negative.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/Outage minutes/));
    await user.type(screen.getByLabelText(/Outage minutes/), '12x');
    expect(screen.getByText(/Enter a number of minutes/)).toBeInTheDocument();
  });

  it('finds a known site, warns about an existing value, and confirms locally', async () => {
    const user = userEvent.setup();
    render(<AddRowPage />, '/data/add-row');
    await choose(user, /Report type/, '4G Saturation');
    await choose(user, /Circle/, 'MP');
    fireEvent.change(screen.getByLabelText(/Reporting date/), { target: { value: '2026-10-02' } });
    await user.type(screen.getByLabelText(/Site ID/), 'uvmpbpl00012');
    await user.type(screen.getByLabelText(/Outage minutes/), '45');
    expect(await screen.findByText('Site found in the master data (read-only)')).toBeInTheDocument();
    expect(await screen.findByText(/already has 30 min for UVMPBPL00012 on 02 Oct 2026/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Review record' }));
    const review = screen.getByText('Review the record').closest('[data-slot="card"]') as HTMLElement;
    expect(within(review).getByText('UVMPBPL00012')).toBeInTheDocument();
    expect(within(review).getByText('Kheda')).toBeInTheDocument();
    expect(within(review).getByText('45 min')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Back to edit' }));
    expect(screen.getByLabelText(/Outage minutes/)).toHaveValue('45');  // the draft is kept
    await user.click(screen.getByRole('button', { name: 'Review record' }));
    await user.click(screen.getByRole('button', { name: 'Confirm record' }));
    expect(screen.getByText('Record validated locally. Backend integration is not enabled yet.')).toBeInTheDocument();
  });

  it('blocks an unknown site and links to Add New Site without creating it', async () => {
    const user = userEvent.setup();
    render(<AddRowPage />, '/data/add-row');
    await choose(user, /Report type/, '4G Saturation');
    await choose(user, /Circle/, 'MP');
    await user.type(screen.getByLabelText(/Site ID/), 'UVMPBPL09999');
    expect(await screen.findByText('Site UVMPBPL09999 is not in the 4G Saturation · MP master data')).toBeInTheDocument();
    const link = await screen.findByRole('link', { name: /Add new site UVMPBPL09999/ });
    expect(link).toHaveAttribute('href', '/data/new-site?site_id=UVMPBPL09999&report_type=4G+Saturation&circle=MP');
    await user.click(screen.getByRole('button', { name: 'Review record' }));
    expect(screen.queryByText('Review the record')).not.toBeInTheDocument();
  });
});

// Upload CSV (server-validated raw daily upload) is tested in UploadCsvPage.test.tsx.

describe('Add New Site', () => {
  it('requires the workbook\'s mandatory fields and a valid Site ID', async () => {
    const user = userEvent.setup();
    render(<AddSitePage />, '/data/new-site');
    await user.click(await screen.findByRole('button', { name: 'Review site' }));
    for (const message of ['Choose a report type.', 'Choose a circle.', 'Site ID is required.', 'Site name is required.', 'Choose the On-Air status.']) {
      expect(screen.getByText(message)).toBeInTheDocument();
    }
    await choose(user, /Report type/, 'LWE');
    await user.type(screen.getByLabelText(/Site ID/), 'UVMPBPL00099');
    expect(screen.getByText(/Not a LWE Site ID format \(expected like LWEBH0303\)/)).toBeInTheDocument();
  });

  it('refuses a duplicate Site ID and points to the existing site', async () => {
    const user = userEvent.setup();
    render(<AddSitePage />, '/data/new-site?site_id=LWEBH0303&report_type=LWE&circle=BH');
    expect(await screen.findByText('LWEBH0303 is already registered')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review sites in BH' })).toHaveAttribute('href', '/?report_type=LWE&circle=BH&scope=all');
    await user.type(screen.getByLabelText(/Site name/), 'Gaya 2');
    await choose(user, /^On-Air/, 'Yes');
    await user.click(screen.getByRole('button', { name: 'Review site' }));
    expect(screen.queryByText('Review the new site')).not.toBeInTheDocument();
  });

  it('is pre-filled from an unknown Site ID and confirms locally', async () => {
    const user = userEvent.setup();
    render(<AddSitePage />, '/data/new-site?site_id=UVMPBPL09999&report_type=4G+Saturation&circle=MP');
    expect(await screen.findByLabelText(/Site ID/)).toHaveValue('UVMPBPL09999');
    expect(screen.getByRole('combobox', { name: /Report type/ })).toHaveTextContent('4G Saturation');
    expect(screen.getByRole('combobox', { name: /Circle/ })).toHaveTextContent('MP');
    await user.type(screen.getByLabelText(/Site name/), 'New Kheda');
    await choose(user, /^On-Air/, 'Yes');
    await choose(user, /Power/, 'N-EB');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Review site' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Review site' }));
    const review = screen.getByText('Review the new site').closest('[data-slot="card"]') as HTMLElement;
    expect(within(review).getByText('New Kheda')).toBeInTheDocument();
    expect(within(review).getByText('N-EB')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm site details' }));
    expect(screen.getByText('Site details validated locally. Master DB integration is not enabled yet.')).toBeInTheDocument();
  });
});

describe('Sidebar', () => {
  it('lists the three workflows under Data Entry, opens that group and highlights the active one', () => {
    renderWithWorkbook(<Sidebar />, { url: '/data/upload-csv' });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('button', { name: 'Data Entry' })).toHaveAttribute('aria-expanded', 'true');
    const labels = within(nav).getAllByRole('link').map((a) => a.textContent);
    expect(labels.slice(labels.indexOf('Add Row'))).toEqual(['Add Row', 'Upload CSV', 'Add Site', 'Users & Roles', 'Organization']);
    expect(within(nav).getByRole('link', { name: 'Upload CSV' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Add Row' })).not.toHaveAttribute('aria-current');
  });
});
