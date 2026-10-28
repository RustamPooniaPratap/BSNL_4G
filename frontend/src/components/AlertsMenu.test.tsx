import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { source } from '../test/fixtures';
import { renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import type { AlertsResponse } from '../types';
import { AlertsMenu } from './AlertsMenu';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchAlerts: vi.fn(),
}));
const fetchAlerts = vi.mocked(api.fetchAlerts);

const response: AlertsResponse = {
  alerts: [
    { id: 'sites_below_60', severity: 'critical', title: '197 On-Air sites below 60% uptime this month', detail: '3.1% of On-Air sites.', link: '/?bucket=lt_60' },
    { id: 'stale_data', severity: 'warning', title: 'Latest data is from 14 Oct (8 days ago)', detail: 'Upload the newest workbook.', link: '/workbook' },
    { id: 'data_outage_out_of_range', severity: 'warning', title: '2 daily outage values outside 0–1,440 minutes', detail: 'Pending a business rule.', link: '/data-source' },
    { id: 'lowest_circle', severity: 'info', title: 'Lowest MTD uptime: OD · LWE (87.50%)', detail: '256 sites.', link: '/?report_type=LWE&circle=OD' },
  ],
  counts: { critical: 1, warning: 2, info: 1 },
  source,
};

beforeEach(() => {
  fetchAlerts.mockClear();
  fetchAlerts.mockResolvedValue(response);
});

describe('AlertsMenu', () => {
  it('shows the number of critical and warning alerts on the bell', async () => {
    renderWithWorkbook(<AlertsMenu />);
    expect(await screen.findByRole('button', { name: 'Alerts: 3 need attention' })).toBeInTheDocument();
  });

  it('lists every alert grouped by priority, matching the bell count', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<AlertsMenu />);
    await user.click(await screen.findByRole('button', { name: /alerts: 3/i }));
    const groups = await screen.findAllByRole('region');
    expect(groups.map((g) => g.getAttribute('aria-label'))).toEqual(['Critical alerts', 'Warning alerts', 'Information alerts']);
    const [critical, warning, info] = groups;
    expect(within(critical).getByRole('heading')).toHaveTextContent('Critical (1)');
    expect(within(critical).getByRole('link')).toHaveAttribute('href', '/?bucket=lt_60');
    const warnings = within(warning).getAllByRole('link');
    expect(warnings).toHaveLength(2);  // every alert counted on the bell is listed
    expect(warnings[0]).toHaveTextContent('Latest data is from 14 Oct');
    expect(within(info).getByRole('link')).toHaveTextContent('Lowest MTD uptime');
    expect(screen.getByText('3 need attention · 4 total')).toBeInTheDocument();
  });

  it('orders alerts by priority even if the API does not', async () => {
    const user = userEvent.setup();
    fetchAlerts.mockResolvedValue({ ...response, alerts: [...response.alerts].reverse() });
    renderWithWorkbook(<AlertsMenu />);
    await user.click(await screen.findByRole('button', { name: /alerts: 3/i }));
    const links = await screen.findAllByRole('link');
    expect(links[0]).toHaveTextContent('197 On-Air sites below 60%');
    expect(links[3]).toHaveTextContent('Lowest MTD uptime');
  });

  it('refetches when a new workbook becomes active', async () => {
    const view = renderWithWorkbook(<AlertsMenu />);
    await screen.findByRole('button', { name: /alerts: 3/i });
    view.unmount();
    renderWithWorkbook(<AlertsMenu />, { workbook: workbookValue({ version: 'v2' }) });
    await screen.findByRole('button', { name: /alerts: 3/i });
    expect(fetchAlerts).toHaveBeenCalledTimes(2);
  });

  it('asks for an upload when no workbook is loaded', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<AlertsMenu />, { workbook: workbookValue({ active: null, version: 'none' }) });
    await user.click(screen.getByRole('button', { name: 'Alerts: no workbook loaded' }));
    expect(await screen.findByRole('link', { name: 'Upload workbook' })).toHaveAttribute('href', '/workbook');
    expect(fetchAlerts).not.toHaveBeenCalled();
  });
});
