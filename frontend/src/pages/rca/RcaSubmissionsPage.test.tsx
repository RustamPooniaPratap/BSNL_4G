import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RequireAdmin } from '../../components/auth/Guards';
import * as api from '../../services/api';
import { CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { AuthUser } from '../../types';
import type { RcaCycleDetail, RcaImportBatch } from '../../types/rca';
import { RcaSubmissionsPage } from './RcaSubmissionsPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchRcaCycles: vi.fn(), fetchRcaCycle: vi.fn(), fetchRcaImports: vi.fn(), startRcaCycle: vi.fn(), setRcaRequired: vi.fn(), finalizeRcaCycle: vi.fn(),
}));
const m = vi.mocked(api);

const upload = (over: Partial<RcaImportBatch> = {}): RcaImportBatch => ({
  id: 11, status: 'committed', status_label: 'Imported', file: 'Book1_RCA.xlsx', checksum: 'abc', sheet: 'Sheet1', uploaded_at: '2026-10-22T10:00:00Z',
  committed_at: '2026-10-22T10:05:00Z', imported_by: 'noc.lead', report_name: 'October 2026 RCA Report', project_scope: 'both', remarks: null,
  period_start: '2026-10-21', period_end: '2026-10-21', cycle: 4, units: [['4G Saturation', 'OD'], ['LWE', 'BH']],
  counts: { total: 610, valid: 608, rejected: 2, inserted: 600, updated: 0, skipped: 8 }, correction: false, conflict_action: null, missing_action: null,
  error: null, file_kept: true, ...over,
});
const CYCLE: RcaCycleDetail = {
  id: 4, name: 'October 2026 RCA Report', period_start: '2026-10-21', period_end: '2026-10-21', period_label: '21 Oct 2026', notes: null,
  created_by: 'noc.lead', created_at: '2026-10-22T10:05:00Z', records: 608,
  uploads_summary: { total: 2, imported: 1, with_rejected_rows: 1, awaiting_confirmation: 0, validation_failed: 1, corrections: 1, last_upload_at: '2026-10-22T10:00:00Z' },
  status: { code: 'partial', label: 'Partially received', required: 3, received: 2, complete: false, final_version: null, can_finalize: false,
    upload_awaiting_confirmation: false, records_checksum: 'x', outstanding: [{ project: 'LWE', circle: 'OD', status: 'pending', status_label: 'Pending — no accepted records' }] },
  units: [
    { project: '4G Saturation', circle: 'OD', status: 'received', status_label: 'Data received', records: 522, outage_minutes: 200973, source_files: ['Book1_RCA.xlsx'] },
    { project: 'LWE', circle: 'BH', status: 'received', status_label: 'Data received', records: 86, outage_minutes: 17530, source_files: ['Book1_RCA.xlsx'] },
    { project: 'LWE', circle: 'OD', status: 'pending', status_label: 'Pending — no accepted records', records: 0, outage_minutes: null, source_files: [] },
  ],
  unexpected: [{ project: 'LWE', circle: 'JH', records: 293 }],
  uploads: [upload()], reports: [], available_units: [['4G Saturation', 'OD'], ['LWE', 'BH'], ['LWE', 'OD'], ['LWE', 'JH']], locked: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRcaCycles.mockResolvedValue({ cycles: [CYCLE], default_units: [], available_units: CYCLE.available_units });
  m.fetchRcaCycle.mockResolvedValue(CYCLE);
  m.fetchRcaImports.mockResolvedValue({ imports: [upload(), upload({ id: 12, status: 'failed', status_label: 'Failed', counts: {}, cycle: null, units: [],
    error: 'The "Sheet1" sheet is missing required columns: RCA.', imported_by: 'other.lead' })], records: 608, all: true });
});

describe('RCA Submissions', () => {
  it('shows received and pending data from the expected scope, apart from the upload status', async () => {
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const status = await screen.findByLabelText('Period status');
    expect(within(status).getByText('Partially received')).toBeInTheDocument();
    expect(within(status).getByText('2 of 3')).toBeInTheDocument();
    expect(within(status).getByText('Pending (no accepted records): OD LWE')).toBeInTheDocument();
    expect(within(status).getByRole('link', { name: 'Download partial report' })).toHaveAttribute('href', expect.stringContaining('/rca/cycles/4/report.xlsx'));
    const coverage = screen.getByLabelText('Expected coverage');
    const rows = within(coverage).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('OD4G SaturationData received522');
    expect(rows[3]).toHaveTextContent('ODLWEPending — no accepted records0');
    expect(within(coverage).getByText(/outside the expected scope: JH LWE \(293\)/)).toBeInTheDocument();
    // The upload itself succeeded, with rejected rows: shown as an upload status, not as completeness.
    const periodUploads = within(screen.getByLabelText('Period uploads')).getAllByRole('row');
    expect(periodUploads[1]).toHaveTextContent('October 2026 RCA Reportnoc.leadBook1_RCA.xlsx4G + LWE');
    expect(periodUploads[1]).toHaveTextContent('600 · 0 · 8 · 2');
    expect(periodUploads[1]).toHaveTextContent('OD 4G, BH LWE');
    // Every upload, failed ones included.
    const all = within(screen.getByLabelText('All uploads')).getAllByRole('row');
    expect(all).toHaveLength(3);
    expect(all[2]).toHaveTextContent('other.lead');
    expect(all[2]).toHaveTextContent('missing required columns');
    expect(m.fetchRcaImports).toHaveBeenCalledWith(expect.anything(), true);
  });

  it('lists the daily reporting status: completeness beside received, failed and corrected uploads', async () => {
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions' });
    const rows = within(await screen.findByLabelText('Daily reporting status')).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('21 Oct 2026October 2026 RCA ReportPartially received2 of 3OD LWE');
    expect(rows[1]).toHaveTextContent('1 (1 with rejected rows)');
    const cells = within(rows[1]).getAllByRole('cell').map((c) => c.textContent);
    expect(cells.slice(6, 9)).toEqual(['1', '0', '1']);  // validation failed, awaiting confirmation, corrections
  });

  it('configures the expected scope of a period', async () => {
    const user = userEvent.setup();
    m.setRcaRequired.mockResolvedValue(CYCLE);
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions?cycle=4' });
    const scope = await screen.findByLabelText('Configure expected scope');
    await user.click(within(scope).getByRole('button', { name: 'Change' }));
    await user.click(within(scope).getByRole('checkbox', { name: 'LWE JH' }));
    await user.click(within(scope).getByRole('button', { name: 'Save 4 expected projects / circles' }));
    expect(m.setRcaRequired).toHaveBeenCalledWith(4, [['4G Saturation', 'OD'], ['LWE', 'BH'], ['LWE', 'OD'], ['LWE', 'JH']]);
  });

  it('says completeness cannot be judged without an expected scope', async () => {
    m.fetchRcaCycle.mockResolvedValue({ ...CYCLE, units: [], status: { ...CYCLE.status, code: 'unconfigured', label: 'Expected scope not configured', required: 0, received: 0, outstanding: [] } });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions?cycle=4' });
    expect(await screen.findByText(/No expected projects \/ circles are configured, so completeness cannot be judged/)).toBeInTheDocument();
    expect(screen.getByText('Configure the expected projects and circles below to track what is still pending.')).toBeInTheDocument();
  });

  it('after a correction to a finalized period offers the revised version', async () => {
    const user = userEvent.setup();
    const v1 = { id: 1, version: 1, filename: 'RCA_Master_2026-10-21_FINAL_v1.xlsx', generated_at: '2026-10-23T10:00:00Z', generated_by: null, automatic: true,
      record_count: 608, superseded_at: null, current: true, available: true };
    const revised: RcaCycleDetail = { ...CYCLE, locked: true, reports: [v1], uploads: [upload({ id: 13, correction: true }), upload()],
      status: { ...CYCLE.status, code: 'revised', label: 'Revised after finalization', received: 3, complete: true, outstanding: [], final_version: 1, can_finalize: true } };
    m.fetchRcaCycle.mockResolvedValue(revised);
    m.finalizeRcaCycle.mockResolvedValue({ ...revised, created: true, report: { ...v1, id: 2, version: 2, automatic: false, generated_by: 'admin' } });
    renderWithWorkbook(<RcaSubmissionsPage />, { url: '/rca/submissions?cycle=4' });
    const status = await screen.findByLabelText('Period status');
    expect(within(status).getByText(/Records changed after final report v1/)).toBeInTheDocument();
    expect(within(screen.getByLabelText('Period uploads')).getByText('Correction')).toBeInTheDocument();
    expect(screen.getByText('Fixed: the final report has been generated.')).toBeInTheDocument();
    await user.click(within(status).getByRole('button', { name: 'Generate revised final report (v2)' }));
    expect(await screen.findByText('Final report v2 generated from 608 accepted records.')).toBeInTheDocument();
  });

  it('is an Admin page: a CI or a NOC Lead is refused', () => {
    const noc: AuthUser = { username: 'noc.lead', name: 'NOC', role: 'noc_lead', role_label: 'NOC Lead', must_change_password: false };
    for (const user of [CI_USER, noc]) {
      const view = renderWithWorkbook(<Routes><Route path="/rca/submissions" element={<RequireAdmin><RcaSubmissionsPage /></RequireAdmin>} /></Routes>,
        { url: '/rca/submissions', auth: authValue({ user }) });
      expect(screen.getByText('You do not have access to this page')).toBeInTheDocument();
      view.unmount();
    }
    expect(m.fetchRcaCycles).not.toHaveBeenCalled();
  });
});
