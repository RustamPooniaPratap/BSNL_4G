import { useState } from 'react';
import { Copy, Loader2, Lock, Plus, Power, Save, Trash2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Field } from '../data/DataEntry';
import { useApiQuery } from '../../hooks/useApiQuery';
import { cloneAccessRole, createAccessRole, deleteAccessRole, fetchAccessRoles, fetchPermissionCatalog, updateAccessRole } from '../../services/api';
import type { AccessRole, ModulePermission, PermissionCatalog } from '../../types';

const key = (p: ModulePermission) => `${p.module}.${p.action}`;

/**
 * Users & Roles › Roles & Permissions. Built-in roles are read only (clone one to customise it); a new role starts with
 * no permission. Each checkbox is one backend-enforced operation of the permission catalogue.
 */
export function RolesTab() {
  const [version, setVersion] = useState(0);
  const roles = useApiQuery(`access-roles-${version}`, fetchAccessRoles);
  const catalog = useApiQuery('permission-catalog', fetchPermissionCatalog);
  const [selected, setSelected] = useState<number | 'new' | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const reload = (text?: string, id?: number) => { setVersion((v) => v + 1); if (text) setMessage({ ok: true, text }); if (id) setSelected(id); };
  const role = roles.data?.roles.find((r) => r.id === selected) ?? null;

  return (
    <div className="space-y-3">
      {message && <Alert variant={message.ok ? 'default' : 'destructive'} role={message.ok ? 'status' : 'alert'}><AlertDescription>{message.text}</AlertDescription></Alert>}
      <div className="grid gap-3 lg:grid-cols-[18rem_1fr]">
        <Card className="gap-1 p-2">
          <Button size="sm" className="mb-1" onClick={() => { setSelected('new'); setMessage(null); }}><Plus /> Create role</Button>
          {roles.error && <p className="p-2 text-sm text-destructive">{roles.error.message}</p>}
          {!roles.data ? <Skeleton className="h-40" /> : (
            <ul aria-label="Roles" className="space-y-0.5">
              {roles.data.roles.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => { setSelected(r.id); setMessage(null); }} aria-current={r.id === selected ? 'true' : undefined}
                    className={cn('flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm', r.id === selected ? 'bg-primary text-primary-foreground' : 'hover:bg-muted')}>
                    <span className="flex items-center gap-1.5">{r.system && <Lock className="size-3.5" aria-label="Built-in" />}{r.name}</span>
                    <span className="text-xs opacity-80">{r.is_active ? `${r.users.length} user(s)` : 'Inactive'}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {catalog.error && <p className="text-sm text-destructive">{catalog.error.message}</p>}
        {catalog.data && selected === 'new' && <RoleEditor key="new" catalog={catalog.data} role={null} onDone={reload} onError={(text) => setMessage({ ok: false, text })} />}
        {catalog.data && role && <RoleEditor key={`${role.id}-${role.updated_at}`} catalog={catalog.data} role={role} onDone={reload} onError={(text) => setMessage({ ok: false, text })} />}
        {selected === null && <Card className="justify-center p-6 text-sm text-muted-foreground">Choose a role to see its permissions and users, or create a custom role.</Card>}
      </div>
    </div>
  );
}

function RoleEditor({ catalog, role, onDone, onError }: {
  catalog: PermissionCatalog; role: AccessRole | null; onDone: (text?: string, id?: number) => void; onError: (text: string) => void;
}) {
  const [name, setName] = useState(role?.name ?? '');
  const [description, setDescription] = useState(role?.description ?? '');
  const [granted, setGranted] = useState<Set<string>>(() => new Set((role?.permissions ?? []).map(key)));
  const [cloneName, setCloneName] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const editable = role === null || role.editable;
  const toggle = (k: string) => setGranted((g) => { const next = new Set(g); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  const perms = () => [...granted].map((k) => { const [module, action] = k.split('.'); return { module, action }; });
  const act = async (name_: string, action: () => Promise<string | [string, number]>) => {
    setBusy(name_);
    setErrors({});
    try {
      const r = await action();
      if (Array.isArray(r)) onDone(r[0], r[1]); else onDone(r);
    } catch (e) {
      const details = (e as { details?: Record<string, unknown> }).details ?? {};
      const mapped = Object.fromEntries(Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)]));
      setErrors(mapped);
      onError(Object.values(mapped)[0] ?? (e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const actions = [...new Set(catalog.modules.flatMap((m) => m.actions.map((a) => a.key)))];
  const actionLabel = (a: string) => catalog.modules.flatMap((m) => m.actions).find((x) => x.key === a)?.label ?? a;

  return (
    <Card className="gap-3 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">{role ? role.name : 'New role'}</h2>
          <p className="text-xs text-muted-foreground">
            {role?.global ? 'Built-in account role: these permissions apply on every project and circle; it is set on the user, not assigned.'
              : role?.system ? 'Built-in role: assigned per project and circle; read only. Clone it to make a custom variant.'
                : 'Custom role: no permission until you tick one. Assign it per project and circle on Access Assignments.'}
          </p>
        </div>
        {role && (role.is_active ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">Active</Badge> : <Badge variant="outline">Inactive</Badge>)}
      </div>
      {editable && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="role-name" label="Role name" required error={errors.name}><Input id="role-name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. IE" /></Field>
          <Field id="role-description" label="Description"><Input id="role-description" value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm" aria-label="Permission matrix">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th className="py-1.5 pr-3">Module</th>{actions.map((a) => <th key={a} className="px-2 py-1.5 text-center">{actionLabel(a)}</th>)}</tr>
          </thead>
          <tbody>
            {catalog.modules.map((m) => (
              <tr key={m.key} className="border-t">
                <td className="py-1.5 pr-3"><span className="font-medium">{m.label}</span><span className="block text-xs text-muted-foreground">{m.description}</span></td>
                {actions.map((a) => {
                  const spec = m.actions.find((x) => x.key === a);
                  const k = `${m.key}.${a}`;
                  return (
                    <td key={a} className="px-2 py-1.5 text-center">
                      {spec ? <input type="checkbox" checked={granted.has(k)} disabled={!editable} onChange={() => toggle(k)} title={spec.description}
                        aria-label={`${m.label}: ${spec.label}`} /> : <span className="text-muted-foreground" aria-hidden="true">·</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">Admin only, never grantable: {catalog.admin_only.join(', ')}.</p>
      {role && <p className="text-xs"><span className="font-medium">Users:</span> {role.users.join(', ') || 'none'}</p>}
      <div className="flex flex-wrap items-end gap-2 border-t pt-3">
        {editable && (
          <Button disabled={!!busy} onClick={() => { void act('save', async () => {
            if (role) {
              await updateAccessRole(role.id, { name, description, permissions: perms() });
              return `${name} saved.`;
            }
            const created = (await createAccessRole({ name, description, permissions: perms() })).role;
            return [`${created.name} created${granted.size ? '' : ' with no permission'}.`, created.id];
          }); }}>
            {busy === 'save' ? <Loader2 className="animate-spin" /> : <Save />} {role ? 'Save' : 'Create role'}
          </Button>
        )}
        {role && editable && (
          <Button variant="outline" disabled={!!busy} onClick={() => { void act('active', async () => (await updateAccessRole(role.id, { is_active: !role.is_active }), `${role.name} ${role.is_active ? 'deactivated: its assignments grant nothing now' : 'activated'}.`)); }}>
            <Power /> {role.is_active ? 'Deactivate' : 'Activate'}
          </Button>
        )}
        {role && (
          <span className="inline-flex items-end gap-1.5">
            <Input aria-label="Name of the copy" placeholder="Name of the copy" value={cloneName} onChange={(e) => setCloneName(e.target.value)} className="h-9 w-44" />
            <Button variant="outline" disabled={!!busy || !cloneName.trim()} onClick={() => { void act('clone', async () => { const r = (await cloneAccessRole(role.id, cloneName.trim())).role; return [`${r.name} created from ${role.name}.`, r.id]; }); }}>
              <Copy /> Clone
            </Button>
          </span>
        )}
        {role && editable && (
          <Button variant="ghost" className="ml-auto text-destructive" disabled={!!busy || role.users.length > 0} title={role.users.length ? 'Assigned to users: remove the assignments or deactivate the role' : 'Delete role'}
            onClick={() => { if (globalThis.confirm?.(`Delete the role ${role.name}?`) !== false) void act('delete', async () => (await deleteAccessRole(role.id), `${role.name} deleted.`)); }}>
            <Trash2 /> Delete
          </Button>
        )}
      </div>
    </Card>
  );
}
