// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import Assistant from './Assistant';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const answer = { text:'Found 1 matching record(s).',sections:[{resource:'purchase-orders',table:'purchase_orders',source:'Mock · Oracle',freshness:'Real-time',columns:['code','status'],rows:[{id:1,code:'PO-1001',status:'overdue'}],citations:[{id:1,code:'PO-1001',href:'/purchase-orders/1'}]}],choices:[],followups:['Show overdue purchase orders','Show spend'],tokens:10,cost_usd:'0.0000',latency_ms:5 };

it('sends with Enter, reveals results and reopens the saved thread', async () => {
  const fetcher = vi.fn((url:string, init?:RequestInit) => {
    if (init?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({conversation_id:1,message_id:2,answer}),{status:200}));
    if (url.endsWith('/conversations/1')) return Promise.resolve(new Response(JSON.stringify({id:1,title:'Orders',messages:[{id:2,role:'assistant',answer}]}),{status:200}));
    return Promise.resolve(new Response(JSON.stringify({items:[{id:1,title:'Orders'}]}),{status:200}));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<Assistant />);
  const box = screen.getByLabelText('Ask the assistant');
  await user.type(box,'overdue orders{Enter}');
  expect(await screen.findByText('Reading records…')).toBeInTheDocument();
  expect(await screen.findByRole('link',{name:'PO-1001'},{timeout:3000})).toHaveAttribute('href','/purchase-orders/1');
  expect(screen.getByText(/estimated tokens/)).toBeInTheDocument();
  expect(screen.getByRole('link',{name:'Export answer'})).toHaveAttribute('href','/api/v1/assistant/conversations/1/messages/2/csv');
  await user.click(screen.getByRole('button',{name:'New'}));
  await user.click(screen.getByRole('button',{name:'Orders'}));
  expect(await screen.findByRole('link',{name:'PO-1001'})).toBeInTheDocument();
});

it('inserts newline with Shift+Enter and reports request errors without losing text', async () => {
  const fetcher = vi.fn((_url:string, init?:RequestInit) => init?.method === 'POST' ? Promise.reject(new Error('network')) : Promise.resolve(new Response(JSON.stringify({items:[]}),{status:200})));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<Assistant />);
  const box = screen.getByLabelText('Ask the assistant');
  await user.type(box,'hello{Shift>}{Enter}{/Shift}world');
  expect(box).toHaveValue('hello\nworld');
  await user.click(screen.getByRole('button',{name:'Send'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to send');
  expect(box).toHaveValue('hello\nworld');
});

it('rejects invalid proposal JSON locally, then sends a valid action and shows the approval', async () => {
  const fetcher = vi.fn((_url:string, init?:RequestInit) => init?.method === 'POST'
    ? Promise.resolve(new Response(JSON.stringify({conversation_id:7,message_id:8,answer:{...answer,text:'A pending approval was created.',sections:[],followups:[],approval_id:42}})))
    : Promise.resolve(new Response(JSON.stringify({items:[]}))));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<Assistant />);
  await user.click(screen.getByText('Attach a structured approval request'));
  const proposal = screen.getByLabelText('Proposal JSON (optional)');
  const box = screen.getByLabelText('Ask the assistant');
  await user.type(box,'Edit supplier');
  await user.click(proposal);
  await user.paste('{broken');
  await user.click(screen.getByRole('button',{name:'Send'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Proposal details must be valid JSON.');
  expect(box).toHaveValue('Edit supplier');
  expect(proposal).toHaveValue('{broken');
  expect(fetcher.mock.calls.filter(([,init]) => init?.method === 'POST')).toHaveLength(0);
  const action = {kind:'supplier_edit',supplier_id:1,details:{risk:'high'}};
  await user.clear(proposal);
  await user.paste(JSON.stringify(action));
  await user.click(screen.getByRole('button',{name:'Send'}));
  const post = fetcher.mock.calls.find(([,init]) => init?.method === 'POST');
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({message:'Edit supplier',conversation_id:null,action});
  expect(await screen.findByRole('link',{name:'View pending approval'},{timeout:3000})).toHaveAttribute('href','/approvals/42');
  expect(screen.getByText('A pending approval was created.')).toBeInTheDocument();
  expect(proposal).toHaveValue('');
});

it('sends clarification choices and followups in the same conversation', async () => {
  let count = 0;
  const fetcher = vi.fn((_url:string, init?:RequestInit) => {
    if (init?.method !== 'POST') return Promise.resolve(new Response(JSON.stringify({items:[]})));
    count++;
    const next = count === 1 ? {...answer,text:'Which area do you mean?',sections:[],choices:['Invoices'],followups:[]} :
      count === 2 ? {...answer,text:'Found invoices.',sections:[],choices:[],followups:['Show spend']} :
      {...answer,text:'Found spend.',sections:[],choices:[],followups:[]};
    return Promise.resolve(new Response(JSON.stringify({conversation_id:7,message_id:count,answer:next})));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<Assistant />);
  await user.type(screen.getByLabelText('Ask the assistant'),'status{Enter}');
  await user.click(await screen.findByRole('button',{name:'Invoices'},{timeout:3000}));
  await user.click(await screen.findByRole('button',{name:'Show spend'},{timeout:3000}));
  expect(await screen.findByText('Found spend.',{}, {timeout:3000})).toBeInTheDocument();
  expect(screen.getByText('Invoices',{selector:'div'})).toBeInTheDocument();
  expect(screen.getByText('Show spend',{selector:'div'})).toBeInTheDocument();
  const bodies = fetcher.mock.calls.filter(([,init]) => init?.method === 'POST').map(([,init]) => JSON.parse(String(init?.body)));
  expect(bodies).toEqual([{message:'status',conversation_id:null},{message:'Invoices',conversation_id:7},{message:'Show spend',conversation_id:7}]);
});

it('reports list and thread failures and allows retrying the conversation list', async () => {
  let lists = 0;
  vi.stubGlobal('fetch',vi.fn((url:string) => {
    if (url.endsWith('/conversations/3')) return Promise.reject(new Error('offline'));
    lists++;
    return lists === 1 ? Promise.reject(new Error('offline')) : Promise.resolve(new Response(JSON.stringify({items:[{id:3,title:'Saved thread'}]})));
  }));
  const user = userEvent.setup(); render(<Assistant />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load conversations.');
  await user.click(screen.getByRole('button',{name:'Retry list'}));
  await user.click(await screen.findByRole('button',{name:'Saved thread'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to open this conversation.');
  expect(screen.getByText('Ask about your procurement records. Answers use local mock data.')).toBeInTheDocument();
});

it('retains a proposal and message after a rejected action request', async () => {
  vi.stubGlobal('fetch',vi.fn((_url:string, init?:RequestInit) => Promise.resolve(init?.method === 'POST'
    ? new Response(JSON.stringify({detail:'Invalid proposal'}),{status:422})
    : new Response(JSON.stringify({items:[]})))));
  const user = userEvent.setup(); render(<Assistant />);
  await user.click(screen.getByText('Attach a structured approval request'));
  await user.click(screen.getByLabelText('Proposal JSON (optional)'));
  await user.paste('{"kind":"supplier_edit","supplier_id":1,"details":{"risk":"high"}}');
  await user.type(screen.getByLabelText('Ask the assistant'),'Edit supplier{Enter}');
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to send your message.');
  expect(screen.getByLabelText('Ask the assistant')).toHaveValue('Edit supplier');
  expect(screen.getByLabelText('Proposal JSON (optional)')).toHaveValue('{"kind":"supplier_edit","supplier_id":1,"details":{"risk":"high"}}');
  expect(screen.queryByRole('link',{name:'View pending approval'})).not.toBeInTheDocument();
});
