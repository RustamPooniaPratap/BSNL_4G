import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import { announceRcaBucketMappingUpdate } from '../../lib/rcaBucketMapping';
import * as api from './api';
import { AutoEmailReportsPage } from './AutoEmailReportsPage';
import { BsnlLettersPage } from './BsnlLettersPage';
import type { LetterDetail, LetterOverview, ReportOptions, ReportOverview, ReportPreview } from './types';

vi.mock('./api', () => ({
  fetchReportOptions: vi.fn(), fetchReportOverview: vi.fn(), fetchReportPreview: vi.fn(), downloadReportFile: vi.fn(),
  downloadAllCircleEmails: vi.fn(), sendReport: vi.fn(), fetchReportRuns: vi.fn(), saveSchedule: vi.fn(),
  fetchRecipients: vi.fn(), createRecipient: vi.fn(), updateRecipient: vi.fn(),
  fetchLetterOptions: vi.fn(), fetchLetterOverview: vi.fn(), openLetter: vi.fn(), fetchLetter: vi.fn(), saveLetterContent: vi.fn(),
  regenerateLetter: vi.fn(), approveLetter: vi.fn(), sendLetter: vi.fn(), setLetterStatus: vi.fn(), downloadLetterFile: vi.fn(),
  downloadLetterRegister: vi.fn(), fetchProfiles: vi.fn(), saveProfile: vi.fn(), fetchBucketMapping: vi.fn(), saveBucketMapping: vi.fn(),
}));
const m = vi.mocked(api);
const file = { blob: new Blob(['x']), filename: 'report.eml' };

const OPTIONS: ReportOptions = {
  projects: ['4G Saturation', 'LWE'], schedule: { daily: false, weekly: false, daily_time: '09:00 IST', weekly_time: 'Monday 10:00 IST' },
  sending_enabled: true, recipients_loaded: 4, permissions: { send: true, manage: true, all_india: true }, target_pct: 98.5, population: 'On-Air sites',
};
const kpis = { sites_reported: 5, target_pct: 98.5, outage_minutes: 600, customer_minutes: 120, outage_hours: 10, customer_hours: 2 };
const OVERVIEW: ReportOverview = {
  period: { start: '2026-11-15', end: '2026-11-15', label: '15 Nov 2026' }, latest_date: '2026-11-15', all_india: { to: [], cc: [] },
  data_status: { status: 'Complete', missing: [] },
  circles: [
    { circle: 'KL', name: 'Kerala', sites: 1, uptime_pct: 100, status: 'Meets SLA', not_meeting_sla: 0, usd_sites: 0, to: [], cc: [], complete: true, can_send: true, data_status: { status: 'Complete', missing: [] }, ...kpis },
    { circle: 'MP', name: 'Madhya Pradesh', sites: 5, uptime_pct: 97.9, status: 'Breach', not_meeting_sla: 2, usd_sites: 3, to: ['head.mp@example.com'], cc: ['noc@example.com'], complete: true, can_send: true, data_status: { status: 'Complete', missing: [] }, ...kpis },
  ],
};
const preview = (circle: string, type = 'D-1'): ReportPreview => ({
  title: `${type} 4G Site Performance – ${circle || 'All India'}`, subject: `${type} 4G Site Performance – ${circle || 'All India'} – 15 Nov 2026`,
  html: '<p>600 Outage Minutes</p>', to: circle ? ['head.mp@example.com'] : ['business@example.com'], cc: circle ? ['noc@example.com'] : [],
  period: OVERVIEW.period, kpis: { ...OVERVIEW.circles[1] }, report_type: type as 'D-1', circle, project: '',
  attachment: 'report.xlsx', sheet_count: 6, sheets: [], data_status: { status: 'Complete', missing: [] },
});

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchReportOptions.mockResolvedValue(OPTIONS);
  m.fetchReportOverview.mockResolvedValue(OVERVIEW);
  m.fetchReportPreview.mockImplementation(async (type, circle) => preview(circle, type));
  m.fetchReportRuns.mockResolvedValue({ runs: [] });
  m.fetchRecipients.mockResolvedValue({ recipients: [], can_manage: { 'D-1': true, Weekly: true, 'All India': true, 'BSNL letter': true } });
  m.downloadReportFile.mockResolvedValue(file);
  m.downloadAllCircleEmails.mockResolvedValue({ ...file, filename: 'all.zip' });
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
});

describe('Auto Email Reports', () => {
  it('shows the D-1 period, schedule, circle table and the All India preview', async () => {
    renderWithWorkbook(<AutoEmailReportsPage />, { url: '/bsnl/auto-email-reports' });
    expect(await screen.findByRole('heading', { name: 'Auto email reports – All India' })).toBeInTheDocument();
    const table = await screen.findByRole('table', { name: 'Circle distribution' });
    expect(within(table).getByText('Madhya Pradesh')).toBeInTheDocument();
    expect(within(table).getByText('No recipients')).toBeInTheDocument();
    expect(within(table).getByText('Outage Minutes')).toBeInTheDocument();
    expect(within(table).getAllByText('600')).toHaveLength(2);
    expect(within(table).getByText(/Cc: noc@example.com/)).toBeInTheDocument();
    expect(screen.getByText('Daily 09:00 IST')).toBeInTheDocument();
    expect(screen.getByText('4 rows')).toBeInTheDocument();
    const header = await screen.findByLabelText('Email header');
    expect(within(header).getByText('business@example.com')).toBeInTheDocument();
    expect(within(header).getByText('report.xlsx (6 sheets)')).toBeInTheDocument();
    expect(screen.getByTitle('Email body')).toHaveAttribute('sandbox', '');
    expect(screen.getByTitle('Email body')).toHaveAttribute('srcdoc', expect.stringContaining('600 Outage Minutes'));
  });

  it('switches to the weekly tab and previews a selected circle', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<AutoEmailReportsPage />, { url: '/bsnl/auto-email-reports' });
    await user.click(await screen.findByRole('tab', { name: 'Weekly report' }));
    expect(screen.getByRole('tab', { name: 'Weekly report' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Monday 10:00 IST')).toBeInTheDocument();
    await waitFor(() => expect(m.fetchReportOverview).toHaveBeenLastCalledWith('Weekly', '', expect.anything()));
    const table = await screen.findByRole('table', { name: 'Circle distribution' });
    await user.click(within(within(table).getByText('Madhya Pradesh').closest('tr')!).getByRole('button', { name: 'Preview' }));
    expect(await screen.findByRole('heading', { name: 'Email preview – Madhya Pradesh' })).toBeInTheDocument();
    expect(m.fetchReportPreview).toHaveBeenLastCalledWith('Weekly', 'MP', '', expect.anything());
    expect(screen.queryByRole('table', { name: 'Circle distribution' })).not.toBeInTheDocument();
    expect(await screen.findByText('head.mp@example.com')).toBeInTheDocument();
  });

  it('downloads circle, all-circle and Excel files without sending', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<AutoEmailReportsPage />, { url: '/bsnl/auto-email-reports' });
    await user.click(await screen.findByRole('button', { name: 'Download email Madhya Pradesh' }));
    expect(m.downloadReportFile).toHaveBeenCalledWith('D-1', 'MP', '', 'eml');
    await user.click(screen.getByRole('button', { name: 'Download all Circle emails' }));
    expect(m.downloadAllCircleEmails).toHaveBeenCalledWith('D-1', '');
    await user.click(await screen.findByRole('button', { name: 'Download Excel attachment' }));
    expect(m.downloadReportFile).toHaveBeenLastCalledWith('D-1', '', '', 'xlsx');
    expect(m.sendReport).not.toHaveBeenCalled();
  });

  it('asks for confirmation before sending and shows the server error', async () => {
    const user = userEvent.setup();
    m.sendReport.mockRejectedValue(new Error('SMTP account is not active.'));
    renderWithWorkbook(<AutoEmailReportsPage />, { url: '/bsnl/auto-email-reports' });
    await user.click(await screen.findByRole('button', { name: 'Send now' }));
    expect(m.sendReport).not.toHaveBeenCalled();
    const confirm = screen.getByRole('group', { name: 'Confirm: Send now' });
    expect(confirm).toHaveTextContent('business@example.com');
    await user.click(within(confirm).getByRole('button', { name: 'Send email' }));
    expect(m.sendReport).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('SMTP account is not active.')).toBeInTheDocument();
  });

  it('hides sending and schedule controls without permission and explains the All India restriction', async () => {
    m.fetchReportOptions.mockResolvedValue({ ...OPTIONS, permissions: { send: false, manage: false, all_india: false } });
    renderWithWorkbook(<AutoEmailReportsPage />, { url: '/bsnl/auto-email-reports' });
    expect(await screen.findByText(/Choose a Circle to preview its email/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send now' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Switch on daily/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download All India summary email' })).not.toBeInTheDocument();
    expect(m.fetchReportPreview).not.toHaveBeenCalled();
  });

  it('shows a loading state and then the load error', async () => {
    m.fetchReportOverview.mockRejectedValue(new Error('Uptime data is unavailable.'));
    renderWithWorkbook(<AutoEmailReportsPage />, { url: '/bsnl/auto-email-reports' });
    expect(screen.getByText('Loading circle reports…')).toBeInTheDocument();
    expect(await screen.findByText('Uptime data is unavailable.')).toBeInTheDocument();
  });
});

const LETTER_OPTIONS = { projects: ['4G Saturation'], latest_rca_date: '2026-11-11', permissions: { edit: true, approve: true, send: true, manage: true },
  statuses: [], max_period_days: 92 };
const REGISTER_ROW: LetterOverview['register'][number] = {
  id: 7, reference: 'MP/BSNL/202611/001', circle: 'MP', circle_name: 'Madhya Pradesh', project: '', period_kind: 'period',
  period_start: '2026-11-01', period_end: '2026-11-11', period_label: '1 Nov – 11 Nov 2026',
  outage_count: 2, site_count: 2, total_minutes: 150, total_hours: 2.5, status: 'Draft',
  prepared_by: 'admin', created_at: '2026-11-17T10:00:00Z', updated_at: '2026-11-17T10:00:00Z',
  approved_by: '', approved_at: null, sent_at: null, send_status: '', send_error: '',
  edited: false, recipients: { to: ['gm.mp@example.com'], cc: [] },
};
const LETTER_OVERVIEW: LetterOverview = {
  period: { kind: 'period', start: '2026-11-01', end: '2026-11-11', label: '1 Nov – 11 Nov 2026' },
  circles: [{ circle: 'MP', name: 'Madhya Pradesh', outages: 2, sites: 2, outage_minutes: 150, hours: 2.5, to: ['gm.mp@example.com'], cc: [], complete: true, letter: null }],
  register: [REGISTER_ROW],
};
const LETTER: LetterDetail = {
  id: 7, reference: 'MP/BSNL/202611/001', circle: 'MP', circle_name: 'Madhya Pradesh', project: '', period_kind: 'period',
  period_start: '2026-11-01', period_end: '2026-11-11', period_label: '1 Nov – 11 Nov 2026', outage_count: 2, site_count: 2, total_minutes: 150, total_hours: 2.5,
  status: 'Draft', prepared_by: 'admin', created_at: '2026-11-17T10:00:00Z', updated_at: '2026-11-17T10:00:00Z', approved_by: '', approved_at: null,
  sent_at: null, send_status: '', send_error: '', edited: false, recipients: { to: ['gm.mp@example.com'], cc: [] },
  html: '<p>Dear Sir / Madam,</p>', generated_html: '<p>Dear Sir / Madam,</p>', causes: [], letter_date: '2026-11-17', subject: 'Site outages',
  annexure: [{ site_id: 'UVMPS1', site_name: 'S1', circle: 'MP', project: '4G Saturation', cluster: 'CI One', ne: 'NE A', date: '2026-11-10',
    start: '2026-11-10', end: '2026-11-10', outage_minutes: 90, hours: 1.5, rca: 'Fibre cut', cause: 'SSA OFC', final_bucket: 'BSNL OFC', bucket: 'Customer', ticket: '' }],
  events: [{ action: 'generated', status_before: '', status_after: 'Draft', note: '', actor: 'admin', created_at: '2026-11-17T10:00:00Z' }],
  current_recipients: { to: ['gm.mp@example.com'], cc: [] }, permissions: { edit: true, approve: true, send: true }, transitions: ['Approved'],
  sending_enabled: false,
};

describe('BSNL Letters', () => {
  beforeEach(() => {
    m.fetchLetterOptions.mockResolvedValue(LETTER_OPTIONS);
    m.fetchLetterOverview.mockResolvedValue(LETTER_OVERVIEW);
    m.fetchProfiles.mockResolvedValue({ profiles: [], can_manage: true });
    m.fetchBucketMapping.mockResolvedValue({ mapping: [{ final_bucket: 'BSNL OFC', bucket: 'Customer' }], buckets: ['Own', 'Customer', 'Third party', 'Pending'], can_manage: true, rule: '' });
    m.openLetter.mockResolvedValue({ letter: LETTER, created: true });
    m.fetchLetter.mockResolvedValue({ letter: LETTER });
    m.downloadLetterFile.mockResolvedValue({ ...file, filename: 'letter.doc' });
  });

  it('lists circles for the default period and switches period buttons', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<BsnlLettersPage />, { url: '/bsnl/letters' });
    expect(await screen.findByText('gm.mp@example.com')).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Customer outages by circle' });
    expect(table).toHaveTextContent('Madhya Pradesh');
    expect(table).toHaveTextContent('Outage Minutes');
    expect(table).toHaveTextContent('150');
    expect(screen.queryByText('Hours')).not.toBeInTheDocument();
    expect(m.fetchLetterOverview).toHaveBeenCalledWith({ period: 'period', date_from: '2026-11-01', date_to: '2026-11-11', project: '' }, expect.anything());
    await user.click(screen.getByRole('button', { name: 'Last week' }));
    await waitFor(() => expect(m.fetchLetterOverview).toHaveBeenLastCalledWith({ period: 'week', date_from: '', date_to: '', project: '' }, expect.anything()));
    expect(screen.queryByLabelText('From')).not.toBeInTheDocument();
  });

  it('refetches the letter overview when the responsibility mapping changes', async () => {
    renderWithWorkbook(<BsnlLettersPage />, { url: '/bsnl/letters' });
    await screen.findByRole('table', { name: 'Customer outages by circle' });
    const callsBefore = m.fetchLetterOverview.mock.calls.length;

    announceRcaBucketMappingUpdate();

    await waitFor(() => expect(m.fetchLetterOverview).toHaveBeenCalledTimes(callsBefore + 1));
  });

  it('prepares a draft explicitly, edits and saves it, then approves after confirmation', async () => {
    const user = userEvent.setup();
    m.fetchLetterOverview.mockResolvedValueOnce(LETTER_OVERVIEW).mockResolvedValue({ ...LETTER_OVERVIEW,
      circles: [{ ...LETTER_OVERVIEW.circles[0], letter: { id: 7, reference: LETTER.reference, status: 'Draft' } }] });
    m.saveLetterContent.mockResolvedValue({ letter: { ...LETTER, edited: true, html: '<p>Edited</p>', updated_at: '2026-11-17T10:05:00Z' } });
    m.approveLetter.mockResolvedValue({ letter: { ...LETTER, status: 'Approved', approved_by: 'admin', approved_at: '2026-11-17T10:06:00Z', transitions: ['Sent', 'Draft'] } });
    renderWithWorkbook(<BsnlLettersPage />, { url: '/bsnl/letters' });
    await user.click(await screen.findByRole('button', { name: 'Open letter Madhya Pradesh' }));
    expect(m.openLetter).not.toHaveBeenCalled();  // selecting a circle never creates a letter
    await user.click(await screen.findByRole('button', { name: 'Prepare draft letter' }));
    expect(m.openLetter).toHaveBeenCalledWith('MP', { period: 'period', date_from: '2026-11-01', date_to: '2026-11-11', project: '' });
    const letterBox = await screen.findByRole('textbox', { name: 'Letter' });
    expect(letterBox).toHaveAttribute('contenteditable', 'true');
    const annexure = screen.getByRole('table', { name: 'Annexure' });
    expect(annexure).toHaveTextContent('Outage Minutes');
    expect(annexure).toHaveTextContent('90');
    expect(screen.queryByText('Duration h')).not.toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Save edits' });
    expect(save).toBeDisabled();
    letterBox.innerHTML = '<p>Edited</p>';
    letterBox.dispatchEvent(new Event('input', { bubbles: true }));
    await waitFor(() => expect(save).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Approve letter' })).toBeDisabled();  // save edits first
    await user.click(save);
    expect(m.saveLetterContent).toHaveBeenCalledWith(7, '<p>Edited</p>');
    expect(await screen.findByText('Letter edits saved.')).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve letter' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Approve letter' }));
    expect(m.approveLetter).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('group', { name: 'Confirm: Approve letter' })).getByRole('button', { name: 'Confirm' }));
    expect(m.approveLetter).toHaveBeenCalledWith(7);
    expect(await screen.findByText(`Letter ${LETTER.reference} approved.`)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Letter' })).toHaveAttribute('contenteditable', 'false');
    expect(screen.getByText(/Sending is disabled on this server/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download email (.eml)' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Download email (.eml)' }));
    expect(m.downloadLetterFile).toHaveBeenCalledWith(7, 'eml');
  });

  it('downloads Word and Excel and offers no editing to view-only users', async () => {
    const user = userEvent.setup();
    m.fetchLetterOptions.mockResolvedValue({ ...LETTER_OPTIONS, permissions: { edit: false, approve: false, send: false, manage: false } });
    m.fetchLetterOverview.mockResolvedValue({ ...LETTER_OVERVIEW, circles: [{ ...LETTER_OVERVIEW.circles[0], letter: { id: 7, reference: LETTER.reference, status: 'Draft' } }] });
    m.fetchLetter.mockResolvedValue({ letter: { ...LETTER, permissions: { edit: false, approve: false, send: false } } });
    renderWithWorkbook(<BsnlLettersPage />, { url: '/bsnl/letters' });
    await user.click(await screen.findByRole('button', { name: 'Open letter Madhya Pradesh' }));
    expect(await screen.findByRole('textbox', { name: 'Letter' })).toHaveAttribute('contenteditable', 'false');
    expect(screen.getByRole('table', { name: 'Letter register' })).toHaveTextContent('Outage Minutes');
    expect(screen.getByRole('table', { name: 'Letter register' })).toHaveTextContent('150');
    expect(screen.queryByRole('button', { name: 'Save edits' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve letter' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Download letter (Word)' }));
    await user.click(screen.getByRole('button', { name: 'Download annexure (Excel)' }));
    expect(m.downloadLetterFile.mock.calls.map((c) => c[1])).toEqual(['doc', 'xlsx']);
  });

  it('reports a period error from the server', async () => {
    m.fetchLetterOverview.mockRejectedValue(new Error('A letter covers at most 92 days.'));
    renderWithWorkbook(<BsnlLettersPage />, { url: '/bsnl/letters' });
    expect(await screen.findByText('A letter covers at most 92 days.')).toBeInTheDocument();
  });
});
