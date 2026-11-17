import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { TicketDashboardResponse, TicketListItem, TicketPage } from '../../types/tickets';
import { TicketDashboardPage } from './TicketDashboardPage';
import { TicketListPage } from './TicketListPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchTicketOptions: vi.fn(),
  fetchTicketDashboard: vi.fn(),
  fetchTickets: vi.fn(),
  closeTicket: vi.fn(),
}));

const m = vi.mocked(api);
const DASHBOARD: TicketDashboardResponse = {
  kpis: { total: 12, open: 9, closed: 3, created_today: 2, notifications_accepted: 10, notifications_failed: 1 },
  status: [], circles: [{ circle: 'MP', count: 12 }], vendors: [], buckets: [], monthly: [],
};
const ticket = (id: number, status: 'Open' | 'Closed', canClose: boolean): TicketListItem => ({
  id, portal_ticket_id: `OFC-2026-${String(id).padStart(5, '0')}`, outage_date: '2026-11-04', circle: 'MP',
  site_id: `MP-S-${id}`, site_name: `Site ${id}`, vendor_name: 'Vendor A', outage_minutes: '150', status,
  email_id: 'tech@example.com', created_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z', can_close: canClose,
});
const pageOf = (tickets: TicketListItem[], total = tickets.length, pageNo = 1, pages = 1): TicketPage => ({
  total, page: pageNo, page_size: 25, pages, tickets,
});
const lastParams = () => m.fetchTickets.mock.calls.at(-1)![0];

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchTicketOptions.mockResolvedValue({ circles: ['KL', 'MP'], vendors: ['Vendor A', 'Vendor B'], statuses: ['Open', 'Closed'], can_upload: true, max_upload_bytes: 1 });
  m.fetchTicketDashboard.mockResolvedValue(DASHBOARD);
  m.fetchTickets.mockImplementation(async (params: URLSearchParams) => {
    const status = params.get('status');
    if (status === 'Closed') return pageOf([ticket(3, 'Closed', false)], 3);
    if (status === 'All') return pageOf([ticket(1, 'Open', true), ticket(3, 'Closed', false)], 12);
    return pageOf([ticket(1, 'Open', true), ticket(2, 'Open', false)], 9, Number(params.get('page') ?? 1), 2);
  });
  m.closeTicket.mockResolvedValue({ ticket: {} as never });
});

describe('Ticket dashboard', () => {
  it('shows Open tickets by default with the filtered count and overall KPI cards', async () => {
    renderWithWorkbook(<TicketDashboardPage />, { url: '/tickets' });
    expect(await screen.findByText('OFC-2026-00001')).toBeInTheDocument();
    const pageHeading = screen.getByRole('heading', { name: 'Ticket Management' });
    expect(pageHeading).toBeInTheDocument();
    expect(within(pageHeading.closest('header')!).getByRole('link', { name: 'Upload Excel' })).toHaveAttribute('href', '/tickets/upload');
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('Open');
    expect(lastParams().get('status')).toBe('Open');
    expect(screen.getByTestId('ticket-count')).toHaveTextContent('9 open tickets');
    expect(screen.getByTestId('kpi-Total Tickets')).toHaveTextContent('12');
    expect(screen.getByTestId('kpi-Open Tickets')).toHaveTextContent('9');
    expect(screen.getByTestId('kpi-Closed Tickets')).toHaveTextContent('3');
    expect(screen.getByTestId('kpi-Emails Sent')).toHaveTextContent('10');
    expect(screen.getByTestId('kpi-Emails Failed')).toHaveTextContent('1');
    expect(within(screen.getByRole('table', { name: 'Ticket register' })).getAllByText('Open')[0]).toHaveClass('bg-amber-50');
    expect(m.fetchTicketDashboard.mock.calls[0][0].toString()).toBe('');
  });

  it('refreshes dashboard and ticket data without changing filters', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TicketDashboardPage />, { url: '/tickets' });
    await screen.findByText('OFC-2026-00001');
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => {
      expect(m.fetchTicketDashboard).toHaveBeenCalledTimes(2);
      expect(m.fetchTickets).toHaveBeenCalledTimes(2);
    });
    expect(lastParams().get('status')).toBe('Open');
  });

  it('switches to Closed and All Tickets without changing the KPI cards', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TicketDashboardPage />, { url: '/tickets' });
    await screen.findByText('OFC-2026-00001');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'Closed');
    expect(await screen.findByText('OFC-2026-00003')).toBeInTheDocument();
    expect(screen.queryByText('OFC-2026-00001')).not.toBeInTheDocument();
    expect(screen.getByTestId('ticket-count')).toHaveTextContent('3 closed tickets');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'All Tickets');
    expect(await screen.findByText('OFC-2026-00001')).toBeInTheDocument();
    expect(lastParams().get('status')).toBe('All');
    expect(screen.getByTestId('ticket-count')).toHaveTextContent('12 tickets');

    expect(m.fetchTicketDashboard).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('kpi-Open Tickets')).toHaveTextContent('9');
    expect(screen.getByTestId('kpi-Total Tickets')).toHaveTextContent('12');
  });

  it('sends search, circle, vendor, dates and status together and resets to the first page', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TicketDashboardPage />, { url: '/tickets' });
    await screen.findByText('OFC-2026-00001');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(lastParams().get('page')).toBe('2'));

    await user.type(screen.getByRole('textbox', { name: 'Search' }), 'MP-S');
    expect(lastParams().get('page')).toBe('1');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Circle' }), 'MP');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Vendor' }), 'Vendor A');
    await user.type(screen.getByLabelText('From date'), '2026-11-01');
    await user.type(screen.getByLabelText('To date'), '2026-11-30');
    await waitFor(() => {
      const params = lastParams();
      expect(Object.fromEntries(params)).toEqual({
        q: 'MP-S', status: 'Open', circle: 'MP', vendor_name: 'Vendor A', date_from: '2026-11-01', date_to: '2026-11-30', page: '1', page_size: '25',
      });
    });
  });

  it('offers Close only where the user may close and records closure remarks', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TicketDashboardPage />, { url: '/tickets' });
    await screen.findByText('OFC-2026-00001');
    expect(screen.getByRole('button', { name: 'Close OFC-2026-00001' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close OFC-2026-00002' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View OFC-2026-00002' })).toHaveAttribute('href', '/tickets/2');

    await user.click(screen.getByRole('button', { name: 'Close OFC-2026-00001' }));
    const sheet = await screen.findByRole('dialog');
    const confirm = within(sheet).getByRole('button', { name: 'Confirm Close' });
    expect(confirm).toBeDisabled();
    await user.type(within(sheet).getByLabelText('Resolution / closure remarks'), '  Splice repaired.  ');
    await user.click(confirm);

    expect(m.closeTicket).toHaveBeenCalledWith(1, 'Splice repaired.');
    expect(await screen.findByText('Ticket OFC-2026-00001 was closed.')).toBeInTheDocument();
    await waitFor(() => expect(m.fetchTicketDashboard).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the remarks panel open with the reason when closing fails', async () => {
    const user = userEvent.setup();
    m.closeTicket.mockRejectedValueOnce(new Error('You do not have permission to close this ticket.'));
    renderWithWorkbook(<TicketDashboardPage />, { url: '/tickets' });
    await user.click(await screen.findByRole('button', { name: 'Close OFC-2026-00001' }));
    const sheet = await screen.findByRole('dialog');
    await user.type(within(sheet).getByLabelText('Resolution / closure remarks'), 'Done');
    await user.click(within(sheet).getByRole('button', { name: 'Confirm Close' }));
    expect(await within(sheet).findByRole('alert')).toHaveTextContent('You do not have permission to close this ticket.');
    expect(m.fetchTicketDashboard).toHaveBeenCalledTimes(1);
  });
});

describe('All Tickets page', () => {
  it('still lists every status by default', async () => {
    renderWithWorkbook(<TicketListPage />, { url: '/tickets/all' });
    expect(await screen.findByText('OFC-2026-00003')).toBeInTheDocument();
    expect(lastParams().get('status')).toBe('All');
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('All');
  });
});
