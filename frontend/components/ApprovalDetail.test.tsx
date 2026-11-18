// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import ApprovalDetail from './ApprovalDetail';
import RequisitionForm from './RequisitionForm';

const router = {replace:vi.fn(),push:vi.fn()};
vi.mock('next/navigation', () => ({useRouter: () => router, usePathname: () => '/approvals/1'}));
const manager = {id:3,email:'proc.manager@procurem.demo',display_name:'David Okonkwo',role:'procurement_manager'};
const approval = {id:1,title:'Laboratory supplies',approval_type:'requisition',status:'pending',requester_name:'Priya Shah',current:{},proposed:{title:'Laboratory supplies'},signatures:[],signatures_required:1,can_sign:true};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows the diff, checks reason, displays password failure and saves a signature', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open',''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  let reject = true;
  vi.stubGlobal('fetch',vi.fn((url: string, init?: RequestInit) => {
    if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify(manager)));
    if (init?.method === 'POST') return Promise.resolve(reject ? new Response(JSON.stringify({detail:'Password does not match. The signature was not saved.'}),{status:422}) : new Response(JSON.stringify({...approval,status:'approved',can_sign:false,signatures:[{signer_id:3,display_name:'David Okonkwo',role:'procurement_manager',meaning:'Approved',reason:'Reviewed carefully',signed_at:'2026-07-07T00:00:00+00:00'}]})));
    return Promise.resolve(new Response(JSON.stringify(approval)));
  }));
  const user = userEvent.setup(); render(<ApprovalDetail id="1" />);
  expect(await screen.findByText('No current record')).toBeInTheDocument();
  expect(screen.getByText('Waiting for signature')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'Approve'}));
  expect(screen.getByRole('button',{name:'Sign'})).toBeDisabled();
  await user.type(screen.getByLabelText('Reason'),'Reviewed carefully');
  await user.type(screen.getByLabelText('Password'),'wrong');
  await user.click(screen.getByRole('button',{name:'Sign'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Password does not match');
  reject = false;
  await user.click(screen.getByRole('button',{name:'Sign'}));
  expect(await screen.findByText('Reviewed carefully', {selector:'p'})).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Approve'})).not.toBeInTheDocument();
});

it('hides signing controls for a requester', async () => {
  vi.stubGlobal('fetch',vi.fn((url:string) => Promise.resolve(new Response(JSON.stringify(url.includes('/auth/me') ? {...manager,id:1,role:'analyst'} : {...approval,can_sign:false})))));
  render(<ApprovalDetail id="1" />);
  expect(await screen.findByText('Waiting for signature')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Approve'})).not.toBeInTheDocument();
});

it('allows analysts to create and submit a requisition', async () => {
  const fetcher = vi.fn((url:string, init?:RequestInit) => {
    if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify({...manager,id:1,role:'analyst'})));
    if (url.includes('/records/suppliers')) return Promise.resolve(new Response(JSON.stringify({items:[{id:1,name:'Thermo Fisher'}]})));
    if (url.endsWith('/submit')) return Promise.resolve(new Response(JSON.stringify({approval_id:4})));
    if (init?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({id:9}),{status:201}));
    return Promise.resolve(new Response('{}'));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<RequisitionForm />);
  await user.selectOptions(await screen.findByLabelText('Supplier'),'1');
  await user.type(screen.getByLabelText('Title'),'Lab supplies');
  await user.type(screen.getByLabelText('Reason'),'Needed for work');
  await user.type(screen.getByLabelText('Description'),'Gloves');
  await user.type(screen.getByLabelText('Unit price (USD)'),'10.25');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith('/requisitions/9'));
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/requisitions/9/submit'))).toBe(true);
});
