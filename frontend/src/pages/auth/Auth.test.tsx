import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { RequireAdmin, RequireAuth } from '../../components/auth/Guards';
import { Sidebar } from '../../components/Sidebar';
import { AuthProvider } from '../../context/AuthProvider';
import { AppLayout } from '../../layouts/AppLayout';
import * as api from '../../services/api';
import { ADMIN_USER, CI_USER, authValue, renderWithWorkbook } from '../../test/renderWithWorkbook';
import { UsersPage } from '../UsersPage';
import { ChangePasswordPage } from './ChangePasswordPage';
import { LoginPage } from './LoginPage';

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let fetchMock: MockInstance<typeof fetch>;
beforeEach(() => { api.setCsrfToken(null); fetchMock = vi.spyOn(globalThis, 'fetch'); });
afterEach(() => fetchMock.mockRestore());

/** The real AuthProvider against a fake backend. */
function renderApp(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/change-password" element={<RequireAuth allowPasswordChange><ChangePasswordPage /></RequireAuth>} />
          <Route path="*" element={<RequireAuth><p>Dashboard</p></RequireAuth>} />
        </Routes>
        <Location />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('sign-in', () => {
  it('sends signed-out users to the login page, and back to where they were after signing in', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/auth/me/')) return json({ error: 'Authentication credentials were not provided.', details: {} }, 401);
      if (url.endsWith('/auth/csrf/')) return json({ csrf_token: 'token-1' });
      if (url.endsWith('/auth/login/')) return json({ user: ADMIN_USER, csrf_token: 'token-2' });
      return json({});
    });
    renderApp('/thresholds');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
    await user.type(screen.getByLabelText('Login ID'), 'asha.admin');
    await user.type(screen.getByLabelText('Password'), 'secret-password');
    await user.click(screen.getByRole('button', { name: /Sign in/ }));
    expect(await screen.findByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/thresholds');
    // Credentials and the CSRF token went with the request; nothing was stored in the browser.
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/auth/login/'))!;
    expect((init as RequestInit).credentials).toBe('include');
    expect(new Headers((init as RequestInit).headers).get('X-CSRFToken')).toBe('token-1');
    expect([window.localStorage.length, window.sessionStorage.length]).toEqual([0, 0]);
  });

  it('shows or hides the password, explains password resets and sends "remember me"', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/auth/me/')) return json({ error: 'x', details: {} }, 401);
      if (url.endsWith('/auth/csrf/')) return json({ csrf_token: 't' });
      return json({ user: ADMIN_USER, csrf_token: 't2' });
    });
    renderApp('/login');
    const password = await screen.findByLabelText('Password');
    expect(password).toHaveAttribute('type', 'password');
    await user.click(screen.getByRole('button', { name: 'Show password' }));
    expect(password).toHaveAttribute('type', 'text');
    await user.click(screen.getByRole('button', { name: 'Forgot password?' }));
    expect(screen.getByText(/Passwords are reset by a portal Admin/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Remember me for 7 days' })).not.toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Remember me for 7 days' }));
    await user.type(screen.getByLabelText('Login ID'), 'asha.admin');
    await user.type(password, 'secret-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByText('Dashboard');
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/auth/login/'))!;
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ username: 'asha.admin', password: 'secret-password', remember: true });
  });

  it('offers "continue without signing in" only when the backend enables the development bypass', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/auth/me/')) return json({ error: 'x', details: {} }, 401);
      if (url.endsWith('/auth/csrf/')) return json({ csrf_token: 't' });
      if (url.endsWith('/auth/dev-login/')) {
        return (init as RequestInit | undefined)?.method === 'POST' ? json({ user: ADMIN_USER, csrf_token: 't2' })
          : json({ enabled: true, username: 'pratap.admin', role: 'admin' });
      }
      return json({});
    });
    renderApp('/portfolio');
    await user.click(await screen.findByRole('button', { name: /Continue without signing in/ }));
    expect(await screen.findByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/portfolio');
  });

  it('hides the bypass when the backend does not offer it (404)', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/auth/me/')) return json({ error: 'x', details: {} }, 401);
      if (url.endsWith('/auth/dev-login/')) return json({ error: 'Not found.', details: {} }, 404);
      return json({ csrf_token: 't' });
    });
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Sign in' });
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/auth/dev-login/'))).toBe(true));
    expect(screen.queryByRole('button', { name: /Continue without signing in/ })).not.toBeInTheDocument();
  });

  it('shows one generic message for any failed sign-in', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/auth/me/')) return json({ error: 'x', details: {} }, 401);
      if (url.endsWith('/auth/csrf/')) return json({ csrf_token: 't' });
      return json({ error: 'Invalid login ID or password.', details: {} }, 400);
    });
    renderApp('/login');
    await user.type(await screen.findByLabelText('Login ID'), 'nobody');
    await user.type(screen.getByLabelText('Password'), 'whatever');
    await user.click(screen.getByRole('button', { name: /Sign in/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid login ID or password.');
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('sends a user with a temporary password to set their own before anything else', async () => {
    fetchMock.mockImplementation(async () => json({ user: { ...CI_USER, must_change_password: true } }));
    renderApp('/portfolio');
    expect(await screen.findByRole('heading', { name: 'Set your password' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/change-password');
  });

  it('returns to the login page with a notice when the session expires', async () => {
    fetchMock.mockImplementation(async () => json({ user: ADMIN_USER }));
    renderApp('/portfolio');
    expect(await screen.findByText('Dashboard')).toBeInTheDocument();
    fetchMock.mockImplementation(async () => json({ error: 'Authentication credentials were not provided.', details: {} }, 401));
    await expect(api.fetchSummary(new URLSearchParams())).rejects.toThrow();
    expect(await screen.findByText('Your session has ended. Sign in again to continue.')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
  });
});

describe('roles in the interface', () => {
  it('hides CSV arrival tracking, team performance, the workbook upload and user management from a CI', async () => {
    const user = userEvent.setup();
    renderWithWorkbook(<Sidebar />, { url: '/portfolio', auth: authValue({ user: CI_USER }) });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    await user.click(within(nav).getByRole('button', { name: 'Data Management' }));
    await user.click(within(nav).getByRole('button', { name: 'Data Entry' }));
    const links = within(nav).getAllByRole('link').map((a) => a.textContent);
    expect(links).toEqual(['Site Portfolio', 'Overview', '4G Saturation', 'LWE', 'Threshold Analysis', 'RCA Register',
      'Data Source & Quality', 'Add Row', 'Upload CSV', 'Add Site']);
    expect(within(nav).queryByText('CSV Arrival & Follow-up')).not.toBeInTheDocument();
    expect(within(nav).queryByText('Administration')).not.toBeInTheDocument();
  });

  it('shows an unauthorized page when a CI opens an Admin page by its URL', () => {
    for (const url of ['/teams', '/daily-ingestion', '/admin/users', '/workbook']) {
      const view = renderWithWorkbook(<Routes><Route path="*" element={<RequireAdmin><p>secret page</p></RequireAdmin>} /></Routes>,
        { url, auth: authValue({ user: CI_USER }) });
      expect(screen.getByRole('heading', { name: 'You do not have access to this page' })).toBeInTheDocument();
      expect(screen.queryByText('secret page')).not.toBeInTheDocument();
      view.unmount();
    }
    renderWithWorkbook(<Routes><Route path="*" element={<RequireAdmin><p>secret page</p></RequireAdmin>} /></Routes>, { url: '/teams' });
    expect(screen.getByText('secret page')).toBeInTheDocument();  // Admin
  });

  it('shows the login ID and role in the account menu, with change password and sign out', async () => {
    const user = userEvent.setup();
    const signOut = vi.fn(async () => {});
    renderWithWorkbook(<><AppLayout><p>page</p></AppLayout><Location /></>, { url: '/portfolio', auth: authValue({ user: CI_USER, signOut }) });
    expect(screen.queryByRole('link', { name: 'Upload workbook' })).not.toBeInTheDocument();  // CI
    await user.click(screen.getByRole('button', { name: 'Account: ravi.ci (CI)' }));
    expect(screen.getByText('ravi.ci · CI')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Change password/ })).toHaveAttribute('href', '/change-password');
    await user.click(screen.getByRole('button', { name: /Sign out/ }));
    expect(signOut).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'));
  });
});

describe('change password', () => {
  it('checks the confirmation locally and shows the server password rules', async () => {
    const user = userEvent.setup();
    const setUser = vi.fn();
    fetchMock.mockImplementation(async (input) => (String(input).endsWith('/auth/csrf/') ? json({ csrf_token: 't' })
      : json({ error: 'Invalid request parameters.', details: { new_password: ['This password is too common.'] } }, 400)));
    renderWithWorkbook(<ChangePasswordPage />, { auth: authValue({ user: { ...CI_USER, must_change_password: true }, setUser }) });
    await user.type(screen.getByLabelText(/Temporary password/), 'Temp-pass-123');
    await user.type(screen.getByLabelText(/^New password/), 'password12345');
    await user.type(screen.getByLabelText(/Confirm new password/), 'password1234');
    await user.click(screen.getByRole('button', { name: /Save password/ }));
    expect(screen.getByText('The two new passwords do not match.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText(/Confirm new password/), '5');
    await user.click(screen.getByRole('button', { name: /Save password/ }));
    expect(await screen.findByText('This password is too common.')).toBeInTheDocument();
    expect(setUser).not.toHaveBeenCalled();
  });
});

describe('user management', () => {
  it('creates a CI and shows the temporary password once', async () => {
    const user = userEvent.setup();
    const created = { id: 7, username: 'meena.ci', name: '', email: '', role: 'ci', is_active: true, is_superuser: false,
      must_change_password: true, last_login: null, date_joined: '2026-10-23T10:00:00' };
    let users = [{ ...created, id: 1, username: 'asha.admin', role: 'admin', must_change_password: false }];
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/auth/csrf/')) return json({ csrf_token: 't' });
      if (url.endsWith('/auth/users/') && (init as RequestInit | undefined)?.method === 'POST') {
        users = [...users, created];
        return json({ user: created, temporary_password: 'Tmp-ABCdef123' }, 201);
      }
      return json({ users });
    });
    renderWithWorkbook(<UsersPage />, { url: '/admin/users' });
    expect(await screen.findByRole('row', { name: 'asha.admin' })).toHaveTextContent('You');
    await user.type(screen.getByLabelText(/Login ID/), 'meena.ci');
    await user.click(screen.getByRole('button', { name: /Create user/ }));
    expect(await screen.findByTestId('temporary-password')).toHaveTextContent('Tmp-ABCdef123');
    const [, init] = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith('/auth/users/') && (i as RequestInit)?.method === 'POST')!;
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ username: 'meena.ci', first_name: '', last_name: '', email: '', role: 'ci' });
    expect(await screen.findByRole('row', { name: 'meena.ci' })).toHaveTextContent('Temporary password');
    await user.click(screen.getByRole('button', { name: 'Done, hide it' }));
    expect(screen.queryByTestId('temporary-password')).not.toBeInTheDocument();
  });

  it('grants a CI user projects and circles from the Organization, one project at a time', async () => {
    const user = userEvent.setup();
    const ci = { id: 9, username: 'odisha.ci', name: '', email: '', role: 'ci', circles: [] as string[], access: [] as { project: string; circle: string }[],
      legacy_circles: [] as string[], is_active: true, is_superuser: false, must_change_password: false, last_login: null, date_joined: '2026-10-23T10:00:00' };
    const admin = { ...ci, id: 1, username: 'asha.admin', role: 'admin' };
    const catalog = {
      projects: [{ key: '4G Saturation', code: '4G', name: '4G Saturation', is_active: true }, { key: 'LWE', code: 'LWE', name: 'LWE', is_active: true }],
      circles: [{ code: 'OD', name: 'Odisha', is_active: true }],
      associations: [{ project: '4G Saturation', circle: 'OD', is_active: true }, { project: 'LWE', circle: 'OD', is_active: true }],
    };
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/auth/csrf/')) return json({ csrf_token: 't' });
      if (url.endsWith('/organization/catalog/')) return json(catalog);
      if (url.endsWith('/organization/access/9/')) {
        ci.access = JSON.parse((init as RequestInit).body as string).pairs;
        return json({ user: { ...ci, pairs: ci.access, limited: true, needs_review: false } });
      }
      return json({ users: [admin, ci] });
    });
    renderWithWorkbook(<UsersPage />, { url: '/admin/users' });
    const row = await screen.findByRole('row', { name: 'odisha.ci' });
    expect(row).toHaveTextContent('None assigned');
    expect(screen.getByRole('row', { name: 'asha.admin' })).toHaveTextContent('All projects and circles');
    await user.click(within(row).getByRole('button', { name: 'Edit circles of odisha.ci' }));
    await user.click(await within(row).findByRole('checkbox', { name: 'OD under 4G Saturation' }));
    expect(within(row).getByRole('checkbox', { name: 'OD under LWE' })).not.toBeChecked();  // OD LWE is a separate grant
    await user.click(within(row).getByRole('button', { name: 'Save access' }));
    const [, init] = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith('/organization/access/9/') && (i as RequestInit)?.method === 'PUT')!;
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ pairs: [{ project: '4G Saturation', circle: 'OD' }], reason: '' });
    expect(await screen.findByText('odisha.ci can now use OD (4G Saturation).')).toBeInTheDocument();
  });
});
