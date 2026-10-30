import { useState } from 'react';
import { Loader2, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useOrganization } from '../../hooks/useOrganization';
import { setOrgAccess } from '../../services/api';

type Pair = { project: string; circle: string };
const keyOf = (p: Pair) => `${p.project}|${p.circle}`;

/**
 * Project/circle grants of one CI user: one checkbox per association of the Organization, grouped by project. The same
 * editor serves Organization > User Access and Users & Roles, so there is one permission model. MP under 4G and MP under
 * LWE are separate grants. Saving replaces the legacy circle-only assignment, which applied to every project.
 */
export function AccessEditor({ username, userId, pairs, legacy, onSaved, onError, onCancel }: {
  username: string; userId: number; pairs: Pair[]; legacy: string[];
  onSaved: (message: string) => void; onError: (message: string) => void; onCancel: () => void;
}) {
  const catalog = useOrganization();
  const [value, setValue] = useState<Set<string>>(() => new Set(pairs.map(keyOf)));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const toggle = (k: string) => setValue((v) => { const next = new Set(v); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  const save = async () => {
    setBusy(true);
    try {
      const chosen = [...value].map((k) => { const [project, circle] = k.split('|'); return { project, circle }; });
      await setOrgAccess(userId, chosen, reason);
      onSaved(chosen.length ? `${username} can now use ${chosen.map((p) => `${p.circle} (${p.project})`).join(', ')}.` : `${username} has no project or circle and cannot upload or export.`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const data = catalog.data;
  return (
    <fieldset className="flex max-w-xl flex-col gap-2 rounded-md border bg-card p-2.5 text-xs" aria-label={`Access of ${username}`}>
      {legacy.length > 0 && (
        <p className="flex items-start gap-1.5 text-amber-800">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          Legacy circle-only access to {legacy.join(', ')} still applies to every project. Choose the projects below; saving replaces it.
        </p>
      )}
      {!data ? <p className="text-muted-foreground">{catalog.error ? catalog.error.message : 'Loading projects and circles…'}</p> : data.projects.map((p) => {
        const links = data.associations.filter((a) => a.project === p.key);
        if (!links.length) return null;
        return (
          <div key={p.key} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="w-24 shrink-0 font-semibold">{p.name}</span>
            {links.map((a) => {
              const k = keyOf(a);
              return (
                <label key={k} className="flex items-center gap-1">
                  <input type="checkbox" checked={value.has(k)} onChange={() => toggle(k)} aria-label={`${a.circle} under ${p.key}`} />
                  {a.circle}{!a.is_active && <span className="text-muted-foreground">(inactive)</span>}
                </label>
              );
            })}
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Reason (optional)" placeholder="Reason (optional, kept in the history)" value={reason} onChange={(e) => setReason(e.target.value)} className="h-7 max-w-64 text-xs" />
        <Button size="sm" className="h-7 px-2 text-xs" disabled={busy || !data} onClick={() => { void save(); }}>{busy && <Loader2 className="animate-spin" />}Save access</Button>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={onCancel}>Cancel</Button>
      </div>
    </fieldset>
  );
}
