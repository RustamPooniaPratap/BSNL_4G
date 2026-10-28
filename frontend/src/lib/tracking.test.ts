import { describe, expect, it } from 'vitest';
import { EMPTY_TRACKING, trackingReducer, type TrackingState } from '../context/tracking';
import { filterOptions } from '../test/fixtures';
import {
  DEFAULT_FILTERS, EMPTY_CONTACT, applyCard, applyFilters, arrivalErrors, buildSubmissions, contactErrors, deadlineFor,
  followUpErrors, kpis, requirementKey, requirementsFrom, submissionKey, type ArrivalRecord,
} from './tracking';

const REQUIREMENTS = requirementsFrom(filterOptions.circles);
const DATE = '2026-10-16';
const NOW = new Date('2026-10-17T12:00:00');
const MP_LWE = { circle: 'MP', reportType: 'LWE' };

const arrival = (overrides: Partial<ArrivalRecord> = {}): ArrivalRecord => ({
  id: 'a1', circle: 'MP', reportType: 'LWE', reportingDate: DATE, arrivalDate: '2026-10-17', arrivalTime: '09:30',
  fileName: 'MP_LWE_16-10-2026.csv', receivedBy: '', notes: '', timeIsEntryTime: false, enteredAt: '2026-10-17T09:31:00', ...overrides,
});
const withArrival = (record: ArrivalRecord, extra: Partial<TrackingState> = {}): TrackingState =>
  ({ ...EMPTY_TRACKING, arrivals: { [submissionKey(record, record.reportingDate)]: record }, ...extra });
const statusOf = (state: TrackingState, now = NOW) =>
  Object.fromEntries(buildSubmissions(REQUIREMENTS, DATE, state, now).map((s) => [`${s.circle} ${s.reportType}`, s.status]));

describe('requirements', () => {
  it('come from the circles and report types in the master data, not every combination', () => {
    expect(REQUIREMENTS.map((r) => `${r.reportType} ${r.circle}`)).toEqual(['4G Saturation MP', '4G Saturation RJ', 'LWE BH', 'LWE MP']);
  });
});

describe('arrival status', () => {
  it('starts with every requirement pending and nothing invented', () => {
    const rows = buildSubmissions(REQUIREMENTS, DATE, EMPTY_TRACKING, NOW);
    expect(rows.every((s) => s.status === 'pending' && s.arrival === null && s.contact === null && s.deadline === null)).toBe(true);
    expect(rows.every((s) => s.followUps.length === 0)).toBe(true);
  });

  it('is never late without a configured deadline, however much time has passed', () => {
    expect(statusOf(EMPTY_TRACKING, new Date('2027-01-01T00:00:00'))['MP LWE']).toBe('pending');
  });

  it('becomes late only after the configured deadline passes', () => {
    const state = { ...EMPTY_TRACKING, deadlines: { LWE: { dayOffset: 1, time: '10:00' } } };
    expect(deadlineFor('LWE', DATE, state.deadlines)?.toString()).toBe(new Date('2026-10-17T10:00:00').toString());
    expect(statusOf(state, new Date('2026-10-17T09:59:00'))['MP LWE']).toBe('pending');
    expect(statusOf(state, new Date('2026-10-17T10:01:00'))['MP LWE']).toBe('late');
    expect(statusOf(state, new Date('2026-10-17T10:01:00'))['MP 4G Saturation']).toBe('pending');  // no 4G deadline
  });

  it('is received when an arrival with complete details exists, and flags arrival after the deadline', () => {
    const state = withArrival(arrival({ arrivalTime: '11:15' }), { deadlines: { LWE: { dayOffset: 1, time: '10:00' } } });
    const mp = buildSubmissions(REQUIREMENTS, DATE, state, NOW).find((s) => s.circle === 'MP' && s.reportType === 'LWE')!;
    expect(mp.status).toBe('received');
    expect(mp.arrivedLate).toBe(true);
    // 4G and LWE are tracked separately: the LWE deadline does not make MP's 4G CSV late.
    expect(statusOf(state)['MP 4G Saturation']).toBe('pending');
    expect(statusOf(state)['BH LWE']).toBe('late');
  });

  it('needs review when arrival details are incomplete or inconsistent', () => {
    const problems = (record: ArrivalRecord) => buildSubmissions(REQUIREMENTS, DATE, withArrival(record), NOW)
      .find((s) => s.circle === 'MP' && s.reportType === 'LWE')!;
    expect(problems(arrival({ fileName: '' })).problems).toEqual(['File name is not recorded.']);
    expect(problems(arrival({ fileName: 'report.xlsx' })).problems).toEqual(['The file name does not end in .csv.']);
    expect(problems(arrival({ arrivalDate: '2026-10-18' })).problems).toEqual(['The arrival time is in the future.']);
    expect(problems(arrival({ arrivalDate: '2026-10-15' })).problems).toEqual(['It arrived before the reporting date it covers.']);
    expect(problems(arrival({ fileName: '' })).status).toBe('needs_review');
  });

  it('does not let contact details change the arrival status', () => {
    const noContact = statusOf(EMPTY_TRACKING);
    const withContact = statusOf({ ...EMPTY_TRACKING, contacts: { [requirementKey(MP_LWE)]: { ...EMPTY_CONTACT, name: 'Asha', phone: '9876543210' } } });
    expect(withContact).toEqual(noContact);
  });
});

describe('KPIs, filters and search', () => {
  const state = withArrival(arrival(), { contacts: { [requirementKey(MP_LWE)]: { ...EMPTY_CONTACT, name: 'Asha Rao', email: 'asha@example.com' } } });
  const rows = buildSubmissions(REQUIREMENTS, DATE, state, NOW);

  it('counts from the records', () => {
    expect(kpis(rows, '2026-10-17')).toEqual({ total: 4, received: 1, pending: 3, receivedToday: 1, late: 0, needsReview: 0, missingContact: 3 });
    expect(kpis(rows, '2026-10-18').receivedToday).toBe(0);
  });

  it('filters by circle, report type, status, contact and late/pending, and searches', () => {
    const f = (changes: object) => applyFilters(rows, { ...DEFAULT_FILTERS, ...changes }).map((s) => `${s.circle} ${s.reportType}`);
    expect(f({ circle: 'MP' })).toEqual(['MP 4G Saturation', 'MP LWE']);
    expect(f({ reportType: 'LWE' })).toEqual(['BH LWE', 'MP LWE']);
    expect(f({ status: 'received' })).toEqual(['MP LWE']);
    expect(f({ contact: 'complete' })).toEqual(['MP LWE']);
    expect(f({ contact: 'missing' })).toHaveLength(3);
    expect(f({ openOnly: true })).toHaveLength(3);
    expect(f({ search: 'asha@' })).toEqual(['MP LWE']);
    expect(f({ search: '16-10-2026.csv' })).toEqual(['MP LWE']);
    expect(f({ search: 'rj' })).toEqual(['RJ 4G Saturation']);
  });

  it('applies KPI cards on top of the filters', () => {
    const lwe = applyFilters(rows, { ...DEFAULT_FILTERS, reportType: 'LWE' });
    expect(applyCard(lwe, 'pending', '2026-10-17').map((s) => s.circle)).toEqual(['BH']);
    expect(applyCard(lwe, 'missing_contact', '2026-10-17').map((s) => s.circle)).toEqual(['BH']);
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
