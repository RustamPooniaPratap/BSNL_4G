import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../services/api';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import type { TicketImportBatch } from '../../types/tickets';
import { TicketUploadPage } from './TicketUploadPage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  previewTicketImport: vi.fn(),
  commitTicketImport: vi.fn(),
  ticketTemplateUrl: vi.fn(() => 'http://localhost:8000/api/tickets/template.xlsx'),
}));

const m = vi.mocked(api);
const PREVIEW: TicketImportBatch = {
  id: 8,
  filename: 'tickets.xlsx',
  checksum_sha256: 'abc',
  status: 'previewed',
  uploaded_at: '2026-11-16T10:00:00Z',
  committed_at: null,
  uploaded_by: 'admin',
  counts: {
    total_rows: 2, blank_rows: 0, sample_rows_skipped: 1, invalid_rows: 1, valid_rows: 0,
    new_tickets: 0, existing_tickets_updated: 0, tickets_closed: 0, tickets_reopened: 0,
    closed_rows_skipped: 0, notifications_attempted: 0, notifications_failed: 0,
  },
  duplicate_of: null,
  error: '',
  rows: [
    { excel_row: 2, outcome: 'sample_skipped', preview_outcome: 'sample_skipped', source_values: { 'Site ID': 'KER-TVM-1029' }, errors: [], portal_ticket_id: null, notification_id: null },
    { excel_row: 3, outcome: 'invalid', preview_outcome: 'invalid', source_values: { 'Site ID': 'BAD' }, errors: [{ field: 'Email ID', message: 'Enter a valid email address.' }], portal_ticket_id: null, notification_id: null },
  ],
};
const DONE: TicketImportBatch = {
  ...PREVIEW,
  status: 'committed',
  committed_at: '2026-11-16T10:01:00Z',
  counts: { ...PREVIEW.counts, invalid_rows: 1, notifications_failed: 0 },
};

beforeEach(() => {
  vi.clearAllMocks();
  m.previewTicketImport.mockResolvedValue(PREVIEW);
  m.commitTicketImport.mockResolvedValue(DONE);
});

describe('Ticket workbook upload', () => {
  it('shows the skipped sample and requires explicit confirmation before committing valid rows', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<TicketUploadPage />, { url: '/tickets/upload' });
    expect(screen.getByRole('link', { name: 'Download Ticket Template' })).toHaveAttribute('href', expect.stringContaining('/tickets/template.xlsx'));

    await user.upload(screen.getByLabelText('Choose Excel workbook'), new File(['workbook'], 'tickets.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Validate & Preview' }));
    expect(await screen.findByText('Row-by-row preview')).toBeInTheDocument();
    expect(await screen.findByText('Template example skipped')).toBeInTheDocument();
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument();

    const importButton = screen.getByRole('button', { name: 'Create / Update Tickets' });
    expect(importButton).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /Continue with valid rows only/ }));
    await user.click(importButton);
    expect(m.commitTicketImport).toHaveBeenCalledWith(8, { accept_invalid: true, confirm_duplicate: false });
    expect(await screen.findByText('Import completed')).toBeInTheDocument();
  });

  it('shows calculated numeric values returned by the preview API', async () => {
    const user = userEvent.setup();
    m.previewTicketImport.mockResolvedValue({
      ...PREVIEW,
      counts: { ...PREVIEW.counts, invalid_rows: 0, valid_rows: 1 },
      rows: [{
        excel_row: 3,
        outcome: 'create',
        preview_outcome: 'valid',
        source_values: { 'Site ID': 'MP-TST-001' },
        values: { outage_minutes: '165', mttr_hours: '2.75' },
        errors: [],
        portal_ticket_id: null,
        notification_id: null,
      }],
    });
    renderWithWorkbook(<TicketUploadPage />, { url: '/tickets/upload' });

    await user.upload(screen.getByLabelText('Choose Excel workbook'), new File(['workbook'], 'tickets.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Validate & Preview' }));

    expect(await screen.findByRole('columnheader', { name: 'Outage Min.' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'MTTR (Hrs.)' })).toBeInTheDocument();
    expect(screen.getByText('165')).toBeInTheDocument();
    expect(screen.getByText('2.75')).toBeInTheDocument();
  });

  it('renders numeric zero values instead of replacing them with dashes', async () => {
    const user = userEvent.setup();
    m.previewTicketImport.mockResolvedValue({
      ...PREVIEW,
      counts: { ...PREVIEW.counts, invalid_rows: 0, valid_rows: 1 },
      rows: [{
        excel_row: 4,
        outcome: 'create',
        preview_outcome: 'valid',
        source_values: { 'Site ID': 'MP-TST-001' },
        values: { outage_minutes: 0, mttr_hours: 0 },
        errors: [],
        portal_ticket_id: null,
        notification_id: null,
      }],
    });
    renderWithWorkbook(<TicketUploadPage />, { url: '/tickets/upload' });

    await user.upload(screen.getByLabelText('Choose Excel workbook'), new File(['workbook'], 'tickets.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Validate & Preview' }));

    const row = await screen.findByRole('row', { name: /4 MP-TST-001/ });
    expect(within(row).getAllByRole('cell', { name: '0' })).toHaveLength(2);
  });

  it('shows the formula-cache validation message with its Excel row and field', async () => {
    const user = userEvent.setup();
    m.previewTicketImport.mockResolvedValue({
      ...PREVIEW,
      rows: [{
        excel_row: 7,
        outcome: 'invalid',
        preview_outcome: 'invalid',
        source_values: { 'Site ID': 'MP-TST-001' },
        values: { outage_minutes: '', mttr_hours: '' },
        errors: [{
          field: 'Outage Min.',
          message: 'Formula result is unavailable. Open the workbook in Excel, recalculate formulas, save the file, and upload again.',
        }],
        portal_ticket_id: null,
        notification_id: null,
      }],
    });
    renderWithWorkbook(<TicketUploadPage />, { url: '/tickets/upload' });

    await user.upload(screen.getByLabelText('Choose Excel workbook'), new File(['workbook'], 'tickets.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Validate & Preview' }));

    expect(await screen.findByText('Formula result is unavailable. Open the workbook in Excel, recalculate formulas, save the file, and upload again.')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '7' })).toBeInTheDocument();
    expect(screen.getByText('Outage Min.:')).toBeInTheDocument();
  });
});
