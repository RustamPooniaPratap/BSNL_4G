import { useMemo, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { Copy, Eye, KeyRound, Loader2, LogOut, Pencil, ShieldCheck, UserCheck, UserPlus, UserX } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { Field, SelectField } from '../components/data/DataEntry';
import { AccessHistoryTab } from '../components/users/AccessHistoryTab';
import { AssignmentsTab } from '../components/users/AssignmentsTab';
import { RolesTab } from '../components/users/RolesTab';
import { useAuth } from '../context/auth';
import { PageHeading } from '../context/pageHeader';
import { useApiQuery } from '../hooks/useApiQuery';
import { projectCode, useOrganization } from '../hooks/useOrganization';
import { fieldA11y } from '../lib/dataEntry';
import { formatDateTime } from '../lib/format';
import { ApiError, createUser, fetchEffectiveAccess, fetchPermissionCatalog, fetchUsers, resetUserPassword, revokeUserSessions, updateUser } from '../services/api';
import type { PortalUser, Role } from '../types';

/** Four sections: one sidebar entry (Administration > Users & Roles), one URL per section. */
const TABS = [
  { path: '/admin/users', label: 'Users' },
  { path: '/admin/users/roles', label: 'Roles & Permissions' },
  { path: '/admin/users/assignments', label: 'Access Assignments' },
  { path: '/admin/users/history', label: 'Access History' },
];

export const ROLE_OPTIONS = [
  { value: 'member', label: 'Assigned access only' }, { value: 'ci', label: 'CI' }, { value: 'noc_lead', label: 'NOC Lead' }, { value: 'admin', label: 'Admin' },
];
const roleLabel = (role: Role | null) => ROLE_OPTIONS.find((o) => o.value === (role ?? 'member'))?.label ?? 'No role';
type Action = 'reset' | 'deactivate' | 'activate' | 'revoke';
const ACTION_LABEL: Record<Action, string> = { reset: 'Reset password', deactivate: 'Deactivate', activate: 'Activate', revoke: 'Sign out everywhere' };

/**
 * Admin-only: accounts, custom roles and their permissions, project/circle access assignments and the access history.
 * Every list comes from the server, which enforces every rule again.
 */
export function UsersPage() {
  const location = useLocation();
  const path = location.pathname.replace(/\/+$/, '') || '/admin/users';
  const current = TABS.find((t) => t.path === path);
  if (!current) return <Navigate to="/admin/users" replace />;
  return (
    <div className="flex flex-col gap-4">
      <PageHeading title="Users & Roles"
        subtitle="Accounts, custom roles and permissions, project/circle access assignments and their history · no self-registration" />
      <nav aria-label="Users & Roles sections" className="flex flex-wrap gap-1 rounded-xl border bg-card p-1 shadow-xs">
        {TABS.map((t) => (
          <Link key={t.path} to={t.path} aria-current={t === current ? 'page' : undefined}
            className={cn('rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
              t === current ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {t.label}
          </Link>
        ))}
      </nav>
      {current.path === '/admin/users' && <UsersTab />}
      {current.path === '/admin/users/roles' && <RolesTab />}
      {current.path === '/admin/users/assignments' && <AssignmentsTab />}
      {current.path === '/admin/users/history' && <AccessHistoryTab />}
    </div>
  );
}

function UsersTab() {
  const { user: me } = useAuth();
  const [version, setVersion] = useState(0);
  const users = useApiQuery(`users|${version}`, fetchUsers);
  const catalog = useOrganization();
  const reload = () => setVersion((v) => v + 1);
  const [secret, setSecret] = useState<{ username: string; password: string; why: string } | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [confirm, setConfirm] = useState<{ id: number; action: Action } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<PortalUser | null>(null);
  const [effective, setEffective] = useState<PortalUser | null>(null);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (users.data?.users ?? []).filter((u) => !q || [u.username, u.name, u.email].some((v) => v?.toLowerCase().includes(q)));
  }, [users.data, search]);

  const attempt = async (id: number | null, action: () => Promise<string | void>) => {
    setBusyId(id);
    setMessage(null);
    try {
      const text = await action();
      if (text) setMessage({ kind: 'ok', text });
      reload();
    } catch (e) {
      setMessage({ kind: 'error', text: (e as Error).message });
    } finally {
      setBusyId(null);
      setConfirm(null);
    }
  };
  const run = (target: PortalUser, action: Action) => attempt(target.id, async () => {
    if (action === 'reset') {
      const r = await resetUserPassword(target.id);
      setSecret({ username: target.username, password: r.temporary_password, why: 'Password reset; the account was signed out everywhere.' });
      return;
    }
    if (action === 'revoke') return `${target.username}: ${(await revokeUserSessions(target.id)).sessions_revoked} session(s) ended.`;
    await updateUser(target.id, { is_active: action === 'activate' });
    return `${target.username} ${action === 'activate' ? 'activated' : 'deactivated and signed out'}.`;
  });

  return (
    <div className="space-y-4">
      {secret && (
        <Alert className="border-amber-300 bg-amber-50/70" role="status">
          <KeyRound className="text-amber-700" />
          <AlertTitle>Temporary password for {secret.username}: shown once</AlertTitle>
          <AlertDescription>
            <span>{secret.why} Give it to the user through a secure channel; they must change it at first sign-in. It cannot be shown again.</span>
            <span className="mt-2 flex flex-wrap items-center gap-2">
              <code className="rounded bg-background px-2 py-1 font-mono text-sm" data-testid="temporary-password">{secret.password}</code>
              <Button size="sm" variant="outline" onClick={() => { void navigator.clipboard?.writeText(secret.password); }}><Copy /> Copy</Button>
              <Button size="sm" variant="ghost" onClick={() => setSecret(null)}>Done, hide it</Button>
            </span>
          </AlertDescription>
        </Alert>
      )}
      {message && (
        <Alert variant={message.kind === 'error' ? 'destructive' : 'default'} role={message.kind === 'error' ? 'alert' : 'status'}>
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}

      <NewUserForm onCreated={(u, password) => { setSecret({ username: u.username, password, why: 'Account created. Give it access on Access Assignments.' }); reload(); }} />

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">Accounts</CardTitle>
            <CardDescription className="text-xs">
              Admin and NOC Lead work on every project and circle. Everyone else works only where Access Assignments allow.
              Superuser accounts are managed with manage.py. You cannot change your own role or access, or deactivate yourself.
            </CardDescription>
          </div>
          <Input aria-label="Search users" placeholder="Search name, login ID or email" value={search} onChange={(e) => setSearch(e.target.value)} className="h-8 w-64" />
        </CardHeader>
        <CardContent className="px-0">
          {users.error ? <p className="px-4 text-sm text-destructive">{users.error.message}</p> : !users.data ? <Skeleton className="mx-4 h-40" /> : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="pl-4">Name</TableHead><TableHead>Email</TableHead><TableHead>Status</TableHead><TableHead className="w-44">Account role</TableHead>
                    <TableHead>Assigned roles</TableHead><TableHead>Projects &amp; circles</TableHead><TableHead>Consolidated RCA</TableHead><TableHead>Last sign-in</TableHead>
                    <TableHead className="pr-4 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {!shown.length && <TableRow><TableCell colSpan={9} className="py-6 text-center text-muted-foreground">No user matches.</TableCell></TableRow>}
                  {shown.map((u) => {
                    const self = u.username === me?.username;
                    const locked = u.is_superuser;
                    const global = u.role === 'admin' || u.role === 'noc_lead' || locked;
                    const assigned = u.assignments ?? [];
                    return (
                      <TableRow key={u.id} aria-label={u.username}>
                        <TableCell className="pl-4">
                          <span className="font-medium">{u.name || u.username}</span>{self && <Badge variant="secondary" className="ml-1.5">You</Badge>}
                          {u.name && <span className="block text-muted-foreground">{u.username}</span>}
                        </TableCell>
                        <TableCell>{u.email || <span className="text-muted-foreground">—</span>}</TableCell>
                        <TableCell>
                          {u.is_active ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">Active</Badge> : <Badge variant="outline">Deactivated</Badge>}
                          {u.must_change_password && <Badge variant="outline" className="ml-1 border-amber-300 text-amber-800">Temporary password</Badge>}
                        </TableCell>
                        <TableCell>
                          {locked || self ? <span className="inline-flex items-center gap-1"><ShieldCheck className="size-3.5" />{locked ? 'Admin (superuser)' : roleLabel(u.role)}</span> : (
                            <SelectField id={`role-${u.id}`} value={u.role ?? 'member'} placeholder="Role" options={ROLE_OPTIONS}
                              onChange={(r) => { void attempt(u.id, async () => { await updateUser(u.id, { role: r as Role }); return `${u.username}: account role is now ${roleLabel(r as Role)}.`; }); }} />
                          )}
                        </TableCell>
                        <TableCell>{global ? <span className="text-muted-foreground">—</span> : [...new Set(assigned.map((a) => a.role))].join(', ') || <span className="text-amber-700">None</span>}</TableCell>
                        <TableCell>
                          {global ? <span className="text-muted-foreground">Every project and circle</span> : assigned.length ? (
                            <span>{assigned.map((a) => `${a.circle ?? 'all circles'} · ${projectCode(catalog.data, a.project)}${a.applies ? '' : ' (not applying)'}`).join(', ')}</span>
                          ) : <span className="text-amber-700">No access</span>}
                          {!!u.legacy_circles?.length && <span className="block text-amber-700">Legacy circles {u.legacy_circles.join(', ')}: grant nothing until reviewed</span>}
                        </TableCell>
                        <TableCell>
                          {u.role === 'admin' || locked ? <span className="text-muted-foreground">Allowed (Admin)</span> : (
                            <label className="inline-flex items-center gap-1.5">
                              <input type="checkbox" checked={!!u.rca_consolidated} disabled={busyId === u.id || self} aria-label={`Consolidated RCA upload for ${u.username}`}
                                onChange={() => { void attempt(u.id, async () => { await updateUser(u.id, { rca_consolidated: !u.rca_consolidated }); return `${u.username} ${u.rca_consolidated ? 'may no longer' : 'may now'} upload consolidated RCA workbooks.`; }); }} />
                              {u.rca_consolidated ? 'Allowed' : 'Not allowed'}
                            </label>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{u.last_login ? formatDateTime(u.last_login) : 'Never'}</TableCell>
                        <TableCell className="pr-4 text-right whitespace-nowrap">
                          {confirm?.id === u.id ? (
                            <span className="inline-flex gap-1">
                              <Button size="sm" variant="destructive" disabled={busyId === u.id} onClick={() => { void run(u, confirm.action); }}>
                                {busyId === u.id && <Loader2 className="animate-spin" />} Confirm: {ACTION_LABEL[confirm.action].toLowerCase()}
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
                            </span>
                          ) : (
                            <span className="inline-flex gap-0.5">
                              <Button size="icon" variant="ghost" aria-label={`Effective permissions of ${u.username}`} title="View effective permissions" onClick={() => setEffective(u)}><Eye /></Button>
                              {!locked && !self && <>
                                <Button size="icon" variant="ghost" aria-label={`Edit ${u.username}`} title="Edit user" onClick={() => setEditing(u)}><Pencil /></Button>
                                {!global && <Link to={`/admin/users/assignments?user=${u.id}`} className="inline-flex h-8 items-center rounded-md px-2 text-xs font-medium hover:bg-muted" aria-label={`Manage access of ${u.username}`}>Manage access</Link>}
                                <Button size="icon" variant="ghost" aria-label={`Reset password for ${u.username}`} title="Reset password" onClick={() => setConfirm({ id: u.id, action: 'reset' })}><KeyRound /></Button>
                                <Button size="icon" variant="ghost" aria-label={`Sign out ${u.username} everywhere`} title="Sign out everywhere" onClick={() => setConfirm({ id: u.id, action: 'revoke' })}><LogOut /></Button>
                                {u.is_active
                                  ? <Button size="icon" variant="ghost" aria-label={`Deactivate ${u.username}`} title="Deactivate" onClick={() => setConfirm({ id: u.id, action: 'deactivate' })}><UserX /></Button>
                                  : <Button size="icon" variant="ghost" aria-label={`Activate ${u.username}`} title="Activate" onClick={() => setConfirm({ id: u.id, action: 'activate' })}><UserCheck /></Button>}
                              </>}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      {editing && <EditUserSheet user={editing} onClose={() => setEditing(null)} onSaved={(text) => { setEditing(null); setMessage({ kind: 'ok', text }); reload(); }} />}
      {effective && <EffectiveSheet user={effective} onClose={() => setEffective(null)} />}
    </div>
  );
}

const errorsOf = (e: unknown) => (e instanceof ApiError && e.status === 400
  ? Object.fromEntries(Object.entries(e.details).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)]))
  : { form: (e as Error).message });

function NewUserForm({ onCreated }: { onCreated: (user: PortalUser, password: string) => void }) {
  const empty = { username: '', first_name: '', last_name: '', email: '', role: 'member' as Role };
  const [draft, setDraft] = useState(empty);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof draft, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!/^[\w.@+-]{3,150}$/.test(draft.username.trim())) { setErrors({ username: 'Use 3 to 150 letters, digits and . @ + - _ only.' }); return; }
    setBusy(true);
    setErrors({});
    try {
      const r = await createUser({ ...draft, username: draft.username.trim() });
      onCreated(r.user, r.temporary_password);
      setDraft(empty);
    } catch (e) {
      setErrors(errorsOf(e));
    } finally {
      setBusy(false);
    }
  };

  const text = (k: 'username' | 'first_name' | 'last_name' | 'email', label: string, required = false) => (
    <Field id={`new-${k}`} label={label} required={required} error={errors[k]} className="w-44">
      <Input {...fieldA11y(`new-${k}`, errors[k])} value={draft[k]} maxLength={150} type={k === 'email' ? 'email' : 'text'} autoComplete="off"
        onChange={(e) => set(k, e.target.value)} />
    </Field>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Add User</CardTitle>
        <CardDescription className="text-xs">A temporary password is generated and shown once; the user must change it at first sign-in. A new user has no project or circle until you assign one.</CardDescription>
      </CardHeader>
      <CardContent>
        <form noValidate onSubmit={submit} className="flex flex-wrap items-end gap-3">
          {text('username', 'Login ID', true)}
          {text('first_name', 'First name')}
          {text('last_name', 'Last name')}
          {text('email', 'Email')}
          <Field id="new-role" label="Account role" required className="w-48">
            <SelectField id="new-role" value={draft.role} placeholder="Role" options={ROLE_OPTIONS} onChange={(v) => set('role', v)} />
          </Field>
          <Button type="submit" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <UserPlus />} Create user</Button>
          {errors.form && <p className="w-full text-xs text-destructive" role="alert">{errors.form}</p>}
        </form>
      </CardContent>
    </Card>
  );
}

function EditUserSheet({ user, onClose, onSaved }: { user: PortalUser; onClose: () => void; onSaved: (text: string) => void }) {
  const [first, ...rest] = (user.name || '').split(' ');
  const [form, setForm] = useState({ first_name: first ?? '', last_name: rest.join(' '), email: user.email ?? '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await updateUser(user.id, form);
      onSaved(`${user.username} updated.`);
    } catch (e) {
      setErrors(errorsOf(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-full sm:max-w-md">
        <SheetHeader><SheetTitle>Edit {user.username}</SheetTitle><SheetDescription>Name and email. The login ID cannot change.</SheetDescription></SheetHeader>
        <form noValidate onSubmit={save} className="space-y-3 px-4">
          {(['first_name', 'last_name', 'email'] as const).map((k) => (
            <Field key={k} id={`edit-${k}`} label={{ first_name: 'First name', last_name: 'Last name', email: 'Email' }[k]} error={errors[k]}>
              <Input id={`edit-${k}`} type={k === 'email' ? 'email' : 'text'} value={form[k]} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
            </Field>
          ))}
          {errors.form && <p className="text-xs text-destructive" role="alert">{errors.form}</p>}
          <Button type="submit" disabled={busy}>{busy && <Loader2 className="animate-spin" />}Save</Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}

/** What the user may do, where: the server's own resolution (built-in role or assignments). */
function EffectiveSheet({ user, onClose }: { user: PortalUser; onClose: () => void }) {
  const data = useApiQuery(`effective-${user.id}`, (signal) => fetchEffectiveAccess(user.id, signal));
  const cat = useApiQuery('permission-catalog', fetchPermissionCatalog);
  const label = (key: string) => {
    const [m, a] = key.split('.');
    const mod = cat.data?.modules.find((x) => x.key === m);
    return `${mod?.label ?? m} · ${mod?.actions.find((x) => x.key === a)?.label ?? a}`;
  };
  return (
    <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Effective permissions: {user.username}</SheetTitle>
          <SheetDescription>Read only. Admin-only pages are not listed; they belong to the Admin role.</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6 text-sm">
          {data.error && <p className="text-destructive">{data.error.message}</p>}
          {!data.data ? <Skeleton className="h-40" /> : !Object.keys(data.data.scopes).length ? (
            <p className="text-muted-foreground">{data.data.is_active ? 'No permission: this user can open no data page.' : 'Deactivated: no access.'}</p>
          ) : (
            <ul className="space-y-2">
              {Object.entries(data.data.scopes).map(([key, pairs]) => (
                <li key={key} className="rounded-md border px-3 py-2">
                  <p className="font-medium">{label(key)}</p>
                  <p className="text-xs text-muted-foreground">{pairs === null ? 'Every project and circle' : pairs.map((p) => `${p.circle} (${p.project})`).join(', ')}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
