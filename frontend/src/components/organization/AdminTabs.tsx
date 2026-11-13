import { Fragment, useState, type FormEvent } from 'react';
import { Loader2, Pencil, Plus, TriangleAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../data/DataEntry';
import { useOrganization } from '../../hooks/useOrganization';
import { formatDateTime } from '../../lib/format';
import { createOrgAlias, fetchOrgAccess, fetchOrgAliases, fetchOrgHistory, updateOrgAlias } from '../../services/api';
import type { OrgAlias, OrgChange, OrgSiteIdMapping } from '../../types/organization';
import { AccessEditor } from './AccessEditor';
import { useOrgList } from '../../hooks/useOrgList';
import { ACTIVE_FILTERS, matchesActive, matchesText, type ActiveFilter } from '../../lib/orgFilters';
import { ActiveBadge, Chips, ConfirmAction, NoticeLine, SearchBox } from './OrgParts';

function Loading({ error }: { error: Error | null }) {
  return error ? <p className="p-3 text-sm text-destructive" role="alert">{error.message}</p> : <Skeleton className="m-4 h-40" />;
}

// --- User access ---------------------------------------------------------------------------------

export function AccessTab() {
  const list = useOrgList('access', fetchOrgAccess);
  const [query, setQuery] = useState('');
  const [show, setShow] = useState<'all' | 'ci' | 'review'>('all');
  const [editing, setEditing] = useState<number | null>(null);
  const users = (list.data?.users ?? []).filter((u) => (show === 'all' || (show === 'ci' ? u.limited : u.needs_review))
    && matchesText(query, u.username, u.name, ...u.pairs.map((p) => p.circle)));
  const review = (list.data?.users ?? []).filter((u) => u.needs_review).length;
  return (
    <div className="flex flex-col gap-3">
      <NoticeLine notice={list.notice} />
      {review > 0 && (
        <p className="flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {review} user{review === 1 ? ' has' : 's have'} a legacy circle-only assignment for a circle of several projects. It still applies to every project of the circle until you choose the projects.
        </p>
      )}
      <Card className="gap-0 overflow-hidden p-0">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
          <SearchBox id="org-access-search" value={query} onChange={setQuery} placeholder="Search users" />
          <Chips label="Users shown" value={show} options={[['all', 'All users'], ['ci', 'CI (limited)'], ['review', 'Needs review']]} onChange={setShow} />
          <p className="ml-auto text-xs text-muted-foreground">Roles, passwords and accounts: Users & Roles. Admins and NOC Leads are not limited.</p>
        </div>
        {!list.data ? <Loading error={list.error} /> : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="pl-4">User</TableHead><TableHead>Role</TableHead><TableHead>Projects and circles</TableHead><TableHead className="pr-4 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} aria-label={`Access of ${u.username}`}>
                  <TableCell className="pl-4"><span className="font-medium">{u.username}</span>{u.name && <p className="text-muted-foreground">{u.name}</p>}{!u.is_active && <Badge variant="outline" className="ml-1">Deactivated</Badge>}</TableCell>
                  <TableCell>{u.role_label}</TableCell>
                  <TableCell>
                    {editing === u.id ? (
                      <AccessEditor username={u.username} userId={u.id} pairs={u.pairs} legacy={u.legacy_circles} onCancel={() => setEditing(null)}
                        onSaved={(text) => { setEditing(null); void list.change(async () => undefined, text); }}
                        onError={(text) => list.setNotice({ kind: 'error', text })} />
                    ) : !u.limited ? <span className="text-muted-foreground">{u.role ? 'Every project and circle (role)' : 'No access (no role)'}</span> : (
                      <span className="flex flex-wrap items-center gap-1">
                        {u.pairs.map((p) => <Badge key={`${p.project}|${p.circle}`} variant="outline">{p.circle} · {p.project}</Badge>)}
                        {u.legacy_circles.map((c) => <Badge key={c} variant="outline" className="border-amber-300 text-amber-800" title="Legacy circle-only assignment: every project">{c} · every project (review)</Badge>)}
                        {!u.pairs.length && !u.legacy_circles.length && <span className="text-amber-700">None granted: cannot upload or export</span>}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="pr-4 text-right">
                    {u.limited && editing !== u.id && <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" aria-label={`Edit access of ${u.username}`} onClick={() => setEditing(u.id)}><Pencil /> Edit</Button>}
                  </TableCell>
                </TableRow>
              ))}
              {!users.length && <TableRow><TableCell colSpan={4} className="py-6 text-center text-muted-foreground">No user matches.</TableCell></TableRow>}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

// --- Code mapping (circle aliases) ---------------------------------------------------------------

export function CodeMappingTab() {
  const list = useOrgList('aliases', fetchOrgAliases);
  const catalog = useOrganization();
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('all');
  const [status, setStatus] = useState<ActiveFilter>('all');
  const [editing, setEditing] = useState<OrgAlias | 'new' | null>(null);
  const sources = list.data?.sources ?? [];
  const all = list.data?.aliases ?? [];
  const rows = all.filter((a) => (source === 'all' || a.source === source) && matchesActive(status, a.is_active) && matchesText(query, a.raw_code, a.circle, a.circle_name, a.project));
  const flagged = all.filter((a) => a.problems.length).length;
  return (
    <div className="flex flex-col gap-3">
      <NoticeLine notice={list.notice} />
      <p className="text-xs text-muted-foreground">
        How each source file writes a circle, and the circle it means (e.g. the raw daily CSV's <strong>OR</strong> is <strong>OD</strong>). A code with no mapping and no
        matching circle is reported in the import, never turned into a new circle. Site identifier mappings (e.g. LWE raw IDs) are separate and not configured here.
      </p>
      <SiteIdMapping rules={list.data?.site_id_mapping ?? []} />
      {flagged > 0 && <p className="text-sm text-amber-800" role="status">{flagged} mapping{flagged === 1 ? ' needs' : 's need'} attention (see the flagged rows).</p>}
      {editing && <AliasForm alias={editing === 'new' ? null : editing} sources={sources} busy={list.busy} onCancel={() => setEditing(null)}
        projects={(catalog.data?.projects ?? []).map((p) => p.key)} circles={catalog.data?.circles ?? []}
        onSave={async (body) => (await list.change(() => (editing === 'new' ? createOrgAlias(body) : updateOrgAlias(editing.id, body)),
          `${body.raw_code} → ${body.circle} saved.`)) && setEditing(null)} />}
      <Card className="gap-0 overflow-hidden p-0">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
          <SearchBox id="org-alias-search" value={query} onChange={setQuery} placeholder="Search codes" />
          <div className="w-60"><SelectField id="org-alias-source-filter" value={source} placeholder="Source" onChange={setSource}
            options={[{ value: 'all', label: 'All sources' }, ...sources]} /></div>
          <Chips label="Mapping status" value={status} options={ACTIVE_FILTERS} onChange={setStatus} />
          <Button size="sm" className="ml-auto" onClick={() => setEditing('new')}><Plus /> Add mapping</Button>
        </div>
        {!list.data ? <Loading error={list.error} /> : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="pl-4">Source</TableHead><TableHead>Project</TableHead><TableHead>Code as written</TableHead><TableHead>Canonical circle</TableHead>
                <TableHead>Notes</TableHead><TableHead>Status</TableHead><TableHead className="pr-4 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((a) => (
                <TableRow key={a.id} aria-label={`Mapping ${a.raw_code} (${a.source_label})`} className={a.problems.length ? 'bg-amber-50/60' : undefined}>
                  <TableCell className="pl-4">{a.source_label}</TableCell>
                  <TableCell>{a.project ?? <span className="text-muted-foreground">Every project</span>}</TableCell>
                  <TableCell className="font-mono">{a.raw_code}</TableCell>
                  <TableCell><span className="font-mono font-semibold">{a.circle}</span> · {a.circle_name}</TableCell>
                  <TableCell className="max-w-72">
                    {a.notes && <span className="text-muted-foreground">{a.notes}</span>}
                    {a.problems.map((p) => <p key={p} className="flex items-start gap-1 text-amber-800"><TriangleAlert className="mt-px size-3 shrink-0" aria-hidden="true" />{p}</p>)}
                  </TableCell>
                  <TableCell><ActiveBadge active={a.is_active} /></TableCell>
                  <TableCell className="pr-4 text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" aria-label={`Edit mapping ${a.raw_code}`} onClick={() => setEditing(a)}><Pencil /> Edit</Button>
                    <ConfirmAction label={a.is_active ? 'Deactivate' : 'Activate'} title={`${a.is_active ? 'Deactivate' : 'Activate'} ${a.raw_code} → ${a.circle}`} busy={list.busy}
                      destructive={a.is_active}
                      effect={a.is_active ? `Files of this source writing "${a.raw_code}" will report it as an unknown circle.` : `"${a.raw_code}" will again be read as ${a.circle}.`}
                      onConfirm={(reason) => list.change(() => updateOrgAlias(a.id, { is_active: !a.is_active, reason }), `${a.raw_code} → ${a.circle} ${a.is_active ? 'deactivated' : 'activated'}.`)} />
                  </TableCell>
                </TableRow>
              ))}
              {!rows.length && <TableRow><TableCell colSpan={7} className="py-6 text-center text-muted-foreground">No mapping matches.</TableCell></TableRow>}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

/** Site identifier mapping per project: separate from circle code aliases, read only here (nothing is guessed). */
function SiteIdMapping({ rules }: { rules: OrgSiteIdMapping[] }) {
  if (!rules.length) return null;
  return (
    <Card className="gap-0 overflow-hidden p-0" role="region" aria-label="Site identifier mapping">
      <div className="border-b px-4 py-2.5">
        <h2 className="text-sm font-semibold">Site identifier mapping</h2>
        <p className="text-xs text-muted-foreground">How a raw file's site ID finds its master site, per project. Separate from the circle codes below; a raw ID never
          resolves to another project's site.</p>
      </div>
      <ul className="divide-y text-xs">
        {rules.map((r) => (
          <li key={r.project} className="flex flex-wrap items-start gap-2 px-4 py-2">
            <span className="w-28 shrink-0 font-semibold">{r.project}</span>
            {r.configured ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">Configured</Badge>
              : <Badge variant="outline" className="border-amber-300 text-amber-800">Not configured</Badge>}
            <span className="min-w-0 flex-1 text-muted-foreground">{r.rule}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AliasForm({ alias, sources, projects, circles, busy, onCancel, onSave }: {
  alias: OrgAlias | null; sources: { value: string; label: string }[]; projects: string[]; circles: { code: string; name: string }[];
  busy: boolean; onCancel: () => void;
  onSave: (body: { source: string; project: string | null; raw_code: string; circle: string; notes: string; reason: string }) => Promise<unknown>;
}) {
  const [form, setForm] = useState({ source: alias?.source ?? '', project: alias?.project ?? '', raw_code: alias?.raw_code ?? '', circle: alias?.circle ?? '', notes: alias?.notes ?? '', reason: '' });
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const submit = (e: FormEvent) => { e.preventDefault(); void onSave({ ...form, project: form.project && form.project !== 'all' ? form.project : null }); };
  return (
    <Card className="p-3">
      <form noValidate onSubmit={submit} aria-label={alias ? `Edit mapping ${alias.raw_code}` : 'Add a mapping'} className="flex flex-wrap items-end gap-3">
        <Field id="org-alias-source" label="Source" required className="w-64">
          <SelectField id="org-alias-source" value={form.source} placeholder="Choose" disabled={!!alias} onChange={(v) => set('source', v)} options={sources} />
        </Field>
        <Field id="org-alias-project" label="Project" plain className="w-44">
          <SelectField id="org-alias-project" value={form.project || 'all'} placeholder="Every project" onChange={(v) => set('project', v)}
            options={[{ value: 'all', label: 'Every project' }, ...projects.map((p) => ({ value: p, label: p }))]} />
        </Field>
        <Field id="org-alias-raw" label="Code as written" required className="w-40"><Input id="org-alias-raw" value={form.raw_code} onChange={(e) => set('raw_code', e.target.value)} maxLength={60} /></Field>
        <Field id="org-alias-circle" label="Canonical circle" required className="w-56">
          <SelectField id="org-alias-circle" value={form.circle} placeholder="Choose" onChange={(v) => set('circle', v)} options={circles.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }))} />
        </Field>
        <Field id="org-alias-notes" label="Notes (how it was verified)" className="min-w-56 flex-1"><Input id="org-alias-notes" value={form.notes} onChange={(e) => set('notes', e.target.value)} maxLength={300} /></Field>
        <Field id="org-alias-reason" label="Reason (history)" className="w-48"><Input id="org-alias-reason" value={form.reason} onChange={(e) => set('reason', e.target.value)} /></Field>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>{busy && <Loader2 className="animate-spin" />}{alias ? 'Save' : 'Add mapping'}</Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
        <p className="w-full text-xs text-muted-foreground">Add only verified mappings. A project mapping applies to that project's files and takes precedence over an every-project mapping of the same source.</p>
      </form>
    </Card>
  );
}

// --- Change history ------------------------------------------------------------------------------

const ENTITY_LABELS: Record<string, string> = {
  organization: 'Organization', project: 'Project', circle: 'Circle', association: 'Project-circle', circle_alias: 'Code mapping', user_access: 'User access',
};

const describe = (value: Record<string, unknown> | null) => (value ? Object.entries(value).map(([k, v]) => `${k}: ${Array.isArray(v) ? (v.length ? v.map((x) => (Array.isArray(x) ? x.join(' / ') : String(x))).join(', ') : '—') : v === null || v === '' ? '—' : String(v)}`).join('; ') : '');

export function HistoryTab() {
  const list = useOrgList('history', fetchOrgHistory);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const changes = (list.data?.changes ?? []).filter((c) => (kind === 'all' || c.entity_type === kind) && matchesText(query, c.entity_label, c.actor, c.action, c.reason));
  return (
    <Card className="gap-0 overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <SearchBox id="org-history-search" value={query} onChange={setQuery} placeholder="Search history" />
        <div className="w-52"><SelectField id="org-history-kind" value={kind} placeholder="Entity" onChange={setKind}
          options={[{ value: 'all', label: 'All changes' }, ...Object.entries(ENTITY_LABELS).map(([value, label]) => ({ value, label }))]} /></div>
        <p className="ml-auto text-xs text-muted-foreground">Read only · latest 500 changes</p>
      </div>
      {!list.data ? <Loading error={list.error} /> : (
        <Table className="text-xs">
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead className="pl-4">When</TableHead><TableHead>What</TableHead><TableHead>Action</TableHead><TableHead>Before → after</TableHead>
              <TableHead>By</TableHead><TableHead className="pr-4">Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {changes.map((c: OrgChange) => (
              <TableRow key={c.id}>
                <TableCell className="pl-4 whitespace-nowrap">{formatDateTime(c.created_at)}</TableCell>
                <TableCell>{ENTITY_LABELS[c.entity_type] ?? c.entity_type}: <span className="font-medium">{c.entity_label}</span></TableCell>
                <TableCell>{c.action.replace(/_/g, ' ')}</TableCell>
                <TableCell className="max-w-md">
                  {c.previous && <Fragment><span className="text-muted-foreground">{describe(c.previous)}</span>{c.new && ' → '}</Fragment>}
                  {c.new && <span>{describe(c.new)}</span>}
                </TableCell>
                <TableCell>{c.actor}</TableCell>
                <TableCell className="pr-4">{c.reason || <span className="text-muted-foreground">—</span>}</TableCell>
              </TableRow>
            ))}
            {!changes.length && <TableRow><TableCell colSpan={6} className="py-6 text-center text-muted-foreground">No change recorded.</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
