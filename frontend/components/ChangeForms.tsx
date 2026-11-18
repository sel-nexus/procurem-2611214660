'use client';
import { useState } from 'react';
import type { FormEvent } from 'react';
import Link from 'next/link';
import { api, ApiError } from '../lib/api';
import type { Row } from './RecordList';

const field = 'h-11 w-full rounded-[10px] border border-edge bg-input px-3 text-ink';
const button = 'rounded-[10px] bg-accent px-4 py-2 text-[#042f2e] disabled:opacity-50';
type Props = { kind: 'supplier' | 'create' | 'award'; role: string; item?: Row; bids?: Row[]; onCreated?: () => void };

/** Submit a role-gated supplier, sourcing event, or bid proposal. */
export default function ChangeForms({ kind, role, item, bids = [], onCreated }: Props) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [approval, setApproval] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  if (!['category_manager','sourcing_specialist'].includes(role)) return null;
  if (kind === 'award' && (item?.status !== 'active' || bids.length === 0)) return null;
  const label = kind === 'supplier' ? 'Propose edit' : kind === 'create' ? 'Create sourcing event' : 'Request award';
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('');
    const values = new FormData(event.currentTarget);
    let path = ''; let body: Record<string, string | number> = {};
    if (kind === 'supplier') {
      path = `/api/v1/suppliers/${item?.id}/proposals`;
      for (const key of ['contact_name','contact_email','risk','status']) {
        const value = String(values.get(key) || '').trim();
        if (value !== String(item?.[key] ?? '')) body[key] = value;
      }
      if (!Object.keys(body).length) { setError('Change at least one field before submitting.'); return; }
    } else if (kind === 'create') {
      path = '/api/v1/sourcing';
      body = {title:String(values.get('title') || '').trim(), event_type:String(values.get('event_type')), estimated_value_usd:String(values.get('estimated_value_usd')), end_date:String(values.get('end_date'))};
      if (!body.title) { setError('Title is required.'); return; }
      if (!Number.isFinite(Number(body.estimated_value_usd)) || Number(body.estimated_value_usd) <= 0) { setError('Amount must be greater than 0.'); return; }
    } else {
      path = `/api/v1/sourcing/${item?.id}/awards`;
      body = {bid_id:Number(values.get('bid_id'))};
      if (!body.bid_id) { setError('Choose a bid.'); return; }
    }
    setBusy(true);
    try {
      const result = await api<{approval_id:number}>(path,{method:'POST',body:JSON.stringify(body)});
      setApproval(result.approval_id); setOpen(false); onCreated?.();
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Unable to submit the proposal. Please try again.'); }
    finally { setBusy(false); }
  }
  return <section className="mt-4">
    {approval ? <p role="status">Proposal submitted. <Link className="text-accent" href={`/approvals/${approval}`}>View pending approval</Link></p> : <button type="button" className={button} onClick={() => { setOpen(!open); setError(''); }} aria-expanded={open}>{open ? 'Cancel' : label}</button>}
    {open && <form onSubmit={submit} className="mt-4 grid max-w-xl gap-4 rounded-2xl border border-edge bg-card p-5">
      <h2 className="font-display text-lg text-ink">{label}</h2>
      {kind === 'supplier' && <>
        <label className="grid gap-1">Contact name<input className={field} name="contact_name" defaultValue={String(item?.contact_name || '')} required maxLength={300} /></label>
        <label className="grid gap-1">Contact email<input className={field} name="contact_email" type="email" defaultValue={String(item?.contact_email || '')} required maxLength={300} /></label>
        <label className="grid gap-1">Risk<select className={field} name="risk" defaultValue={String(item?.risk || 'low')}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
        <label className="grid gap-1">Status<select className={field} name="status" defaultValue={String(item?.status || 'active')}><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
      </>}
      {kind === 'create' && <>
        <label className="grid gap-1">Title<input className={field} name="title" required maxLength={300} /></label>
        <label className="grid gap-1">Event type<select className={field} name="event_type"><option>RFQ</option><option>RFP</option><option>Auction</option></select></label>
        <label className="grid gap-1">Estimated value (USD)<input className={field} name="estimated_value_usd" type="number" min="0.01" step="0.01" required /></label>
        <label className="grid gap-1">End date<input className={field} name="end_date" type="date" required /></label>
      </>}
      {kind === 'award' && <label className="grid gap-1">Bid<select className={field} name="bid_id" required defaultValue=""><option value="">Choose a bid</option>{bids.map(bid => <option key={String(bid.id)} value={String(bid.id)}>{bid.supplier_name} · ${bid.amount_usd}</option>)}</select></label>}
      {error && <p role="alert" className="text-sm text-rose-400">{error}</p>}
      <button disabled={busy} className={button} type="submit">{busy ? 'Submitting…' : 'Submit for approval'}</button>
    </form>}
  </section>;
}
