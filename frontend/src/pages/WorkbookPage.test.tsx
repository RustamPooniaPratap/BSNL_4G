import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { activeWorkbook } from '../test/fixtures';
import { renderWithWorkbook, workbookValue } from '../test/renderWithWorkbook';
import { DataLayerStatus } from './WorkbookPage';

describe('DataLayerStatus', () => {
  it('shows the reporting data read-only: no upload and no source switch', () => {
    renderWithWorkbook(<DataLayerStatus />);
    const card = screen.getByRole('region', { name: 'Reporting data' });
    expect(card).toHaveTextContent('Every dashboard page reads the data layer');
    expect(card).toHaveTextContent(activeWorkbook.month);
    expect(screen.queryByLabelText('Choose Master workbook')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('explains that nothing is loaded yet', () => {
    renderWithWorkbook(<DataLayerStatus />, { workbook: workbookValue({ active: null, message: 'No sites in the site master yet.' }) });
    expect(screen.getByText('No reporting data yet')).toBeInTheDocument();
    expect(screen.getByText(/No sites in the site master yet\./)).toBeInTheDocument();
  });
});
