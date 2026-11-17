import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import { ApiError } from '../../services/api';
import * as api from './api';
import { ApiMasterPage } from './ApiMasterPage';
import type { ApiEndpointDetail, ApiEndpointRow, RegistryOverview } from './types';

vi.mock('./api', () => ({
  fetchRegistryOverview: vi.fn(), fetchEndpoints: vi.fn(), fetchEndpoint: vi.fn(), reviewEndpoint: vi.fn(), syncRegistry: vi.fn(),
}));
const m = vi.mocked(api);
vi.setConfig({ testTimeout: 20000 });

const OVERVIEW: RegistryOverview = {
  total: 196, approved: 0, pending: 196, rejected: 0, deprecated: 0, blocked: 169, field_review: 12, reviewable: 27, no_longer_present: 0,
  methods: { DELETE: 6, GET: 106, PATCH: 9, POST: 69, PUT: 6 },
  modules: [{ module: "All KPI's", total: 6, approved: 0, blocked: 0 }, { module: 'Authentication & Users', total: 23, approved: 0, blocked: 23 }],
  last_sync: '2026-11-16T10:40:00+05:30',
};
const row = (over: Partial<ApiEndpointRow>): ApiEndpointRow => ({
  id: 1, key: 'allkpis-summary:GET', name: 'GET Allkpis Summary', path: '/api/all-kpis/summary/', method: 'GET', module: "All KPI's",
  description: '', status: 'pending', status_label: 'Pending', blocked: false, block_reason: '', field_review: '', present: true,
  access_type: 'Internal (reviewable)', ...over,
});
const ROWS = [
  row({}),
  row({ id: 2, key: 'auth-login:POST', name: 'POST Auth Login', path: '/api/auth/login/', method: 'POST', module: 'Authentication & Users',
    blocked: true, block_reason: 'Authentication and user management', access_type: 'Internal only' }),
  row({ id: 3, key: 'site-portfolio-breakdowns:GET', name: 'GET Site Portfolio Breakdowns', path: '/api/site-portfolio/breakdowns/',
    module: 'Site Portfolio', field_review: 'Names of O&M Head users per circle (om_heads)' }),
];
const detail = (r: ApiEndpointRow, over: Partial<ApiEndpointDetail> = {}): ApiEndpointDetail => ({
  ...r, url_name: r.key.split(':')[0], view: 'apps.allkpis.views.summary', permission_classes: ['Can_dashboard_view'],
  authentication_classes: ['SessionAuth'], path_params: [], review_note: '', reviewed_by: null, reviewed_at: null,
  first_seen: '2026-11-16T10:40:00+05:30', last_seen: '2026-11-16T10:40:00+05:30', external_route: null,
  allowed_transitions: r.blocked ? ['approved', 'rejected'] : ['approved', 'rejected'], ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  m.fetchRegistryOverview.mockResolvedValue(OVERVIEW);
  m.fetchEndpoints.mockResolvedValue({ count: ROWS.length, results: ROWS });
  m.fetchEndpoint.mockImplementation(async (id: number) => detail(ROWS.find((r) => r.id === id)!));
});

describe('API Master', () => {
  it('shows registry counts from the backend, with no application or request figures yet', async () => {
    renderWithWorkbook(<ApiMasterPage />, { url: '/admin/api-master' });
    expect(await screen.findByRole('group', { name: 'Total registered APIs' })).toHaveTextContent('196');
    expect(screen.getByRole('group', { name: 'Approved APIs' })).toHaveTextContent('0');
    expect(screen.getByRole('group', { name: 'Pending APIs' })).toHaveTextContent('196');
    expect(screen.getByRole('group', { name: 'Blocked (internal only)' })).toHaveTextContent('169');
    expect(screen.getByRole('table', { name: 'Endpoints by module' })).toHaveTextContent('Authentication & Users');
    expect(screen.queryByRole('group', { name: /applications|credentials|requests/i })).not.toBeInTheDocument();
  });

  it('runs discovery on request and reports what changed', async () => {
    m.syncRegistry.mockResolvedValue({ discovered: 196, created: 196, updated: 0, no_longer_present: 0, approvals_withdrawn: 0, total: 196 });
    renderWithWorkbook(<ApiMasterPage />, { url: '/admin/api-master' });
    await userEvent.click(await screen.findByRole('button', { name: 'Discover endpoints' }));
    expect(await screen.findByText(/Discovery finished: 196 endpoints found, 196 new/)).toBeInTheDocument();
    await waitFor(() => expect(m.fetchRegistryOverview).toHaveBeenCalledTimes(2));  // refreshed after the sync
  });

  it('lists endpoints with the registry columns and sends the filters to the backend', async () => {
    renderWithWorkbook(<ApiMasterPage />, { url: '/admin/api-master/registry' });
    const table = await screen.findByRole('table', { name: 'API endpoints' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(
      ['API Name', 'Endpoint URL', 'HTTP Method', 'Module', 'Description', 'Access Type', 'Approval Status', 'Action']);
    expect(within(table).getByText('/api/auth/login/').closest('tr')).toHaveTextContent('Authentication and user management');
    await userEvent.type(screen.getByLabelText('Search'), 'kpi');
    await waitFor(() => expect((m.fetchEndpoints.mock.calls.at(-1)![0] as URLSearchParams).get('q')).toBe('kpi'));
  });

  it('records an approval with a reason and shows the saved status', async () => {
    m.reviewEndpoint.mockResolvedValue(detail(ROWS[0], { status: 'approved', status_label: 'Approved' }));
    renderWithWorkbook(<ApiMasterPage />, { url: '/admin/api-master/registry' });
    await userEvent.click(await screen.findByRole('button', { name: 'View GET /api/all-kpis/summary/' }));
    const form = await screen.findByRole('form', { name: 'Review decision' });
    await userEvent.click(within(form).getByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: 'Approved' }));
    await userEvent.type(within(form).getByLabelText('Reason (required)'), 'Aggregated KPIs, scope-limited');
    await userEvent.click(within(form).getByRole('button', { name: 'Save decision' }));
    expect(m.reviewEndpoint).toHaveBeenCalledWith(1, { status: 'approved', note: 'Aggregated KPIs, scope-limited', fields_reviewed: false });
    expect(await within(form).findByRole('status')).toHaveTextContent('Saved: Approved.');
  });

  it('asks for a field review confirmation and shows the backend refusal', async () => {
    m.reviewEndpoint.mockRejectedValue(new ApiError('Invalid request parameters.', 400,
      { fields_reviewed: 'Confirm that the response fields were reviewed (Names of O&M Head users per circle (om_heads)).' }));
    renderWithWorkbook(<ApiMasterPage />, { url: '/admin/api-master/registry' });
    await userEvent.click(await screen.findByRole('button', { name: 'View GET /api/site-portfolio/breakdowns/' }));
    const form = await screen.findByRole('form', { name: 'Review decision' });
    await userEvent.click(within(form).getByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: 'Approved' }));
    expect(within(form).getByRole('checkbox')).not.toBeChecked();
    await userEvent.type(within(form).getByLabelText('Reason (required)'), 'Needed');
    await userEvent.click(within(form).getByRole('button', { name: 'Save decision' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Confirm that the response fields were reviewed');
  });

  it('never offers Approved for a blocked endpoint', async () => {
    renderWithWorkbook(<ApiMasterPage />, { url: '/admin/api-master/registry' });
    await userEvent.click(await screen.findByRole('button', { name: 'View POST /api/auth/login/' }));
    const form = await screen.findByRole('form', { name: 'Review decision' });
    expect(form).toHaveTextContent('Blocked endpoints can never be approved');
    await userEvent.click(within(form).getByRole('combobox'));
    expect(screen.queryByRole('option', { name: 'Approved' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Rejected' })).toBeInTheDocument();
  });
});
