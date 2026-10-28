import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { breakdown } from '../../test/fixtures';
import type { BreakdownResponse } from '../../types';
import { CircleComparison } from './CircleComparison';

const rows = () => within(screen.getByRole('table', { hidden: true })).getAllByRole('row', { hidden: true }).map((r) => r.textContent);
const headers = () => within(screen.getByRole('table', { hidden: true })).getAllByRole('columnheader', { hidden: true }).map((h) => h.textContent);

const circle = breakdown.circles[0];
const withSeptember: BreakdownResponse = {
  ...breakdown,
  comparison: { key: '2026-09', label: 'Sep-26', available: true, start: '2026-09-01', end: '2026-09-03', days_reported: 3 },
  circles: [
    { ...circle, circle: 'MP', report_type: '4G Saturation', mtd_uptime_pct: 93.2, previous_uptime_pct: 92.9, mtd_change_pts: 0.3,
      mtd_outage_minutes: 600, previous_outage_minutes: 800 },
    { ...circle, circle: 'OD', report_type: '4G Saturation', mtd_uptime_pct: 89.6, previous_uptime_pct: 91.1, mtd_change_pts: -1.5,
      mtd_outage_minutes: 400, previous_outage_minutes: 300 },
    { ...circle, circle: 'JH', report_type: 'LWE', mtd_uptime_pct: 95.4, previous_uptime_pct: null, mtd_change_pts: null,
      mtd_outage_minutes: null, previous_outage_minutes: null },
  ],
};

describe('CircleComparison', () => {
  it('explains when the previous month has no daily values, and shows MTD only', () => {
    render(<CircleComparison breakdown={breakdown} loading={false} error={null} />);
    expect(screen.getByText(/appears once its daily outage values are available/)).toBeInTheDocument();
    expect(headers()).toEqual(['Circle', 'Sites in scope', 'MTD 01–03 Oct', 'Daily uptime']);
  });

  it('pairs MTD with the same days of last month, lowest MTD first, with exact values and changes', () => {
    render(<CircleComparison breakdown={withSeptember} loading={false} error={null} />);
    expect(screen.getByText(/against the same days of Sep-26/)).toBeInTheDocument();
    expect(rows().slice(1).map((r) => r!.split('·')[0])).toEqual(['OD ', 'MP ', 'JH ']);  // lowest MTD first
    expect(rows()[1]).toBe('OD · 4G289.60%91.10%-1.50 pts50.00%');
    expect(rows()[3]).toMatch(/^JH · LWE295\.40%—/);  // no previous value: shown as —, never 0
    const od = screen.getByTitle(/^OD · 4G: MTD 89.60%, Sep-26 91.10%, change -1.50 pts/);
    expect(od).toHaveTextContent('▼1.5');
  });

  it('switches to outage minutes per site, highest first, and shows missing values as missing, never zero', async () => {
    const user = userEvent.setup();
    render(<CircleComparison breakdown={withSeptember} loading={false} error={null} />);
    await user.click(screen.getByRole('button', { name: 'Outage' }));
    expect(screen.getByRole('button', { name: 'Outage' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/MTD outage minutes per site against the same days of Sep-26/)).toBeInTheDocument();
    expect(headers()).toEqual(['Circle', 'Sites in scope', 'Outage MTD 01–03 Oct', 'Per site MTD 01–03 Oct', 'Per site Sep-26 01–03 Sept', 'Change']);
    // 2 sites each: MP 600 / 2 = 300 per site (Sep 400), OD 400 / 2 = 200 (Sep 150); JH has no outage data.
    expect(rows().slice(1)).toEqual([
      'MP · 4G2600 min300 min400 min-100 min',
      'OD · 4G2400 min200 min150 min+50 min',
      'JH · LWE2————',
    ]);
    expect(screen.getByTitle(/^MP · 4G: MTD 300 min per site/)).toHaveTextContent('▼100');
    expect(screen.getByTitle(/^MP · 4G/).querySelector('.text-emerald-700')).not.toBeNull();  // less outage is better
    expect(screen.getByTitle(/^OD · 4G/).querySelector('.text-destructive')).not.toBeNull();
    await user.click(screen.getByRole('button', { name: 'Uptime' }));
    expect(headers()[2]).toBe('MTD 01–03 Oct');
  });

  it('filters by network', async () => {
    const user = userEvent.setup();
    render(<CircleComparison breakdown={withSeptember} loading={false} error={null} />);
    await user.click(screen.getByRole('button', { name: 'LWE' }));
    expect(rows().slice(1).map((r) => r!.slice(0, 2))).toEqual(['JH']);
    await user.click(screen.getByRole('button', { name: 'All' }));
    expect(rows()).toHaveLength(4);
  });
});
