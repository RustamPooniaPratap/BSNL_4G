import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { CI_USER, authValue, renderWithWorkbook } from '../test/renderWithWorkbook';
import { Sidebar } from './Sidebar';

const nav = () => screen.getByRole('navigation', { name: 'Main' });
const links = () => within(nav()).getAllByRole('link').map((a) => a.textContent);
const Location = () => {
  const { pathname, search } = useLocation();
  return <p data-testid="location">{pathname + search}</p>;
};

describe('Sidebar order and groups', () => {
  it('lists every entry in order for an Admin, with all groups opened', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<Sidebar />, { url: '/portfolio' });
    await user.click(within(nav()).getByRole('button', { name: 'Data Management' }));
    await user.click(within(nav()).getByRole('button', { name: 'Data Entry' }));
    await user.click(within(nav()).getByRole('button', { name: 'CSV Arrival & Follow-up' }));
    expect(links()).toEqual(['Site Portfolio', 'Overview', '4G Saturation', 'LWE', 'Threshold Analysis', 'Team Performance',
      'RCA Register', 'RCA Summary', 'Cause Mapping', 'RCA Import',
      'Data Source', 'Data Source & Quality', 'Add Row', 'Upload CSV', 'Add Site', 'CSV Arrival Tracking', 'Users & Roles']);
    expect(within(nav()).getByText('Data')).toBeInTheDocument();
    expect(within(nav()).getByText('Administration')).toBeInTheDocument();
  });

  it('keeps closed groups out of the tab order and the accessibility tree', () => {
    renderWithWorkbook(<Sidebar />, { url: '/portfolio' });
    expect(within(nav()).getByRole('button', { name: 'Data Entry' })).toHaveAttribute('aria-expanded', 'false');
    expect(within(nav()).queryByRole('link', { name: 'Add Row' })).not.toBeInTheDocument();
    expect(document.getElementById('nav-group-data-entry')).toHaveAttribute('inert');
  });

  it('opens Overview from its label and toggles its children only from the chevron', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><Location /></>, { url: '/portfolio' });
    const chevron = within(nav()).getByRole('button', { name: 'Collapse Overview' });
    await user.click(chevron);
    expect(within(nav()).queryByRole('link', { name: 'LWE' })).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/portfolio');  // the chevron does not navigate
    await user.click(within(nav()).getByRole('button', { name: 'Expand Overview' }));
    expect(within(nav()).getByRole('link', { name: 'LWE' })).toBeInTheDocument();

    await user.click(within(nav()).getByRole('link', { name: 'Overview' }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
    expect(within(nav()).getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
  });

  it('opens the group of the current page on a direct visit (refresh) and highlights the page', () => {
    renderWithWorkbook(<Sidebar />, { url: '/data-source' });
    expect(within(nav()).getByRole('button', { name: 'Data Management' })).toHaveAttribute('aria-expanded', 'true');
    expect(within(nav()).getByRole('link', { name: 'Data Source & Quality' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).getByRole('button', { name: 'Data Entry' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('highlights 4G Saturation and LWE by their query parameter, and reopens Overview when one is reached', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><Link to="/?report_type=LWE&trend=weekly">go</Link></>, { url: '/thresholds' });
    await user.click(within(nav()).getByRole('button', { name: 'Collapse Overview' }));
    await user.click(screen.getByRole('link', { name: 'go' }));
    expect(within(nav()).getByRole('button', { name: 'Collapse Overview' })).toHaveAttribute('aria-expanded', 'true');
    expect(within(nav()).getByRole('link', { name: 'LWE' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current');
  });

  it('links every entry to its existing route', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<Sidebar />, { url: '/data/new-site' });
    await user.click(within(nav()).getByRole('button', { name: 'Data Management' }));
    await user.click(within(nav()).getByRole('button', { name: 'CSV Arrival & Follow-up' }));
    const href = (name: string) => within(nav()).getByRole('link', { name }).getAttribute('href');
    expect(Object.fromEntries(['Site Portfolio', 'Overview', '4G Saturation', 'LWE', 'Threshold Analysis', 'Team Performance', 'Data Source',
      'Data Source & Quality', 'Add Row', 'Upload CSV', 'Add Site', 'CSV Arrival Tracking', 'Users & Roles'].map((n) => [n, href(n)]))).toEqual({
      'Site Portfolio': '/portfolio', Overview: '/', '4G Saturation': '/?report_type=4G+Saturation', LWE: '/?report_type=LWE',
      'Threshold Analysis': '/thresholds', 'Team Performance': '/teams', 'Data Source': '/workbook', 'Data Source & Quality': '/data-source',
      'Add Row': '/data/add-row', 'Upload CSV': '/data/upload-csv', 'Add Site': '/data/new-site',
      'CSV Arrival Tracking': '/daily-ingestion', 'Users & Roles': '/admin/users',
    });
  });

  it('opens CSV Arrival & Follow-up on its page', () => {
    renderWithWorkbook(<Sidebar />, { url: '/daily-ingestion' });
    expect(within(nav()).getByRole('button', { name: 'CSV Arrival & Follow-up' })).toHaveAttribute('aria-expanded', 'true');
    expect(within(nav()).getByRole('link', { name: 'CSV Arrival Tracking' })).toHaveAttribute('aria-current', 'page');
  });

  it('nests Uptime Buckets & Site Details under Threshold Analysis: the label opens the main page, the chevron toggles', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><Location /></>, { url: '/thresholds/buckets?report_type=LWE' });
    expect(within(nav()).getByRole('button', { name: 'Collapse Threshold Analysis' })).toHaveAttribute('aria-expanded', 'true');  // opened on its subpage
    expect(within(nav()).getByRole('link', { name: 'Uptime Buckets & Site Details' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).getByRole('link', { name: 'Threshold Analysis' })).not.toHaveAttribute('aria-current');
    await user.click(within(nav()).getByRole('button', { name: 'Collapse Threshold Analysis' }));
    expect(within(nav()).queryByRole('link', { name: 'Uptime Buckets & Site Details' })).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/thresholds/buckets');
    await user.click(within(nav()).getByRole('link', { name: 'Threshold Analysis' }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/thresholds$/);
    expect(within(nav()).getByRole('link', { name: 'Uptime Buckets & Site Details' })).toHaveAttribute('href', '/thresholds/buckets');  // reopened
  });

  it('shows a CI only the groups and pages a CI may open', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<Sidebar />, { url: '/portfolio', auth: authValue({ user: CI_USER }) });
    expect(within(nav()).getByText('Data')).toBeInTheDocument();  // Data Management and Data Entry remain
    expect(within(nav()).queryByRole('button', { name: 'CSV Arrival & Follow-up' })).not.toBeInTheDocument();
    await user.click(within(nav()).getByRole('button', { name: 'Data Management' }));
    expect(within(nav()).queryByRole('link', { name: 'Data Source' })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'Team Performance', hidden: true })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'CSV Arrival Tracking', hidden: true })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'Users & Roles', hidden: true })).not.toBeInTheDocument();
  });
});
