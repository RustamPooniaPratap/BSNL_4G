import { describe, expect, it } from 'vitest';
import { EMPTY_TRACKING, trackingReducer, type TrackingState } from '../context/tracking';
import { trackerItem, trackerUpload } from '../test/fixtures';
import {
  DEFAULT_FILTERS, EMPTY_CONTACT, applyCard, applyFilters, arrivalErrors, buildSubmissions, contactErrors, deadlineFor,
  followUpErrors, kpis, requirementKey, requirementsFrom, submissionKey, type ArrivalRecord,
} from './tracking';

const DATE = '2026-10-16';
const NOW = new Date('2026-10-17T12:00:00');
const MP_LWE = { circle: 'MP', reportType: 'LWE' };
// As the server reports them: MP 4G complete from the workbook, RJ 4G partial from a CSV, BH LWE nothing, MP LWE a blocked file.
const ITEMS = [
  trackerItem('4G Saturation', 'MP', { data_state: 'complete', sites_with_data: 10, sites_missing: 0, coverage_pct: 100, data_source: { master_workbook: 10, raw_daily_csv: 0, correction: 0 } }),
  trackerItem('4G Saturation', 'RJ', { data_state: 'partial', sites_with_data: 6, sites_missing: 4, coverage_pct: 60, upload_state: 'imported', uploads: [trackerUpload({ file: 'rj_day.csv' })] }),
  trackerItem('LWE', 'BH'),
  trackerItem('LWE', 'MP', { upload_state: 'blocked', uploads: [trackerUpload({ state: 'blocked', imported: null, error: 'Wrong circle.' })] }),
];

const arrival = (overrides: Partial<ArrivalRecord> = {}): ArrivalRecord => ({
  id: 'a1', circle: 'MP', reportType: 'LWE', reportingDate: DATE, arrivalDate: '2026-10-17', arrivalTime: '09:30',
  fileName: 'MP_LWE_16-10-2026.csv', receivedBy: '', notes: '', timeIsEntryTime: false, enteredAt: '2026-10-17T09:31:00', ...overrides,
});
const withArrival = (record: ArrivalRecord, extra: Partial<TrackingState> = {}): TrackingState =>
  ({ ...EMPTY_TRACKING, arrivals: { [submissionKey(record, record.reportingDate)]: record }, ...extra });
const statusOf = (state: TrackingState, now = NOW, items = ITEMS) =>
  Object.fromEntries(buildSubmissions(items, DATE, state, now).map((s) => [`${s.circle} ${s.reportType}`, s.status]));

describe('requirements', () => {
  it('are the project circles the server returned, 4G before LWE', () => {
    expect(requirementsFrom([...ITEMS].reverse()).map((r) => `${r.reportType} ${r.circle}`)).toEqual(['4G Saturation MP', '4G Saturation RJ', 'LWE BH', 'LWE MP']);
  });
});

describe('data status', () => {
  it('comes from the stored data first, then from the upload history, never "pending"', () => {
    expect(statusOf(EMPTY_TRACKING)).toEqual({
      'MP 4G Saturation': 'complete', 'RJ 4G Saturation': 'partial', 'BH LWE': 'no_data', 'MP LWE': 'file_received',
    });
  });

  it('is complete without any CSV upload when the stored data covers every expected site', () => {
    const mp = buildSubmissions(ITEMS, DATE, EMPTY_TRACKING, NOW)[0];
    expect(mp.server.upload_state).toBe('none');
    expect(mp.status).toBe('complete');
  });

  it('is never late without a configured deadline, however much time has passed', () => {
    expect(statusOf(EMPTY_TRACKING, new Date('2027-01-01T00:00:00'))['BH LWE']).toBe('no_data');
  });

  it('is late only with no data and no upload, after the configured deadline', () => {
    const state = { ...EMPTY_TRACKING, deadlines: { LWE: { dayOffset: 1, time: '10:00' }, '4G Saturation': { dayOffset: 1, time: '10:00' } } };
    expect(deadlineFor('LWE', DATE, state.deadlines)?.toString()).toBe(new Date('2026-10-17T10:00:00').toString());
    expect(statusOf(state, new Date('2026-10-17T09:59:00'))['BH LWE']).toBe('no_data');
    const after = statusOf(state, new Date('2026-10-17T10:01:00'));
    expect(after).toEqual({ 'MP 4G Saturation': 'complete', 'RJ 4G Saturation': 'partial', 'BH LWE': 'late', 'MP LWE': 'file_received' });
  });

  it('a discarded upload is not a received file', () => {
    const items = [trackerItem('LWE', 'BH', { upload_state: 'discarded', uploads: [trackerUpload({ state: 'discarded', imported: null })] })];
    expect(statusOf(EMPTY_TRACKING, NOW, items)).toEqual({ 'BH LWE': 'no_data' });
  });

  it('manual arrival notes and contacts never change the status', () => {
    const noted = buildSubmissions(ITEMS, DATE, withArrival(arrival({ circle: 'BH', fileName: '' })), NOW).find((s) => s.circle === 'BH')!;
    expect(noted.status).toBe('no_data');
    expect(noted.problems).toEqual(['File name is not recorded.']);
    const withContact = statusOf({ ...EMPTY_TRACKING, contacts: { [requirementKey(MP_LWE)]: { ...EMPTY_CONTACT, name: 'Asha', phone: '9876543210' } } });
    expect(withContact).toEqual(statusOf(EMPTY_TRACKING));
  });

  it('checks manual notes for incomplete or inconsistent details', () => {
    const problems = (record: ArrivalRecord) => buildSubmissions(ITEMS, DATE, withArrival(record), NOW).find((s) => s.circle === 'MP' && s.reportType === 'LWE')!.problems;
    expect(problems(arrival({ fileName: 'report.xlsx' }))).toEqual(['The file name does not end in .csv.']);
    expect(problems(arrival({ arrivalDate: '2026-10-18' }))).toEqual(['The arrival time is in the future.']);
    expect(problems(arrival({ arrivalDate: '2026-10-15' }))).toEqual(['It arrived before the reporting date it covers.']);
  });
});

describe('KPIs, filters and search', () => {
  const state = withArrival(arrival(), { contacts: { [requirementKey(MP_LWE)]: { ...EMPTY_CONTACT, name: 'Asha Rao', email: 'asha@example.com' } } });
  const rows = buildSubmissions(ITEMS, DATE, state, NOW);

  it('counts from the server facts', () => {
    expect(kpis(rows)).toEqual({ total: 4, complete: 1, partial: 1, noData: 2, csvRecorded: 2, late: 0, missingContact: 3 });
  });

  it('filters by circle, project, status, contact and incomplete, and searches uploads too', () => {
    const f = (changes: object) => applyFilters(rows, { ...DEFAULT_FILTERS, ...changes }).map((s) => `${s.circle} ${s.reportType}`);
    expect(f({ circle: 'MP' })).toEqual(['MP 4G Saturation', 'MP LWE']);
    expect(f({ reportType: 'LWE' })).toEqual(['BH LWE', 'MP LWE']);
    expect(f({ status: 'partial' })).toEqual(['RJ 4G Saturation']);
    expect(f({ contact: 'complete' })).toEqual(['MP LWE']);
    expect(f({ contact: 'missing' })).toHaveLength(3);
    expect(f({ openOnly: true })).toEqual(['RJ 4G Saturation', 'BH LWE', 'MP LWE']);
    expect(f({ search: 'asha@' })).toEqual(['MP LWE']);
    expect(f({ search: 'rj_day' })).toEqual(['RJ 4G Saturation']);
    expect(f({ search: 'noc.lead' })).toEqual(['RJ 4G Saturation', 'MP LWE']);
  });

  it('applies KPI cards on top of the filters', () => {
    const lwe = applyFilters(rows, { ...DEFAULT_FILTERS, reportType: 'LWE' });
    expect(applyCard(lwe, 'no_data').map((s) => s.circle)).toEqual(['BH', 'MP']);
    expect(applyCard(lwe, 'csv_recorded').map((s) => s.circle)).toEqual(['MP']);
    expect(applyCard(rows, 'complete').map((s) => s.circle)).toEqual(['MP']);
    expect(applyCard(lwe, 'missing_contact').map((s) => s.circle)).toEqual(['BH']);
  });
});

describe('form checks', () => {
  const draft = { circle: 'MP', reportType: 'LWE', reportingDate: DATE, arrivalDate: '2026-10-17', arrivalTime: '09:30', fileName: 'x.csv', receivedBy: '', notes: '', timeIsEntryTime: false };

  it('requires the arrival date and time and refuses future times', () => {
    expect(arrivalErrors({ ...draft, arrivalDate: '', arrivalTime: '' }, {}, NOW)).toMatchObject({ arrivalDate: expect.any(String), arrivalTime: expect.any(String) });
    expect(arrivalErrors({ ...draft, arrivalTime: '12:30' }, {}, NOW).arrivalTime).toBe('The arrival time cannot be in the future.');
    expect(arrivalErrors({ ...draft, fileName: 'x.xlsx' }, {}, NOW).fileName).toMatch(/\.csv/);
    expect(arrivalErrors(draft, {}, NOW)).toEqual({});
  });

  it('prevents a second arrival for the same circle, report type and date, but allows editing it', () => {
    const existing = withArrival(arrival()).arrivals;
    expect(arrivalErrors(draft, existing, NOW).circle).toMatch(/already recorded for MP · LWE/);
    expect(arrivalErrors(draft, existing, NOW, 'a1')).toEqual({});
    expect(arrivalErrors({ ...draft, reportingDate: '2026-10-15', arrivalDate: '2026-10-16' }, existing, NOW)).toEqual({});
    expect(arrivalErrors({ ...draft, reportType: '4G Saturation' }, existing, NOW)).toEqual({});
  });

  it('accepts blank contacts and checks the details that are given', () => {
    expect(contactErrors(EMPTY_CONTACT)).toEqual({});
    expect(contactErrors({ ...EMPTY_CONTACT, name: 'Asha', phone: '12345' }).phone).toMatch(/10 to 15 digits/);
    expect(contactErrors({ ...EMPTY_CONTACT, name: 'Asha', email: 'asha@' }).email).toMatch(/valid email/);
    expect(contactErrors({ ...EMPTY_CONTACT, phone: '+91 98765 43210' }).name).toMatch(/name/);
  });

  it('records follow-ups without a contact, but not in the future', () => {
    const base = { at: '2026-10-17T11:00', contactPerson: '', method: 'call' as const, outcome: 'No answer', expectedAt: '', nextFollowUp: '' };
    expect(followUpErrors(base, NOW)).toEqual({});
    expect(followUpErrors({ ...base, at: '2026-10-17T13:00' }, NOW).at).toMatch(/future/);
    expect(followUpErrors({ ...base, method: '', outcome: ' ' }, NOW)).toMatchObject({ method: expect.any(String), outcome: expect.any(String) });
    expect(followUpErrors({ ...base, nextFollowUp: '2026-10-17T10:00' }, NOW).nextFollowUp).toMatch(/after/);
  });
});

describe('tracking state', () => {
  it('replaces an edited arrival when its key changes and removes arrivals', () => {
    const record = arrival();
    const key = submissionKey(record, DATE);
    let state = trackingReducer(EMPTY_TRACKING, { type: 'saveArrival', key, record });
    const moved = { ...record, reportingDate: '2026-10-15' };
    const newKey = submissionKey(moved, '2026-10-15');
    state = trackingReducer(state, { type: 'saveArrival', key: newKey, record: moved, replaceKey: key });
    expect(Object.keys(state.arrivals)).toEqual([newKey]);
    expect(trackingReducer(state, { type: 'removeArrival', key: newKey }).arrivals).toEqual({});
  });
});
