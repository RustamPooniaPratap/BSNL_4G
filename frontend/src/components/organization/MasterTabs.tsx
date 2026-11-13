import { useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { Loader2, Pencil, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../data/DataEntry';
import { formatNumber } from '../../lib/format';
import {
  createOrgAssociation, createOrgCircle, createOrgProject, deleteOrgCircle, fetchOrgAssociations, fetchOrgCircles, fetchOrgProjects, removeOrgAssociation,
  updateOrgAssociation, updateOrgCircle, updateOrgProject,
} from '../../services/api';
import type { OrgCircle, OrgProject, OrgRemoval } from '../../types/organization';
import { TypedConfirmDialog } from './TypedConfirmDialog';
import { useOrgList } from '../../hooks/useOrgList';
import { ACTIVE_FILTERS, matchesActive, matchesText, type ActiveFilter } from '../../lib/orgFilters';
import { ActiveBadge, Chips, ConfirmAction, NoticeLine, SearchBox, UsageSummary } from './OrgParts';

function Toolbar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">{children}</div>;
}

function Loading({ error }: { error: Error | null }) {
  return error ? <p className="p-3 text-sm text-destructive" role="alert">{error.message}</p> : <Skeleton className="m-4 h-40" />;
}

const DEPENDENCY_LABELS: Record<string, string> = {
  sites: 'sites', daily: 'daily values', monthly: 'monthly values', uploads: 'uploads', rca: 'RCA records', rca_expected: 'expected RCA units',
  escalation: 'escalation sites', users: 'user grants',
};

/** The server's answer to Remove, as said to the Admin (it may keep the association instead of removing it). */
function removalMessage(circle: string, project: string, r: OrgRemoval) {
  if (r.outcome === 'removed') return `${circle} removed from ${project}.`;
  const deps = Object.entries(r.dependencies).map(([k, n]) => `${formatNumber(n ?? 0)} ${DEPENDENCY_LABELS[k] ?? k}`).join(', ');
  return `${circle} under ${project} was not removed because records refer to it (${deps}); it is ${r.outcome === 'deactivated' ? 'now' : 'already'} inactive. No record was deleted.`;
}

// --- Projects ------------------------------------------------------------------------------------

export function ProjectsTab() {
  const list = useOrgList('projects', fetchOrgProjects);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<ActiveFilter>('all');
  const [editing, setEditing] = useState<OrgProject | 'new' | null>(null);
  const rows = (list.data?.projects ?? []).filter((p) => matchesActive(status, p.is_active) && matchesText(query, p.key, p.code, p.name));
  return (
    <div className="flex flex-col gap-3">
      <NoticeLine notice={list.notice} />
      {editing && <ProjectForm project={editing === 'new' ? null : editing} busy={list.busy} onCancel={() => setEditing(null)}
        onSave={async (body) => (await list.change<unknown>(() => (editing === 'new' ? createOrgProject(body) : updateOrgProject(editing.id, body)),
          editing === 'new' ? `Project ${body.name} added.` : `Project ${body.name} saved.`)) && setEditing(null)} />}
      <Card className="gap-0 overflow-hidden p-0">
        <Toolbar>
          <SearchBox id="org-project-search" value={query} onChange={setQuery} placeholder="Search projects" />
          <Chips label="Project status" value={status} options={ACTIVE_FILTERS} onChange={setStatus} />
          <Button size="sm" className="ml-auto" onClick={() => setEditing('new')}><Plus /> Add project</Button>
        </Toolbar>
        {!list.data ? <Loading error={list.error} /> : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="pl-4">Project</TableHead><TableHead>Code</TableHead><TableHead>Identifier (stored)</TableHead>
                <TableHead>Circles</TableHead><TableHead>Records</TableHead><TableHead>Status</TableHead><TableHead className="pr-4 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.id} aria-label={`Project ${p.name}`}>
                  <TableCell className="pl-4"><span className="font-medium">{p.name}</span>{p.description && <p className="text-muted-foreground">{p.description}</p>}</TableCell>
                  <TableCell>{p.code}</TableCell>
                  <TableCell className="font-mono">{p.key}</TableCell>
                  <TableCell className="max-w-64">{p.circles.length ? p.circles.map((c) => c.is_active ? c.code : `${c.code} (inactive)`).join(', ') : <span className="text-muted-foreground">None associated</span>}</TableCell>
                  <TableCell><UsageSummary usage={p.usage} /></TableCell>
                  <TableCell><ActiveBadge active={p.is_active} /></TableCell>
                  <TableCell className="pr-4 text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}><Pencil /> Edit</Button>
                    <ConfirmAction label={p.is_active ? 'Deactivate' : 'Activate'} title={`${p.is_active ? 'Deactivate' : 'Activate'} ${p.name}`} busy={list.busy}
                      destructive={p.is_active}
                      effect={p.is_active ? 'No new uploads or records can be made for it. Its sites, daily, monthly, upload and RCA records are kept.' : 'It becomes available again in selectors.'}
                      onConfirm={(reason) => list.change(() => updateOrgProject(p.id, { is_active: !p.is_active, reason }), `${p.name} ${p.is_active ? 'deactivated' : 'activated'}.`)} />
                  </TableCell>
                </TableRow>
              ))}
              {!rows.length && <TableRow><TableCell colSpan={7} className="py-6 text-center text-muted-foreground">No project matches.</TableCell></TableRow>}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function ProjectForm({ project, busy, onCancel, onSave }: {
  project: OrgProject | null; busy: boolean; onCancel: () => void;
  onSave: (body: { key: string; code: string; name: string; description: string; reason: string }) => Promise<unknown>;
}) {
  const [form, setForm] = useState({ key: project?.key ?? '', code: project?.code ?? '', name: project?.name ?? '', description: project?.description ?? '', reason: '' });
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = (e: FormEvent) => { e.preventDefault(); void onSave(form); };
  return (
    <Card className="p-3">
      <form noValidate onSubmit={submit} aria-label={project ? `Edit ${project.name}` : 'Add a project'} className="flex flex-wrap items-end gap-3">
        <Field id="org-project-key" label="Identifier (stored on records)" required className="w-48">
          <Input id="org-project-key" value={form.key} onChange={set('key')} disabled={!!project} maxLength={20} />
        </Field>
        <Field id="org-project-code" label="Short code" required className="w-28"><Input id="org-project-code" value={form.code} onChange={set('code')} maxLength={12} /></Field>
        <Field id="org-project-name" label="Name" required className="w-56"><Input id="org-project-name" value={form.name} onChange={set('name')} maxLength={80} /></Field>
        <Field id="org-project-description" label="Description" className="min-w-56 flex-1"><Input id="org-project-description" value={form.description} onChange={set('description')} /></Field>
        <Field id="org-project-reason" label="Reason (history)" className="w-56"><Input id="org-project-reason" value={form.reason} onChange={set('reason')} /></Field>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>{busy && <Loader2 className="animate-spin" />}{project ? 'Save' : 'Add project'}</Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
        {project && <p className="w-full text-xs text-muted-foreground">The identifier is stored on this project's records and cannot change; edit the name or short code instead.</p>}
      </form>
    </Card>
  );
}

// --- Circles -------------------------------------------------------------------------------------

export function CirclesTab() {
  const list = useOrgList('circles', fetchOrgCircles);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<ActiveFilter>('all');
  const [editing, setEditing] = useState<OrgCircle | 'new' | null>(null);
  const rows = (list.data?.circles ?? []).filter((c) => matchesActive(status, c.is_active) && matchesText(query, c.code, c.name, ...c.projects.map((p) => p.project)));
  return (
    <div className="flex flex-col gap-3">
      <NoticeLine notice={list.notice} />
      {editing && <CircleForm circle={editing === 'new' ? null : editing} busy={list.busy} onCancel={() => setEditing(null)}
        onSave={async (body) => (await list.change(() => (editing === 'new' ? createOrgCircle(body) : updateOrgCircle(editing.id, body)),
          editing === 'new' ? `Circle ${body.code} added. Associate it with a project in Project-Circle Mapping.` : `Circle ${body.code} saved.`)) && setEditing(null)} />}
      <Card className="gap-0 overflow-hidden p-0">
        <Toolbar>
          <SearchBox id="org-circle-search" value={query} onChange={setQuery} placeholder="Search circles" />
          <Chips label="Circle status" value={status} options={ACTIVE_FILTERS} onChange={setStatus} />
          <Button size="sm" className="ml-auto" onClick={() => setEditing('new')}><Plus /> Add circle</Button>
        </Toolbar>
        {!list.data ? <Loading error={list.error} /> : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="pl-4">Code</TableHead><TableHead>Name</TableHead><TableHead>Projects and their records</TableHead>
                <TableHead>Aliases</TableHead><TableHead>Status</TableHead><TableHead className="pr-4 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.id} aria-label={`Circle ${c.code}`}>
                  <TableCell className="pl-4 font-mono font-semibold">{c.code}</TableCell>
                  <TableCell>{c.name}{c.description && <p className="text-muted-foreground">{c.description}</p>}</TableCell>
                  <TableCell>
                    {c.projects.length ? (
                      <ul className="flex flex-col gap-0.5">
                        {c.projects.map((p) => (
                          <li key={p.project}><span className="font-medium">{p.project_code}</span>{!p.is_active && ' (inactive)'}: <UsageSummary usage={p.usage} /></li>
                        ))}
                      </ul>
                    ) : <span className="text-muted-foreground">No project yet</span>}
                    {c.unassociated_data.map((u) => (
                      <p key={u.project} className="text-amber-800">Not associated with {u.project}, but has <UsageSummary usage={u.usage} /></p>
                    ))}
                  </TableCell>
                  <TableCell>{formatNumber(c.aliases)}</TableCell>
                  <TableCell><ActiveBadge active={c.is_active} /></TableCell>
                  <TableCell className="pr-4 text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" aria-label={`Edit ${c.code}`} onClick={() => setEditing(c)}><Pencil /> Edit</Button>
                    <ConfirmAction label={c.is_active ? 'Deactivate' : 'Activate'} title={`${c.is_active ? 'Deactivate' : 'Activate'} ${c.code}`} busy={list.busy}
                      destructive={c.is_active}
                      effect={c.is_active ? 'It is no longer offered for uploads or new records under any project. Historical records are kept and stay visible.' : 'It becomes available again for its associated projects.'}
                      onConfirm={(reason) => list.change(() => updateOrgCircle(c.id, { is_active: !c.is_active, reason }), `${c.code} ${c.is_active ? 'deactivated' : 'activated'}.`)} />
                    <TypedConfirmDialog trigger="Delete" triggerLabel={`Delete ${c.code}`} title={`Delete circle ${c.code} · ${c.name}`} action="Delete circle"
                      phrase={`${c.code} - ${c.name}`} disabled={!c.deletable} error={list.notice?.kind === 'error' ? list.notice.text : null}
                      onConfirm={(reason) => list.change(() => deleteOrgCircle(c.id, { reason }), `Circle ${c.code} deleted.`)}>
                      <p>The global circle record is deleted permanently. This is possible only because nothing refers to it: no project association,
                        code mapping, site, daily or monthly value, upload, RCA record or user grant.</p>
                    </TypedConfirmDialog>
                  </TableCell>
                </TableRow>
              ))}
              {!rows.length && <TableRow><TableCell colSpan={6} className="py-6 text-center text-muted-foreground">No circle matches.</TableCell></TableRow>}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function CircleForm({ circle, busy, onCancel, onSave }: {
  circle: OrgCircle | null; busy: boolean; onCancel: () => void;
  onSave: (body: { code: string; name: string; description: string; reason: string }) => Promise<unknown>;
}) {
  const [form, setForm] = useState({ code: circle?.code ?? '', name: circle?.name ?? '', description: circle?.description ?? '', reason: '' });
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: k === 'code' ? e.target.value.toUpperCase() : e.target.value }));
  return (
    <Card className="p-3">
      <form noValidate onSubmit={(e) => { e.preventDefault(); void onSave(form); }} aria-label={circle ? `Edit ${circle.code}` : 'Add a circle'} className="flex flex-wrap items-end gap-3">
        <Field id="org-circle-code" label="Code (stored on records)" required className="w-40">
          <Input id="org-circle-code" value={form.code} onChange={set('code')} disabled={!!circle} maxLength={20} placeholder="e.g. KL" />
        </Field>
        <Field id="org-circle-name" label="Name" required className="w-56"><Input id="org-circle-name" value={form.name} onChange={set('name')} maxLength={80} placeholder="e.g. Kerala" /></Field>
        <Field id="org-circle-description" label="Description" className="min-w-56 flex-1"><Input id="org-circle-description" value={form.description} onChange={set('description')} /></Field>
        <Field id="org-circle-reason" label="Reason (history)" className="w-56"><Input id="org-circle-reason" value={form.reason} onChange={set('reason')} /></Field>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>{busy && <Loader2 className="animate-spin" />}{circle ? 'Save' : 'Add circle'}</Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
        <p className="w-full text-xs text-muted-foreground">
          {circle ? 'The code is stored on this circle\'s records and cannot change; edit the name instead.'
            : 'One record per circle, whichever projects it belongs to. Adding a circle creates no sites, data, uploads or access.'}
        </p>
      </form>
    </Card>
  );
}

// --- Project-circle mapping ----------------------------------------------------------------------

export function MappingTab() {
  const list = useOrgList('associations', fetchOrgAssociations);
  const projects = useOrgList('projects-for-mapping', fetchOrgProjects);
  const circles = useOrgList('circles-for-mapping', fetchOrgCircles);
  const [query, setQuery] = useState('');
  const [project, setProject] = useState('all');
  const [status, setStatus] = useState<ActiveFilter>('all');
  const [draft, setDraft] = useState({ project: '', circle: '', reason: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const all = list.data?.associations ?? [];
  const rows = all.filter((a) => (project === 'all' || a.project === project) && matchesActive(status, a.is_active) && matchesText(query, a.circle, a.circle_name, a.project));
  const projectKeys = (projects.data?.projects ?? []).map((p) => p.key);
  const circleCodes = (circles.data?.circles ?? []).map((c) => c.code);
  const add = async (e: FormEvent) => {
    e.preventDefault();
    setErrors({});
    if (!draft.project || !draft.circle) return setErrors({ form: 'Choose a project and a circle.' });
    if (await list.change(() => createOrgAssociation(draft), `${draft.circle} associated with ${draft.project}. No sites, data, obligations or access were created.`)) {
      setDraft({ project: draft.project, circle: '', reason: '' });
    }
  };
  // Matrix: one row per circle, one column per project.
  const matrixCircles = [...new Set(all.map((a) => a.circle))].sort();
  return (
    <div className="flex flex-col gap-3">
      <NoticeLine notice={list.notice} />
      <Card className="p-3">
        <form noValidate onSubmit={add} aria-label="Associate a circle with a project" className="flex flex-wrap items-end gap-3">
          <Field id="org-map-project" label="Project" required className="w-48">
            <SelectField id="org-map-project" value={draft.project} placeholder="Choose" onChange={(v) => setDraft((d) => ({ ...d, project: v }))}
              options={(projects.data?.projects ?? []).map((p) => ({ value: p.key, label: p.is_active ? p.name : `${p.name} (inactive)` }))} />
          </Field>
          <Field id="org-map-circle" label="Existing circle" required className="w-56">
            <SelectField id="org-map-circle" value={draft.circle} placeholder="Choose" onChange={(v) => setDraft((d) => ({ ...d, circle: v }))}
              options={(circles.data?.circles ?? []).filter((c) => !all.some((a) => a.project === draft.project && a.circle === c.code))
                .map((c) => ({ value: c.code, label: `${c.code} · ${c.name}${c.is_active ? '' : ' (inactive)'}` }))} />
          </Field>
          <Field id="org-map-reason" label="Reason (history)" className="w-56">
            <Input id="org-map-reason" value={draft.reason} onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))} />
          </Field>
          <Button type="submit" disabled={list.busy}>{list.busy && <Loader2 className="animate-spin" />}<Plus /> Associate</Button>
          {errors.form && <p className="w-full text-xs text-destructive" role="alert">{errors.form}</p>}
          <p className="w-full text-xs text-muted-foreground">Membership only: associating a circle creates no sites, daily or monthly data, reporting obligation, user access or RCA records.</p>
        </form>
      </Card>
      {list.data && projectKeys.length > 0 && (
        <Card className="gap-0 overflow-hidden p-0">
          <div className="border-b px-4 py-2.5"><h2 className="text-sm font-semibold">Circles by project</h2></div>
          <div className="overflow-x-auto">
            <Table className="text-xs" aria-label="Project-circle matrix">
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  <TableHead className="pl-4">Circle</TableHead>
                  {projectKeys.map((p) => <TableHead key={p} className="text-center">{p}</TableHead>)}
                </TableRow>
              </TableHeader>
              <TableBody>
                {matrixCircles.map((c) => (
                  <TableRow key={c}>
                    <TableCell className="pl-4 font-mono font-semibold">{c}</TableCell>
                    {projectKeys.map((p) => {
                      const a = all.find((x) => x.project === p && x.circle === c);
                      return <TableCell key={p} className="text-center">{a ? (a.is_active ? 'Yes' : 'Inactive') : <span className="text-muted-foreground">No</span>}</TableCell>;
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {circleCodes.length > matrixCircles.length && (
            <p className="border-t px-4 py-2 text-xs text-muted-foreground">Not associated with any project: {circleCodes.filter((c) => !matrixCircles.includes(c)).join(', ')}.</p>
          )}
        </Card>
      )}
      <Card className="gap-0 overflow-hidden p-0">
        <Toolbar>
          <SearchBox id="org-map-search" value={query} onChange={setQuery} placeholder="Search associations" />
          <Chips label="Project" value={project} options={[['all', 'All projects'], ...projectKeys.map((p) => [p, p] as [string, string])]} onChange={setProject} />
          <Chips label="Association status" value={status} options={ACTIVE_FILTERS} onChange={setStatus} />
        </Toolbar>
        {!list.data ? <Loading error={list.error} /> : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="pl-4">Project</TableHead><TableHead>Circle</TableHead><TableHead className="text-right">Approved sites</TableHead>
                <TableHead className="text-right">On-Air</TableHead><TableHead>Other records</TableHead><TableHead>Status</TableHead><TableHead className="pr-4 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((a) => {
                const used = Object.values(a.usage).some((n) => n > 0);
                return (
                  <TableRow key={a.id} aria-label={`${a.circle} under ${a.project}`}>
                    <TableCell className="pl-4">{a.project}{!a.project_active && <span className="text-muted-foreground"> (project inactive)</span>}</TableCell>
                    <TableCell><span className="font-mono font-semibold">{a.circle}</span> · {a.circle_name}{!a.circle_active && <span className="text-muted-foreground"> (circle inactive)</span>}</TableCell>
                    <TableCell className="text-right tabular-nums">{a.usage.sites ? formatNumber(a.usage.sites) : <span className="text-muted-foreground">None</span>}</TableCell>
                    <TableCell className="text-right tabular-nums">{a.usage.sites ? formatNumber(a.usage.on_air_sites) : <span className="text-muted-foreground">—</span>}</TableCell>
                    <TableCell><UsageSummary usage={{ ...a.usage, sites: 0 }} /></TableCell>
                    <TableCell><ActiveBadge active={a.is_active} /></TableCell>
                    <TableCell className="pr-4 text-right whitespace-nowrap">
                      <ConfirmAction label={a.is_active ? 'Deactivate' : 'Activate'} title={`${a.is_active ? 'Deactivate' : 'Activate'} ${a.circle} under ${a.project}`} busy={list.busy}
                        destructive={a.is_active}
                        effect={a.is_active ? 'The circle is no longer offered for this project\'s uploads and new records. Stored records are kept.' : 'The circle is offered again for this project.'}
                        onConfirm={(reason) => list.change(() => updateOrgAssociation(a.id, { is_active: !a.is_active, reason }), `${a.circle} under ${a.project} ${a.is_active ? 'deactivated' : 'activated'}.`)} />
                      <TypedConfirmDialog trigger="Remove" triggerLabel={`Remove ${a.circle} from ${a.project}`} title={`Remove ${a.circle} from ${a.project}`}
                        action="Confirm removal" phrase={`${a.circle} - ${a.project}`} error={list.notice?.kind === 'error' ? list.notice.text : null}
                        onConfirm={(reason) => list.change(() => removeOrgAssociation(a.id, { reason }), (r) => removalMessage(a.circle, a.project, r))}>
                        <p>Only the association of <strong>{a.circle}</strong> with <strong>{a.project}</strong> is affected. The global circle and its other project
                          associations stay as they are.</p>
                        {used ? (
                          <p className="mt-2 text-amber-800">Records refer to it (<UsageSummary usage={{ ...a.usage, on_air_sites: 0 }} />), so it will not be deleted: it is kept
                            {a.is_active ? ' and deactivated' : ' inactive'}, out of new uploads and options. No record is deleted.</p>
                        ) : <p className="mt-2">Nothing refers to it, so it is removed.</p>}
                      </TypedConfirmDialog>
                    </TableCell>
                  </TableRow>
                );
              })}
              {!rows.length && <TableRow><TableCell colSpan={7} className="py-6 text-center text-muted-foreground">No association matches.</TableCell></TableRow>}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
