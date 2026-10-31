import { useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Field, SelectField } from '../data/DataEntry';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDateTime } from '../../lib/format';
import { fetchAccessHistory, fetchUsers } from '../../services/api';

const label = (action: string) => action.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const detailText = (details: Record<string, unknown>) =>
  Object.entries(details).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ');

/** Users & Roles › Access History: who changed which user, role, permission or assignment, and when (latest 500). */
export function AccessHistoryTab() {
  const [user, setUser] = useState('');
  const [action, setAction] = useState('');
  const params = new URLSearchParams(Object.entries({ user, action }).filter(([, v]) => v));
  const history = useApiQuery(`access-history-${params}`, (signal) => fetchAccessHistory(params, signal));
  const users = useApiQuery('access-users', fetchUsers);
  return (
    <Card>
      <CardContent className="space-y-3 px-0">
        <div className="flex flex-wrap gap-3 px-4">
          <Field id="ah-user" label="User" className="w-56">
            <SelectField id="ah-user" value={user || '__all'} placeholder="All users" onChange={(v) => setUser(v === '__all' ? '' : v)}
              options={[{ value: '__all', label: 'All users' }, ...(users.data?.users ?? []).map((u) => ({ value: String(u.id), label: u.username }))]} />
          </Field>
          <Field id="ah-action" label="Change" className="w-56">
            <SelectField id="ah-action" value={action || '__all'} placeholder="All changes" onChange={(v) => setAction(v === '__all' ? '' : v)}
              options={[{ value: '__all', label: 'All changes' }, ...(history.data?.actions ?? []).map((a) => ({ value: a, label: label(a) }))]} />
          </Field>
        </div>
        {history.error && <p className="px-4 text-sm text-destructive">{history.error.message}</p>}
        {!history.data ? <Skeleton className="mx-4 h-32" /> : (
          <div className="overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  <TableHead className="pl-4">When</TableHead><TableHead>By</TableHead><TableHead>Change</TableHead><TableHead>User / role</TableHead><TableHead>Scope</TableHead><TableHead className="pr-4">Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {!history.data.events.length && <TableRow><TableCell colSpan={6} className="py-6 text-center text-muted-foreground">No access change recorded yet.</TableCell></TableRow>}
                {history.data.events.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="pl-4 whitespace-nowrap">{formatDateTime(e.at)}</TableCell>
                    <TableCell>{e.actor}</TableCell>
                    <TableCell>{label(e.action)}</TableCell>
                    <TableCell>{e.user || '—'}</TableCell>
                    <TableCell>{e.scope || '—'}</TableCell>
                    <TableCell className="max-w-md pr-4 break-words text-muted-foreground">{detailText(e.details) || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
