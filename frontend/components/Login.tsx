'use client';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../lib/api';
import type { User } from '../lib/api';

const accounts = [
  ['Priya Shah','analyst','analyst@procurem.demo','Demo@1234'],
  ['Lena Berg','category manager','category.mgr@procurem.demo','Demo@1234'],
  ['David Okonkwo','procurement manager','proc.manager@procurem.demo','Demo@1234'],
  ['Amir Rahman','sourcing specialist','sourcing@procurem.demo','Demo@1234'],
  ['Sofia Alvarez','finance analyst','finance@procurem.demo','Demo@1234'],
  ['Grace Adeyemi','compliance','compliance@procurem.demo','Demo@1234'],
  ['Helen Cho','admin','admin@procurem.demo','Admin@5678'],
];
/** Render sign-in and the current authenticated identity. */
export default function Login() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { api<User>('/api/v1/auth/me').then(setUser).catch((e: unknown) => { if (!(e instanceof ApiError && e.status === 401)) setError('Unable to connect. Please try again.'); }).finally(() => setLoading(false)); }, []);
  /** Submit the credentials and display the server identity. */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try { setUser(await api<User>('/api/v1/auth/login', { method:'POST', body:JSON.stringify({email,password,remember_me:remember}) })); setPassword(''); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Unable to connect. Please try again.'); }
    finally { setBusy(false); }
  }
  /** Revoke the session before returning to sign-in. */
  async function signOut() {
    setBusy(true); setError('');
    try { await api<void>('/api/v1/auth/logout', { method:'POST' }); setUser(null); }
    catch (e) { if (e instanceof ApiError && e.status === 401) setUser(null); else setError('Unable to sign out. Please try again.'); }
    finally { setBusy(false); }
  }
  if (loading) return <main className="grid min-h-screen place-items-center text-muted" aria-live="polite">Checking session…</main>;
  if (user) return <main className="min-h-screen p-4 md:p-8"><header className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-4 border-b border-edge pb-5"><span className="font-display text-2xl font-semibold text-ink">Procurem</span><div className="flex items-center gap-4"><span>{user.display_name} <span className="ml-2 rounded-full bg-raised px-3 py-1 text-xs text-muted">{user.role.replaceAll('_',' ')}</span></span><button className="text-accent" disabled={busy} onClick={signOut}>Sign out</button></div></header><section className="mx-auto mt-8 max-w-4xl rounded-2xl border border-edge bg-card p-5"><h1 className="font-display text-[28px] text-ink">Workspace</h1><p className="mt-2">Signed in as {user.display_name}.</p><p className="mt-2 text-muted">Procurement records and Home will be available in the next workspace release.</p>{error && <p role="alert" className="mt-3 text-danger">{error}</p>}</section></main>;
  return <main className="grid min-h-screen place-items-center bg-[radial-gradient(ellipse_at_center,rgba(45,212,191,0.08),transparent_60%)] p-4"><section className="w-full max-w-[480px] rounded-2xl border border-edge bg-card p-5 shadow-[0_10px_30px_rgba(0,0,0,0.28)] sm:p-8" aria-labelledby="login-title">
    <h1 id="login-title" className="font-display text-2xl font-semibold tracking-tight text-ink">Procurem</h1><p className="mt-1 text-muted">Procurement workspace</p>
    <form className="mt-6 space-y-4" onSubmit={submit}>
      <div><label htmlFor="email" className="mb-1.5 block font-medium text-ink">Email</label><input id="email" type="email" required aria-required="true" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} className="h-11 w-full rounded-[10px] border border-edge bg-input px-3 text-ink" /></div>
      <div><label htmlFor="password" className="mb-1.5 block font-medium text-ink">Password</label><input id="password" type="password" required aria-required="true" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} aria-invalid={!!error} aria-describedby={error ? 'login-error' : undefined} className="h-11 w-full rounded-[10px] border border-edge bg-input px-3 text-ink" /></div>
      <label className="flex items-center gap-2 text-body"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} className="h-4 w-4 accent-accent" /> Remember me</label>
      {error && <p id="login-error" role="alert" className="text-xs text-danger">{error}</p>}
      <button disabled={busy} className="h-11 w-full rounded-[10px] bg-accent font-semibold text-accentInk hover:bg-focus disabled:opacity-60">{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
    <div className="mt-7 border-t border-edge pt-5"><h2 className="text-base font-semibold text-ink">Demo accounts</h2><p className="mt-1 text-xs text-muted">Use any account to explore the workspace.</p><ul className="mt-3 max-h-56 overflow-y-auto pr-1" aria-label="Demo accounts">{accounts.map(([name,role,mail,pass]) => <li key={mail} className="border-b border-edge py-2.5 last:border-0"><div className="flex flex-wrap items-center justify-between gap-1"><span className="font-medium text-ink">{name}</span><span className="rounded-full bg-raised px-2 py-0.5 text-xs text-muted">{role}</span></div><div className="mt-1 break-all text-xs text-muted">{mail} · {pass}</div></li>)}</ul></div>
  </section></main>;
}
