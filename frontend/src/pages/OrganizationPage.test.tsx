import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/api';
import { renderWithWorkbook } from '../test/renderWithWorkbook';
import type { OrgAccessUser, OrgAlias, OrgAssociation, OrgCircle, OrgProject, OrgUsage, OrganizationCatalog } from '../types/organization';
import { OrganizationPage } from './OrganizationPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchOrganizationCatalog: vi.fn(), fetchOrgProjects: vi.fn(), fetchOrgCircles: vi.fn(), fetchOrgAssociations: vi.fn(), fetchOrgAliases: vi.fn(),
  fetchOrgAccess: vi.fn(), fetchOrgHistory: vi.fn(), createOrgCircle: vi.fn(), updateOrgProject: vi.fn(), createOrgAssociation: vi.fn(),
  removeOrgAssociation: vi.fn(), setOrgAccess: vi.fn(), deleteOrgCircle: vi.fn(),
}));
vi.setConfig({ testTimeout: 20000 });

/** Synthetic organization: MP and OD in both projects, RJ in 4G only, BH in LWE only. */
const none: OrgUsage = { sites: 0, on_air_sites: 0, daily: 0, monthly: 0, uploads: 0, rca: 0, rca_expected: 0, escalation: 0, users: 0 };
const usage = (sites: number, extra: Partial<OrgUsage> = {}): OrgUsage => ({ ...none, sites, on_air_sites: sites, daily: sites * 10, monthly: sites, ...extra });
const PAIRS: [string, string, OrgUsage][] = [
  ['4G Saturation', 'MP', usage(1483)], ['4G Saturation', 'OD', usage(1603)], ['4G Saturation', 'RJ', usage(1458)],
  ['LWE', 'MP', usage(22)], ['LWE', 'OD', usage(256)], ['LWE', 'BH', none],
];
const catalog: OrganizationCatalog = {
  projects: [{ key: '4G Saturation', code: '4G', name: '4G Saturation', is_active: true }, { key: 'LWE', code: 'LWE', name: 'LWE', is_active: true }],
  circles: ['BH', 'MP', 'OD', 'RJ'].map((code) => ({ code, name: `Circle ${code}`, is_active: true })),
  associations: PAIRS.map(([project, circle]) => ({ project, circle, is_active: true })),
};
const projects: OrgProject[] = catalog.projects.map((p, i) => ({
  id: i + 1, ...p, description: '', circles: PAIRS.filter(([k]) => k === p.key).map(([, code]) => ({ code, is_active: true })), usage: none,
  created_at: '2026-10-30T10:00:00', updated_at: '2026-10-30T10:00:00',
}));
const circles: OrgCircle[] = catalog.circles.map((c, i) => ({
  id: i + 1, ...c, description: '', aliases: c.code === 'OD' ? 1 : 0, deletable: false, created_at: '2026-10-30T10:00:00', updated_at: '2026-10-30T10:00:00',
  projects: PAIRS.filter(([, code]) => code === c.code).map(([project, , u]) => ({ project, project_code: project === 'LWE' ? 'LWE' : '4G', is_active: true, usage: u })),
  unassociated_data: c.code === 'RJ' ? [{ project: 'LWE', usage: { ...none, rca: 1 } }] : [],
}));
const associations: OrgAssociation[] = PAIRS.map(([project, circle, u], i) => ({
  id: i + 1, project, project_code: project === 'LWE' ? 'LWE' : '4G', project_active: true, circle, circle_name: `Circle ${circle}`, circle_active: true,
  is_active: true, usage: u, created_at: '2026-10-30T10:00:00',
}));
const aliases: OrgAlias[] = [{
  id: 1, source: 'raw_daily_csv', source_label: 'Raw daily CSV (network availability dump)', project: null, raw_code: 'OR', circle: 'OD', circle_name: 'Circle OD',
  is_active: true, notes: 'Verified on the Odisha dump.', problems: [], created_by: 'system', updated_at: '2026-10-30T10:00:00',
}];
const ci = (over: Partial<OrgAccessUser>): OrgAccessUser => ({
  id: 7, username: 'ci.mp', name: '', role: 'ci', role_label: 'CI', is_active: true, limited: true, pairs: [], legacy_circles: [], needs_review: false, ...over,
});

const page = (url: string) => renderWithWorkbook(<OrganizationPage />, { url });
const tabs = () => screen.getByRole('navigation', { name: 'Organization sections' });

beforeEach(() => {
  vi.mocked(api.fetchOrganizationCatalog).mockResolvedValue(catalog);
  vi.mocked(api.fetchOrgProjects).mockResolvedValue({ projects });
  vi.mocked(api.fetchOrgCircles).mockResolvedValue({ circles });
  vi.mocked(api.fetchOrgAssociations).mockResolvedValue({ associations });
  vi.mocked(api.fetchOrgAliases).mockResolvedValue({ aliases, sources: [{ value: 'raw_daily_csv', label: 'Raw daily CSV (network availability dump)' }],
    site_id_mapping: [{ project: '4G Saturation', configured: true, rule: 'The raw BTS IP ID is the master site ID.' },
      { project: 'LWE', configured: false, rule: 'Not configured: the authoritative mapping has not been supplied.' }] });
  vi.mocked(api.fetchOrgAccess).mockResolvedValue({ users: [ci({ pairs: [{ project: '4G Saturation', circle: 'MP' }] }), ci({ id: 8, username: 'ci.od', legacy_circles: ['OD'], needs_review: true }),
    { ...ci({ id: 1, username: 'asha.admin' }), role: 'admin', role_label: 'Admin', limited: false }] });
  vi.mocked(api.fetchOrgHistory).mockResolvedValue({ changes: [{ id: 1, entity_type: 'circle', entity_id: '4', entity_label: 'RJ', action: 'updated', previous: { name: 'Raj' },
    new: { name: 'Rajasthan' }, actor: 'asha.admin', reason: 'Spelling', created_at: '2026-10-30T11:00:00' }] });
});

describe('Organization page', () => {
  it('has six tabs in one page, opens a tab from its URL and sends an unknown tab to Projects', async () => {
    page('/admin/organization/circles');
    expect(within(tabs()).getAllByRole('link').map((a) => a.textContent))
      .toEqual([
        'Projects',
        'Circles',
        'Operational Areas',
        'Project-Circle Mapping',
        'O&M Assignments',
        'Personnel Master',
        'Site Assignments',
        'Mappings & Conflicts',
        'Personnel Merge',
        'User Access',
        'Code Mapping',
        'Change History',
      ]);
    expect(within(tabs()).getByRole('link', { name: 'Circles' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('row', { name: 'Circle MP' })).toBeInTheDocument();
  });

  it('redirects an unknown tab to Projects', async () => {
    page('/admin/organization/nope');
    expect(await screen.findByRole('row', { name: 'Project 4G Saturation' })).toBeInTheDocument();
    expect(within(tabs()).getByRole('link', { name: 'Projects' })).toHaveAttribute('aria-current', 'page');
  });

  it('deactivates a project only after confirmation, with the reason for the history', async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateOrgProject).mockResolvedValue({ project: { ...projects[1], is_active: false } });
    page('/admin/organization');
    const row = await screen.findByRole('row', { name: 'Project LWE' });
    expect(within(row).getByText('MP, OD, BH')).toBeInTheDocument();
    await user.click(within(row).getByRole('button', { name: 'Deactivate LWE' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Deactivate LWE' });
    expect(dialog).toHaveTextContent('records are kept');
    expect(api.updateOrgProject).not.toHaveBeenCalled();
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason (optional)' }), 'Project closed');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    expect(api.updateOrgProject).toHaveBeenCalledWith(2, { is_active: false, reason: 'Project closed' });
    expect(await screen.findByRole('status')).toHaveTextContent('LWE deactivated.');
  });

  it('adds a circle once, without sites, and shows each project\'s own records for a shared circle', async () => {
    const user = userEvent.setup();
    vi.mocked(api.createOrgCircle).mockResolvedValue({ circles });
    page('/admin/organization/circles');
    const mp = await screen.findByRole('row', { name: 'Circle MP' });
    expect(mp).toHaveTextContent('4G: 1,483 sites');
    expect(mp).toHaveTextContent('LWE: 22 sites');  // one MP record, separate site counts per project
    expect(screen.getByRole('row', { name: 'Circle RJ' })).toHaveTextContent('Not associated with LWE, but has 1 RCA');
    expect(screen.getByRole('row', { name: 'Circle BH' })).toHaveTextContent('LWE: No records');
    await user.click(screen.getByRole('button', { name: 'Add circle' }));
    await user.type(screen.getByLabelText(/Code \(stored on records\)/), 'kl');
    await user.type(screen.getByLabelText(/^Name/), 'Kerala');
    await user.click(within(screen.getByRole('form', { name: 'Add a circle' })).getByRole('button', { name: 'Add circle' }));
    expect(api.createOrgCircle).toHaveBeenCalledWith({ code: 'KL', name: 'Kerala', description: '', reason: '' });
    expect(await screen.findByRole('status')).toHaveTextContent('Circle KL added. Associate it with a project');
  });

  it('maps circles to projects as membership only, and removes only an unused association', async () => {
    page('/admin/organization/mapping');
    const matrix = await screen.findByRole('table', { name: 'Project-circle matrix' });
    const row = (code: string) => within(matrix).getAllByRole('row').find((r) => within(r).queryByText(code))!;
    expect(within(row('MP')).getAllByRole('cell').map((c) => c.textContent)).toEqual(['MP', 'Yes', 'Yes']);
    expect(within(row('RJ')).getAllByRole('cell').map((c) => c.textContent)).toEqual(['RJ', 'Yes', 'No']);
    expect(within(screen.getByRole('row', { name: 'MP under LWE' })).getAllByRole('cell')[2]).toHaveTextContent('22');
    expect(screen.getByText(/Membership only/)).toHaveTextContent('creates no sites, daily or monthly data, reporting obligation, user access or RCA records');
  });

  it('removes an association only after the exact name is typed, with one request', async () => {
    const user = userEvent.setup();
    vi.mocked(api.removeOrgAssociation).mockResolvedValue({ associations, outcome: 'removed', dependencies: {} });
    page('/admin/organization/mapping');
    const row = await screen.findByRole('row', { name: 'BH under LWE' });
    await user.click(within(row).getByRole('button', { name: 'Remove BH from LWE' }));
    const dialog = screen.getByRole('dialog', { name: 'Remove BH from LWE' });
    expect(api.removeOrgAssociation).not.toHaveBeenCalled();  // opening the dialog sends nothing
    expect(dialog).toHaveTextContent('Nothing refers to it, so it is removed.');
    const confirm = within(dialog).getByRole('button', { name: 'Confirm removal' });
    const box = within(dialog).getByRole('textbox', { name: 'Type BH - LWE to confirm' });
    await user.type(box, 'BH - lwe');
    expect(confirm).toBeDisabled();  // not the exact text
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.removeOrgAssociation).not.toHaveBeenCalled();  // Cancel does nothing
    await user.click(within(row).getByRole('button', { name: 'Remove BH from LWE' }));
    const again = screen.getByRole('dialog', { name: 'Remove BH from LWE' });
    await user.type(within(again).getByRole('textbox', { name: 'Type BH - LWE to confirm' }), 'BH - LWE');
    await user.click(within(again).getByRole('button', { name: 'Confirm removal' }));
    expect(api.removeOrgAssociation).toHaveBeenCalledTimes(1);
    expect(api.removeOrgAssociation).toHaveBeenCalledWith(6, { reason: '' });
    expect(await screen.findByRole('status')).toHaveTextContent('BH removed from LWE.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('says so when Remove keeps a used association inactive instead', async () => {
    const user = userEvent.setup();
    vi.mocked(api.removeOrgAssociation).mockResolvedValue({ associations, outcome: 'deactivated', dependencies: { sites: 1483, daily: 14830 } });
    page('/admin/organization/mapping');
    const row = await screen.findByRole('row', { name: 'MP under 4G Saturation' });
    await user.click(within(row).getByRole('button', { name: 'Remove MP from 4G Saturation' }));
    const dialog = screen.getByRole('dialog', { name: 'Remove MP from 4G Saturation' });
    expect(dialog).toHaveTextContent('so it will not be deleted: it is kept and deactivated');
    expect(dialog).toHaveTextContent('global circle and its other project associations stay');
    await user.type(within(dialog).getByRole('textbox', { name: 'Type MP - 4G Saturation to confirm' }), 'MP - 4G Saturation');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm removal' }));
    expect(await screen.findByRole('status')).toHaveTextContent('MP under 4G Saturation was not removed because records refer to it (1,483 sites, 14,830 daily values); it is now inactive.');
  });

  it('deletes only a circle that nothing refers to, after typing its identity', async () => {
    const user = userEvent.setup();
    vi.mocked(api.fetchOrgCircles).mockResolvedValue({ circles: [...circles, { ...circles[0], id: 9, code: 'KL', name: 'Kerala', projects: [], aliases: 0, deletable: true }] });
    vi.mocked(api.deleteOrgCircle).mockResolvedValue({ circles });
    page('/admin/organization/circles');
    expect(within(await screen.findByRole('row', { name: 'Circle MP' })).getByRole('button', { name: 'Delete MP' })).toBeDisabled();
    await user.click(within(screen.getByRole('row', { name: 'Circle KL' })).getByRole('button', { name: 'Delete KL' }));
    const dialog = screen.getByRole('dialog', { name: 'Delete circle KL · Kerala' });
    await user.type(within(dialog).getByRole('textbox', { name: 'Type KL - Kerala to confirm' }), 'KL - Kerala');
    await user.click(within(dialog).getByRole('button', { name: 'Delete circle' }));
    expect(api.deleteOrgCircle).toHaveBeenCalledWith(9, { reason: '' });
    expect(await screen.findByRole('status')).toHaveTextContent('Circle KL deleted.');
  });

  it('keeps a refused removal open with the server\'s message and shows no success', async () => {
    const user = userEvent.setup();
    vi.mocked(api.removeOrgAssociation).mockRejectedValue(Object.assign(new Error('Request failed'), { details: { form: ['Database unavailable.'] } }));
    page('/admin/organization/mapping');
    const row = await screen.findByRole('row', { name: 'BH under LWE' });
    await user.click(within(row).getByRole('button', { name: 'Remove BH from LWE' }));
    const dialog = screen.getByRole('dialog', { name: 'Remove BH from LWE' });
    await user.type(within(dialog).getByRole('textbox', { name: 'Type BH - LWE to confirm' }), 'BH - LWE');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm removal' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Database unavailable.');  // inside the dialog, which stays open
    expect(screen.queryByRole('status')).not.toBeInTheDocument();  // no success shown
    expect(api.removeOrgAssociation).toHaveBeenCalledTimes(1);
  });

  it('grants a shared circle per project: MP under 4G does not include MP under LWE', async () => {
    const user = userEvent.setup();
    vi.mocked(api.setOrgAccess).mockResolvedValue({ user: ci({}) });
    page('/admin/organization/access');
    const row = await screen.findByRole('row', { name: 'Access of ci.mp' });
    expect(row).toHaveTextContent('MP · 4G Saturation');
    expect(screen.getByRole('row', { name: 'Access of asha.admin' })).toHaveTextContent('Every project and circle (role)');
    expect(screen.getByRole('row', { name: 'Access of ci.od' })).toHaveTextContent('OD · every project (review)');
    expect(screen.getAllByRole('status')[0]).toHaveTextContent('1 user has a legacy circle-only assignment');
    await user.click(within(row).getByRole('button', { name: 'Edit access of ci.mp' }));
    const editor = await screen.findByRole('group', { name: 'Access of ci.mp' });
    const mp4g = await within(editor).findByRole('checkbox', { name: 'MP under 4G Saturation' });
    const mpLwe = within(editor).getByRole('checkbox', { name: 'MP under LWE' });
    expect([mp4g, mpLwe].map((c) => (c as HTMLInputElement).checked)).toEqual([true, false]);
    await user.click(within(editor).getByRole('checkbox', { name: 'OD under LWE' }));
    await user.click(within(editor).getByRole('button', { name: 'Save access' }));
    expect(api.setOrgAccess).toHaveBeenCalledWith(7, [{ project: '4G Saturation', circle: 'MP' }, { project: 'LWE', circle: 'OD' }], '');
  });

  it('lists the verified code mappings and keeps the history read only', async () => {
    const user = userEvent.setup();
    page('/admin/organization/code-mapping');
    const row = await screen.findByRole('row', { name: /Mapping OR/ });
    expect(row).toHaveTextContent('Every project');
    expect(row).toHaveTextContent('OD · Circle OD');
    const siteIds = screen.getByRole('region', { name: 'Site identifier mapping' });
    expect(siteIds).toHaveTextContent('LWENot configured');
    await user.click(within(tabs()).getByRole('link', { name: 'Change History' }));
    await waitFor(() => expect(within(tabs()).getByRole('link', { name: 'Change History' })).toHaveAttribute('aria-current', 'page'));
    const change = await screen.findByRole('row', { name: /RJ/ });
    expect(change).toHaveTextContent('name: Raj → name: Rajasthan');
    expect(change).toHaveTextContent('asha.admin');
    expect(within(change).queryByRole('button')).not.toBeInTheDocument();
  });
});
