'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, ApiError } from '../lib/api';
import type { User } from '../lib/api';
import Shell from './Shell';
import type { ListResponse } from './RecordList';

const input = 'h-11 w-full rounded-[10px] border border-edge bg-input px-3 text-ink';
type Line = { description: string; quantity: string; unit_price: string };
/** Create and optionally submit a requisition using the signed-in analyst. */
export default function RequisitionForm() {
  const router = useRouter();
  const [user,setUser] = useState<User | null>(null);
  const [suppliers,setSuppliers] = useState<ListResponse['items']>([]);
  const [supplier,setSupplier] = useState('');
  const [title,setTitle] = useState('');
  const [reason,setReason] = useState('');
  const [lines,setLines] = useState<Line[]>([{description:'',quantity:'1',unit_price:''}]);
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [draftId,setDraftId] = useState<number | null>(null);
  useEffect(() => { let live = true; Promise.all([api<User>('/api/v1/auth/me'),api<ListResponse>('/api/v1/records/suppliers?page_size=100&sort=name')]).then(([identity, result]) => { if (live) { setUser(identity); setSuppliers(result.items); } }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError('Unable to load the requisition form.'); }); return () => { live = false; }; },[router]);
  function update(index: number, key: keyof Line, value: string) { setLines(current => current.map((line,i) => i === index ? {...line,[key]:value} : line)); }
  async function save(submit: boolean) {
    setError('');
    if (!draftId && !supplier) { setError('Supplier is required.'); return; }
    if (!draftId && (!title.trim() || !reason.trim() || lines.some(line => !line.description.trim() || !/^[1-9]\d*$/.test(line.quantity) || !/^\d+(\.\d{1,2})?$/.test(line.unit_price) || Number(line.unit_price) <= 0))) { setError('Enter a title, reason, and valid lines. Amount must be greater than 0.'); return; }
    setBusy(true);
    try {
      const id = draftId ?? (await api<{id:number}>('/api/v1/requisitions',{method:'POST',body:JSON.stringify({supplier_id:Number(supplier),title,reason,lines:lines.map(line => ({...line,quantity:Number(line.quantity)}))})})).id;
      setDraftId(id);
      if (submit) await api(`/api/v1/requisitions/${id}/submit`,{method:'POST'});
      router.push(`/requisitions/${id}`);
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Unable to save the requisition.'); } finally { setBusy(false); }
  }
  return <Shell title="New requisition"><Link href="/requisitions" className="text-accent">← Requisitions</Link><h1 className="mt-4 font-display text-[28px] text-ink">New requisition</h1>{error && <p role="alert" className="mt-4 text-danger">{error}</p>}{!user ? <p aria-live="polite">Loading form…</p> : user.role !== 'analyst' ? <p className="mt-4">Only analysts can create requisitions.</p> : <div className="mt-4 max-w-3xl space-y-4 rounded-2xl border border-edge bg-card p-5">
    {draftId && <p>Draft saved. Retry submission or open it from the requisition list.</p>}
    <label className="grid gap-1">Supplier<select className={input} value={supplier} disabled={!!draftId} onChange={e => setSupplier(e.target.value)} required><option value="">Choose a supplier</option>{suppliers.map(s => <option key={String(s.id)} value={String(s.id)}>{s.name}</option>)}</select></label>
    <label className="grid gap-1">Title<input className={input} value={title} disabled={!!draftId} onChange={e => setTitle(e.target.value)} required /></label>
    <label className="grid gap-1">Reason<textarea className="min-h-24 rounded-[10px] border border-edge bg-input p-3" value={reason} disabled={!!draftId} onChange={e => setReason(e.target.value)} required /></label>
    <h2 className="font-display text-lg text-ink">Lines</h2>{lines.map((line,index) => <fieldset key={index} className="grid gap-3 rounded border border-edge p-3 sm:grid-cols-3"><legend>Line {index+1}</legend><label className="grid gap-1">Description<input className={input} value={line.description} disabled={!!draftId} onChange={e => update(index,'description',e.target.value)} required /></label><label className="grid gap-1">Quantity<input className={input} type="number" min="1" step="1" value={line.quantity} disabled={!!draftId} onChange={e => update(index,'quantity',e.target.value)} required /></label><label className="grid gap-1">Unit price (USD)<input className={input} inputMode="decimal" value={line.unit_price} disabled={!!draftId} onChange={e => update(index,'unit_price',e.target.value)} required /></label>{lines.length > 1 && !draftId && <button onClick={() => setLines(lines.filter((_,i) => i !== index))}>Remove line {index+1}</button>}</fieldset>)}
    {!draftId && <button className="rounded border border-edge bg-raised px-4 py-2" onClick={() => setLines([...lines,{description:'',quantity:'1',unit_price:''}])}>Add line</button>}
    <div className="flex flex-wrap gap-3"><button disabled={busy || !!draftId} className="rounded border border-edge bg-raised px-4 py-2 disabled:opacity-50" onClick={() => save(false)}>Save as draft</button><button disabled={busy} className="rounded bg-accent px-4 py-2 text-[#042f2e] disabled:opacity-50" onClick={() => save(true)}>Submit for approval</button></div>
  </div>}</Shell>;
}
