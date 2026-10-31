import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { AlertMessage, AlertOptions } from '../../types/alerts';
import type { OrganizationCatalog } from '../../types/organization';
import { AlertAutomationsPage } from './AlertAutomationsPage';
import { AlertEmailSetupPage } from './AlertEmailSetupPage';
import { AlertHistoryPage } from './AlertHistoryPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchAlertAccount: vi.fn(), saveAlertAccount: vi.fn(), testAlertAccount: vi.fn(), activateAlertAccount: vi.fn(),
  fetchAlertOptions: vi.fn(), fetchAlertAutomations: vi.fn(), saveAlertAutomation: vi.fn(), previewAlertAutomation: vi.fn(),
  enableAlertAutomation: vi.fn(), runAlertAutomation: vi.fn(), deleteAlertAutomation: vi.fn(),
  fetchAlertHistory: vi.fn(), fetchAlertMessage: vi.fn(), retryAlertMessage: vi.fn(), resendAlertMessage: vi.fn(),
  fetchOrganizationCatalog: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });
const WORKER = { running: false, last_seen: null };
const OPTIONS: AlertOptions = {
  kinds: [
    { value: 'csv_reminder', label: 'CSV Arrival Reminder', description: 'Remind circles.', template: 'reminder', frequency: 'daily', report_day: 'yesterday' },
    { value: 'uptime_report', label: 'Automatic Uptime Report', description: 'Send reports.', template: 'report', frequency: 'daily', report_day: 'yesterday' },
  ],
  reports: [{ value: 'daily_uptime', label: 'Daily Uptime Report', formats: ['xlsx'], scoped: true, description: 'Daily.' }],
  templates: [{ value: 'reminder', label: 'Reminder / Alert', subject: 'Action Required – {{circle_name}}', message: '{{notification_message}}' },
    { value: 'report', label: 'Report distribution', subject: '{{report_name}} – {{report_period}}', message: 'Attached.' }],
  placeholders: ['circle_name', 'report_name'], users: [{ id: 7, username: 'ops', name: 'Ops Lead', email: 'ops@example.com', role: 'admin' }],
  timezone: 'Asia/Kolkata', max_file_bytes: 10485760, file_types: ['.pdf', '.xlsx'], account_active: true, worker: WORKER,
};
const MESSAGE: AlertMessage = {
  id: 5, created_at: '2026-10-30T09:00:00+05:30', sent_at: null, automation: 'Daily report', automation_id: 1, trigger: 'schedule', execution: 3,
  to: ['ops@example.com'], cc: [], bcc: [], subject: 'Daily Uptime Report – 29 Oct 2026', attachments: [{ name: 'daily.xlsx', format: 'xlsx', period: '29 Oct 2026' }],
  status: 'failed', status_label: 'Failed', attempts: 3, error: 'SMTPAuthenticationError 535: denied', smtp_response: '', resend_of: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchAlertOptions.mockResolvedValue(OPTIONS);
  m.fetchAlertAutomations.mockResolvedValue({ automations: [] });
  m.fetchOrganizationCatalog.mockResolvedValue({ projects: [{ key: '4G Saturation', name: '4G Saturation', code: '4G', is_active: true }],
    circles: [], associations: [{ project: '4G Saturation', circle: 'MP', is_active: true }] } as unknown as OrganizationCatalog);
});

describe('Alert › Email Setup', () => {
  it('never shows the stored password and sends a blank password to keep it', async () => {
    const user = userEvent.setup();
    const account = { id: 1, name: 'Portal', host: 'smtp.example.com', port: 587, security: 'starttls', auth: 'password', username: 'svc', password_set: true,
      from_email: 'portal@example.com', from_name: 'Portal', reply_to: '', timeout: 20, is_active: false, tested_ok_at: null, last_test: '', updated_at: 'x' } as const;
    m.fetchAlertAccount.mockResolvedValue({ account, worker: WORKER });
    m.saveAlertAccount.mockResolvedValue({ account, worker: WORKER });
    renderWithWorkbook(<AlertEmailSetupPage />, { url: '/admin/alerts/email' });
    const password = await screen.findByLabelText(/Password/);
    expect(password).toHaveValue('');
    expect(screen.getByText(/Leave blank to keep it/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Activate/ })).toBeDisabled();  // not tested yet
    expect(screen.getByText(/alert worker is not running/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Save Configuration/ }));
    await waitFor(() => expect(m.saveAlertAccount).toHaveBeenCalledWith(expect.objectContaining({ host: 'smtp.example.com', password: '' })));
  });
});

describe('Alert › Automations', () => {
  it('configures a report in six steps, previews the real email and saves it', async () => {
    const user = userEvent.setup();
    m.previewAlertAutomation.mockResolvedValue({ subject: 'Daily Uptime Report – 29 Oct 2026', text: '', html: '<p>Preview</p>',
      attachments: [{ name: 'Daily Uptime Report', format: 'xlsx', period: '29 Oct 2026' }], next_run_at: '2026-11-01T09:00:00+05:30' });
    m.saveAlertAutomation.mockResolvedValue({ automation: { id: 9, enabled: false } as never });
    renderWithWorkbook(<AlertAutomationsPage />, { url: '/admin/alerts/automations' });
    const templates = await screen.findByRole('region', { name: 'Templates' });
    await user.click(within(templates).getAllByRole('button', { name: /Configure/ })[1]);
    const steps = await screen.findByRole('list', { name: 'Steps' });
    expect(within(steps).getAllByRole('button').map((b) => b.textContent)).toEqual(['1. Schedule', '2. Scope', '3. Recipients', '4. Attachments', '5. Message', '6. Review']);
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByLabelText(/Ops Lead/));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByLabelText('Daily Uptime Report'));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByTitle('Email preview')).toBeInTheDocument();
    expect(m.previewAlertAutomation).toHaveBeenCalledWith(expect.objectContaining({ kind: 'uptime_report', to_users: [7], attachments: [{ report: 'daily_uptime', format: 'xlsx' }] }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(m.saveAlertAutomation).toHaveBeenCalledWith(null, expect.objectContaining({ kind: 'uptime_report' })));
    expect(m.enableAlertAutomation).not.toHaveBeenCalled();
  });
});

describe('Alert › Email History', () => {
  it('lists emails with their SMTP status and retries a failed one', async () => {
    const user = userEvent.setup();
    m.fetchAlertHistory.mockResolvedValue({ total: 1, page: 1, pages: 1, messages: [MESSAGE], queued_runs: 0, worker: WORKER, runs_without_email: [] });
    m.fetchAlertMessage.mockResolvedValue({ message: { ...MESSAGE, html: '<p>x</p>', attempt_log: [{ at: MESSAGE.created_at, ok: false, detail: 'denied', by: 'worker' }], resends: [] } });
    m.retryAlertMessage.mockResolvedValue({ message: { ...MESSAGE, status: 'accepted', status_label: 'Accepted by SMTP' } });
    renderWithWorkbook(<AlertHistoryPage />, { url: '/admin/alerts/history' });
    await user.click(await screen.findByRole('button', { name: MESSAGE.subject }));
    expect(await screen.findByText(/SMTPAuthenticationError/)).toBeInTheDocument();
    expect(screen.getByText(/delivery to the mailbox is not reported/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Retry/ }));
    await waitFor(() => expect(m.retryAlertMessage).toHaveBeenCalledWith(5));
  });
});
