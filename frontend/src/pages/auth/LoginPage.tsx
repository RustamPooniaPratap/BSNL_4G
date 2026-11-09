import { useState, type FormEvent, type ReactNode } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { CircleAlert, Eye, EyeOff, Info, Loader2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '../../context/auth';
import { ApiError } from '../../services/api';

/** Fibre-route style lines with nodes: decoration only. */
function RouteArtwork() {
  const node = (x: number, y: number, color: string) => (
    <g key={`${x}-${y}`}>
      <circle cx={x} cy={y} r="11" fill={color} opacity="0.12" />
      <circle cx={x} cy={y} r="4.5" fill="white" stroke={color} strokeWidth="2.5" />
    </g>
  );
  return (
    <svg viewBox="0 0 980 260" className="h-auto w-full" aria-hidden="true" preserveAspectRatio="none">
      <path d="M0 80 C 220 50, 380 120, 560 70 S 860 -10, 980 30" fill="none" stroke="#5eead4" strokeOpacity="0.7" strokeWidth="1.5" />
      <path d="M0 145 C 200 115, 340 190, 500 140 S 820 70, 980 110" fill="none" stroke="#7dd3fc" strokeOpacity="0.8" strokeWidth="1.5" />
      <path d="M0 205 C 200 195, 400 240, 555 200 S 840 130, 980 185" fill="none" stroke="url(#route)" strokeWidth="2" />
      <defs>
        <linearGradient id="route" x1="0" x2="1">
          <stop offset="0" stopColor="#22c55e" />
          <stop offset="1" stopColor="#0e7490" />
        </linearGradient>
      </defs>
      {[node(808, 26, '#14b8a6'), node(162, 113, '#0ea5e9'), node(499, 141, '#14b8a6'), node(555, 201, '#14b8a6')]}
    </svg>
  );
}

/** Split sign-in layout: brand panel on the left (wide screens), the form on the right. Also used to set a password. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-2">
      <section className="relative hidden flex-col justify-between overflow-hidden border-r px-14 py-12 lg:flex" aria-label="Pratap">
        <img src="/logo.png" alt="Pratap — Carving Lives" className="-ml-3 h-auto w-64 self-start object-contain" />
        <div className="-mx-14"><RouteArtwork /></div>
        <div className="max-w-lg">
          <p className="text-4xl leading-tight font-semibold tracking-tight text-slate-900">One clear view of every circle and site.</p>
          <p className="mt-4 text-base text-slate-600">
            4G Saturation and LWE uptime, thresholds, circle performance and daily reporting, in a single operations workspace.
          </p>
        </div>
      </section>
      <main className="flex items-center justify-center bg-slate-50 px-6 py-12">
        <div className="w-full max-w-md">
          <img src="/logo.png" alt="Pratap — Carving Lives" className="mb-8 h-auto w-44 object-contain lg:hidden" />
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">{title}</h1>
          <p className="mt-2 text-base text-slate-600">{subtitle}</p>
          <div className="mt-9">{children}</div>
        </div>
      </main>
    </div>
  );
}

export function LoginPage() {
  const { status, user, notice, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? '/portfolio';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === 'signed_in' && user) return <Navigate to={user.must_change_password ? '/change-password' : from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password) { setError('Enter your email ID and password.'); return; }
    setBusy(true);
    setError(null);
    try {
      const me = await signIn(email.trim(), password, remember);
      navigate(me.must_change_password ? '/change-password' : from, { replace: true });
    } catch (e) {
      // The server gives one generic message, so it never reveals whether a login ID exists.
      setError(e instanceof ApiError && e.status === 429 ? 'Too many sign-in attempts. Wait a minute and try again.'
        : e instanceof ApiError && e.status !== 0 ? 'Invalid email ID or password.' : (e as Error).message);
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Sign in" subtitle="4G Saturation & LWE reporting">
      <form noValidate onSubmit={submit} className="space-y-6">
        {notice && !error && <Alert><Info /><AlertDescription>{notice}</AlertDescription></Alert>}
        {error && <Alert variant="destructive" role="alert"><CircleAlert /><AlertDescription>{error}</AlertDescription></Alert>}
        <div className="space-y-2">
          <Label htmlFor="login-email" className="text-sm">Email ID</Label>
          <Input id="login-email" type="email" autoComplete="email" autoFocus placeholder="name@example.com" value={email} maxLength={150}
            className="h-11 bg-white text-base" onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="login-password" className="text-sm">Password</Label>
            <button type="button" className="text-sm font-medium text-sky-700 hover:underline focus-visible:underline focus-visible:outline-none"
              aria-expanded={forgot} aria-controls="forgot-help" onClick={() => setForgot((f) => !f)}>
              Forgot password?
            </button>
          </div>
          <div className="relative">
            <Input id="login-password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} maxLength={128}
              className="h-11 bg-white pr-11 text-base" onChange={(e) => setPassword(e.target.value)} />
            <button type="button" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              className="absolute top-1/2 right-2 flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-slate-500 hover:text-slate-800 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {forgot && (
            <p id="forgot-help" className="rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-900">
              Passwords are reset by a portal Admin. Ask your Admin for a temporary password; you will choose a new one when you sign in.
            </p>
          )}
        </div>
        <label className="flex items-center gap-2.5 text-sm text-slate-700">
          <input type="checkbox" className="size-4 accent-sky-700" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember me for 7 days
        </label>
        <Button type="submit" className="h-11 w-full bg-sky-700 text-base hover:bg-sky-800" disabled={busy || status === 'loading'}>
          {busy && <Loader2 className="animate-spin" />} Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
