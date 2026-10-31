import { useMemo, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CircleCheck, CircleX, Loader2, Plus, Trash2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../data/DataEntry';
import { useAuth } from '../../context/auth';
import { useApiQuery } from '../../hooks/useApiQuery';
import { activeCirclesOf, useOrganization } from '../../hooks/useOrganization';
import {
  createAccessAssignment, deleteAccessAssignment, fetchAccessAssignments, fetchAccessPreview, fetchAccessRoles, fetchPermissionCatalog, fetchUsers,
  updateAccessAssignment,
} from '../../services/api';
import type { AccessAssignment, AccessRole, PortalUser } from '../../types';

const errorText = (e: unknown) => {
  const details = (e as { details?: Record<string, unknown> }).details ?? {};
  const first = Object.values(details)[0];
  return first ? String(Array.isArray(first) ? first[0] : first) : (e as Error).message;
};
/** Users whose access comes from assignments (Admin and NOC Lead work everywhere through their account role). */
const assignable = (u: PortalUser, me?: string) => !u.is_superuser && u.role !== 'admin' && u.role !== 'noc_lead' && u.username !== me;

/**
 * Users & Roles › Access Assignments: role X for user U on project P (every circle) or on selected circles. Projects and
 * circles come from Organization › Project-Circle Mapping; nothing is granted automatically when they are added.
 */
export function AssignmentsTab() {
  const { user: me } = useAuth();
  const [params, setParams] = useSearchParams();
  const [version, setVersion] = useState(0);
  const users = useApiQuery('access-users', fetchUsers);
  const roles = useApiQuery(`access-roles-${version}`, fetchAccessRoles);
  const rows = useApiQuery(`access-assignments-${version}`, fetchAccessAssignments);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const filterUser = params.get('user') ?? '';
  const candidates = (users.data?.users ?? []).filter((u) => assignable(u, me?.username));
  const assignableRoles = (roles.data?.roles ?? []).filter((r) => r.assignable && r.is_active);
  const shown = (rows.data?.assignments ?? []).filter((a) => !filterUser || String(a.user_id) === filterUser);
  const reload = (text: string) => { setVersion((v) => v + 1); setMessage({ ok: true, text }); };
  const act = async (a: AccessAssignment, action: () => Promise<unknown>, text: string) => {
    setBusy(a.id);
    setMessage(null);
    try {
      await action();
      reload(text);
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      {message && <Alert variant={message.ok ? 'default' : 'destructive'} role={message.ok ? 'status' : 'alert'}><AlertDescription>{message.text}</AlertDescription></Alert>}
      {users.data && roles.data && (
        <AssignForm users={candidates} roles={assignableRoles} initialUser={filterUser} onSaved={reload} onError={(text) => setMessage({ ok: false, text })} />
      )}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">Assignments</CardTitle>
            <CardDescription className="text-xs">One row per circle (or entire project). Change a row's role or status, or revoke it, without touching the others.</CardDescription>
          </div>
          <Field id="assign-filter" label="User" className="w-56">
            <SelectField id="assign-filter" value={filterUser || '__all'} placeholder="All users"
              options={[{ value: '__all', label: 'All users' }, ...candidates.map((u) => ({ value: String(u.id), label: u.name ? `${u.name} (${u.username})` : u.username }))]}
              onChange={(v) => setParams(v === '__all' ? {} : { user: v }, { replace: true })} />
          </Field>
        </CardHeader>
        <CardContent className="px-0">
          {rows.error ? <p className="px-4 text-sm text-destructive">{rows.error.message}</p> : !rows.data ? <Skeleton className="mx-4 h-32" /> : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="pl-4">User</TableHead><TableHead>Project</TableHead><TableHead>Scope</TableHead><TableHead className="w-44">Role</TableHead>
                    <TableHead>Status</TableHead><TableHead>Valid until</TableHead><TableHead>Applies</TableHead><TableHead className="pr-4 text-right">Revoke</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {!shown.length && <TableRow><TableCell colSpan={8} className="py-6 text-center text-muted-foreground">No assignment{filterUser ? ' for this user' : ''} yet.</TableCell></TableRow>}
                  {shown.map((a) => (
                    <TableRow key={a.id} aria-label={`${a.username} ${a.project} ${a.circle ?? 'entire project'}`}>
                      <TableCell className="pl-4 font-medium">{a.username}</TableCell>
                      <TableCell>{a.project}</TableCell>
                      <TableCell>{a.circle ?? <Badge variant="outline">Entire project</Badge>}</TableCell>
                      <TableCell>
                        <SelectField id={`a-role-${a.id}`} value={String(a.role_id)} placeholder="Role" disabled={busy === a.id}
                          options={[...new Map([[a.role_id, a.role], ...assignableRoles.map((r) => [r.id, r.name] as [number, string])]).entries()].map(([id, name]) => ({ value: String(id), label: name }))}
                          onChange={(v) => { void act(a, () => updateAccessAssignment(a.id, { role: Number(v) }), `${a.username}: role changed for ${a.circle ?? a.project}.`); }} />
                      </TableCell>
                      <TableCell>
                        <label className="inline-flex items-center gap-1.5">
                          <input type="checkbox" checked={a.status === 'active'} disabled={busy === a.id} aria-label={`Active: ${a.username} ${a.circle ?? a.project}`}
                            onChange={() => { void act(a, () => updateAccessAssignment(a.id, { status: a.status === 'active' ? 'inactive' : 'active' }), `${a.username}: assignment ${a.status === 'active' ? 'deactivated' : 'activated'}.`); }} />
                          {a.status === 'active' ? 'Active' : 'Inactive'}
                        </label>
                      </TableCell>
                      <TableCell>{a.valid_until ?? '—'}</TableCell>
                      <TableCell>{a.applies ? <span className="text-emerald-700">Yes</span> : <span className="text-amber-700">No: {a.problem}</span>}</TableCell>
                      <TableCell className="pr-4 text-right">
                        <Button size="icon" variant="ghost" className="text-destructive" disabled={busy === a.id} aria-label={`Revoke ${a.role} for ${a.username} on ${a.circle ?? a.project}`}
                          onClick={() => { if (globalThis.confirm?.(`Revoke ${a.role} for ${a.username} on ${a.circle ?? 'all of ' + a.project}?`) !== false) void act(a, () => deleteAccessAssignment(a.id), `${a.username}: access revoked.`); }}>
                          <Trash2 />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      {users.data && <AccessPreviewCard users={candidates} />}
    </div>
  );
}

function AssignForm({ users, roles, initialUser, onSaved, onError }: {
  users: PortalUser[]; roles: AccessRole[]; initialUser: string; onSaved: (text: string) => void; onError: (text: string) => void;
}) {
  const catalog = useOrganization();
  const empty = { user: initialUser, project: '', scope: 'circles' as 'project' | 'circles', circles: [] as string[], role: '', status: 'active', valid_until: '' };
  const [f, setF] = useState(empty);
  const [busy, setBusy] = useState(false);
  const projects = (catalog.data?.projects ?? []).filter((p) => p.is_active);
  const circles = f.project ? activeCirclesOf(catalog.data, f.project) : [];
  const ready = f.user && f.project && f.role && (f.scope === 'project' || f.circles.length > 0);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const made = (await createAccessAssignment({ user: Number(f.user), role: Number(f.role), project: f.project, scope: f.scope, circles: f.circles,
        status: f.status, valid_until: f.valid_until || null })).assignments;
      const u = users.find((x) => String(x.id) === f.user);
      onSaved(`${u?.username}: ${made[0]?.role} on ${f.scope === 'project' ? `all of ${f.project}` : `${f.circles.join(', ')} (${f.project})`}.`);
      setF({ ...empty, user: f.user });
    } catch (e) {
      onError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Assign access</CardTitle>
        <CardDescription className="text-xs">
          Only combinations set up in Organization › Project-Circle Mapping are offered. "Entire project" covers every circle of the project, including circles
          associated with it later; choose circles to restrict.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!users.length ? <p className="text-sm text-muted-foreground">No user to assign: Admins and NOC Leads already work on every project and circle.</p> : (
          <form noValidate onSubmit={submit} className="grid gap-3 md:grid-cols-3">
            <Field id="as-user" label="User" required>
              <SelectField id="as-user" value={f.user} placeholder="Select user" options={users.map((u) => ({ value: String(u.id), label: u.name ? `${u.name} (${u.username})` : u.username }))}
                onChange={(v) => setF((x) => ({ ...x, user: v }))} />
            </Field>
            <Field id="as-project" label="Project" required>
              <SelectField id="as-project" value={f.project} placeholder="Select project" options={projects.map((p) => ({ value: p.key, label: p.name }))}
                onChange={(v) => setF((x) => ({ ...x, project: v, circles: [] }))} />
            </Field>
            <Field id="as-role" label="Role" required>
              <SelectField id="as-role" value={f.role} placeholder="Select role" options={roles.map((r) => ({ value: String(r.id), label: r.name }))}
                onChange={(v) => setF((x) => ({ ...x, role: v }))} />
            </Field>
            <fieldset className="md:col-span-3">
              <legend className="mb-1 text-xs font-medium">Access scope</legend>
              <div className="flex flex-wrap gap-4 text-sm">
                {(['circles', 'project'] as const).map((s) => (
                  <label key={s} className="flex items-center gap-1.5">
                    <input type="radio" name="as-scope" checked={f.scope === s} onChange={() => setF((x) => ({ ...x, scope: s }))} />
                    {s === 'project' ? 'Entire project' : 'Selected circles'}
                  </label>
                ))}
              </div>
              {f.scope === 'circles' && (
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 rounded-md border p-2 text-sm" aria-label="Circles">
                  {!f.project ? <span className="text-muted-foreground">Select a project first.</span> : !circles.length ? <span className="text-muted-foreground">No active circle in {f.project}.</span>
                    : circles.map((c) => (
                      <label key={c} className="flex items-center gap-1">
                        <input type="checkbox" checked={f.circles.includes(c)} aria-label={`${c} under ${f.project}`}
                          onChange={(e) => setF((x) => ({ ...x, circles: e.target.checked ? [...x.circles, c].sort() : x.circles.filter((y) => y !== c) }))} />
                        {c}
                      </label>
                    ))}
                </div>
              )}
            </fieldset>
            <Field id="as-status" label="Status">
              <SelectField id="as-status" value={f.status} placeholder="Status" options={[{ value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]}
                onChange={(v) => setF((x) => ({ ...x, status: v }))} />
            </Field>
            <Field id="as-until" label="Valid until (optional)"><Input id="as-until" type="date" value={f.valid_until} onChange={(e) => setF((x) => ({ ...x, valid_until: e.target.value }))} /></Field>
            <div className="flex items-end"><Button type="submit" disabled={busy || !ready}>{busy ? <Loader2 className="animate-spin" /> : <Plus />} Save assignment</Button></div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

/** Read-only check of what a user may do in one module on one project/circle (no impersonation, nothing changes). */
function AccessPreviewCard({ users }: { users: PortalUser[] }) {
  const catalog = useOrganization();
  const modules = useApiQuery('permission-catalog', fetchPermissionCatalog);
  const [q, setQ] = useState({ user: '', project: '', circle: '', module: '' });
  const params = useMemo(() => new URLSearchParams(q), [q]);
  const complete = Object.values(q).every(Boolean);
  const preview = useApiQuery(complete ? `access-preview-${params}` : null, (signal) => fetchAccessPreview(params, signal));
  const projects = (catalog.data?.projects ?? []).filter((p) => p.is_active);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Access Preview</CardTitle>
        <CardDescription className="text-xs">Shows which actions are allowed and which assignment grants them. Preview only: it does not sign in as the user or change anything.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-4">
          <Field id="pv-user" label="User"><SelectField id="pv-user" value={q.user} placeholder="User" options={users.map((u) => ({ value: String(u.id), label: u.username }))} onChange={(v) => setQ((x) => ({ ...x, user: v }))} /></Field>
          <Field id="pv-project" label="Project"><SelectField id="pv-project" value={q.project} placeholder="Project" options={projects.map((p) => ({ value: p.key, label: p.name }))} onChange={(v) => setQ((x) => ({ ...x, project: v, circle: '' }))} /></Field>
          <Field id="pv-circle" label="Circle"><SelectField id="pv-circle" value={q.circle} placeholder="Circle" options={(q.project ? activeCirclesOf(catalog.data, q.project) : []).map((c) => ({ value: c, label: c }))} onChange={(v) => setQ((x) => ({ ...x, circle: v }))} /></Field>
          <Field id="pv-module" label="Module"><SelectField id="pv-module" value={q.module} placeholder="Module" options={(modules.data?.modules ?? []).map((m) => ({ value: m.key, label: m.label }))} onChange={(v) => setQ((x) => ({ ...x, module: v }))} /></Field>
        </div>
        {preview.error && <p className="text-sm text-destructive">{preview.error.message}</p>}
        {preview.data && (
          <div className="space-y-2" aria-label="Preview result">
            {!preview.data.is_active && <p className="text-sm text-amber-700">This account is deactivated: everything is denied.</p>}
            <ul className="space-y-1.5">
              {preview.data.actions.map((a) => (
                <li key={a.action} className="flex items-start gap-2 text-sm">
                  {a.allowed ? <CircleCheck className="mt-0.5 size-4 text-emerald-600" aria-label="Allowed" /> : <CircleX className="mt-0.5 size-4 text-muted-foreground" aria-label="Denied" />}
                  <span><span className="font-medium">{a.label}</span>: {a.allowed ? `allowed by ${a.granted_by.map((g) => `${g.role} (${g.scope})`).join(', ')}` : 'denied'}</span>
                </li>
              ))}
            </ul>
            {preview.data.not_applying.length > 0 && (
              <p className="text-xs text-amber-700">Not applying: {preview.data.not_applying.map((n) => `${n.role} (${n.scope}): ${n.reason}`).join('; ')}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
