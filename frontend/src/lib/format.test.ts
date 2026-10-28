import { describe, expect, it } from 'vitest';
import { formatCompact, formatDate, formatMinutes, formatNumber, formatPct } from './format';

describe('format helpers', () => {
  it('formats percentages and missing values', () => {
    expect(formatPct(93.0676)).toBe('93.07%');
    expect(formatPct(80, 1)).toBe('80.0%');
    expect(formatPct(null)).toBe('—');
    expect(formatPct(0)).toBe('0.00%');
  });

  it('formats ISO dates without shifting the day', () => {
    expect(formatDate('2026-10-01')).toBe('01 Oct 2026');
    expect(formatDate(null)).toBe('—');
  });

  it('formats counts and outage minutes with Indian grouping', () => {
    expect(formatNumber(123456)).toBe('1,23,456');
    expect(formatMinutes(656924.77)).toBe('6,56,925 min');
    expect(formatMinutes(null)).toBe('—');
    expect(formatCompact(656925)).toBe('6.6L');
  });
});
