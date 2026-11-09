import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { approvedFinalBuckets, approvedSubBuckets } from '../../lib/rcaTaxonomy';
import type { RcaOptions } from '../../types/rca';
import { RcaFilterBar } from './RcaShared';

/** Part of the taxonomy as the server sends it (apps.rca.taxonomy): the dropdowns must show exactly this, nothing else. */
const CLASSIFICATION = [
  { final_bucket: 'IaaSP Others', bucket_2: ['Shadow issue', 'Natural Clamity'] },
  { final_bucket: 'BSNL Media', bucket_2: ['Nokia mini link', 'Fluctuation'] },
  { final_bucket: 'DMW', bucket_2: ['Ceragoan Radio', 'Fluctuation'] },
];
const key = (v: string) => v.toLowerCase();
// The filter options as the server builds them from the same taxonomy (services.options).
const subs = new Map<string, string[]>();
CLASSIFICATION.forEach((c) => c.bucket_2.forEach((b) => subs.set(b, [...(subs.get(b) ?? []), c.final_bucket])));
const OPTIONS: RcaOptions = {
  dates: [], months: [], projects: [], circles: [], categories: [], statuses: [], total_records: 0, classification: CLASSIFICATION,
  final_buckets: CLASSIFICATION.map((c) => ({ value: key(c.final_bucket), label: c.final_bucket, approved: true, unclassified: false })),
  bucket_2: [...[...subs].map(([b, finals]) => ({ value: key(b), label: b, approved: true, unclassified: false, final_buckets: finals })),
    { value: '__unclassified__', label: 'Unclassified (blank or "-")', unclassified: true, approved: false, final_buckets: [] }],
};

async function optionsOf(name: RegExp) {
  await userEvent.setup().click(screen.getByRole('combobox', { name }));
  return screen.getAllByRole('option').map((o) => o.textContent);
}

describe('RCA taxonomy dropdowns', () => {
  it('reads the approved lists from the server taxonomy only', () => {
    expect(approvedFinalBuckets(OPTIONS)).toEqual(['IaaSP Others', 'BSNL Media', 'DMW']);
    expect(approvedSubBuckets(OPTIONS, 'DMW')).toEqual(['Ceragoan Radio', 'Fluctuation']);
    expect(approvedSubBuckets(OPTIONS, 'Unknown')).toEqual([]);
  });

  it('offers exactly the approved Final Buckets', async () => {
    render(<RcaFilterBar options={OPTIONS} params={new URLSearchParams()} onChange={vi.fn()} onReset={vi.fn()} />);
    expect(await optionsOf(/^Final Bucket/)).toEqual(['All Final Buckets', 'IaaSP Others', 'BSNL Media', 'DMW']);
  });

  it('offers the Sub Buckets of the chosen Final Bucket only', async () => {
    render(<RcaFilterBar options={OPTIONS} params={new URLSearchParams('final_bucket=dmw')} onChange={vi.fn()} onReset={vi.fn()} />);
    expect(await optionsOf(/^Bucket - 2/)).toEqual(['All Bucket - 2', 'Ceragoan Radio', 'Fluctuation', 'Unclassified (blank or "-")']);
  });
});
