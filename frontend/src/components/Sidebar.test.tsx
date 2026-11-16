import { screen, waitFor, within } from '@testing-library/react';
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
    await user.click(within(nav()).getByRole('button', { name: 'Uptime Data' }));
    await user.click(within(nav()).getByRole('button', { name: 'Data Arrival & Follow-up' }));
    await user.click(within(nav()).getByRole('button', { name: 'Alert' }));
    await user.click(within(nav()).getByRole('button', { name: "All KPI's" }));
    expect(links()).toEqual(['Site Portfolio', 'Master Data', 'Overview', '4G Saturation', 'LWE', 'Threshold Analysis', 'Team Performance',
      'All KPIs – Overview', 'KPI Trends (Month / Week)', 'Ranking', 'Availability', 'Outage Minutes', 'USD Sites', 'NSLA Sites', 'Sites Below 98.5%',
      'Sites Below 60%', 'RCA', 'Circle / CI / IE / Site', 'RCA Register', 'RCA Summary', 'RCA Submissions', 'Upload Circle RCA',
      'Data Source', 'Data Source & Quality', 'Uptime Data Upload', 'CSV Arrival Tracking', 'Users & Roles', 'Organization',
      'Email Setup', 'Automations', 'Email History']);
    expect(within(nav()).getByText('Data')).toBeInTheDocument();
    expect(within(nav()).getByText('Administration')).toBeInTheDocument();
  });

  it('groups the RCA Summary pages, opens the Overview from the label and keeps the filters inside the section', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><Location /></>, { url: '/rca/summary/breakdown?project=LWE&circle=BH' });
    const group = document.getElementById('nav-group-rca-summary')!;
    expect(within(group).getAllByRole('link').map((a) => a.textContent))
      .toEqual(['Overview', 'Circle-wise RCA Breakdown', 'Root Cause Analysis', 'Project & Circle Analysis', 'Daily & Monthly Trends']);
    expect(within(group).getByRole('link', { name: 'Circle-wise RCA Breakdown' })).toHaveAttribute('aria-current', 'page');
    expect(within(group).getByRole('link', { name: 'Daily & Monthly Trends' })).toHaveAttribute('href', '/rca/summary/trends?project=LWE&circle=BH');
    await user.click(within(nav()).getByRole('link', { name: 'RCA Summary' }));  // the label opens the Overview
    expect(screen.getByTestId('location')).toHaveTextContent('/rca/summary?project=LWE&circle=BH');
    expect(within(group).getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    await user.click(within(nav()).getByRole('link', { name: 'RCA Register' }));
    expect(within(nav()).getByRole('link', { name: 'RCA Summary' })).toHaveAttribute('href', '/rca/summary');  // outside: no carried filters
  });

  it('has one Organization entry under Administration, active on every Organization tab', () => {
    renderWithWorkbook(<Sidebar />, { url: '/admin/organization/code-mapping' });
    expect(within(nav()).getByRole('link', { name: 'Organization' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).queryByRole('link', { name: 'Code Mapping' })).not.toBeInTheDocument();  // tabs are inside the page
  });

  it('shows no Organization or Alert entry to a CI user', () => {
    renderWithWorkbook(<Sidebar />, { url: '/portfolio', auth: authValue({ user: CI_USER }) });
    expect(within(nav()).queryByRole('link', { name: 'Organization' })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('button', { name: 'Alert' })).not.toBeInTheDocument();
  });

  it('shows no RCA Summary pages to a CI user', () => {
    renderWithWorkbook(<Sidebar />, { url: '/rca', auth: authValue({ user: CI_USER }) });
    expect(within(nav()).queryByRole('link', { name: 'RCA Summary' })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'Root Cause Analysis' })).not.toBeInTheDocument();
  });

  it('keeps closed groups out of the tab order and the accessibility tree', () => {
    renderWithWorkbook(<Sidebar />, { url: '/portfolio' });
    expect(within(nav()).getByRole('button', { name: 'Uptime Data' })).toHaveAttribute('aria-expanded', 'false');
    expect(within(nav()).queryByRole('link', { name: 'Uptime Data Upload' })).not.toBeInTheDocument();
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
    expect(within(nav()).getByRole('button', { name: 'Uptime Data' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('nests KPI sections, preserves filters on tab navigation, and expands the active route on refresh', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><Location /></>, { url: '/all-kpis?tab=availability&project=4G%20Saturation&circle=MP' });
    const group = within(nav()).getByRole('button', { name: "All KPI's" });
    expect(group).toHaveAttribute('aria-expanded', 'true');
    expect(within(nav()).getByRole('link', { name: 'Availability' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav()).getByText('Overview & Reports')).toBeInTheDocument();
    expect(within(nav()).getByText('Performance KPIs')).toBeInTheDocument();
    expect(within(nav()).getByText('Analysis')).toBeInTheDocument();

    await user.click(group);
    expect(within(nav()).queryByRole('link', { name: 'Availability' })).not.toBeInTheDocument();
    await user.click(group);
    await user.click(within(nav()).getByRole('link', { name: 'Outage Minutes' }));
    expect(screen.getByTestId('location')).toHaveTextContent('tab=outage');
    expect(screen.getByTestId('location')).toHaveTextContent(/project=4G(?:%20|\+)Saturation/);
    expect(screen.getByTestId('location')).toHaveTextContent('circle=MP');
    expect(within(nav()).getByRole('link', { name: 'Outage Minutes' })).toHaveAttribute('aria-current', 'page');
  });

  it('navigates each existing KPI section to its matching tab query', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<><Sidebar /><Location /></>, { url: '/portfolio' });
    await user.click(within(nav()).getByRole('button', { name: "All KPI's" }));
    const destinations = [
      ['All KPIs – Overview', '/all-kpis'],
      ['KPI Trends (Month / Week)', '/all-kpis?tab=trends'],
      ['Ranking', '/all-kpis?tab=ranking'],
      ['Availability', '/all-kpis?tab=availability'],
      ['Outage Minutes', '/all-kpis?tab=outage'],
      ['USD Sites', '/all-kpis?tab=usd'],
      ['NSLA Sites', '/all-kpis?tab=nsla'],
      ['Sites Below 98.5%', '/all-kpis?tab=below_98_5'],
      ['Sites Below 60%', '/all-kpis?tab=below_60'],
      ['RCA', '/all-kpis?tab=rca'],
      ['Circle / CI / IE / Site', '/all-kpis?tab=drilldown'],
    ];
    for (const [label, href] of destinations) {
      const link = within(nav()).getByRole('link', { name: label });
      expect(link).toHaveAttribute('href', href);
      await user.click(link);
      await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(href));
      expect(within(nav()).getByRole('link', { name: label })).toHaveAttribute('aria-current', 'page');
    }
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
    renderWithWorkbook(<Sidebar />, { url: '/data/upload-csv' });
    await user.click(within(nav()).getByRole('button', { name: 'Data Management' }));
    await user.click(within(nav()).getByRole('button', { name: 'Data Arrival & Follow-up' }));
    const href = (name: string) => within(nav()).getByRole('link', { name }).getAttribute('href');
    expect(Object.fromEntries(['Site Portfolio', 'Master Data', 'Overview', '4G Saturation', 'LWE', 'Threshold Analysis', 'Team Performance', 'Data Source',
      'Data Source & Quality', 'Uptime Data Upload', 'CSV Arrival Tracking', 'Users & Roles'].map((n) => [n, href(n)]))).toEqual({
      'Site Portfolio': '/portfolio', 'Master Data': '/master-data', Overview: '/', '4G Saturation': '/?report_type=4G+Saturation', LWE: '/?report_type=LWE',
      'Threshold Analysis': '/thresholds', 'Team Performance': '/teams', 'Data Source': '/workbook', 'Data Source & Quality': '/data-source',
      'Uptime Data Upload': '/data/upload-csv',
      'CSV Arrival Tracking': '/daily-ingestion', 'Users & Roles': '/admin/users',
    });
  });

  it('lists only the Uptime Data Upload under Uptime Data (Add Row and Add Site were removed)', () => {
    renderWithWorkbook(<Sidebar />, { url: '/data/upload-csv' });
    expect(within(nav()).getByRole('button', { name: 'Uptime Data' })).toHaveAttribute('aria-expanded', 'true');
    const labels = within(nav()).getAllByRole('link').map((a) => a.textContent);
    expect(labels.slice(labels.indexOf('Uptime Data Upload'), labels.indexOf('Uptime Data Upload') + 2)).toEqual(['Uptime Data Upload', 'Users & Roles']);
    expect(within(nav()).getByRole('link', { name: 'Uptime Data Upload' })).toHaveAttribute('aria-current', 'page');
    for (const removed of ['Add Row', 'Add Site']) expect(within(nav()).queryByRole('link', { name: removed })).not.toBeInTheDocument();
  });

  it('opens Data Arrival & Follow-up on its page', () => {
    renderWithWorkbook(<Sidebar />, { url: '/daily-ingestion' });
    expect(within(nav()).getByRole('button', { name: 'Data Arrival & Follow-up' })).toHaveAttribute('aria-expanded', 'true');
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
    expect(within(nav()).getByText('Data')).toBeInTheDocument();  // Data Management and Uptime Data remain
    expect(within(nav()).queryByRole('button', { name: 'Data Arrival & Follow-up' })).not.toBeInTheDocument();
    await user.click(within(nav()).getByRole('button', { name: 'Data Management' }));
    expect(within(nav()).queryByRole('link', { name: 'Data Source' })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'Team Performance', hidden: true })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'CSV Arrival Tracking', hidden: true })).not.toBeInTheDocument();
    expect(within(nav()).queryByRole('link', { name: 'Users & Roles', hidden: true })).not.toBeInTheDocument();
  });
});
