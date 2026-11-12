import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { PopulationSelect } from '../components/PopulationSelect';
import { useDashboardFilters } from '../hooks/useDashboardFilters';
import { POPULATION_STORAGE_KEY } from '../lib/population';
import { filterOptions } from '../test/fixtures';
import { PopulationProvider, usePopulation } from './population';

const Location = () => { const l = useLocation(); return <p data-testid="location">{l.pathname + l.search}</p>; };
const Current = () => { const { scope, label } = usePopulation(); return <p data-testid="population">{scope}|{label}</p>; };
/** A page that still passes the old page default: the global selection must win. */
function LegacyPage() {
  const { filters, setFilters, reset } = useDashboardFilters(filterOptions, { defaultScope: 'om_start' });
  return (
    <>
      <p data-testid="params">{filters?.snapshotParams.toString()}</p>
      <button type="button" onClick={() => setFilters({ scope: 'om_start', circle: 'MP' })}>O&amp;M Start in MP</button>
      <button type="button" onClick={reset}>Reset</button>
    </>
  );
}

function renderApp(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <PopulationProvider>
        <Routes>
          <Route path="*" element={<><Current /><PopulationSelect /><LegacyPage /><Link to="/portfolio">Portfolio</Link><Location /></>} />
        </Routes>
      </PopulationProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => window.localStorage.clear());

describe('Global population', () => {
  it('starts On-Air, mirrors the selection into the URL and offers only On-Air and O&M Start', async () => {
    const user = userEvent.setup();
    renderApp('/');
    expect(screen.getByTestId('population')).toHaveTextContent('on_air|On-Air');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?scope=on_air'));
    await user.click(screen.getByRole('combobox', { name: 'Population' }));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['On-Air', 'O&M Start']);  // no "All sites"
  });

  it('takes the URL first, then localStorage, and persists every change to both', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(POPULATION_STORAGE_KEY, 'om_start');
    const first = renderApp('/thresholds');
    expect(screen.getByTestId('population')).toHaveTextContent('om_start');  // from localStorage
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/thresholds?scope=om_start'));
    first.unmount();

    renderApp('/?scope=on_air');  // a shared link wins over the stored selection
    expect(screen.getByTestId('population')).toHaveTextContent('on_air');
    await waitFor(() => expect(window.localStorage.getItem(POPULATION_STORAGE_KEY)).toBe('on_air'));
    await user.click(screen.getByRole('combobox', { name: 'Population' }));
    await user.click(screen.getByRole('option', { name: 'O&M Start' }));
    expect(screen.getByTestId('population')).toHaveTextContent('om_start');
    expect(window.localStorage.getItem(POPULATION_STORAGE_KEY)).toBe('om_start');
    expect(screen.getByTestId('location')).toHaveTextContent('scope=om_start');
    // Another page keeps the selection (the link has no scope; it is mirrored back into the URL).
    await user.click(screen.getByRole('link', { name: 'Portfolio' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/portfolio?scope=om_start'));
    expect(screen.getByTestId('population')).toHaveTextContent('om_start');
  });

  it('ignores an invalid or "all" scope in the URL and replaces it with the selection', async () => {
    window.localStorage.setItem(POPULATION_STORAGE_KEY, 'om_start');
    renderApp('/?scope=all&circle=MP');
    expect(screen.getByTestId('population')).toHaveTextContent('om_start');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/?scope=om_start&circle=MP'));
  });

  it('drives useDashboardFilters: no page default, setFilters changes it for every page, reset keeps it', async () => {
    const user = userEvent.setup();
    renderApp('/');
    // The legacy defaultScope 'om_start' does not override the global On-Air selection.
    expect(new URLSearchParams(screen.getByTestId('params').textContent!).get('scope')).toBe('on_air');
    await user.click(screen.getByRole('button', { name: 'O&M Start in MP' }));
    expect(screen.getByTestId('population')).toHaveTextContent('om_start');
    const params = new URLSearchParams(screen.getByTestId('params').textContent!);
    expect([params.get('scope'), params.get('circle')]).toEqual(['om_start', 'MP']);
    expect(screen.getByTestId('location')).toHaveTextContent('circle=MP');
    await act(async () => { await user.click(screen.getByRole('button', { name: 'Reset' })); });
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/\?scope=om_start$/);  // page filters cleared, population kept
    expect(screen.getByTestId('population')).toHaveTextContent('om_start');
  });
});
