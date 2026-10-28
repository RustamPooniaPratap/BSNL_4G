import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CircleAlert, KeyRound, Loader2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Field } from '../../components/data/DataEntry';
import { Input } from '@/components/ui/input';
import { useAuth } from '../../context/auth';
import { fieldA11y } from '../../lib/dataEntry';
import { ApiError, changePassword } from '../../services/api';
import { AuthShell } from './LoginPage';

type Fields = 'current' | 'next' | 'confirm';

/** Change password: required after a temporary password, available to everyone from the account menu. */
export function ChangePasswordPage() {
  const { user, setUser, signOut } = useAuth();
  const navigate = useNavigate();
  const forced = Boolean(user?.must_change_password);
  const [values, setValues] = useState<Record<Fields, string>>({ current: '', next: '', confirm: '' });
  const [errors, setErrors] = useState<Partial<Record<Fields, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: Fields, v: string) => setValues((s) => ({ ...s, [k]: v }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const e: Partial<Record<Fields, string>> = {};
    if (!values.current) e.current = 'Enter your current password.';
    if (values.next.length < 10) e.next = 'Use at least 10 characters.';
    if (values.next !== values.confirm) e.confirm = 'The two new passwords do not match.';
    setErrors(e);
    setError(null);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const me = await changePassword(values.current, values.next);
      setUser(me);
      navigate('/portfolio', { replace: true, state: { passwordChanged: true } });
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const d = err.details as Record<string, string[] | undefined>;
        setErrors({ current: d.current_password?.[0], next: d.new_password?.join(' ') });
        if (!d.current_password && !d.new_password) setError(err.message);
      } else {
        setError((err as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  const input = (k: Fields, id: string, label: string, autoComplete: string) => (
    <Field id={id} label={label} required error={errors[k]}>
      <Input {...fieldA11y(id, errors[k])} type="password" autoComplete={autoComplete} value={values[k]} maxLength={128} onChange={(ev) => set(k, ev.target.value)} />
    </Field>
  );

  return (
    <AuthShell title={forced ? 'Set your password' : 'Change password'}
      subtitle={forced ? 'You signed in with a temporary password. Choose your own before using the portal.' : `Signed in as ${user?.username ?? ''}.`}>
      <form noValidate onSubmit={submit} className="space-y-4">
        {error && <Alert variant="destructive" role="alert"><CircleAlert /><AlertDescription>{error}</AlertDescription></Alert>}
        {input('current', 'pw-current', forced ? 'Temporary password' : 'Current password', 'current-password')}
        {input('next', 'pw-new', 'New password', 'new-password')}
        {input('confirm', 'pw-confirm', 'Confirm new password', 'new-password')}
        <p className="text-xs text-muted-foreground">At least 10 characters; not only digits, not a common password and not similar to your login ID.</p>
        <Button type="submit" className="w-full" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <KeyRound />} Save password</Button>
        {forced
          ? <Button type="button" variant="ghost" className="w-full" onClick={() => { void signOut(); }}>Sign out</Button>
          : <Link to="/portfolio" className={buttonVariants({ variant: 'ghost', className: 'w-full' })}>Cancel</Link>}
      </form>
    </AuthShell>
  );
}
