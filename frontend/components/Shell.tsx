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
  const [unread, setUnread] = useState<number | null>(null);
  const router = useRouter();
  const path = usePathname();
  useEffect(() => { let live = true; api<User>('/api/v1/auth/me').then(value => { if (live) setUser(value); }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError('Unable to check your session. Please try again.'); }); return () => { live = false; }; }, [router]);
  useEffect(() => {
    if (!user) return;
    let live = true;
    const refresh = () => { api<{count:number}>('/api/v1/notifications/unread-count').then(value => { if (live) setUnread(value.count); }).catch(() => { if (live) setUnread(null); }); };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    window.addEventListener('notifications-changed', refresh);
    return () => { live = false; window.clearInterval(timer); window.removeEventListener('notifications-changed', refresh); };
  }, [user]);
  async function logout() { try { await api<void>('/api/v1/auth/logout', {method:'POST'}); router.replace('/'); } catch (e) { if (e instanceof ApiError && e.status === 401) router.replace('/'); else setError('Unable to sign out. Please try again.'); } }
  if (!user) return <main className="grid min-h-screen place-items-center text-muted" aria-live="polite">{error || 'Checking session…'}</main>;
  return <div className="min-h-screen md:pl-64">
    {open && <button className="fixed inset-0 z-20 bg-black/60 md:hidden" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside className={`${open ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-30 w-64 overflow-y-auto border-r border-edge bg-input p-4 transition-transform md:translate-x-0`}>
      <div className="mb-8 px-3 font-display text-2xl font-semibold text-ink">Procurem</div>
      <nav aria-label="Main navigation" className="space-y-1">{[...links, ...(['procurement_manager','compliance','admin'].includes(user.role) ? [['Audit log','/audit']] : []), ...(['compliance','admin'].includes(user.role) ? [['Roles','/roles']] : []), ['Settings','/settings']].map(([label,href]) => <Link key={href} href={href} onClick={() => setOpen(false)} aria-current={path === href || path.startsWith(href + '/') ? 'page' : undefined} className={`flex min-h-10 items-center border-l-[3px] px-3 ${path === href || path.startsWith(href + '/') ? 'border-accent bg-raised text-ink' : 'border-transparent text-muted hover:text-body'}`}>{label}</Link>)}</nav>
    </aside>
    <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-edge px-4 py-3 md:px-8"><div className="flex items-center gap-3"><button className="rounded border border-edge px-3 py-1 md:hidden" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Open navigation">Menu</button><span className="font-display text-lg text-ink">{title}</span></div><div className="flex flex-wrap items-center gap-3"><Link href="/notifications" aria-label={unread === null ? 'Notifications (count unavailable)' : `Notifications${unread ? `, ${unread} unread` : ''}`} className="relative rounded border border-edge p-2 text-body"><svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 20h4"/></svg>{unread !== null && unread > 0 && <span className="absolute -right-2 -top-2 rounded-full bg-accent px-1 text-xs text-[#042f2e]">{unread}</span>}</Link><span className="grid h-8 w-8 place-items-center rounded-full bg-raised text-ink" aria-hidden="true">{user.display_name.split(' ').map(x => x[0]).join('').slice(0,2)}</span><span>{user.display_name}</span><span className="rounded-full bg-raised px-2 py-1 text-xs text-muted">{user.role.replaceAll('_',' ')}</span><button className="text-accent" onClick={logout}>Sign out</button></div></header>
    {error && <p role="alert" className="px-4 pt-4 text-danger md:px-8">{error}</p>}
    <main className="p-4 md:p-8">{children}</main>
  </div>;
}
