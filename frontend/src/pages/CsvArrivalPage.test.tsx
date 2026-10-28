import { fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TrackingProvider } from '../context/TrackingProvider';
import * as api from '../services/api';
import { filterOptions } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import { CsvArrivalPage } from './CsvArrivalPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchFilterOptions: vi.fn(),
  fetchRawFiles: vi.fn(),
  uploadDataFile: vi.fn(),
  fetchEmailStatus: vi.fn(),
  fetchReminderTemplate: vi.fn(),
  sendReminder: vi.fn(),
  sendPersonalEmail: vi.fn(),
}));
vi.setConfig({ testTimeout: 20000 });

const NOW = new Date('2026-10-17T12:00:00');  // the page's default reporting date is "today", 17 Oct
const TEST_MODE = { test_mode: true, transport: 'console', from_email: 'bsnl-reporting@localhost', automatic_reminders: false };
const printed = (kind: 'reminder' | 'personal', to: string, subject: string) => ({
  status: 'printed' as const, test_mode: true, kind, to: to.split(',').map((a) => a.trim()), cc: [], subject,
  message: 'TEST MODE: the email was printed in the backend terminal. It was not delivered to anyone.',
});
let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  vi.mocked(api.fetchFilterOptions).mockResolvedValue(filterOptions);
  vi.mocked(api.fetchRawFiles).mockResolvedValue({ count: 1, files: [{ name: 'MP_LWE_17-10-2026.csv', size_bytes: 120, modified_at: '2026-10-17T09:00:00', extension: '.csv' }] });
  vi.mocked(api.fetchEmailStatus).mockResolvedValue(TEST_MODE);
  vi.mocked(api.fetchReminderTemplate).mockReset().mockResolvedValue({ ...TEST_MODE, subject: 'Reminder: LWE uptime CSV for MP, 17 Oct 2026', body: 'Standard reminder body' });
  vi.mocked(api.sendReminder).mockReset().mockImplementation(async (r) => printed('reminder', r.to, 'Reminder: LWE uptime CSV for MP, 17 Oct 2026'));
  vi.mocked(api.sendPersonalEmail).mockReset().mockImplementation(async (m) => printed('personal', m.to, m.subject));
  fetchSpy = vi.spyOn(globalThis, 'fetch');
});
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();  // reads go through the mocked API; nothing is written anywhere
  expect(api.uploadDataFile).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

const renderPage = () => renderWithWorkbook(<TrackingProvider><CsvArrivalPage now={NOW} /></TrackingProvider>, { url: '/daily-ingestion' });
const card = (label: string) => screen.getByRole('button', { name: new RegExp(`^${label}`) });
const row = (name: string) => screen.getByRole('row', { name: new RegExp(`^${name}: open details`) });
const statuses = () => screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[2].textContent);

async function pick(user: ReturnType<typeof userEvent.setup>, label: RegExp, option: string) {
  await user.click(await screen.findByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: option }));
}

async function recordArrival(user: ReturnType<typeof userEvent.setup>, name: string, file = 'MP_LWE_17-10-2026.csv') {
  await user.click(within(row(name)).getByRole('button', { name: 'Record arrival' }));
  await user.click(await screen.findByRole('button', { name: /It arrived just now/ }));
  if (file) fireEvent.change(screen.getByLabelText(/CSV file name/), { target: { value: file } });
  await user.click(screen.getByRole('button', { name: 'Record arrival' }));
}

describe('CSV Arrival & Follow-up', () => {
  it('starts with every circle pending and nothing invented', async () => {
    renderPage();
    expect(await screen.findByText('CSV Arrival & Follow-up')).toBeInTheDocument();
    expect(screen.getByText(/Changes are currently held in the frontend; persistent storage is not enabled/)).toBeInTheDocument();
    expect(within(card('Reporting circles')).getByText('4')).toBeInTheDocument();
    expect(within(card('CSVs pending')).getByText('4')).toBeInTheDocument();
    expect(within(card('CSVs received')).getByText('0')).toBeInTheDocument();
    expect(within(card('Missing contact details')).getByText('4')).toBeInTheDocument();
    expect(statuses()).toEqual(['Pending', 'Pending', 'Pending', 'Pending']);
    expect(screen.getAllByText('Not added')).toHaveLength(4);
    expect(screen.getAllByText('Not configured')).toHaveLength(4);
    // The highlight cards (pending, late, recently received, missing contacts, timeline) were removed.
    for (const removed of ['Pending circles', 'Recently received', 'Missing contacts', 'Submission timeline']) {
      expect(screen.queryByRole('region', { name: removed })).not.toBeInTheDocument();
    }
    // 4G and LWE stay separate rows for MP.
    expect(row('MP 4G')).toBeInTheDocument();
    expect(row('MP LWE')).toBeInTheDocument();
  });

  it('records an arrival with the time of entry labelled as such', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(within(row('MP LWE')).getByRole('button', { name: 'Record arrival' }));
    expect(await screen.findByRole('combobox', { name: /Circle \/ State/ })).toHaveTextContent('MP');  // prefilled from the row
    expect(screen.getByRole('combobox', { name: /Report type/ })).toHaveTextContent('LWE');
    await user.click(screen.getByRole('button', { name: 'Record arrival' }));
    expect(screen.getByText('Enter the date the CSV arrived.')).toBeInTheDocument();  // required
    await user.click(screen.getByRole('button', { name: /It arrived just now/ }));
    await user.type(screen.getByLabelText(/CSV file name/), 'MP_LWE_17-10-2026.csv');
    await user.click(screen.getByRole('button', { name: 'Record arrival' }));

    expect(await screen.findByText('Arrival recorded for MP · LWE (17 Oct 2026).')).toBeInTheDocument();
    expect(within(row('MP LWE')).getByText('Received')).toBeInTheDocument();
    expect(within(row('MP LWE')).getByText('time of entry')).toBeInTheDocument();
    expect(within(card('CSVs received')).getByText('1')).toBeInTheDocument();
    expect(within(card('Received today')).getByText('1')).toBeInTheDocument();
    expect(within(row('MP 4G')).getByText('Pending')).toBeInTheDocument();  // the 4G CSV is separate
  });

  it('refuses a second arrival for the same circle, report type and date', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await recordArrival(user, 'MP LWE');
    await user.click(screen.getAllByRole('button', { name: /Record arrival/ })[0]);  // header button
    await pick(user, /Report type/, 'LWE');
    await pick(user, /Circle \/ State/, 'MP');
    expect(screen.getByText(/An arrival is already recorded for MP · LWE on this date/)).toBeInTheDocument();
  });

  it('flags an arrival without a file name as Needs review', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await recordArrival(user, 'BH LWE', '');
    expect(await within(row('BH LWE')).findByText('Needs review')).toBeInTheDocument();
    await user.click(row('BH LWE'));
    expect(await screen.findByText('File name is not recorded.')).toBeInTheDocument();
  });

  it('marks submissions late only after a configured deadline passes', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(screen.getByRole('button', { name: /Deadlines/ }));
    const lwe = (await screen.findByText('LWE', { selector: 'legend' })).closest('fieldset') as HTMLElement;
    await user.click(within(lwe).getByRole('checkbox', { name: 'Deadline configured' }));  // next day, 10:00
    await user.click(screen.getByRole('button', { name: 'Save deadlines' }));
    // For 17 Oct the LWE CSV is due 18 Oct 10:00, which has not passed.
    expect(within(card('Late submissions')).getByText('0')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Reporting date'), { target: { value: '2026-10-15' } });
    // For 15 Oct it was due 16 Oct 10:00: LWE is late, 4G (no deadline) is still pending.
    expect(within(row('BH LWE')).getByText('Late')).toBeInTheDocument();
    expect(within(row('MP 4G')).getByText('Pending')).toBeInTheDocument();
    expect(within(card('Late submissions')).getByText('2')).toBeInTheDocument();
  });

  it('adds contact details later without changing the arrival status', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(within(row('RJ 4G')).getByRole('button', { name: 'Edit contact for RJ 4G' }));
    await user.type(await screen.findByLabelText(/Contact person/), 'Asha Rao');
    await user.type(screen.getByLabelText(/Phone number/), '12');
    await user.click(screen.getByRole('button', { name: 'Save contact' }));
    expect(screen.getByText(/Enter 10 to 15 digits/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/Phone number/));
    await user.type(screen.getByLabelText(/Phone number/), '+91 98765 43210');
    await user.click(screen.getByRole('button', { name: 'Save contact' }));
    expect(within(row('RJ 4G')).getByText('Asha Rao')).toBeInTheDocument();
    expect(within(row('RJ 4G')).getByText('Pending')).toBeInTheDocument();
    expect(within(card('Missing contact details')).getByText('3')).toBeInTheDocument();
  });

  it('records a follow-up without a contact and shows it in the history', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(within(row('BH LWE')).getByRole('button', { name: 'Add follow-up for BH LWE' }));
    await pick(user, /Method/, 'Message');
    await user.type(screen.getByLabelText(/Outcome/), 'Asked on the circle group; promised by 2 pm');
    await user.click(screen.getByRole('button', { name: 'Add follow-up' }));
    expect(within(row('BH LWE')).getByText('Asked on the circle group; promised by 2 pm')).toBeInTheDocument();
    await user.click(row('BH LWE'));
    const history = await screen.findByRole('region', { name: 'Follow-up history' });
    expect(within(history).getByText(/Message/)).toBeInTheDocument();
  });

  it('combines cards, filters, search and sorting', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await recordArrival(user, 'MP LWE');
    await user.click(card('CSVs received'));
    expect(screen.getAllByRole('row')).toHaveLength(2);
    await user.click(card('CSVs received'));  // select again to clear
    await pick(user, /^Project/, 'LWE');
    expect(statuses()).toEqual(['Pending', 'Received']);  // status order: pending before received
    await user.click(screen.getByRole('button', { name: /Circle \/ State/ }));
    expect(screen.getAllByRole('row').slice(1).map((r) => r.getAttribute('aria-label'))).toEqual(['BH LWE: open details', 'MP LWE: open details']);
    await user.type(screen.getByLabelText('Search'), 'mp_lwe');
    expect(screen.getAllByRole('row')).toHaveLength(2);
    await user.type(screen.getByLabelText('Search'), 'zzz');
    expect(screen.getByText('No circle matches these filters.')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Clear filters' })[0]);
    expect(screen.getAllByRole('row')).toHaveLength(5);
  });

  it('starts empty again after a refresh: edits are not stored anywhere', async () => {
    const user = userEvent.setup();
    const view = renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await recordArrival(user, 'MP LWE');
    expect(within(card('CSVs received')).getByText('1')).toBeInTheDocument();
    view.unmount();  // a page refresh discards the in-memory state
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    expect(within(card('CSVs received')).getByText('0')).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
  });
});

async function addContactEmail(user: ReturnType<typeof userEvent.setup>, name: string, email: string) {
  await user.click(within(row(name)).getByRole('button', { name: `Edit contact for ${name}` }));
  await user.type(await screen.findByLabelText(/Contact person/), 'Asha Rao');
  await user.type(screen.getByLabelText(/Email address/), email);
  await user.click(screen.getByRole('button', { name: 'Save contact' }));
}

describe('Email actions', () => {
  it('sends the standard reminder to the recorded contact after showing it, in test mode', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    expect(await screen.findByText('Email: test mode · not delivered')).toBeInTheDocument();
    await addContactEmail(user, 'MP LWE', 'circle.mp@example.com');
    await user.click(within(row('MP LWE')).getByRole('button', { name: 'Send reminder for MP LWE' }));
    expect(await screen.findByText('TEST MODE')).toBeInTheDocument();
    const preview = await screen.findByRole('region', { name: 'Email preview' });
    expect(preview).toHaveTextContent('circle.mp@example.com');
    expect(preview).toHaveTextContent('Standard reminder body');
    expect(screen.getByText('Not configured (not mentioned in the email)')).toBeInTheDocument();
    expect(api.sendReminder).not.toHaveBeenCalled();  // nothing is sent before the explicit action
    await user.click(screen.getByRole('button', { name: /Send reminder now/ }));
    expect(api.sendReminder).toHaveBeenCalledTimes(1);
    expect(api.sendReminder).toHaveBeenCalledWith({ circle: 'MP', report_type: 'LWE', reporting_date: '2026-10-17', deadline: undefined, to: 'circle.mp@example.com', cc: '' });
    expect(await screen.findByText('Printed in the backend terminal (test mode)')).toBeInTheDocument();
    expect(screen.getByText(/It was not delivered to anyone/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Send reminder now/ })).not.toBeInTheDocument();  // no repeat click
  });

  it('will not send a reminder without a recipient, and offers to add one', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(within(row('RJ 4G')).getByRole('button', { name: 'Send reminder for RJ 4G' }));
    expect(await screen.findByText('Recipient missing')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Send reminder now/ })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Add contact email' }));
    expect(await screen.findByLabelText(/Email address/)).toBeInTheDocument();
    expect(api.sendReminder).not.toHaveBeenCalled();
  });

  it('shows the backend failure instead of success', async () => {
    vi.mocked(api.sendReminder).mockRejectedValue(new api.ApiError('The email could not be sent: the mail server did not accept it. Nothing was delivered.', 502));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await addContactEmail(user, 'MP LWE', 'circle.mp@example.com');
    await user.click(within(row('MP LWE')).getByRole('button', { name: 'Send reminder for MP LWE' }));
    await screen.findByRole('region', { name: 'Email preview' });
    await user.click(screen.getByRole('button', { name: /Send reminder now/ }));
    expect(await screen.findByText('Not sent')).toBeInTheDocument();
    expect(screen.getByText(/Nothing was delivered/)).toBeInTheDocument();
    expect(screen.queryByText(/Printed in the backend terminal/)).not.toBeInTheDocument();
  });

  it('composes an edited reminder, validates it, previews it and sends only on Send email', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(row('MP LWE'));
    const contact = await screen.findByRole('region', { name: 'Contact' });
    await user.click(within(contact).getByRole('button', { name: /Compose email/ }));
    await user.click(screen.getByRole('button', { name: 'Review email' }));
    expect(screen.getByText('Enter at least one recipient.')).toBeInTheDocument();
    expect(screen.getByText('Enter a subject.')).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^To/), 'test@example.com, bad@');
    await user.type(screen.getByLabelText(/^CC/), 'nope');
    expect(screen.getByText('Not a valid email address: bad@.')).toBeInTheDocument();
    expect(screen.getByText('Not a valid email address: nope.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/^To/));
    await user.type(screen.getByLabelText(/^To/), 'test@example.com');
    await user.clear(screen.getByLabelText(/^CC/));
    await user.click(screen.getByRole('button', { name: /Load standard reminder/ }));
    expect(api.fetchReminderTemplate).toHaveBeenCalledWith({ circle: 'MP', report_type: 'LWE', reporting_date: '2026-10-17', deadline: undefined });
    expect(await screen.findByDisplayValue('Standard reminder body')).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/^Subject/));
    await user.type(screen.getByLabelText(/^Subject/), 'Edited subject');
    await user.type(screen.getByLabelText(/^Message/), ' Please call me.');
    await user.click(screen.getByRole('button', { name: 'Review email' }));
    const preview = screen.getByRole('region', { name: 'Email preview' });
    expect(preview).toHaveTextContent('Edited subject');
    expect(preview).toHaveTextContent('Standard reminder body Please call me.');
    expect(api.sendPersonalEmail).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /Send email/ }));
    expect(api.sendPersonalEmail).toHaveBeenCalledWith({ to: 'test@example.com', cc: '', subject: 'Edited subject', body: 'Standard reminder body Please call me.' });
    expect(await screen.findByText('Printed in the backend terminal (test mode)')).toBeInTheDocument();
  });

  it('never sends when the composer is cancelled or closed', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(screen.getByRole('button', { name: /Compose email/ }));
    expect(screen.queryByRole('button', { name: /Load standard reminder/ })).not.toBeInTheDocument();  // blank: no circle chosen
    await user.type(screen.getByLabelText(/^To/), 'test@example.com');
    await user.type(screen.getByLabelText(/^Subject/), 'Hello');
    await user.type(screen.getByLabelText(/^Message/), 'Body');
    await user.click(screen.getByRole('button', { name: 'Review email' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('region', { name: 'Email preview' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Compose email/ }));
    await user.keyboard('{Escape}');
    expect(api.sendPersonalEmail).not.toHaveBeenCalled();
    expect(api.sendReminder).not.toHaveBeenCalled();
  });

  it('shows the backend field errors when the backend rejects the email', async () => {
    vi.mocked(api.sendPersonalEmail).mockRejectedValue(new api.ApiError('Invalid email request.', 400, { to: ['Not a valid email address: x@y.'] }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await user.click(screen.getByRole('button', { name: /Compose email/ }));
    await user.type(screen.getByLabelText(/^To/), 'x@y.co');
    await user.type(screen.getByLabelText(/^Subject/), 'Hello');
    await user.type(screen.getByLabelText(/^Message/), 'Body');
    await user.click(screen.getByRole('button', { name: 'Review email' }));
    await user.click(screen.getByRole('button', { name: /Send email/ }));
    expect(await screen.findByText('Not a valid email address: x@y.')).toBeInTheDocument();
    expect(screen.getByLabelText(/^To/)).toBeInTheDocument();  // back on the edit step
  });

  it('sends a reminder from the toolbar by choosing a pending report, through the same confirmation', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await addContactEmail(user, 'MP LWE', 'circle.mp@example.com');
    const toolbar = screen.getByRole('search', { name: 'Tracking filters' });
    await user.click(within(toolbar).getByRole('button', { name: /Send reminder/ }));
    const list = await screen.findByRole('list', { name: 'Pending reports' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect(within(list).getAllByText('No contact email')).toHaveLength(3);
    await user.click(within(list).getByRole('button', { name: /MP.*LWE.*circle\.mp@example\.com/ }));
    expect(await screen.findByRole('region', { name: 'Email preview' })).toHaveTextContent('circle.mp@example.com');
    expect(api.sendReminder).not.toHaveBeenCalled();  // still needs the explicit Send reminder now
    await user.click(screen.getByRole('button', { name: /Send reminder now/ }));
    expect(api.sendReminder).toHaveBeenCalledTimes(1);
  });

  it('groups the filter card: date and filters on the left, email actions together, Record arrival as the primary action', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    const toolbar = screen.getByRole('search', { name: 'Tracking filters' });
    expect(within(within(toolbar).getByRole('group', { name: 'Email' })).getAllByRole('button').map((b) => b.textContent?.trim()))
      .toEqual(['Send reminder', 'Compose email']);
    expect(screen.getByText(/^Sat, 17 Oct 2026 \(today\) · /)).toBeInTheDocument();  // the page context, in the top bar
    fireEvent.change(within(toolbar).getByLabelText('Reporting date'), { target: { value: '2026-10-16' } });
    expect(screen.getByText(/^Fri, 16 Oct 2026 · /)).toBeInTheDocument();
    expect(screen.getByText('Circle-wise submissions · 16 Oct 2026')).toBeInTheDocument();
    await user.click(within(toolbar).getByRole('button', { name: /Record arrival/ }));
    expect(await screen.findByText('Record CSV arrival')).toBeInTheDocument();
  });

  it('shows the email mode as a chip: live mode is labelled with its transport, failures as unavailable', async () => {
    vi.mocked(api.fetchEmailStatus).mockResolvedValue({ ...TEST_MODE, test_mode: false, transport: 'graph' });
    const view = renderPage();
    expect(await screen.findByText('Email: live · graph')).toBeInTheDocument();
    view.unmount();
    vi.mocked(api.fetchEmailStatus).mockRejectedValue(new api.ApiError('The reporting API could not be reached.', 0));
    renderPage();
    expect(await screen.findByText('Email unavailable')).toBeInTheDocument();
  });
});
