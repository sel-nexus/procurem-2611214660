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
