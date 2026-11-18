'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, ApiError } from '../../lib/api';
import Shell from '../../components/Shell';

type Dashboard = { supplier_count: number; open_order_count: number; no_invoice_count: number; open_order_usd: string; pending_approval_count: number; spend: {category:string; amount_usd:string}[]; latest_month:string | null; demo_data_loaded:boolean };
/** Summarize current database metrics and the latest analytical spend. */
export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const router = useRouter();
  useEffect(() => { let live = true; setError(false); api<Dashboard>('/api/v1/dashboard').then(value => { if (live) setData(value); }).catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) router.replace('/'); else if (live) setError(true); }); return () => { live = false; }; }, [retry,router]);
  const money = (v: string) => Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const metrics = data ? [['Suppliers',String(data.supplier_count),'/suppliers'],['Open purchase orders',String(data.open_order_count),'/purchase-orders?status=open'],['Open orders without invoice',String(data.no_invoice_count),'/purchase-orders?status=open&no_invoice=true'],['Open order total (USD)',`$${money(data.open_order_usd)}`,'/purchase-orders?status=open'],['Pending approvals',String(data.pending_approval_count),'/approvals']] : [];
  const max = Math.max(1,...(data?.spend.map(x => Number(x.amount_usd)) || []));
  return <Shell title="Home"><h1 className="font-display text-[28px] text-ink">Home</h1><p className="mt-1 text-muted">Figures come from mock data loaded at startup.</p>{error ? <div role="alert" className="mt-6 rounded-2xl border border-edge bg-card p-5">Something went wrong loading this page. <button className="text-accent" onClick={() => setRetry(retry+1)}>Retry</button></div> : !data ? <div aria-live="polite" className="mt-6 rounded-2xl border border-edge bg-card p-5">Loading records…</div> : !data.demo_data_loaded ? <div role="alert" className="mt-6 rounded-2xl border border-edge bg-card p-5">Demo data did not load.</div> : <><div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">{metrics.map(([label,value,href]) => { const content = <><span className="text-muted">{label}</span><strong className="mt-2 block text-right text-[32px] font-medium tabular-nums text-ink">{value}</strong><span className="text-xs text-muted">Real-time{label === 'Open order total (USD)' ? ' · USD orders only' : ''}</span></>; return href ? <Link key={label} href={href} className="rounded-2xl border border-edge bg-card p-5 hover:bg-raised">{content}</Link> : <div key={label} className="rounded-2xl border border-edge bg-card p-5">{content}</div>; })}</div><section className="mt-4 rounded-2xl border border-edge bg-card p-5"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-display text-lg text-ink">Spend by category</h2><p className="text-xs text-muted">Latest month: {data.latest_month}</p></div><span className="rounded-full bg-raised px-3 py-1 text-xs text-muted">Analytical</span></div><Link href="/spend" className="mt-5 block space-y-3" aria-label="View spend by category">{data.spend.map(item => <div key={item.category} className="grid grid-cols-[9rem_1fr_auto] items-center gap-3 text-xs sm:grid-cols-[12rem_1fr_auto]"><span>{item.category}</span><span className="h-3 rounded-sm bg-accent" style={{width:`${Number(item.amount_usd)/max*100}%`}} /><span className="tabular-nums">${money(item.amount_usd)}</span></div>)}</Link></section></>}</Shell>;
}
