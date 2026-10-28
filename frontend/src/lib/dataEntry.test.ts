import { describe, expect, it } from 'vitest';
import {
  detectColumns, newSiteLink, normaliseCircle, outageError, outageWarning, parseCsv, parseDate, siteIdError, validateCsv,
} from './dataEntry';

const META = { reportType: '4G Saturation', circle: 'MP', date: '2026-10-16' };
const KNOWN = new Set(['UVMPBPL00012', 'UVMPBPL00020']);
const check = (text: string, known: Set<string> | null = KNOWN, meta = META) => validateCsv(parseCsv(text), meta, known);
const messages = (text: string, known: Set<string> | null = KNOWN, meta = META) =>
  check(text, known, meta).issues.map((i) => `${i.severity}@${i.line}: ${i.message}`);

describe('field checks', () => {
  it('validates Site ID formats per report type', () => {
    expect(siteIdError('UVMPBPL00012', '4G Saturation')).toBeNull();
    expect(siteIdError('uvmpbpl00012', '4G Saturation')).toBeNull();  // case is normalised
    expect(siteIdError('LWEBH0303', 'LWE')).toBeNull();
    expect(siteIdError('LWEUPE2212', 'LWE')).toBeNull();
    expect(siteIdError('', 'LWE')).toBe('Site ID is required.');
    expect(siteIdError('UV MP 001', '4G Saturation')).toBe('Site ID cannot contain spaces.');
    expect(siteIdError('LWEBH0303', '4G Saturation')).toMatch(/Not a 4G Saturation Site ID format/);
    expect(siteIdError('UV_MP_001', '4G Saturation')).toMatch(/expected like UVMPBPL00012/);
  });

  it('parses dates strictly', () => {
    expect(parseDate('2026-10-16')).toBe('2026-10-16');
    expect(parseDate('16-10-2026')).toBe('2026-10-16');  // as in Data/raw/test_sample_upload.csv
    expect(parseDate('16/10/2026')).toBe('2026-10-16');
    expect(parseDate('31-02-2026')).toBeNull();
    expect(parseDate('2026-13-01')).toBeNull();
    expect(parseDate('Oct 16')).toBeNull();
  });

  it('checks outage minutes', () => {
    expect(outageError('0')).toBeNull();
    expect(outageError('45.5')).toBeNull();
    expect(outageError('')).toMatch(/required/);
    expect(outageError('abc')).toMatch(/number/);
    expect(outageError('1,440')).toMatch(/number/);
    expect(outageError('-5')).toMatch(/negative/);
    expect(outageWarning('1500')).toMatch(/full day/);
    expect(outageWarning('1440')).toBeNull();
  });

  it('normalises LWE circle names and builds the Add New Site link', () => {
    expect(normaliseCircle('Madhya Pradesh')).toBe('MP');
    expect(normaliseCircle(' od ')).toBe('OD');
    expect(newSiteLink('uvmpbpl09999', 'LWE', 'MP')).toBe('/data/new-site?site_id=UVMPBPL09999&report_type=LWE&circle=MP');
  });
});

describe('parseCsv', () => {
  it('handles quotes, escaped quotes, CRLF, a BOM and blank lines', () => {
    const csv = parseCsv('﻿Site ID,Site name\r\n"UVMPBPL00012","Kheda, ""East"""\r\n\r\nUVMPBPL00020,Plain\n');
    expect(csv.headers).toEqual(['Site ID', 'Site name']);
    expect(csv.rows).toEqual([['UVMPBPL00012', 'Kheda, "East"'], ['UVMPBPL00020', 'Plain']]);
    expect(csv.lines).toEqual([2, 4]);
  });

  it('recognises header aliases and reports unknown or repeated columns', () => {
    const { roles, unknown, duplicates } = detectColumns(['BTS IP ID', 'Nw Avail (4G TCS)', 'Report Date', 'Remarks', 'btsIpId']);
    expect(roles).toEqual({ site_id: 0, availability_pct: 1, date: 2 });
    expect(unknown).toEqual(['Remarks']);
    expect(duplicates).toEqual(['btsIpId']);
  });
});

describe('validateCsv', () => {
  // The selected reporting date is 2026-10-16; the sample file writes dates as DD-MM-YYYY.
  const HEAD = 'btsIpId,Outage Minutes,Report Date';

  it('accepts a clean file', () => {
    const result = check(`${HEAD}\nUVMPBPL00012,0,16-10-2026\nUVMPBPL00020,45,2026-10-16\n`);
    expect(result).toMatchObject({ rowCount: 2, validRows: 2, errorCount: 0, warningCount: 0, measure: 'outage_minutes' });
    expect(result.dateCheck).toMatchObject({ status: 'passed', expected: '2026-10-16', column: 'Report Date', mixed: false });
    // Different formats of the same day are one date after normalising, not two strings.
    expect(result.dateCheck.detected).toEqual([{ date: '2026-10-16', lines: [2, 3] }]);
  });

  it('detects empty files and files without rows', () => {
    expect(messages('')).toEqual(['error@null: The file is empty.']);
    expect(messages(`${HEAD}\n`)).toContain('error@null: The file has a header row but no data rows.');
  });

  it('requires the Site ID, reporting date and one value column', () => {
    expect(messages('Name,Outage Minutes,Report Date\nx,1,16-10-2026\n')[0]).toMatch(/^error@1: Missing the Site ID column/);
    expect(messages('btsIpId,Remarks,Report Date\nUVMPBPL00012,x,16-10-2026\n')).toEqual(expect.arrayContaining([expect.stringMatching(/^error@1: Missing the value column/)]));
    expect(messages('btsIpId,Outage,Availability,Date\nUVMPBPL00012,1,99,16-10-2026\n')).toContain('error@1: The file has both an outage-minutes and an availability column; keep only one.');
  });

  it('blocks a file without a reporting-date column', () => {
    const result = check('btsIpId,Outage Minutes\nUVMPBPL00012,0\n');
    expect(result.issues[0].message).toMatch(/^Missing the reporting-date column \(one of: Report Date, Reporting Date, Date\)/);
    expect(result.dateCheck).toMatchObject({ status: 'failed', column: null, message: 'The file has no reporting-date column.' });
  });

  it('flags any repeated column header, even ones that are not checked', () => {
    expect(messages(`${HEAD},Remarks,remarks \nUVMPBPL00012,0,16-10-2026,a,b\n`)).toContain('error@1: Column "remarks" appears more than once.');
    expect(messages(`${HEAD},BTS IP ID\nUVMPBPL00012,0,16-10-2026,x\n`)).toContain('error@1: Column "BTS IP ID" appears more than once.');
  });

  it('flags malformed rows, missing and invalid values', () => {
    const found = messages(`${HEAD}\nUVMPBPL00012\nUVMPBPL00020,,16-10-2026\n,5,16-10-2026\nUVMPBPL00012,abc,16-10-2026\n`);
    expect(found).toEqual([
      'error@2: Has 1 value but the header has 3 columns.',
      'error@3: Outage minutes are empty.',
      'error@4: Site ID is empty.',
      'error@5: Outage "abc" is not a number.',
    ]);
  });

  it('flags duplicate Site IDs and exact copies', () => {
    const result = check(`${HEAD}\nUVMPBPL00012,0,16-10-2026\nUVMPBPL00012,0,16-10-2026\nuvmpbpl00012,5,16-10-2026\n`);
    expect(result.issues.map((i) => `${i.severity}@${i.line}: ${i.message}`)).toEqual([
      'error@3: Duplicate Site ID UVMPBPL00012 (first on line 2).',
      'warning@3: Exact copy of line 2.',
      'error@4: Duplicate Site ID UVMPBPL00012 (first on line 2).',
    ]);
    expect(result.validRows).toBe(1);
  });

  it('flags Site IDs missing from the master data, or in the wrong format', () => {
    const result = check(`${HEAD}\nUVMPBPL09999,0,16-10-2026\nLWEBH0303,0,16-10-2026\n`);
    const unknown = result.issues.filter((i) => i.unknownSite).map((i) => i.siteId);
    expect(unknown).toEqual(['UVMPBPL09999']);
    expect(result.issues[1].message).toMatch(/Not a 4G Saturation Site ID format/);
    // While the master data is loading the unknown-site check waits.
    expect(check(`${HEAD}\nUVMPBPL09999,0,16-10-2026\n`, null).errorCount).toBe(0);
  });

  it('flags circle, date and report type that disagree with the upload details', () => {
    const found = messages(
      'BTS IP ID,Nw Avail (4G TCS),Report Date,Circle,Project\n'
      + 'UVMPBPL00012,99.5,16-10-2026,Madhya Pradesh,4G Satu.\n'
      + 'UVMPBPL00020,98.2,17-10-2026,RJ,LWE\n'
      + 'UVMPBPL00012,101,31-02-2026,MP,4G Satu.\n',
    );
    expect(found).toEqual([
      'error@null: The file contains 2 different reporting dates (2026-10-16: 1 row, 2026-10-17: 1 row). A file must cover one date.',
      'warning@1: Values are availability %, not outage minutes. The conversion to outage minutes is not confirmed yet.',
      'error@3: Date 2026-10-17 does not match the selected reporting date 2026-10-16.',
      'error@3: Circle "RJ" does not match the selected circle MP.',
      'error@3: Report type "LWE" does not match the selected 4G Saturation.',
      'error@4: Duplicate Site ID UVMPBPL00012 (first on line 2).',
      'error@4: Availability 101 is outside 0–100%.',
      'error@4: Date "31-02-2026" is not a valid date (use YYYY-MM-DD or DD-MM-YYYY).',
    ]);
  });

  it('warns about outage above a full day and unused columns without blocking', () => {
    const result = check(`${HEAD},Remarks\nUVMPBPL00012,1500,16-10-2026,late\n`);
    expect(result.errorCount).toBe(0);
    expect(result.issues.map((i) => i.message)).toEqual(['Columns not used and not checked: Remarks.', 'Outage 1500 min is more than a full day.']);
  });
});

describe('reporting date check', () => {
  const HEAD = 'btsIpId,Outage Minutes,Reporting Date';

  it('fails when every row has another date, naming the expected and detected dates and lines', () => {
    const result = check(`${HEAD}\nUVMPBPL00012,0,15/10/2026\nUVMPBPL00020,5,15-10-2026\n`);
    expect(result.dateCheck).toMatchObject({
      status: 'failed', expected: '2026-10-16', mixed: false,
      detected: [{ date: '2026-10-15', lines: [2, 3] }],
      message: 'Expected 2026-10-16 on every row; found 2 rows with another date.',
    });
    expect(result.errorCount).toBe(2);
  });

  it('blocks a mixed-date file even when one of the dates is the selected one', () => {
    const result = check(`${HEAD}\nUVMPBPL00012,0,2026-10-16\nUVMPBPL00020,5,2026-10-17\n`);
    expect(result.dateCheck.mixed).toBe(true);
    expect(result.dateCheck.status).toBe('failed');
    expect(result.dateCheck.detected.map((d) => d.date)).toEqual(['2026-10-16', '2026-10-17']);
    expect(result.issues[0]).toMatchObject({ line: null, severity: 'error' });
    expect(result.issues[0].message).toMatch(/2 different reporting dates/);
  });

  it('fails for empty or unreadable dates and lists their lines', () => {
    const result = check(`${HEAD}\nUVMPBPL00012,0,\nUVMPBPL00020,5,16th Oct\n`);
    expect(result.dateCheck.status).toBe('failed');
    expect(result.dateCheck.invalid).toEqual([{ value: '', lines: [2] }, { value: '16th Oct', lines: [3] }]);
    expect(result.dateCheck.message).toBe('Expected 2026-10-16 on every row; found 1 row without a date, 1 row with an unreadable date.');
    expect(messages(`${HEAD}\nUVMPBPL00012,0,\n`)).toContain('error@2: Reporting date is empty.');
  });

  it('waits until a reporting date is selected', () => {
    const result = check(`${HEAD}\nUVMPBPL00012,0,2026-10-16\n`, KNOWN, { ...META, date: '' });
    expect(result.dateCheck.status).toBe('pending');
  });
});
