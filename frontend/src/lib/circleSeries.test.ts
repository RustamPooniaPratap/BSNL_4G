import { describe, expect, it } from 'vitest';
import { trend } from '../test/fixtures';
import { allCircleKeys, circleColor, circleLabel, lowestCircles, parseSelection, selectedSeries, trendByCircle } from './circleSeries';

const circles = [
  { value: 'MP', report_types: ['4G Saturation', 'LWE'] },
  { value: 'BH', report_types: ['LWE'] },
  { value: 'RJ', report_types: ['4G Saturation'] },
];

describe('circle series', () => {
  it('orders 4G before LWE and keeps each circle colour the same everywhere', () => {
    const keys = allCircleKeys(circles);
    expect(keys).toEqual(['4G Saturation|MP', '4G Saturation|RJ', 'LWE|BH', 'LWE|MP']);
    expect(circleLabel('LWE|MP')).toBe('MP · LWE');
    expect(new Set(keys.map((k) => circleColor(k, keys))).size).toBe(4);
    expect(circleColor('LWE|BH', keys)).toBe(circleColor('LWE|BH', keys));
  });

  it('starts with at most four circles, never all; a chosen list is kept in full; "none" and unknown keys are respected', () => {
    const six = ['a', 'b', 'c', 'd', 'e', 'f'];
    expect(parseSelection(null, six)).toEqual([]);
    expect(parseSelection(null, six, ['f', 'e'])).toEqual(['f', 'e']);  // the given starting choice
    expect(parseSelection(null, six, six)).toEqual(['a', 'b', 'c', 'd']);  // the starting choice is capped
    expect(parseSelection('a,b,c,d,e', six)).toEqual(['a', 'b', 'c', 'd', 'e']);  // e.g. all LWE circles
    expect(parseSelection('none', ['a'], ['a'])).toEqual([]);
    expect(parseSelection('b,zz', ['a', 'b'])).toEqual(['b']);
  });

  it('starts with the circles with the lowest MTD uptime, circles without a value last', () => {
    const c = (circle: string, mtd: number | null) => ({ report_type: 'LWE', circle, mtd_uptime_pct: mtd });
    expect(lowestCircles([c('A', 99), c('B', null), c('C', 80), c('D', 95), c('E', 90)])).toEqual(['LWE|C', 'LWE|E', 'LWE|D', 'LWE|A']);
  });

  it('draws only circles present in the data and keeps missing values as null', () => {
    const keys = allCircleKeys(circles);
    expect(selectedSeries([{ key: 'LWE|BH', report_type: 'LWE', circle: 'BH', sites: 1 }], ['LWE|BH', 'LWE|MP'], keys)?.keys).toEqual(['LWE|BH']);
    expect(selectedSeries([], ['LWE|BH'], keys)).toBeNull();
    const reshaped = trendByCircle({ ...trend, series: trend.series.map((p) => ({ ...p, by_circle: { 'LWE|BH': p.reported ? 97 : null } })) }, ['LWE|BH']);
    expect(reshaped.report_types).toEqual(['LWE|BH']);
    expect(reshaped.series.map((p) => p.by_report_type['LWE|BH'])).toEqual([97, null]);
    expect(reshaped.series[0].outage_by_report_type).toEqual({ 'LWE|BH': null });  // absent in the response: null, not 0
  });
});
