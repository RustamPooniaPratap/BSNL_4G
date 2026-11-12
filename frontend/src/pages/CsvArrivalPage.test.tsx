import { act, fireEvent, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TrackingProvider } from '../context/TrackingProvider';
import * as api from '../services/api';
import { arrivalTracker, trackerItem, trackerUpload } from '../test/fixtures';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { ArrivalTracker, TrackerItem } from '../types/rawUpload';
import { CsvArrivalPage } from './CsvArrivalPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchArrivalTracker: vi.fn(),
  fetchRawFiles: vi.fn(),
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

/** What the server reports per date (synthetic). 17 Oct: every combination of stored data and upload state. */
const DAYS: Record<string, TrackerItem[]> = {
  '2026-10-17': [
    trackerItem('4G Saturation', 'MP', {
      data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, records_observed: 11,
      data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 }, latest_data_date: '2026-10-17', latest_complete_date: '2026-10-17',
      range: [{ date: '2026-10-15', sites_with_data: 10, state: 'complete' }, { date: '2026-10-16', sites_with_data: 0, state: 'none' }, { date: '2026-10-17', sites_with_data: 10, state: 'complete' }],
    }),
    trackerItem('4G Saturation', 'OD', {
      data_state: 'partial', sites_with_data: 6, sites_missing: 4, coverage_pct: 60, data_source: { master_workbook: 0, raw_daily_csv: 6, correction: 0 },
      latest_data_date: '2026-10-17', latest_complete_date: '2026-10-12', latest_upload_date: '2026-10-17', latest_import_date: '2026-10-17',
      upload_state: 'imported', uploads: [trackerUpload({ file: 'od_day.csv', imported: 6 })],
    }),
    trackerItem('4G Saturation', 'RJ', { latest_data_date: '2026-10-12', latest_complete_date: '2026-10-12' }),
    trackerItem('LWE', 'BH', {
      upload_state: 'blocked', latest_upload_date: '2026-10-17',
      uploads: [trackerUpload({ id: 9, state: 'blocked', status_label: 'Rejected', imported: null, ready_to_import: 0, error: 'The file is for circle JH, not BH.', file: 'bh_day.csv' })],
    }),
    trackerItem('LWE', 'MP'),
  ],
  '2026-10-12': [
    trackerItem('4G Saturation', 'MP', { data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 } }),
    trackerItem('4G Saturation', 'OD', { data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 } }),
    trackerItem('4G Saturation', 'RJ', { data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 } }),
    trackerItem('LWE', 'BH', { data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 } }),
    trackerItem('LWE', 'MP', { data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 } }),
  ],
};
const respond = (params: { date: string }) => arrivalTracker(params.date, DAYS[params.date] ?? DAYS['2026-10-17'].map((i) => trackerItem(i.project, i.circle)));

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  vi.mocked(api.fetchArrivalTracker).mockReset().mockImplementation(async (params) => respond(params));
  vi.mocked(api.fetchRawFiles).mockResolvedValue({ count: 1, files: [{ name: 'MP_LWE_17-10-2026.csv', size_bytes: 120, modified_at: '2026-10-17T09:00:00', extension: '.csv' }] });
  vi.mocked(api.fetchEmailStatus).mockResolvedValue(TEST_MODE);
  vi.mocked(api.fetchReminderTemplate).mockReset().mockResolvedValue({ ...TEST_MODE, subject: 'Reminder: LWE uptime CSV for MP, 17 Oct 2026', body: 'Standard reminder body' });
  vi.mocked(api.sendReminder).mockReset().mockImplementation(async (r) => printed('reminder', r.to, 'Reminder: LWE uptime CSV for MP, 17 Oct 2026'));
  vi.mocked(api.sendPersonalEmail).mockReset().mockImplementation(async (m) => printed('personal', m.to, m.subject));
  fetchSpy = vi.spyOn(globalThis, 'fetch');
});
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();  // reads go through the mocked API; nothing is written anywhere
  fetchSpy.mockRestore();
});

const renderPage = () => renderWithWorkbook(<TrackingProvider><CsvArrivalPage now={NOW} /></TrackingProvider>, { url: '/daily-ingestion' });
const loaded = () => screen.findByText(/^Circle-wise data and CSV uploads/);
const card = (label: string) => screen.getByRole('button', { name: new RegExp(`^${label}`) });
const row = (name: string) => screen.getByRole('row', { name: new RegExp(`^${name}: open details`) });
const cell = (name: string, column: number) => within(row(name)).getAllByRole('cell')[column];
const statuses = () => screen.getAllByRole('row', { name: /open details/ }).map((r) => within(r).getAllByRole('cell')[2].firstChild?.textContent);

async function pick(user: ReturnType<typeof userEvent.setup>, label: RegExp, option: string) {
  await user.click(await screen.findByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: option }));
}

describe('CSV Arrival & Follow-up', () => {
  it('shows the stored data and the CSV upload state separately, never "Pending"', async () => {
    renderPage();
    await loaded();
    expect(api.fetchArrivalTracker).toHaveBeenCalledWith({ date: '2026-10-17', start: '2026-10-04', end: '2026-10-17' }, expect.anything());
    expect(screen.queryByText('Pending')).not.toBeInTheDocument();
    // Complete data from the Uptime Master with no CSV upload is complete, not pending.
    expect(cell('MP 4G', 2)).toHaveTextContent('Data complete');
    expect(cell('MP 4G', 2)).toHaveTextContent('From Uptime Master');
    expect(cell('MP 4G', 3)).toHaveTextContent('10 / 10 sites');
    expect(cell('MP 4G', 4)).toHaveTextContent('No CSV upload recorded');
    // Partial data from an imported CSV.
    expect(cell('OD 4G', 2)).toHaveTextContent('Partial data');
    expect(cell('OD 4G', 3)).toHaveTextContent('6 / 10 sites60% · 4 missing');
    expect(cell('OD 4G', 4)).toHaveTextContent('CSV imported');
    expect(cell('OD 4G', 4)).toHaveTextContent('od_day.csv');
    expect(cell('OD 4G', 4)).toHaveTextContent('noc.lead');
    // A blocked file: received, but no usable data.
    expect(cell('BH LWE', 2)).toHaveTextContent('File received · no usable data');
    expect(cell('BH LWE', 4)).toHaveTextContent('CSV blocked');
    // Nothing stored and nothing uploaded.
    expect(cell('RJ 4G', 2)).toHaveTextContent('No data available');
    expect(cell('RJ 4G', 5)).toHaveTextContent('12 Oct 2026');  // the latest stored date, not today
    expect(cell('MP LWE', 5)).toHaveTextContent('None stored');
    expect(within(card('Project circles')).getByText('5')).toBeInTheDocument();
    expect(within(card('Data complete')).getByText('1')).toBeInTheDocument();
    expect(within(card('Partial data')).getByText('1')).toBeInTheDocument();
    expect(within(card('No usable data')).getByText('3')).toBeInTheDocument();
    expect(within(card('CSV uploads recorded')).getByText('2')).toBeInTheDocument();
    expect(within(card('Past deadline')).getByText('0')).toBeInTheDocument();
    expect(screen.getAllByText('Not configured')).toHaveLength(5);
    expect(screen.getByText(/Data status is read from the reporting data for the selected date/)).toBeInTheDocument();
  });

  it('loads each selected date from the server and never shows another date while it loads', async () => {
    renderPage();
    await loaded();
    let release: (value: ArrivalTracker) => void = () => {};
    vi.mocked(api.fetchArrivalTracker).mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    fireEvent.change(screen.getByLabelText('Reporting date'), { target: { value: '2026-10-12' } });
    expect(screen.getByLabelText('Loading CSV arrival tracking')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /open details/ })).not.toBeInTheDocument();  // 17 Oct's rows are gone
    await act(async () => release(respond({ date: '2026-10-12' })));
    expect(await screen.findByText('Circle-wise data and CSV uploads · 12 Oct 2026')).toBeInTheDocument();
    expect(statuses()).toEqual(Array(5).fill('Data complete'));
    expect(api.fetchArrivalTracker).toHaveBeenLastCalledWith({ date: '2026-10-12', start: '2026-09-29', end: '2026-10-12' }, expect.anything());
    fireEvent.change(screen.getByLabelText('Reporting date'), { target: { value: '2026-10-17' } });
    await loaded();
    expect(cell('RJ 4G', 2)).toHaveTextContent('No data available');
  });

  it('shows a server failure with a retry, not an empty tracker', async () => {
    vi.mocked(api.fetchArrivalTracker).mockRejectedValueOnce(new api.ApiError('The reporting API could not be reached.', 0));
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText('The tracker could not be loaded')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Try again/ }));
    await loaded();
    expect(cell('MP 4G', 2)).toHaveTextContent('Data complete');
  });

  it('marks a circle past its deadline only with no data and no upload, and only once a deadline is configured', async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();
    await user.click(screen.getByRole('button', { name: /Deadlines/ }));
    for (const legend of ['LWE', '4G Saturation']) {
      const set = (await screen.findByText(legend, { selector: 'legend' })).closest('fieldset') as HTMLElement;
      await user.click(within(set).getByRole('checkbox', { name: 'Deadline configured' }));  // next day, 10:00
    }
    await user.click(screen.getByRole('button', { name: 'Save deadlines' }));
    // For 17 Oct the CSVs are due 18 Oct 10:00, which has not passed.
    expect(within(card('Past deadline')).getByText('0')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Reporting date'), { target: { value: '2026-10-15' } });
    await screen.findByText('Circle-wise data and CSV uploads · 15 Oct 2026');
    expect(statuses()).toEqual(Array(5).fill('No data · past deadline'));
    fireEvent.change(screen.getByLabelText('Reporting date'), { target: { value: '2026-10-12' } });
    await screen.findByText('Circle-wise data and CSV uploads · 12 Oct 2026');
    expect(within(card('Past deadline')).getByText('0')).toBeInTheDocument();  // stored data is never late
  });

  it('opens the details: stored data, every upload with its state, latest dates and contact', async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();
    await user.click(row('BH LWE'));
    const uploads = await screen.findByRole('region', { name: 'CSV uploads' });
    expect(uploads).toHaveTextContent('CSV blocked');
    expect(uploads).toHaveTextContent('bh_day.csv');
    expect(uploads).toHaveTextContent('Upload #9');
    expect(uploads).toHaveTextContent('The file is for circle JH, not BH.');
    expect(uploads).toHaveTextContent('Latest CSV received: 17 Oct 2026 · latest imported: —');
    const stored = screen.getByRole('region', { name: 'Stored daily data' });
    expect(stored).toHaveTextContent('10 On-Air of 12 in the master');
    expect(stored).toHaveTextContent('No usable records on this date');
    await user.keyboard('{Escape}');
    await user.click(row('MP 4G'));
    const mp = await screen.findByRole('region', { name: 'Stored daily data' });
    expect(mp).toHaveTextContent('Uptime Master');
    expect(mp).toHaveTextContent('11 usable records, including sites not On-Air');
    expect(screen.getByRole('region', { name: 'CSV uploads' })).toHaveTextContent('No CSV upload recorded for this date.');
  });

  it('keeps manual arrival notes as notes: they never change the status', async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();
    await user.click(row('MP LWE'));
    await user.click(await screen.findByRole('button', { name: 'Add manual note' }));
    await user.click(await screen.findByRole('button', { name: /It arrived just now/ }));
    await user.click(screen.getByRole('button', { name: 'Record arrival' }));
    expect(await screen.findByText('Note recorded for MP · LWE (17 Oct 2026).')).toBeInTheDocument();
    expect(cell('MP LWE', 2)).toHaveTextContent('No data available');
    await user.click(row('MP LWE'));
    expect(await screen.findByText('File name is not recorded.')).toBeInTheDocument();
  });

  it('adds contact details and follow-ups without changing the status', async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();
    await user.click(within(row('RJ 4G')).getByRole('button', { name: 'Edit contact for RJ 4G' }));
    await user.type(await screen.findByLabelText(/Contact person/), 'Asha Rao');
    await user.type(screen.getByLabelText(/Phone number/), '12');
    await user.click(screen.getByRole('button', { name: 'Save contact' }));
    expect(screen.getByText(/Enter 10 to 15 digits/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/Phone number/));
    await user.type(screen.getByLabelText(/Phone number/), '+91 98765 43210');
    await user.click(screen.getByRole('button', { name: 'Save contact' }));
    expect(within(row('RJ 4G')).getByText('Asha Rao')).toBeInTheDocument();
    expect(cell('RJ 4G', 2)).toHaveTextContent('No data available');
    expect(within(card('Missing contact details')).getByText('4')).toBeInTheDocument();
    await user.click(within(row('BH LWE')).getByRole('button', { name: 'Add follow-up for BH LWE' }));
    await pick(user, /Method/, 'Message');
    await user.type(screen.getByLabelText(/Outcome/), 'Asked for the corrected BH file');
    await user.click(screen.getByRole('button', { name: 'Add follow-up' }));
    expect(within(row('BH LWE')).getByText('Asked for the corrected BH file')).toBeInTheDocument();
    await user.click(row('BH LWE'));
    expect(within(await screen.findByRole('region', { name: 'Follow-up history' })).getByText(/Message/)).toBeInTheDocument();
  });

  it('combines cards, filters, search and sorting', async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();
    await user.click(card('CSV uploads recorded'));
    expect(screen.getAllByRole('row', { name: /open details/ }).map((r) => r.getAttribute('aria-label'))).toEqual(['BH LWE: open details', 'OD 4G: open details']);
    await user.click(card('CSV uploads recorded'));  // select again to clear
    await pick(user, /^Project/, 'LWE');
    expect(statuses()).toEqual(['No data available', 'File received · no usable data']);  // most urgent first
    await user.click(screen.getByRole('button', { name: /Circle \/ State/ }));
    expect(screen.getAllByRole('row', { name: /open details/ }).map((r) => r.getAttribute('aria-label'))).toEqual(['BH LWE: open details', 'MP LWE: open details']);
    await user.type(screen.getByLabelText('Search'), 'bh_day');
    expect(screen.getAllByRole('row', { name: /open details/ })).toHaveLength(1);
    await user.type(screen.getByLabelText('Search'), 'zzz');
    expect(screen.getByText('No circle matches these filters.')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Clear filters' })[0]);
    expect(screen.getAllByRole('row', { name: /open details/ })).toHaveLength(5);
    await user.click(screen.getByLabelText('Incomplete only'));
    expect(screen.getAllByRole('row', { name: /open details/ })).toHaveLength(4);
  });

  it('shows daily coverage across a range with its gaps, and opens a day from it', async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();
    const grid = screen.getByRole('table', { name: 'Daily coverage by circle' });
    const mpRow = within(grid).getByRole('button', { name: 'MP 4G 16 Oct 2026: no data' }).closest('tr')!;
    expect(mpRow.lastElementChild).toHaveTextContent('1');  // one day without data in the range
    expect(within(grid).getByRole('button', { name: 'MP 4G 15 Oct 2026: 10 of 10 sites' })).toBeInTheDocument();
    await user.click(within(grid).getByRole('button', { name: 'MP 4G 15 Oct 2026: 10 of 10 sites' }));
    expect(await screen.findByText('Circle-wise data and CSV uploads · 15 Oct 2026')).toBeInTheDocument();
    const form = screen.getByRole('form', { name: 'Coverage range' });
    fireEvent.change(within(form).getByLabelText('Range from'), { target: { value: '2026-10-01' } });
    fireEvent.change(within(form).getByLabelText('Range to'), { target: { value: '2026-10-15' } });
    await user.click(within(form).getByRole('button', { name: 'Show range' }));
    expect(api.fetchArrivalTracker).toHaveBeenLastCalledWith({ date: '2026-10-15', start: '2026-10-01', end: '2026-10-15' }, expect.anything());
    fireEvent.change(within(form).getByLabelText('Range from'), { target: { value: '2026-01-01' } });
    expect(within(form).getByText('Choose at most 92 days.')).toBeInTheDocument();
    expect(within(form).getByRole('button', { name: 'Show range' })).toBeDisabled();
  });

  it('reloads the server status after a refresh; only browser-held notes are lost', async () => {
    const user = userEvent.setup();
    const view = renderPage();
    await loaded();
    await user.click(within(row('RJ 4G')).getByRole('button', { name: 'Add follow-up for RJ 4G' }));
    await pick(user, /Method/, 'Call');
    await user.type(screen.getByLabelText(/Outcome/), 'No answer');
    await user.click(screen.getByRole('button', { name: 'Add follow-up' }));
    expect(within(row('RJ 4G')).getByText('No answer')).toBeInTheDocument();
    view.unmount();  // a page refresh
    renderPage();
    await loaded();
    expect(cell('MP 4G', 2)).toHaveTextContent('Data complete');  // from the server again
    expect(screen.queryByText('No answer')).not.toBeInTheDocument();
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

  it('sends a reminder from the toolbar by choosing a circle without data, through the same confirmation', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    await addContactEmail(user, 'MP LWE', 'circle.mp@example.com');
    const toolbar = screen.getByRole('search', { name: 'Tracking filters' });
    await user.click(within(toolbar).getByRole('button', { name: /Send reminder/ }));
    const list = await screen.findByRole('list', { name: 'Circles without data' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);  // RJ 4G and MP LWE: no stored data and no upload
    expect(within(list).getAllByText('No contact email')).toHaveLength(1);
    await user.click(within(list).getByRole('button', { name: /MP.*LWE.*circle\.mp@example\.com/ }));
    expect(await screen.findByRole('region', { name: 'Email preview' })).toHaveTextContent('circle.mp@example.com');
    expect(api.sendReminder).not.toHaveBeenCalled();  // still needs the explicit Send reminder now
    await user.click(screen.getByRole('button', { name: /Send reminder now/ }));
    expect(api.sendReminder).toHaveBeenCalledTimes(1);
  });

  it('groups the filter card: date and filters on the left, email actions together, Refresh as the primary action', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('CSV Arrival & Follow-up');
    const toolbar = screen.getByRole('search', { name: 'Tracking filters' });
    expect(within(within(toolbar).getByRole('group', { name: 'Email' })).getAllByRole('button').map((b) => b.textContent?.trim()))
      .toEqual(['Send reminder', 'Compose email']);
    expect(screen.getByText(/^Sat, 17 Oct 2026 \(today\) · /)).toBeInTheDocument();  // the page context, in the top bar
    fireEvent.change(within(toolbar).getByLabelText('Reporting date'), { target: { value: '2026-10-16' } });
    expect(screen.getByText(/^Fri, 16 Oct 2026 · /)).toBeInTheDocument();
    expect(await screen.findByText('Circle-wise data and CSV uploads · 16 Oct 2026')).toBeInTheDocument();
    await user.click(within(toolbar).getByRole('button', { name: /Refresh/ }));
    expect(api.fetchArrivalTracker).toHaveBeenLastCalledWith({ date: '2026-10-16', start: '2026-10-03', end: '2026-10-16' }, expect.anything());
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

  it('shows the coverage threshold used and labels an inactive unit (not expected on the date)', async () => {
    vi.mocked(api.fetchArrivalTracker).mockImplementation(async (params) => arrivalTracker(params.date, DAYS['2026-10-17'].map((i) =>
      i.circle === 'OD' ? { ...i, coverage_threshold_pct: 90, active: true }
        : i.project === 'LWE' && i.circle === 'MP' ? { ...i, data_state: 'no_scope' as const, active: false, coverage_pct: null, coverage_threshold_pct: null } : i)));
    renderPage();
    await loaded();
    expect(cell('OD 4G', 3)).toHaveTextContent('6 / 10 sites60% (threshold 90%) · 4 missing');
    expect(cell('MP LWE', 3)).toHaveTextContent('InactiveUnit not expected on this date');
  });
});
