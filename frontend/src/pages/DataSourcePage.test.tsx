import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { sourceStatus } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import { DataSourcePage } from './DataSourcePage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchSourceStatus: vi.fn(),
}));

const fetchSourceStatus = vi.mocked(api.fetchSourceStatus);

beforeEach(() => { fetchSourceStatus.mockClear(); });

describe('DataSourcePage calculation check', () => {
  it('lists major differences between the workbook and the dashboard', async () => {
    fetchSourceStatus.mockResolvedValue(sourceStatus);
    renderWithWorkbook(<DataSourcePage />, { url: '/data-source#calculation-check' });

    const card = (await screen.findByText('Calculation check')).closest('#calculation-check') as HTMLElement;
    expect(within(card).getByText('2 major differences')).toBeInTheDocument();
    const row = within(card).getByText('Summ!E5').closest('tr') as HTMLElement;
    expect(within(row).getByText('All circles · 4G On-Air MTD uptime')).toBeInTheDocument();
    expect(within(row).getByText('99.00%')).toBeInTheDocument();
    expect(within(row).getByText('87.22%')).toBeInTheDocument();
    expect(within(row).getByText('-11.78 pts')).toBeInTheDocument();
    expect(within(row).getByText('=1-BL5/(1440*D5*14)')).toBeInTheDocument();
    expect(within(within(card).getByText('Summ!D4').closest('tr') as HTMLElement).getByText('-1')).toBeInTheDocument();
  });

  it('confirms when every figure matches', async () => {
    fetchSourceStatus.mockResolvedValue({
      ...sourceStatus,
      calculation_check: { ...sourceStatus.calculation_check, difference_count: 0, differences: [] },
    });
    renderWithWorkbook(<DataSourcePage />);
    expect(await screen.findByText('All match')).toBeInTheDocument();
    expect(screen.getByText(/12 current-month figures in Day wise Trend and Summ were recalculated/)).toBeInTheDocument();
  });
});
