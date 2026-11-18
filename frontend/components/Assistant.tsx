'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';

type Citation = { id:number; code:string; href:string };
type Section = { resource:string; table:string; source:string; freshness:string; columns:string[]; rows:Record<string, string | number | null>[]; citations:Citation[] };
type Answer = { text:string; sections:Section[]; choices:string[]; followups:string[]; tokens:number; cost_usd:string; latency_ms:number; approval_id?:number };
type Message = { id:number; role:'user'|'assistant'; content?:string; answer?:Answer };
type Thread = { id:number; title:string; messages:Message[] };
type Summary = { id:number; title:string };

/** Present persisted conversations and locally reveal complete answers. */
export default function Assistant() {
  const [threads,setThreads] = useState<Summary[]>([]);
  const [current,setCurrent] = useState<number | null>(null);
  const [messages,setMessages] = useState<Message[]>([]);
  const [input,setInput] = useState('');
  const [proposal,setProposal] = useState('');
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState('');
  const [step,setStep] = useState('');
  const [revealed,setRevealed] = useState<number | null>(null);
  const generation = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  function cancelReveal() { generation.current++; timers.current.forEach(clearTimeout); timers.current = []; setStep(''); setRevealed(null); }
  async function loadList() { const data = await api<{items:Summary[]}>('/api/v1/assistant/conversations?page_size=100'); setThreads(data.items); }
  useEffect(() => { loadList().catch(() => setError('Unable to load conversations. Please retry.')); return () => { generation.current++; timers.current.forEach(clearTimeout); }; }, []);
  async function open(id:number) {
    cancelReveal(); setLoading(true); setError('');
    try { const thread = await api<Thread>(`/api/v1/assistant/conversations/${id}`); setCurrent(id); setMessages(thread.messages); }
    catch { setError('Unable to open this conversation. Please retry.'); }
    finally { setLoading(false); }
  }
  async function send(value:string) {
    const message = value.trim(); if (!message || loading) return;
    let action: unknown;
    try { action = proposal.trim() ? JSON.parse(proposal) : undefined; } catch { setError('Proposal details must be valid JSON.'); return; }
    cancelReveal(); setLoading(true); setError(''); setInput('');
    try {
      const result = await api<{conversation_id:number;message_id:number;answer:Answer}>('/api/v1/assistant/messages',{method:'POST',body:JSON.stringify({message,conversation_id:current,action})});
      setProposal('');
      setCurrent(result.conversation_id);
      setMessages(old => [...old,{id:-result.message_id,role:'user',content:message},{id:result.message_id,role:'assistant',answer:result.answer}]);
      setStep('Reading records…'); setRevealed(0);
      const version = generation.current;
      for (let i=1;i<=10;i++) timers.current.push(setTimeout(() => { if (generation.current === version) { setRevealed(Math.ceil(result.answer.text.length*i/10)); if (i===10) { setStep(''); setRevealed(null); setLoading(false); } } },400+i*100));
      loadList().catch(() => setError('Answer saved, but conversation list could not be refreshed.'));
    } catch { setInput(value); setError('Unable to send your message. Please retry.'); setLoading(false); }
  }
  const latest = [...messages].reverse().find(m => m.role === 'assistant');
  return <div className="grid gap-4 md:grid-cols-[300px_minmax(0,1fr)]">
    <aside className="rounded-2xl border border-edge bg-card p-4"><div className="flex items-center justify-between gap-2"><h2 className="font-display text-lg text-ink">Conversations</h2><button className="text-accent" disabled={loading} onClick={() => { cancelReveal(); setCurrent(null); setMessages([]); setError(''); }}>New</button></div><div className="mt-3 flex gap-2 overflow-x-auto md:flex-col">{threads.map(t => <button key={t.id} disabled={loading} onClick={() => open(t.id)} aria-current={current===t.id ? 'true' : undefined} className={`shrink-0 rounded-lg px-3 py-2 text-left hover:bg-raised ${current===t.id ? 'bg-raised text-ink' : 'text-muted'}`}>{t.title}</button>)}</div></aside>
    <section aria-label="Assistant conversation" className="flex min-h-[65vh] min-w-0 flex-col"><div className="flex-1 space-y-3" aria-live="polite">{messages.length===0 && <p className="text-muted">Ask about your procurement records. Answers use local mock data.</p>}{messages.map(m => m.role==='user' ? <div key={m.id} className="ml-auto w-fit max-w-[720px] whitespace-pre-wrap rounded-2xl border border-edge bg-raised p-4">{m.content}</div> : m.answer && <div key={m.id} className="max-w-[720px]">{m.id===latest?.id && step && <p className="mb-2 text-xs text-muted">{step}</p>}<div className="rounded-2xl border border-edge bg-card p-5"><p className="whitespace-pre-wrap">{m.id===latest?.id && revealed!==null ? m.answer.text.slice(0,revealed) : m.answer.text}</p>{(m.id!==latest?.id || revealed===null) && <>{m.answer.sections.map(section => <section key={section.resource} className="mt-5"><h3 className="font-display text-lg text-ink">{section.table.replaceAll('_',' ')}</h3><p className="my-2 text-xs text-muted">{section.source} · {section.freshness} · {section.table}</p>{section.rows.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>{section.columns.map(col => <th key={col} scope="col" className="border-b border-edge px-2 py-2 text-muted">{col.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{section.rows.map(row => <tr key={String(row.id)}>{section.columns.map(col => <td key={col} className="border-b border-edge px-2 py-2">{String(row[col] ?? '—')}</td>)}</tr>)}</tbody></table></div> : <p className="text-muted">No matching records.</p>}<div className="mt-3 flex flex-wrap gap-2">{section.citations.map(c => <Link className="rounded-full bg-raised px-3 py-1 text-xs text-accent" key={c.id} href={c.href}>{c.code}</Link>)}</div></section>)}{m.answer.approval_id && <Link className="mt-3 block text-accent" href={`/approvals/${m.answer.approval_id}`}>View pending approval</Link>}<div className="mt-4 text-xs text-muted">{m.answer.tokens} estimated tokens · ${m.answer.cost_usd} estimated cost · {m.answer.latency_ms} ms</div>{current && <a className="mt-2 inline-block text-sm text-accent" href={`${process.env.NEXT_PUBLIC_API_URL ?? ''}/api/v1/assistant/conversations/${current}/messages/${m.id}/csv`} download>Export answer</a>}<div className="mt-3 flex flex-wrap gap-3">{m.answer.choices.map(choice => <button className="text-accent" disabled={loading} key={choice} onClick={() => send(choice)}>{choice}</button>)}</div></>}</div>{m.id===latest?.id && revealed===null && <div className="mt-2 flex flex-wrap gap-3">{m.answer.followups.map(q => <button className="text-sm text-accent" disabled={loading} key={q} onClick={() => send(q)}>{q}</button>)}</div>}</div>)}</div>
    {error && <p role="alert" className="mt-4 text-danger">{error} <button className="text-accent" onClick={() => loadList().then(() => setError('')).catch(() => setError('Unable to load conversations. Please retry.'))}>Retry list</button></p>}
    <form className="sticky bottom-0 mt-5 border-t border-edge bg-page py-4" onSubmit={e => { e.preventDefault(); void send(input); }}><label htmlFor="assistant-message" className="mb-2 block text-sm text-ink">Ask the assistant</label><div className="flex items-end gap-3"><textarea id="assistant-message" rows={2} maxLength={4000} value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key==='Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(input); } }} className="min-w-0 flex-1 resize-y rounded-lg border border-edge bg-input p-3 text-ink" /><button disabled={loading || !input.trim()} className="min-h-11 rounded-lg bg-accent px-5 text-accent-ink disabled:opacity-50">Send</button></div><p className="mt-2 text-xs text-muted">Enter to send, Shift+Enter for a new line</p><details className="mt-3 text-sm text-muted"><summary className="cursor-pointer">Attach a structured approval request</summary><p className="mt-2">Enter a complete JSON proposal. Supported kinds: requisition, supplier_edit, sourcing_create, sourcing_award. For example: {'{"kind":"supplier_edit","supplier_id":1,"details":{"risk":"high"}}'}. Other requests require their corresponding form fields; no change is applied until approval.</p><label htmlFor="assistant-proposal" className="mt-2 block">Proposal JSON (optional)</label><textarea id="assistant-proposal" value={proposal} onChange={e => setProposal(e.target.value)} rows={3} className="mt-2 w-full rounded-lg border border-edge bg-input p-3 text-ink" /></details>{loading && !step && <p role="status" className="text-xs text-muted">Loading…</p>}</form></section>
  </div>;
}
