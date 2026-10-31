import { useState, type FormEvent } from 'react';
import { CircleAlert, CircleCheck, Loader2, PlugZap, Power, Save, Send } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Field, SelectField } from '../../components/data/DataEntry';
import { PageHeading } from '../../context/pageHeader';
import { useApiQuery } from '../../hooks/useApiQuery';
import { formatDateTime } from '../../lib/format';
import { activateAlertAccount, fetchAlertAccount, saveAlertAccount, testAlertAccount } from '../../services/api';
import type { AlertAccount } from '../../types/alerts';
import { WorkerStatus } from './AlertParts';

type Form = Omit<AlertAccount, 'id' | 'password_set' | 'is_active' | 'tested_ok_at' | 'last_test' | 'updated_at'> & { password: string };
const EMPTY: Form = { name: 'Portal email', host: '', port: 587, security: 'starttls', auth: 'password', username: '', password: '', from_email: '', from_name: 'BSNL Reporting Portal', reply_to: '', timeout: 20 };

/**
 * Alert › Email Setup: the approved outgoing account, configured once. The password is sent once and stored encrypted
 * on the server; it is never shown again. Automated emails start only after a test email succeeded and the account is
 * activated; changing the connection deactivates it until it is tested again.
 */
export function AlertEmailSetupPage() {
  const [version, setVersion] = useState(0);
  const query = useApiQuery(`alert-account-${version}`, fetchAlertAccount);
  const account = query.data?.account ?? null;
  return (
    <div className="space-y-4">
      <PageHeading title="Email Setup" subtitle="The outgoing email account used by every alert and automation. Configure it once, test it, then activate it." />
      {query.data && <WorkerStatus worker={query.data.worker} />}
      {query.error && <p className="text-sm text-destructive" role="alert">{query.error.message}</p>}
      {query.data && <AccountForm key={account?.updated_at ?? 'new'} account={account} onChanged={() => setVersion((v) => v + 1)} />}
    </div>
  );
}

function AccountForm({ account, onChanged }: { account: AlertAccount | null; onChanged: () => void }) {
  const [form, setForm] = useState<Form>(account ? { ...account, password: '' } : EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [testTo, setTestTo] = useState('');
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const run = async (name: string, action: () => Promise<{ ok: boolean; text: string }>) => {
    setBusy(name);
    setResult(null);
    setErrors({});
    try {
      setResult(await action());
    } catch (e) {
      const details = (e as { details?: Record<string, unknown> }).details ?? {};
      setErrors(Object.fromEntries(Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)])));
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    void run('save', async () => {
      const r = await saveAlertAccount({ ...form });
      onChanged();
      return { ok: true, text: r.account.is_active ? 'Saved.' : 'Saved. Send a test email, then activate the account.' };
    });
  };
  const test = (to = '') => run(to ? 'email' : 'connection', async () => {
    try {
      const r = await testAlertAccount(to);
      onChanged();
      return { ok: r.ok, text: r.message };
    } catch (e) {
      onChanged();
      throw e;
    }
  });
  const text = (k: keyof Form, label: string, type = 'text', required = false) => (
    <Field id={`acc-${k}`} label={label} required={required} error={errors[k]}>
      <Input id={`acc-${k}`} type={type} value={String(form[k] ?? '')} onChange={(e) => set(k, (type === 'number' ? Number(e.target.value) : e.target.value) as never)} />
    </Field>
  );
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card className="gap-4 px-5 py-4 xl:col-span-2">
        <form noValidate onSubmit={save} aria-label="Email configuration" className="grid gap-3 sm:grid-cols-2">
          {text('name', 'Configuration name', 'text', true)}
          <div className="grid grid-cols-[1fr_6rem] gap-3">{text('host', 'SMTP host', 'text', true)}{text('port', 'Port', 'number', true)}</div>
          <Field id="acc-security" label="Encryption" required>
            <SelectField id="acc-security" value={form.security} placeholder="Encryption" onChange={(v) => set('security', v as Form['security'])}
              options={[{ value: 'starttls', label: 'STARTTLS (port 587)' }, { value: 'ssl', label: 'SSL/TLS (port 465)' }, { value: 'none', label: 'None (internal relay only)' }]} />
          </Field>
          <Field id="acc-auth" label="Authentication" required>
            <SelectField id="acc-auth" value={form.auth} placeholder="Authentication" onChange={(v) => set('auth', v as Form['auth'])}
              options={[{ value: 'password', label: 'Username and password (SMTP AUTH)' }, { value: 'none', label: 'No authentication (approved relay)' }]} />
          </Field>
          {form.auth === 'password' && text('username', 'Username', 'text', true)}
          {form.auth === 'password' && (
            <Field id="acc-password" label="Password" required={!account?.password_set} error={errors.password}
              hint={account?.password_set ? 'A password is stored (encrypted). Leave blank to keep it.' : 'Stored encrypted on the server; never shown again.'}>
              <Input id="acc-password" type="password" autoComplete="new-password" value={form.password} onChange={(e) => set('password', e.target.value)} />
            </Field>
          )}
          {text('from_email', 'Sender email', 'email', true)}
          {text('from_name', 'Display name')}
          {text('reply_to', 'Reply-to address', 'email')}
          {text('timeout', 'Connection timeout (seconds)', 'number', true)}
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button type="submit" disabled={!!busy}>{busy === 'save' ? <Loader2 className="animate-spin" /> : <Save />} Save Configuration</Button>
            <Button type="button" variant="outline" disabled={!!busy || !account} onClick={() => { void test(); }}>{busy === 'connection' ? <Loader2 className="animate-spin" /> : <PlugZap />} Test Connection</Button>
          </div>
        </form>
        {result && (
          <p role={result.ok ? 'status' : 'alert'} className={`flex items-start gap-1.5 rounded-md border px-3 py-2 text-sm ${result.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-destructive/30 bg-destructive/5 text-destructive'}`}>
            {result.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" />}{result.text}
          </p>
        )}
      </Card>
      <Card className="gap-3 px-5 py-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Status</h2>
          {account?.is_active ? <Badge variant="outline" className="border-emerald-300 text-emerald-800">Active</Badge> : <Badge variant="outline">Not active</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">
          {account?.tested_ok_at ? `Last successful test email: ${formatDateTime(account.tested_ok_at)}.` : 'No successful test email since the last change.'}
          {account?.last_test ? ` Last result: ${account.last_test}` : ''}
        </p>
        <Field id="acc-test-to" label="Send a test email to">
          <Input id="acc-test-to" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="you@example.com" />
        </Field>
        <Button type="button" variant="outline" disabled={!!busy || !account || !testTo.trim()} onClick={() => { void test(testTo.trim()); }}>
          {busy === 'email' ? <Loader2 className="animate-spin" /> : <Send />} Send Test Email
        </Button>
        <Button type="button" disabled={!!busy || !account || (!account.is_active && !account.tested_ok_at)}
          variant={account?.is_active ? 'outline' : 'default'}
          onClick={() => run('activate', async () => { const r = await activateAlertAccount(!account!.is_active); onChanged();
            return { ok: true, text: r.account.is_active ? 'Activated: automations may now send email.' : 'Deactivated: no automated email is sent, and enabled automations were paused.' }; })}>
          <Power /> {account?.is_active ? 'Deactivate' : 'Activate'}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Microsoft 365 may not allow SMTP passwords (SMTP AUTH is often disabled). Use the method your email administrator approves: an account with SMTP AUTH
          enabled, or an internal relay that accepts this server without a password.
        </p>
      </Card>
    </div>
  );
}
