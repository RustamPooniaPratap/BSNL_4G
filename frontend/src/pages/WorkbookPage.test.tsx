import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { ApiError } from '../services/api';
import { activeWorkbook } from '../test/fixtures';
import { renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import { WorkbookPage } from './WorkbookPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  uploadWorkbook: vi.fn(),
}));

const uploadWorkbook = vi.mocked(api.uploadWorkbook);
const xlsx = (name = 'Master.xlsx') =>
  new File(['PK'], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });

// mockClear, not mockReset: each test sets its own implementation.
beforeEach(() => { uploadWorkbook.mockClear(); });

describe('WorkbookPage', () => {
  it('shows the workbook in use and its worksheets', () => {
    renderWithWorkbook(<WorkbookPage />);
    expect(screen.getByText('Workbook in use')).toBeInTheDocument();
    expect(screen.getByText(activeWorkbook.workbook)).toBeInTheDocument();
    expect(screen.getByText('Worksheets found (1)')).toBeInTheDocument();
  });

  it('explains that nothing is loaded yet', () => {
    renderWithWorkbook(<WorkbookPage />, { workbook: workbookValue({ active: null }) });
    expect(screen.getByText('No workbook loaded')).toBeInTheDocument();
  });

  it('uploads, reports progress and activates the accepted workbook', async () => {
    const user = userEvent.setup();
    const setActive = vi.fn();
    const accepted = { ...activeWorkbook, workbook: 'New Master.xlsx' };
    uploadWorkbook.mockImplementation(async (_file, onProgress) => {
      onProgress?.(0.5);
      onProgress?.(1);
      return { status: 'accepted', active: accepted };
    });
    renderWithWorkbook(<WorkbookPage />, { workbook: workbookValue({ setActive }) });

    await user.upload(screen.getByLabelText('Choose Master workbook'), xlsx('New Master.xlsx'));
    await user.click(screen.getByRole('button', { name: /upload and validate/i }));

    expect(await screen.findByText(/Workbook accepted\. The dashboard now uses “New Master\.xlsx”/)).toBeInTheDocument();
    expect(setActive).toHaveBeenCalledWith(accepted);
    expect(uploadWorkbook).toHaveBeenCalledWith(expect.objectContaining({ name: 'New Master.xlsx' }), expect.any(Function));
  });

  it('shows validation problems and keeps the current workbook when rejected', async () => {
    const user = userEvent.setup();
    const setActive = vi.fn();
    const rejection = new ApiError(
      "The workbook does not have the expected structure. The previously loaded workbook 'master.xlsx' is still in use.",
      422,
      { problems: ["The workbook 'bad.xlsx' has no 'Up-Time Report' sheet."], previous_workbook_kept: true },
    );
    uploadWorkbook.mockImplementation(async () => { throw rejection; });
    renderWithWorkbook(<WorkbookPage />, { workbook: workbookValue({ setActive }) });

    await user.upload(screen.getByLabelText('Choose Master workbook'), xlsx('bad.xlsx'));
    await user.click(screen.getByRole('button', { name: /upload and validate/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Workbook not accepted');
    expect(alert).toHaveTextContent("no 'Up-Time Report' sheet");
    expect(alert).toHaveTextContent('is still in use');
    expect(setActive).not.toHaveBeenCalled();
  });

  it('refuses non-.xlsx files before uploading', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderWithWorkbook(<WorkbookPage />);
    await user.upload(screen.getByLabelText('Choose Master workbook'), new File(['a,b'], 'daily.csv', { type: 'text/csv' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('.xlsx');
    expect(uploadWorkbook).not.toHaveBeenCalled();
  });
});
