import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../context/auth';
import { WorkbookContext, type WorkbookContextValue } from '../context/workbook';
import type { AuthUser } from '../types';
import { activeWorkbook } from './fixtures';

export function workbookValue(overrides: Partial<WorkbookContextValue> = {}): WorkbookContextValue {
  return {
    active: activeWorkbook,
    message: null,
    loading: false,
    error: null,
    version: 'v1',
    refresh: vi.fn(),
    setActive: vi.fn(),
    ...overrides,
  };
}

export const ADMIN_USER: AuthUser = { username: 'asha.admin', name: 'Asha', role: 'admin', role_label: 'Admin', must_change_password: false };
/** The built-in CI role's permissions (accounts.catalog.CI_PERMISSIONS), held on the user's assigned circles. */
export const CI_PERMISSIONS = { csv_upload: ['upload'], dashboard: ['export', 'view'], data_uptime_sites: ['export', 'view'], data_uptime_daily: ['export', 'view'], data_uptime_monthly: ['export', 'view'], data_escalation: ['export', 'view'], data_rca: ['export', 'view'], rca_register: ['create', 'edit', 'view'], rca_upload: ['upload'] };
export const CI_USER: AuthUser = { username: 'ravi.ci', name: 'Ravi', role: 'ci', role_label: 'CI', must_change_password: false, permissions: CI_PERMISSIONS };

export function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: 'signed_in', user: ADMIN_USER, notice: null,
    signIn: vi.fn(), devSignIn: vi.fn(), signOut: vi.fn(async () => {}), setUser: vi.fn(),
    ...overrides,
  };
}

/** Render inside a router, a signed-in user (Admin by default) and a workbook context (active workbook by default). */
export function renderWithWorkbook(ui: ReactElement, { url = '/', workbook = workbookValue(), auth = authValue() } = {}) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthContext.Provider value={auth}>
        <WorkbookContext.Provider value={workbook}>{ui}</WorkbookContext.Provider>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}
