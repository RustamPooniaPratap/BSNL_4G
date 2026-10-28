import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { records } from '../../test/fixtures';
import { SiteTable } from './SiteTable';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRecords: vi.fn(),
}));

const fetchRecords = vi.mocked(api.fetchRecords);
const lastParams = () => fetchRecords.mock.calls[fetchRecords.mock.calls.length - 1][0];

function renderTable(onSelectSite = vi.fn()) {
  render(
    <MemoryRouter>
      <SiteTable params={new URLSearchParams({ scope: 'on_air' })} version="v1" bucket="" onBucketChange={vi.fn()} onSelectSite={onSelectSite} />
    </MemoryRouter>,
  );
  return onSelectSite;
}

beforeEach(() => {
  fetchRecords.mockReset();
  fetchRecords.mockImplementation(async (params) => records(60, Number(params.get('page')), 3));
});

describe('SiteTable', () => {
  it('requests the worst MTD uptime first and shows the match count', async () => {
    renderTable();
    expect(await screen.findByText(/60 matching sites/)).toBeInTheDocument();
    expect(lastParams().get('sort')).toBe('mtd_uptime_pct');
    expect(lastParams().get('direction')).toBe('asc');
    expect(screen.getByRole('columnheader', { name: /MTD uptime/ })).toHaveAttribute('aria-sort', 'ascending');
  });

  it('toggles sort direction and changes sort column', async () => {
    const user = userEvent.setup();
    renderTable();
    await screen.findByText(/60 matching sites/);
    await user.click(screen.getByRole('button', { name: /MTD uptime/ }));
    await waitFor(() => expect(lastParams().get('direction')).toBe('desc'));
    await user.click(screen.getByRole('button', { name: /Site ID/ }));
    await waitFor(() => expect(lastParams().get('sort')).toBe('site_id'));
    expect(lastParams().get('direction')).toBe('asc');
  });

  it('paginates and returns to page 1 when the search changes', async () => {
    const user = userEvent.setup();
    renderTable();
    await screen.findByText('Page 1 of 3');
    await user.click(screen.getByRole('button', { name: /next/i }));
    await waitFor(() => expect(lastParams().get('page')).toBe('2'));
    expect(await screen.findByText('Page 2 of 3')).toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Search sites' }), 'bhopal');
    await waitFor(() => expect(lastParams().get('search')).toBe('bhopal'));
    expect(lastParams().get('page')).toBe('1');
  });

  it('opens a site from the keyboard', async () => {
    const user = userEvent.setup();
    const onSelectSite = renderTable();
    const row = await screen.findByRole('row', { name: /UVMP001/ });
    row.focus();
    await user.keyboard('{Enter}');
    expect(onSelectSite).toHaveBeenCalledWith(expect.objectContaining({ site_id: 'UVMP001' }));
  });

  it('shows the API error message', async () => {
    fetchRecords.mockRejectedValue(new api.ApiError('Invalid request parameters.', 400));
    renderTable();
    expect(await screen.findByText('Invalid request parameters.')).toBeInTheDocument();
  });

  it('shows who is responsible for each site, linked to their team page', async () => {
    const onSelectSite = renderTable();
    const row = await screen.findByRole('row', { name: /UVMP001/ });
    const ci = within(row).getByRole('link', { name: 'CI East' });
    expect(ci).toHaveAttribute('href', '/teams?group=ci&team=CI+East&report_type=4G+Saturation&circle=MP');
    expect(within(row).getByRole('link', { name: 'IE MP' })).toHaveAttribute('href', '/teams?group=ie&team=IE+MP&report_type=4G+Saturation&circle=MP');
    await userEvent.setup().click(ci);
    expect(onSelectSite).not.toHaveBeenCalled();  // the link does not also open the site panel
  });
});
