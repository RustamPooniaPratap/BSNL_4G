import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { filterOptions, records, site, teams } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import { TeamsPage } from './TeamsPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchTeams: vi.fn(),
  fetchRecords: vi.fn(),
}));

const fetchTeams = vi.mocked(api.fetchTeams);
const fetchRecords = vi.mocked(api.fetchRecords);
const lastRecordsQuery = () => fetchRecords.mock.calls.at(-1)![0] as URLSearchParams;

beforeEach(() => {
  vi.mocked(api.fetchFilterOptions).mockResolvedValue(filterOptions);
  fetchTeams.mockReset().mockResolvedValue(teams);
  fetchRecords.mockReset().mockResolvedValue({
    ...records(1),
    records: [site('UVMP003', { mtd_uptime_pct: 0, bucket: 'lt_60', ie_name: 'IE MP', ci_name: 'CI East' })],
  });
  Element.prototype.scrollIntoView = vi.fn();
});

describe('TeamsPage', () => {
  it('summarises teams and lists sites below 60% with who is responsible', async () => {
    renderWithWorkbook(<TeamsPage />, { url: '/teams' });
    expect(await screen.findByText('CIs with sites below 60%')).toBeInTheDocument();
    expect(screen.getByText('Sites below 60% MTD and who is responsible')).toBeInTheDocument();
    expect(lastRecordsQuery().get('bucket')).toBe('lt_60');

    const row = (await screen.findByText('UVMP003')).closest('tr') as HTMLElement;
    expect(within(row).getByRole('link', { name: 'CI East' })).toHaveAttribute('href', '/teams?group=ci&team=CI+East&report_type=4G+Saturation&circle=MP');
    expect(within(row).getByRole('link', { name: 'IE MP' })).toHaveAttribute('href', '/teams?group=ie&team=IE+MP&report_type=4G+Saturation&circle=MP');
  });

  it('ranks teams lowest MTD first and filters sites by the selected team', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TeamsPage />, { url: '/teams' });
    const ranking = (await screen.findByText('CI ranking')).closest('[data-slot="card"]') as HTMLElement;
    await within(ranking).findByText('CI West');  // the card title shows before the data arrives
    const rows = within(ranking).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('CI East');
    expect(rows[0]).toHaveTextContent('1 IE');
    expect(rows[1]).toHaveTextContent('CI West');

    await user.click(rows[1]);
    await waitFor(() => expect(lastRecordsQuery().get('ci_name')).toBe('CI West'));
    expect(screen.getByText('Sites of CI CI West')).toBeInTheDocument();
  });

  it('switches to IEs and requests IE grouping', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TeamsPage />, { url: '/teams' });
    await screen.findByText('CI ranking');
    await user.click(screen.getByRole('button', { name: 'By IE' }));
    await waitFor(() => expect((fetchTeams.mock.calls.at(-1)![0] as URLSearchParams).get('group')).toBe('ie'));
  });

  it('opens a specific team from a link', async () => {
    renderWithWorkbook(<TeamsPage />, { url: '/teams?group=ie&team=IE+MP&circle=MP' });
    expect(await screen.findByText('Sites of IE IE MP')).toBeInTheDocument();
    await waitFor(() => expect(lastRecordsQuery().get('ie_name')).toBe('IE MP'));
  });
});
