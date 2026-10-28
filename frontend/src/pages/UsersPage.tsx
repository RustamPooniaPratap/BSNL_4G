import { useState, type FormEvent } from 'react';
import { Copy, KeyRound, Loader2, LogOut, ShieldCheck, UserPlus, UserX, UserCheck } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeading } from '../context/pageHeader';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../components/data/DataEntry';
import { useAuth } from '../context/auth';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDateTime } from '../lib/format';
import { fieldA11y } from '../lib/dataEntry';
import { ApiError, createUser, fetchUsers, resetUserPassword, revokeUserSessions, updateUser } from '../services/api';
import type { PortalUser, Role } from '../types';

const ROLE_OPTIONS = [{ value: 'ci', label: 'CI' }, { value: 'noc_lead', label: 'NOC Lead' }, { value: 'admin', label: 'Admin' }];
const ROLE_NAMES: Record<Role, string> = { admin: 'an Admin', noc_lead: 'a NOC Lead', ci: 'a CI' };
type Action = 'reset' | 'deactivate' | 'activate' | 'revoke';
const ACTION_LABEL: Record<Action, string> = { reset: 'Reset password', deactivate: 'Deactivate', activate: 'Activate', revoke: 'Sign out everywhere' };

/** Admin-only: provision accounts, change roles, reset temporary passwords, deactivate and revoke sessions. */
export function UsersPage() {
  const { user: me } = useAuth();
  const [version, setVersion] = useState(0);
  const users = useApiQuery(`users|${version}`, fetchUsers);
  const reload = () => setVersion((v) => v + 1);
  const [secret, setSecret] = useState<{ username: string; password: string; why: string } | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [confirm, setConfirm] = useState<{ id: number; action: Action } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const run = async (target: PortalUser, action: Action) => {
    setBusyId(target.id);
    setMessage(null);
    try {
      if (action === 'reset') {
        const r = await resetUserPassword(target.id);
        setSecret({ username: target.username, password: r.temporary_password, why: 'Password reset; the account was signed out everywhere.' });
      } else if (action === 'revoke') {
        const r = await revokeUserSessions(target.id);
        setMessage({ kind: 'ok', text: `${target.username}: ${r.sessions_revoked} session(s) ended.` });
      } else {
        await updateUser(target.id, { is_active: action === 'activate' });
        setMessage({ kind: 'ok', text: `${target.username} ${action === 'activate' ? 'activated' : 'deactivated and signed out'}.` });
      }
      reload();
    } catch (e) {
      setMessage({ kind: 'error', text: (e as Error).message });
    } finally {
      setBusyId(null);
      setConfirm(null);
    }
  };

  const changeRole = async (target: PortalUser, role: Role) => {
    setMessage(null);
    try {
      await updateUser(target.id, { role });
      setMessage({ kind: 'ok', text: `${target.username} is now ${ROLE_NAMES[role]}.` });
      reload();
    } catch (e) {
      setMessage({ kind: 'error', text: (e as Error).message });
    }
  };

  return (
    <div className="space-y-4">
      <PageHeading title="Users & Roles"
        subtitle="Create accounts, assign Admin, NOC Lead or CI, reset temporary passwords and deactivate accounts · no self-registration" />

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

      <NewUserForm onCreated={(u, password) => { setSecret({ username: u.username, password, why: 'Account created.' }); reload(); }} />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Accounts</CardTitle>
          <CardDescription className="text-xs">Superuser accounts are managed with manage.py by a superuser. You cannot change your own role or deactivate yourself.</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {users.error ? <p className="px-4 text-sm text-destructive">{users.error.message}</p> : !users.data ? <Skeleton className="mx-4 h-40" /> : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="pl-4">Login ID</TableHead><TableHead>Name</TableHead><TableHead className="w-36">Role</TableHead><TableHead>Circles (raw uploads)</TableHead>
                    <TableHead>Status</TableHead><TableHead>Last sign-in</TableHead><TableHead className="pr-4 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.data.users.map((u) => {
                    const self = u.username === me?.username;
                    const locked = u.is_superuser;
                    return (
                      <TableRow key={u.id} aria-label={u.username}>
                        <TableCell className="pl-4 font-medium">{u.username}{self && <Badge variant="secondary" className="ml-1.5">You</Badge>}</TableCell>
                        <TableCell>{u.name || <span className="text-muted-foreground">—</span>}</TableCell>
                        <TableCell>
                          {locked || self ? <span className="inline-flex items-center gap-1"><ShieldCheck className="size-3.5" />{u.is_superuser ? 'Admin (superuser)' : ROLE_OPTIONS.find((o) => o.value === u.role)?.label ?? 'No role'}</span> : (
                            <SelectField id={`role-${u.id}`} value={u.role ?? ''} placeholder="No role" options={ROLE_OPTIONS} onChange={(r) => { void changeRole(u, r as Role); }} />
                          )}
                        </TableCell>
                        <TableCell>
                          {u.role === 'ci' && !locked
                            ? <CirclesEditor user={u} onSaved={(text) => { setMessage({ kind: 'ok', text }); reload(); }} onError={(text) => setMessage({ kind: 'error', text })} />
                            : <span className="text-muted-foreground">All circles</span>}
                        </TableCell>
                        <TableCell>
                          {u.is_active ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">Active</Badge> : <Badge variant="outline">Deactivated</Badge>}
                          {u.must_change_password && <Badge variant="outline" className="ml-1 border-amber-300 text-amber-800">Temporary password</Badge>}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{u.last_login ? formatDateTime(u.last_login) : 'Never'}</TableCell>
                        <TableCell className="pr-4 text-right whitespace-nowrap">
                          {locked || self ? <span className="text-muted-foreground">—</span> : confirm?.id === u.id ? (
                            <span className="inline-flex gap-1">
                              <Button size="sm" variant="destructive" disabled={busyId === u.id} onClick={() => { void run(u, confirm.action); }}>
                                {busyId === u.id && <Loader2 className="animate-spin" />} Confirm: {ACTION_LABEL[confirm.action].toLowerCase()}
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
                            </span>
                          ) : (
                            <span className="inline-flex gap-0.5">
                              <Button size="icon" variant="ghost" aria-label={`Reset password for ${u.username}`} title="Reset password" onClick={() => setConfirm({ id: u.id, action: 'reset' })}><KeyRound /></Button>
                              <Button size="icon" variant="ghost" aria-label={`Sign out ${u.username} everywhere`} title="Sign out everywhere" onClick={() => setConfirm({ id: u.id, action: 'revoke' })}><LogOut /></Button>
                              {u.is_active
                                ? <Button size="icon" variant="ghost" aria-label={`Deactivate ${u.username}`} title="Deactivate" onClick={() => setConfirm({ id: u.id, action: 'deactivate' })}><UserX /></Button>
                                : <Button size="icon" variant="ghost" aria-label={`Activate ${u.username}`} title="Activate" onClick={() => setConfirm({ id: u.id, action: 'activate' })}><UserCheck /></Button>}
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
    </div>
  );
}

function NewUserForm({ onCreated }: { onCreated: (user: PortalUser, password: string) => void }) {
  const [draft, setDraft] = useState({ username: '', first_name: '', last_name: '', email: '', role: 'ci' as Role });
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
      setDraft({ username: '', first_name: '', last_name: '', email: '', role: 'ci' });
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        setErrors(Object.fromEntries(Object.entries(e.details).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)])));
      } else {
        setErrors({ form: (e as Error).message });
      }
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
        <CardTitle className="text-sm font-semibold">Add a user</CardTitle>
        <CardDescription className="text-xs">A temporary password is generated and shown once; the user must change it at first sign-in.</CardDescription>
      </CardHeader>
      <CardContent>
        <form noValidate onSubmit={submit} className="flex flex-wrap items-end gap-3">
          {text('username', 'Login ID', true)}
          {text('first_name', 'First name')}
          {text('last_name', 'Last name')}
          {text('email', 'Email')}
          <Field id="new-role" label="Role" required className="w-36">
            <SelectField id="new-role" value={draft.role} placeholder="Role" options={ROLE_OPTIONS} onChange={(v) => set('role', v)} />
          </Field>
          <Button type="submit" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <UserPlus />} Create user</Button>
          {errors.form && <p className="w-full text-xs text-destructive" role="alert">{errors.form}</p>}
        </form>
      </CardContent>
    </Card>
  );
}

const CIRCLES = ['AP', 'BH', 'CG', 'JH', 'MH', 'MP', 'OD', 'RJ', 'TL', 'UP', 'WB'];

/** The circles a CI user may upload raw daily data for and export (checked again by the server). */
function CirclesEditor({ user, onSaved, onError }: { user: PortalUser; onSaved: (message: string) => void; onError: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const assigned = user.circles ?? [];
  const [value, setValue] = useState<string[]>(assigned);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await updateUser(user.id, { circles: value });
      setOpen(false);
      onSaved(value.length ? `${user.username} can upload for ${value.join(', ')}.` : `${user.username} has no circle and cannot upload raw data.`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <span className="inline-flex items-center gap-1.5">
        {assigned.length ? assigned.join(', ') : <span className="text-amber-700">None assigned</span>}
        <Button size="sm" variant="ghost" className="h-6 px-1.5 text-xs" aria-label={`Edit circles of ${user.username}`} onClick={() => { setValue(assigned); setOpen(true); }}>Edit</Button>
      </span>
    );
  }
  return (
    <fieldset className="flex max-w-72 flex-wrap items-center gap-x-2 gap-y-1" aria-label={`Circles of ${user.username}`}>
      {CIRCLES.map((c) => (
        <label key={c} className="flex items-center gap-1">
          <input type="checkbox" checked={value.includes(c)} onChange={() => setValue((v) => (v.includes(c) ? v.filter((x) => x !== c) : [...v, c].sort()))} />
          {c}
        </label>
      ))}
      <Button size="sm" className="h-6 px-2 text-xs" disabled={busy} onClick={() => { void save(); }}>Save</Button>
      <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => setOpen(false)}>Cancel</Button>
    </fieldset>
  );
}
