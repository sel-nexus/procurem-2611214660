'use client';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { api, ApiError } from '../lib/api';
import type { User } from '../lib/api';

const links = [['Home','/home'],['Assistant','/assistant'],['Suppliers','/suppliers'],['Catalog','/catalog'],['Purchase orders','/purchase-orders'],['Invoices','/invoices'],['Contracts','/contracts'],['Requisitions','/requisitions'],['Sourcing','/sourcing'],['Spend','/spend'],['Knowledge','/knowledge'],['Approvals','/approvals']];
/** Protect workspace pages and provide consistent identity and navigation. */
export default function Shell({ title, children }: { title: string; children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const path = usePathname();
  useEffect(() => { let live = true; api<User>('/api/v1/auth/me').then(value => { if (live) setUser(value); }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError('Unable to check your session. Please try again.'); }); return () => { live = false; }; }, [router]);
  async function logout() { try { await api<void>('/api/v1/auth/logout', {method:'POST'}); router.replace('/'); } catch (e) { if (e instanceof ApiError && e.status === 401) router.replace('/'); else setError('Unable to sign out. Please try again.'); } }
  if (!user) return <main className="grid min-h-screen place-items-center text-muted" aria-live="polite">{error || 'Checking session…'}</main>;
  return <div className="min-h-screen md:pl-64">
    {open && <button className="fixed inset-0 z-20 bg-black/60 md:hidden" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside className={`${open ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-30 w-64 overflow-y-auto border-r border-edge bg-input p-4 transition-transform md:translate-x-0`}>
      <div className="mb-8 px-3 font-display text-2xl font-semibold text-ink">Procurem</div>
      <nav aria-label="Main navigation" className="space-y-1">{links.map(([label,href]) => <Link key={href} href={href} onClick={() => setOpen(false)} aria-current={path === href || path.startsWith(href + '/') ? 'page' : undefined} className={`flex min-h-10 items-center border-l-[3px] px-3 ${path === href || path.startsWith(href + '/') ? 'border-accent bg-raised text-ink' : 'border-transparent text-muted hover:text-body'}`}>{label}</Link>)}</nav>
    </aside>
    <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-edge px-4 py-3 md:px-8"><div className="flex items-center gap-3"><button className="rounded border border-edge px-3 py-1 md:hidden" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Open navigation">Menu</button><span className="font-display text-lg text-ink">{title}</span></div><div className="flex flex-wrap items-center gap-3"><span className="grid h-8 w-8 place-items-center rounded-full bg-raised text-ink" aria-hidden="true">{user.display_name.split(' ').map(x => x[0]).join('').slice(0,2)}</span><span>{user.display_name}</span><span className="rounded-full bg-raised px-2 py-1 text-xs text-muted">{user.role.replaceAll('_',' ')}</span><button className="text-accent" onClick={logout}>Sign out</button></div></header>
    {error && <p role="alert" className="px-4 pt-4 text-danger md:px-8">{error}</p>}
    <main className="p-4 md:p-8">{children}</main>
  </div>;
}
