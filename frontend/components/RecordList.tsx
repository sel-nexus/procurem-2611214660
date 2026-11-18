'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, ApiError } from '../lib/api';
import { useRouter } from 'next/navigation';
import Shell from './Shell';

export type Row = Record<string, string | number | null>;
type Resource = { title: string; source: string; columns: [string,string][]; filters: string[]; search?: boolean };
export const resources: Record<string, Resource> = {
  suppliers:{title:'Suppliers',source:'JAGGAER',columns:[['code','Code'],['name','Supplier'],['category','Category'],['country','Country'],['risk','Risk'],['status','Status'],['spend_ytd_usd','Spend YTD (USD)']],filters:['category','risk','status'],search:true},
  catalog:{title:'Catalog',source:'Catalog',columns:[['code','Code'],['name','Item'],['category','Category'],['supplier_name','Supplier'],['unit_price','Unit price'],['currency','Currency'],['status','Status']],filters:['category','supplier'],search:true},
  'purchase-orders':{title:'Purchase orders',source:'Oracle',columns:[['code','PO number'],['supplier_name','Supplier'],['category','Category'],['amount','Amount'],['currency','Currency'],['status','Status'],['requester_name','Requester'],['due_date','Due date'],['has_invoice','Invoice']],filters:['status','supplier','no_invoice'],search:true},
  invoices:{title:'Invoices',source:'Oracle',columns:[['code','Invoice'],['supplier_name','Supplier'],['po_code','PO'],['amount','Amount'],['currency','Currency'],['status','Status'],['invoice_date','Invoice date']],filters:['status','supplier']},
  contracts:{title:'Contracts',source:'Oracle',columns:[['code','Contract'],['supplier_name','Supplier'],['contract_type','Type'],['value_usd','Value (USD)'],['start_date','Start date'],['end_date','End date'],['status','Status']],filters:['status','supplier']},
  requisitions:{title:'Requisitions',source:'Oracle',columns:[['code','Requisition'],['supplier_name','Supplier'],['total_amount_usd','Total (USD)'],['status','Status'],['requester_name','Requester'],['created_at','Created']],filters:[]},
  sourcing:{title:'Sourcing',source:'JAGGAER',columns:[['code','Event'],['title','Title'],['event_type','Type'],['status','Status'],['end_date','End date'],['bid_count','Bids'],['estimated_value_usd','Estimated value (USD)']],filters:[]},
  spend:{title:'Spend',source:'Spend',columns:[['category','Category'],['year','Year'],['month','Month'],['amount_usd','Amount (USD)']],filters:['category','from_month','to_month']},
  knowledge:{title:'Knowledge',source:'Knowledge',columns:[['code','Code'],['title','Title'],['version','Version'],['updated_at','Last updated']],filters:[],search:true},
};
const money = new Set(['spend_ytd_usd','unit_price','amount','value_usd','total_amount_usd','estimated_value_usd','amount_usd','line_amount']);
/** Format a stored value without treating a missing value as zero. */
export function display(key: string, value: string | number | null | undefined): string {
  if (value == null) return key === 'po_code' ? 'No PO' : '—';
  if (key === 'has_invoice') return value ? 'Yes' : 'No';
  if (money.has(key) && Number.isFinite(Number(value))) return Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  return String(value).replaceAll('_',' ');
}
export type ListResponse = { items: Row[]; total: number; page: number; page_size: number; source_label: string; freshness: string; chart?: {month:string; amount_usd:string}[] };
const control = 'h-11 rounded-[10px] border border-edge bg-input px-3 text-ink';
/** Render a shareable, sortable and paginated record directory. */
export default function RecordList({ resource }: { resource: string }) {
  const spec = resources[resource];
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [suppliers, setSuppliers] = useState<Row[]>([]);
  useEffect(() => { const sync = () => setQuery(window.location.search.slice(1)); sync(); window.addEventListener('popstate',sync); return () => window.removeEventListener('popstate',sync); }, [resource]);
  useEffect(() => { if (!spec) return; let live = true; setLoading(true); setError(false); api<ListResponse>(`/api/v1/records/${resource}?${query}`).then(value => { if (live) setData(value); }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError(true); }).finally(() => { if (live) setLoading(false); }); return () => { live = false; }; }, [resource,query,retry,router,spec]);
  useEffect(() => { if (!spec?.filters.includes('supplier')) return; let live = true; api<ListResponse>('/api/v1/records/suppliers?page_size=100&sort=name').then(value => { if (live) setSuppliers(value.items); }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError(true); }); return () => { live = false; }; }, [router,spec]);
  function update(key: string, value: string) { const next = new URLSearchParams(query); if (value) next.set(key,value); else next.delete(key); if (key !== 'page') next.delete('page'); const text = next.toString(); window.history.pushState(null,'',`${window.location.pathname}${text ? `?${text}` : ''}`); setQuery(text); }
  function reset() { window.history.pushState(null,'',window.location.pathname); setQuery(''); }
  if (!spec) return <Shell title="Not found"><h1 className="text-ink">Page not found.</h1></Shell>;
  const params = new URLSearchParams(query);
  return <Shell title={spec.title}><div className="mb-6"><h1 className="font-display text-[28px] text-ink">{spec.title}</h1><p className="mt-1 text-muted">Browse records from the local procurement workspace.</p><div className="mt-3 flex gap-2 text-xs"><span className="rounded-full bg-accent/10 px-3 py-1 text-accent">Mock · {spec.source}</span><span className="rounded-full bg-raised px-3 py-1 text-muted">{resource === 'spend' ? 'Analytical' : 'Real-time'}</span></div></div>
    <div className="mb-5 flex flex-wrap items-end gap-3">{spec.search && <label className="grid gap-1 text-xs text-muted">Search<input className={control} value={params.get('search') || ''} onChange={e => update('search',e.target.value)} /></label>}{spec.filters.map(filter => <label key={filter} className="grid gap-1 text-xs text-muted">{filter.replaceAll('_',' ')}{filter === 'no_invoice' ? <select className={control} value={params.get(filter) || ''} onChange={e => update(filter,e.target.value)}><option value="">All invoices</option><option value="true">No invoice</option></select> : filter === 'supplier' ? <select className={control} value={params.get(filter) || ''} onChange={e => update(filter,e.target.value)}><option value="">All suppliers</option>{suppliers.map(s => <option key={String(s.id)} value={String(s.id)}>{s.name}</option>)}</select> : <input className={control} type={filter.includes('month') ? 'number' : 'text'} min={filter.includes('month') ? 1 : undefined} max={filter.includes('month') ? 12 : undefined} placeholder="All" value={params.get(filter) || ''} onChange={e => update(filter,e.target.value)} />}</label>)}<button className="h-11 rounded-[10px] border border-edge bg-raised px-4" onClick={reset}>Reset filters</button></div>
    {resource === 'spend' && data?.chart && !loading && !error && data.chart.length > 0 && <section className="mb-4 rounded-2xl border border-edge bg-card p-5"><h2 className="font-display text-lg text-ink">Spend by month</h2><div className="mt-4 space-y-3">{data.chart.map(point => <div key={point.month} className="grid grid-cols-[5rem_1fr_auto] items-center gap-3 text-xs"><span>{point.month}</span><span className="h-3 rounded-sm bg-accent" style={{width:`${Number(point.amount_usd)/Math.max(...data.chart!.map(p => Number(p.amount_usd)),1)*100}%`}} /><span className="tabular-nums">${display('amount_usd',point.amount_usd)}</span></div>)}</div></section>}
    {loading ? <div className="rounded-2xl border border-edge bg-card p-5" aria-live="polite">Loading records…</div> : error ? <div className="rounded-2xl border border-edge bg-card p-5" role="alert">Something went wrong loading this page. <button className="text-accent" onClick={() => setRetry(retry+1)}>Retry</button></div> : !data?.items.length ? <div className="rounded-2xl border border-edge bg-card p-5">No records match these filters. <button className="text-accent" onClick={reset}>Reset filters</button></div> : <><div className="overflow-x-auto rounded-2xl border border-edge bg-card"><table className="w-full text-left text-[13px]"><thead><tr>{spec.columns.map(([key,label]) => <th scope="col" key={key} aria-sort={params.get('sort') === key ? params.get('order') === 'desc' ? 'descending' : 'ascending' : 'none'} className="whitespace-nowrap border-b border-edge p-4 text-xs font-medium text-muted"><button onClick={() => { const next = new URLSearchParams(query); next.set('sort',key); next.set('order',params.get('sort') === key && params.get('order') !== 'desc' ? 'desc' : 'asc'); next.delete('page'); const text = next.toString(); window.history.pushState(null,'',`?${text}`); setQuery(text); }}>{label}{params.get('sort') === key ? params.get('order') === 'desc' ? ' ↓' : ' ↑' : ''}</button></th>)}</tr></thead><tbody>{data.items.map(row => <tr key={String(row.id)} className="border-b border-edge last:border-0 hover:bg-raised">{spec.columns.map(([key],index) => <td key={key} className={`whitespace-nowrap p-4 ${money.has(key) ? 'text-right tabular-nums' : ''}`}>{index === 0 ? <Link className="text-accent hover:underline" href={`/${resource}/${row.id}`}>{display(key,row[key])}</Link> : display(key,row[key])}</td>)}</tr>)}</tbody></table></div><div className="mt-4 flex items-center gap-4 text-muted"><button disabled={data.page <= 1} onClick={() => update('page',String(data.page-1))} className="disabled:opacity-40">Previous</button><span>Page {data.page} · {data.total} records</span><button disabled={data.page * data.page_size >= data.total} onClick={() => update('page',String(data.page+1))} className="disabled:opacity-40">Next</button></div></>}
  </Shell>;
}
