'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, ApiError } from '../lib/api';
import type { User } from '../lib/api';
import Shell from './Shell';

type Signature = { signer_id:number; display_name:string; role:string; meaning:string; reason:string; signed_at:string };
type Approval = { id:number; title:string; approval_type:string; status:string; requester_name:string; current:Record<string,unknown>; proposed:Record<string,unknown>; signatures:Signature[]; signatures_required:number; can_sign:boolean };
/** Display a proposal and collect a password-confirmed signature when authorized. */
export default function ApprovalDetail({id}: {id:string}) {
  const router = useRouter();
  const [data,setData] = useState<Approval | null>(null);
  const [user,setUser] = useState<User | null>(null);
  const [error,setError] = useState('');
  const [meaning,setMeaning] = useState<'Approved'|'Rejected'>('Approved');
  const [reason,setReason] = useState('');
  const [password,setPassword] = useState('');
  const [dialogError,setDialogError] = useState('');
  const [busy,setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { let live = true; Promise.all([api<Approval>(`/api/v1/approvals/${encodeURIComponent(id)}`),api<User>('/api/v1/auth/me')]).then(([value,identity]) => { if (live) { setData(value); setUser(identity); } }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError(e instanceof ApiError && e.status === 404 ? 'Approval not found.' : 'Something went wrong loading this page.'); }); return () => { live = false; }; },[id,router]);
  function open(value:'Approved'|'Rejected') { setMeaning(value); setReason(''); setPassword(''); setDialogError(''); dialog.current?.showModal(); }
  async function sign() { setBusy(true); setDialogError(''); try { const result = await api<Approval>(`/api/v1/approvals/${encodeURIComponent(id)}/sign`,{method:'POST',body:JSON.stringify({meaning,reason,password})}); setData(result); setPassword(''); dialog.current?.close(); } catch (e) { setDialogError(e instanceof ApiError ? e.message : 'Unable to save the signature.'); } finally { setBusy(false); } }
  const fields = data ? Array.from(new Set([...Object.keys(data.current),...Object.keys(data.proposed)])) : [];
  function value(item: unknown) { return item == null ? '—' : typeof item === 'object' ? JSON.stringify(item) : String(item); }
  return <Shell title="Approval"><Link href="/approvals" className="text-accent">← Approvals</Link>{error ? <p role="alert" className="mt-4 text-danger">{error}</p> : !data ? <p aria-live="polite" className="mt-4">Loading records…</p> : <><h1 className="mt-4 font-display text-[28px] text-ink">{data.title}</h1><p className="mt-2 text-muted">{data.approval_type.replaceAll('_',' ')} · {data.status.replaceAll('_',' ')} · Requested by {data.requester_name}</p><div className="mt-5 grid gap-4 md:grid-cols-2">{(['current','proposed'] as const).map(side => <section key={side} className="rounded-2xl border border-edge bg-card p-5"><h2 className="font-display text-lg text-ink">{side === 'current' ? 'Current' : 'Proposed'}</h2>{side === 'current' && !Object.keys(data.current).length ? <p className="mt-3 text-muted">No current record</p> : <dl className="mt-3 space-y-3">{fields.map(field => <div key={field}><dt className="text-xs text-muted">{field.replaceAll('_',' ')}</dt><dd className={`break-words ${side === 'proposed' && JSON.stringify(data.current[field]) !== JSON.stringify(data.proposed[field]) ? 'text-warning' : 'text-ink'}`}>{value(data[side][field])}</dd></div>)}</dl>}</section>)}</div><h2 className="mt-6 font-display text-lg text-ink">Signatures</h2><div className="mt-3 grid gap-4 md:grid-cols-2">{Array.from({length:data.signatures_required},(_,index) => { const signature = data.signatures[index]; return <section key={index} className={`rounded-2xl border ${signature ? 'border-edge' : 'border-dashed border-muted'} bg-card p-5`}>{signature ? <><p className="text-ink">{signature.display_name} · {signature.role.replaceAll('_',' ')}</p><p>{signature.meaning}</p><p>{signature.reason}</p><time className="text-muted">{signature.signed_at} UTC</time></> : <p>Waiting for signature</p>}</section>; })}</div>{data.can_sign && <div className="mt-5 flex gap-3"><button className="rounded bg-accent px-4 py-2 text-[#042f2e]" onClick={() => open('Approved')}>Approve</button><button className="rounded border border-danger px-4 py-2 text-danger" onClick={() => open('Rejected')}>Reject</button></div>}</>}
    <dialog ref={dialog} aria-labelledby="signature-title" className="w-[calc(100%-2rem)] max-w-[420px] rounded-2xl border border-edge bg-card p-5 text-body backdrop:bg-black/70" onClick={e => { if (e.target === dialog.current) dialog.current?.close(); }}><h2 id="signature-title" className="font-display text-lg text-ink">{meaning} signature</h2><p className="mt-2 text-muted">{user?.display_name} · Confirm your decision with your password.</p><label className="mt-4 grid gap-1">Reason<textarea className="min-h-24 rounded border border-edge bg-input p-3" value={reason} onChange={e => setReason(e.target.value)} required minLength={8} /></label><label className="mt-4 grid gap-1">Password<input className="h-11 rounded border border-edge bg-input px-3" type="password" value={password} onChange={e => setPassword(e.target.value)} aria-invalid={!!dialogError} aria-describedby={dialogError ? 'signature-error' : undefined} /></label>{dialogError && <p id="signature-error" role="alert" className="mt-2 text-danger">{dialogError}</p>}<div className="mt-4 flex gap-3"><button disabled={busy || reason.trim().length < 8 || !password} className="rounded bg-accent px-4 py-2 text-[#042f2e] disabled:opacity-50" onClick={sign}>Sign</button><button className="rounded border border-edge bg-raised px-4 py-2" onClick={() => { setPassword(''); dialog.current?.close(); }}>Cancel</button></div></dialog>
  </Shell>;
}
