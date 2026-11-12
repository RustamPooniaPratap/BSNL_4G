import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { filterOptions } from '../../test/fixtures';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { RawUploadOptions } from '../../types/rawUpload';
import { ReportDownloadCard } from './ReportDownload';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchFilterOptions: vi.fn(),
  downloadReport: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });

const OPTIONS: RawUploadOptions = {
  projects: [
    { value: '4G Saturation', configured: true, availability_column: 'Nw Avail (4G TCS)', circles: ['MP', 'RJ'] },
    { value: 'LWE', configured: false, availability_column: 'Nw Avail (4G TCS)', circles: ['BH', 'MP'] },
  ],
  assigned_circles: null, max_bytes: 1, formula: '',
};
const FILTERS = {
  ...filterOptions,
  reporting_dates: ['2026-10-01', '2026-10-02', '2026-10-03'],
  default_date: '2026-10-03',
  daily_history: [{ key: '2026-09', label: 'Sep-26', dates: ['2026-09-29', '2026-09-30'] }],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchFilterOptions.mockResolvedValue(FILTERS);
  m.downloadReport.mockResolvedValue({ blob: new Blob(['x']), filename: 'Daily_Uptime_LWE_MP_2026-09-30.xlsx' });
  URL.createObjectURL = vi.fn(() => 'blob:report');
  URL.revokeObjectURL = vi.fn();
});

const circleOptions = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('combobox', { name: /Circle/ }));
  const names = screen.getAllByRole('option').map((o) => o.textContent);
  await user.keyboard('{Escape}');
  return names;
};

describe('Report download', () => {
  it('requires one reporting date for the daily report and sends the chosen project, circle and date', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<ReportDownloadCard options={OPTIONS} />);
    expect(await screen.findByRole('radio', { name: 'Daily Uptime Report' })).toHaveAttribute('aria-checked', 'true');
    const download = screen.getByRole('button', { name: /Download/ });
    expect(download).toBeDisabled();  // no date chosen yet
    await user.click(screen.getByRole('combobox', { name: /Project/ }));
    await user.click(await screen.findByRole('option', { name: 'LWE' }));
    expect(await circleOptions(user)).toEqual(['All Circles', 'BH', 'MP']);  // only that project's circles
    await user.click(screen.getByRole('combobox', { name: /Circle/ }));
    await user.click(await screen.findByRole('option', { name: 'MP' }));
    await user.type(screen.getByLabelText('Report date'), '2026-09-30');  // an earlier month's daily values
    await user.click(download);
    expect(m.downloadReport).toHaveBeenCalledWith('daily', { report_type: 'LWE', circle: 'MP', date: '2026-09-30' }, 'on_air');
    expect(await screen.findByText('Downloaded Daily_Uptime_LWE_MP_2026-09-30.xlsx.')).toBeInTheDocument();
  });

  it('downloads the full consolidated report for the month to the latest date by default, across all projects', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<ReportDownloadCard options={OPTIONS} />);
    await user.click(await screen.findByRole('radio', { name: 'Full Consolidated Report' }));
    expect(screen.getByLabelText('Month to date, up to')).toHaveValue('2026-10-03');
    expect(await circleOptions(user)).toEqual(['All Circles', 'BH', 'MP', 'RJ']);  // every permitted circle, once
    await user.click(screen.getByRole('button', { name: /Download/ }));
    expect(m.downloadReport).toHaveBeenCalledWith('consolidated', { report_type: '', circle: '', reporting_date: '2026-10-03' }, 'on_air');
  });

  it('refuses dates without data and shows the server error instead of a download', async () => {
    m.downloadReport.mockRejectedValue(new api.ApiError('No LWE sites in RJ in the selected data source.', 404));
    const user = userEvent.setup();
    renderWithWorkbook(<ReportDownloadCard options={OPTIONS} />);
    const date = await screen.findByLabelText('Report date');
    await user.type(date, '2026-10-20');
    expect(screen.getByText(/no daily values for 20 Oct 2026/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download/ })).toBeDisabled();
    await user.clear(date);
    await user.type(date, '2026-10-02');
    await user.click(screen.getByRole('button', { name: /Download/ }));
    expect(await screen.findByText('The report could not be prepared')).toBeInTheDocument();
    expect(screen.getByText('No LWE sites in RJ in the selected data source.')).toBeInTheDocument();
    expect(screen.queryByText(/^Downloaded/)).not.toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('offers nothing to a user without circles', async () => {
    renderWithWorkbook(<ReportDownloadCard options={{ ...OPTIONS, assigned_circles: [] }} />);
    expect(await screen.findByRole('button', { name: /Download/ })).toBeDisabled();
  });
});
