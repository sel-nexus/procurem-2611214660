'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import Link from 'next/link';
import { api, ApiError } from '../lib/api';

type Role = 'analyst'|'category_manager'|'procurement_manager'|'sourcing_specialist'|'finance_analyst'|'compliance'|'admin';
type Account = {id:number; display_name:string; email:string; role:Role; status:'active'|'inactive'};
type Page = {items:Account[]; total:number; page:number; page_size:number};
type PasswordResult = {user:Account; temporary_password:string};
const roles:Role[] = ['analyst','category_manager','procurement_manager','sourcing_specialist','finance_analyst','compliance','admin'];
const card = 'rounded-2xl border border-edge bg-card p-5';
const input = 'min-h-11 w-full rounded-[10px] border border-edge bg-input px-3 text-ink';
const button = 'min-h-11 rounded-[10px] border border-edge bg-raised px-4 text-body';
const primary = 'min-h-11 rounded-[10px] bg-accent px-4 font-medium text-[#042f2e]';
const message = (error:unknown, fallback:string) => error instanceof ApiError ? error.message : fallback;

/** Present a secret once and clear it when the dialog closes. */
function PasswordDialog({password, close}:{password:string; close:()=>void}) {
  const ref = useRef<HTMLDivElement>(null);
  const [copyStatus,setCopyStatus] = useState('');
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => { document.body.style.overflow = oldOverflow; previous?.focus(); };
  }, []);
  function keys(event:KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const buttons = ref.current?.querySelectorAll<HTMLButtonElement>('button');
      if (!buttons?.length) return;
      if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons[buttons.length-1].focus(); }
      else if (!event.shiftKey && document.activeElement === buttons[buttons.length-1]) { event.preventDefault(); buttons[0].focus(); }
    }
  }
  async function copy() { try { await navigator.clipboard.writeText(password); setCopyStatus('Password copied.'); } catch { setCopyStatus('Unable to copy. Select and copy the password manually.'); } }
  return <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4" onMouseDown={event => {if (event.target === event.currentTarget) close();}}><div ref={ref} role="dialog" aria-modal="true" aria-labelledby="password-title" onKeyDown={keys} className={`${card} w-full max-w-md space-y-4`}><h2 id="password-title" className="text-lg text-ink">Temporary password</h2><p>This password is shown once.</p><p className="break-all rounded border border-edge bg-input p-3 text-ink">{password}</p><div className="flex gap-3"><button type="button" className={primary} onClick={() => void copy()}>Copy</button><button type="button" className={button} onClick={close}>Close</button></div><p role="status">{copyStatus}</p></div></div>;
}

/** Render the administrator's searchable account list and creation form. */
export default function Users() {
  const [data,setData] = useState<Page|null>(null); const [error,setError] = useState(''); const [search,setSearch] = useState(''); const [page,setPage] = useState(1); const [sort,setSort] = useState('display_name'); const [order,setOrder] = useState<'asc'|'desc'>('asc');
  const [name,setName] = useState(''); const [email,setEmail] = useState(''); const [role,setRole] = useState<Role>('analyst'); const [busy,setBusy] = useState(false); const [password,setPassword] = useState('');
  const [version,setVersion] = useState(0); const request = useRef(0);
  const load = useCallback(async () => { const id = ++request.current; setError(''); const query = new URLSearchParams({search,page:String(page),sort,order}); try { const result = await api<Page>(`/api/v1/users?${query}`); if (request.current === id) setData(result); } catch (e) { if (request.current === id) { setData(null); setError(message(e,'Unable to load users. Please try again.')); } } },[search,page,sort,order,version]);
  useEffect(() => {void load(); return () => { request.current++; };},[load]);
  async function create(event:FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { const result = await api<PasswordResult>('/api/v1/users',{method:'POST',body:JSON.stringify({display_name:name,email,role})}); setName(''); setEmail(''); setRole('analyst'); setPassword(result.temporary_password); setPage(1); setVersion(v => v+1); } catch (e) {setError(message(e,'Unable to create user. Please try again.'));} finally {setBusy(false);} }
  function changeSort(key:string) {if (key === sort) setOrder(order === 'asc' ? 'desc' : 'asc'); else {setSort(key); setOrder('asc');} setPage(1);}
  return <div className="space-y-4"><h1 className="font-display text-3xl text-ink">Users</h1><p className="text-muted">Manage workspace accounts and access.</p>{error && <p role="alert" className="text-danger">{error} {!data && <button className="text-accent" onClick={() => void load()}>Retry</button>}</p>}
    {data && <section className={card}><h2 className="mb-4 text-lg text-ink">Create user</h2><form onSubmit={create} className="grid gap-4 md:grid-cols-3"><label className="space-y-2">Display name<input className={input} required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></label><label className="space-y-2">Email<input className={input} type="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label><label className="space-y-2">Role<select className={input} value={role} onChange={e => setRole(e.target.value as Role)}>{roles.map(r => <option value={r} key={r}>{r.replaceAll('_',' ')}</option>)}</select></label><div><button disabled={busy} className={primary}>Create user</button></div></form></section>}
    <section className={card}><label className="block max-w-md space-y-2">Search by name or email<input className={input} value={search} maxLength={100} onChange={e => {setSearch(e.target.value); setPage(1);}} /></label><div className="mt-4 overflow-x-auto">{!data && !error ? <p>Loading users…</p> : data?.items.length === 0 ? <p>No users match your search.</p> : data && <table className="w-full min-w-max text-left"><thead><tr>{[['display_name','Display name'],['email','Email'],['role','Role'],['status','Status']].map(([key,label]) => <th scope="col" aria-sort={sort === key ? (order === 'asc' ? 'ascending' : 'descending') : 'none'} className="p-3 text-muted" key={key}><button onClick={() => changeSort(key)}>{label}{sort === key ? (order === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>)}</tr></thead><tbody>{data.items.map(item => <tr key={item.id} className={`border-t border-edge ${item.status === 'inactive' ? 'text-muted' : ''}`}><th scope="row" className="p-3 font-medium"><Link className="text-accent underline" href={`/users/${item.id}`}>{item.display_name}</Link></th><td className="p-3">{item.email}</td><td className="p-3">{item.role.replaceAll('_',' ')}</td><td className="p-3"><span className={`rounded-full px-2 py-1 text-xs ${item.status === 'inactive' ? 'bg-danger/15 text-danger' : 'bg-[#34d399]/15 text-[#34d399]'}`}>{item.status}</span></td></tr>)}</tbody></table>}</div>{data && <div className="mt-4 flex flex-wrap items-center gap-3"><button className={button} disabled={page <= 1} onClick={() => setPage(page-1)}>Previous</button><span>Page {page} · {data.total} results</span><button className={button} disabled={page*data.page_size >= data.total} onClick={() => setPage(page+1)}>Next</button></div>}</section>{password && <PasswordDialog password={password} close={() => setPassword('')} />}</div>;
}

/** Edit a single account and issue a fresh temporary credential. */
export function UserDetail({id}:{id:string}) {
  const [account,setAccount] = useState<Account|null>(null); const [error,setError] = useState(''); const [notice,setNotice] = useState(''); const [busy,setBusy] = useState(false); const [password,setPassword] = useState('');
  const load = useCallback(async () => {setError(''); try {setAccount(await api<Account>(`/api/v1/users/${encodeURIComponent(id)}`));} catch (e) {setError(message(e,'Unable to load user. Please try again.'));}},[id]);
  useEffect(() => {void load();},[load]);
  async function save(event:FormEvent) {event.preventDefault(); if (!account) return; setBusy(true); setError(''); setNotice(''); try {setAccount(await api<Account>(`/api/v1/users/${encodeURIComponent(id)}`,{method:'PUT',body:JSON.stringify({display_name:account.display_name,role:account.role,status:account.status})})); setNotice('User saved.');} catch (e) {setError(message(e,'Unable to save user.'));} finally {setBusy(false);}}
  async function reset() {setBusy(true); setError(''); setNotice(''); try {const result = await api<PasswordResult>(`/api/v1/users/${encodeURIComponent(id)}/reset-password`,{method:'POST'}); setPassword(result.temporary_password);} catch (e) {setError(message(e,'Unable to reset password.'));} finally {setBusy(false);}}
  return <div className="max-w-3xl space-y-4"><Link href="/users" className="text-accent">← Users</Link><h1 className="font-display text-3xl text-ink">User detail</h1>{error && <p role="alert" className="text-danger">{error} {!account && <button className="text-accent" onClick={() => void load()}>Retry</button>}</p>}{notice && <p role="status">{notice}</p>}{!account && !error && <p>Loading user…</p>}{account && <><section className={card}><h2 className="text-lg text-ink">{account.display_name}</h2><p>{account.email}</p><p>{account.status}</p></section><section className={card}><h2 className="mb-4 text-lg text-ink">Edit user</h2><form onSubmit={save} className="space-y-4"><label className="block space-y-2">Display name<input className={input} required maxLength={100} value={account.display_name} onChange={e => setAccount({...account,display_name:e.target.value})}/></label><label className="block space-y-2">Role<select className={input} value={account.role} onChange={e => setAccount({...account,role:e.target.value as Role})}>{roles.map(r => <option key={r} value={r}>{r.replaceAll('_',' ')}</option>)}</select></label><label className="block space-y-2">Status<select className={input} value={account.status} onChange={e => setAccount({...account,status:e.target.value as Account['status']})}><option value="active">active</option><option value="inactive">inactive</option></select></label><div className="flex flex-wrap gap-3"><button disabled={busy} className={primary}>Save</button><button type="button" disabled={busy} className={button} onClick={() => void reset()}>Reset password</button></div></form></section></>}{password && <PasswordDialog password={password} close={() => setPassword('')} />}</div>;
}
