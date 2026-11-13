import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RcaImportBatch, RcaImportReport } from '../../types/rca';
import { RcaImportPreview } from './RcaImportPreview';

const REPORT: RcaImportReport = {
  filename: 'Oct.xlsx', sheet: 'Sheet1', rows_read: 10, valid_rows: 6, rejected_rows: 4, blank_rows: 0, unknown_columns: [], dates: { '2026-10-21': 6 },
  projects: { '4G Saturation': 6 }, projects_raw: { '4G Satu': 6 }, circles: { '4G Saturation|OD': 6 }, circle_names: { 'Odisha -> OD': 6 },
  distinct_sites: 3, outage_minutes: 100, final_buckets: {}, bucket_2: {}, distinct_rca: 3, label_variants: {},
  severity_counts: { error: 4, warning: 2, info: 1 }, issue_counts: { duplicate_record: 3, final_bucket_not_approved: 1 }, issues: [],
  new_rows: 6, unchanged_rows: 0, conflict_rows: 0, conflicts: [], already_imported: null,
  duplicates: { rows: 3, groups: 2, sites: 1, identical_rows: 1, differing_rows: 2,
    examples: [{ site_id: 'OD0001', project: '4G Saturation', reporting_date: '2026-10-21', final_bucket: 'BSNL Media', sub_bucket: 'Nokia mini link', first_row: 2, rejected_rows: [5, 6] },
      { site_id: 'OD0001', project: '4G Saturation', reporting_date: '2026-10-21', final_bucket: 'TCS', sub_bucket: '', first_row: 3, rejected_rows: [7] }] },
  sites_with_several_records: 1,
  final_bucket_problems: [{ value: 'Vsat', code: 'final_bucket_not_approved', rows: 1, example_rows: [9] }], final_bucket_error_rows: 1,
  sub_bucket_warnings: { rows: 2, missing_rows: 1, not_approved_rows: 1, values: [{ final_bucket: 'IaasP Others', value: 'Natural Clamity', code: 'sub_bucket_not_approved', rows: 1, example_rows: [4] }] },
  rca_description_warnings: 1,
};
const BATCH: RcaImportBatch = {
  id: 22, status: 'previewed', status_label: 'Validated — awaiting confirmation', file: 'Oct.xlsx', checksum: 'x', sheet: 'Sheet1', uploaded_at: '2026-11-04T10:00:00Z',
  committed_at: null, imported_by: 'admin', report_name: 'October', project_scope: 'both', remarks: null, period_start: '2026-10-31', period_end: '2026-10-31',
  cycle: null, units: [], counts: { total: 10, valid: 6, rejected: 4 }, correction: false, conflict_action: null, missing_action: null, error: null, file_kept: true, report: REPORT,
};

describe('RcaImportPreview validation priorities', () => {
  it('lists duplicates by the four-field key, Final Bucket errors and the non-blocking Sub Bucket and description warnings', () => {
    render(<RcaImportPreview batch={BATCH} busy={false} onCommit={vi.fn()} onDiscard={vi.fn()} />);
    const groups = screen.getByLabelText('Validation priorities');
    expect(groups).toHaveTextContent('3 duplicate rows rejected (2 duplicate groups, 1 sites; 1 identical, 2 with another RCA description, outage or other column)');
    expect(groups).toHaveTextContent('same Site ID, date, Final Bucket and Sub Bucket');
    expect(groups).toHaveTextContent('OD0001 (4G Saturation), 21 Oct 2026, BSNL Media / Nokia mini link: kept row 2, rejected rows 5, 6');
    expect(groups).toHaveTextContent('TCS / blank: kept row 3, rejected row 7');
    expect(groups).toHaveTextContent('1 rows with a missing or unapproved Final Bucket: the workbook cannot be imported');
    expect(groups).toHaveTextContent('“Vsat”: 1 rows (row 9)');
    expect(within(groups).getByText(/2 Sub Bucket warnings/).closest('p')).toHaveTextContent('they do not block the import');
    expect(groups).toHaveTextContent('IaasP Others / “Natural Clamity”: 1 rows (row 4)');
    expect(groups).toHaveTextContent('1 sites have more than one RCA record on a date');
    expect(groups).toHaveTextContent('1 rows have a blank or placeholder RCA description: kept as written; they do not block the import.');
  });
});
