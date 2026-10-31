import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Sidebar } from '../components/Sidebar';
import { canOpen, homePath } from '../context/auth';
import * as api from '../services/api';
import { authValue, renderWithWorkbook } from '../test/renderWithWorkbook';
import type { AccessRole, AuthUser, PermissionCatalog } from '../types';
import { UsersPage } from './UsersPage';

vi.mock('../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/api')>()),
  fetchAccessRoles: vi.fn(), fetchPermissionCatalog: vi.fn(), createAccessRole: vi.fn(), updateAccessRole: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });

/** An upload-only user (custom role "IE" with RCA Upload › Upload on one circle). */
const IE: AuthUser = { username: 'ie.user', name: 'IE', role: 'member', role_label: 'Assigned access', must_change_password: false,
  permissions: { rca_upload: ['upload'] }, rca_upload: { circle: true, consolidated: false } };
const CATALOG: PermissionCatalog = {
  modules: [
    { key: 'rca_register', label: 'RCA Register', description: 'Records.', actions: [{ key: 'view', label: 'View', description: 'Browse.' }] },
    { key: 'rca_upload', label: 'RCA Upload', description: 'Upload Circle RCA.', actions: [{ key: 'upload', label: 'Upload', description: 'Upload files.' }] },
  ],
  admin_only: ['Organization', 'Users & Roles'],
};
const CI_ROLE: AccessRole = { id: 3, name: 'CI', description: '', system: true, system_key: 'ci', is_active: true, editable: false, assignable: true, global: false,
  permissions: [{ module: 'rca_register', action: 'view' }], users: ['ravi.ci'], created_at: '', updated_at: '' };

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchPermissionCatalog.mockResolvedValue(CATALOG);
  m.fetchAccessRoles.mockResolvedValue({ roles: [CI_ROLE] });
});

describe('permission-based pages', () => {
  it('an upload-only role opens its upload page and nothing else', () => {
    expect(canOpen(IE, '/rca/import')).toBe(true);
    for (const path of ['/', '/portfolio', '/rca', '/rca/summary', '/master-data', '/data/upload-csv', '/admin/users', '/rca/import/consolidated']) {
      expect(canOpen(IE, path)).toBe(false);
    }
    expect(homePath(IE)).toBe('/rca/import');
    renderWithWorkbook(<Sidebar />, { url: '/rca/import', auth: authValue({ user: IE }) });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(['Upload Circle RCA']);
  });
});

describe('Users & Roles › Roles & Permissions', () => {
  it('shows built-in roles read only and creates a custom role with exactly the ticked permissions', async () => {
    const user = userEvent.setup();
    const created: AccessRole = { ...CI_ROLE, id: 9, name: 'IE', system: false, system_key: null, editable: true, permissions: [{ module: 'rca_upload', action: 'upload' }], users: [] };
    m.createAccessRole.mockResolvedValue({ role: created });
    renderWithWorkbook(<UsersPage />, { url: '/admin/users/roles' });
    await user.click(await screen.findByRole('button', { name: /CI/ }));
    expect(await screen.findByRole('checkbox', { name: 'RCA Register: View' })).toBeDisabled();  // built-in: read only
    await user.click(screen.getByRole('button', { name: 'Create role' }));
    await user.type(screen.getByLabelText(/Role name/), 'IE');
    expect(screen.getByRole('checkbox', { name: 'RCA Upload: Upload' })).not.toBeChecked();  // a new role starts with nothing
    await user.click(screen.getByRole('checkbox', { name: 'RCA Upload: Upload' }));
    await user.click(within(screen.getByRole('table', { name: 'Permission matrix' }).closest('div')!.parentElement!).getAllByRole('button', { name: /Create role/ }).at(-1)!);
    await waitFor(() => expect(m.createAccessRole).toHaveBeenCalledWith({ name: 'IE', description: '', permissions: [{ module: 'rca_upload', action: 'upload' }] }));
    expect(await screen.findByText('IE created.')).toBeInTheDocument();
  });
});
