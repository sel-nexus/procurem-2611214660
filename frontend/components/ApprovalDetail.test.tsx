// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import ApprovalDetail from './ApprovalDetail';
import RequisitionForm from './RequisitionForm';

const router = {replace:vi.fn(),push:vi.fn()};
vi.mock('next/navigation', () => ({useRouter: () => router, usePathname: () => '/approvals/1'}));
const manager = {id:3,email:'proc.manager@procurem.demo',display_name:'David Okonkwo',role:'procurement_manager'};
const approval = {id:1,title:'Laboratory supplies',approval_type:'requisition',status:'pending',requester_name:'Priya Shah',current:{},proposed:{title:'Laboratory supplies'},signatures:[],signatures_required:1,can_sign:true};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); router.push.mockClear(); router.replace.mockClear(); });

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
  expect(screen.getByText('requisition · approved · Requested by Priya Shah')).toBeInTheDocument();
  expect(screen.getByText('David Okonkwo · procurement manager')).toBeInTheDocument();
  expect(screen.getByText('Approved', {selector:'p'})).toBeInTheDocument();
  expect(screen.queryByText('Waiting for signature')).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Approve'})).not.toBeInTheDocument();
});

it('hides signing controls for a requester', async () => {
  vi.stubGlobal('fetch',vi.fn((url:string) => Promise.resolve(new Response(JSON.stringify(url.includes('/auth/me') ? {...manager,id:1,role:'analyst'} : {...approval,can_sign:false})))));
  render(<ApprovalDetail id="1" />);
  expect(await screen.findByText('Waiting for signature')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Approve'})).not.toBeInTheDocument();
});

it('renders the current and proposed diff and saves a rejection', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open',''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const change = {...approval,approval_type:'supplier_edit',title:'Supplier edit',current:{risk:'low',contact_name:'Old contact'},proposed:{risk:'high',contact_name:'New contact'}};
  const fetcher = vi.fn((url:string, init?:RequestInit) => {
    if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify(manager)));
    if (init?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({...change,status:'rejected',can_sign:false,signatures:[{signer_id:3,display_name:'David Okonkwo',role:'procurement_manager',meaning:'Rejected',reason:'Insufficient evidence',signed_at:'2026-07-07T00:00:00+00:00'}]})));
    return Promise.resolve(new Response(JSON.stringify(change)));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<ApprovalDetail id="1" />);
  expect(await screen.findByText('Old contact')).toBeInTheDocument();
  expect(screen.getByText('New contact')).toBeInTheDocument();
  expect(screen.getByText('low')).toBeInTheDocument();
  expect(screen.getByText('high')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'Reject'}));
  await user.type(screen.getByLabelText('Reason'),'Insufficient evidence');
  await user.type(screen.getByLabelText('Password'),'Demo@1234');
  await user.click(screen.getByRole('button',{name:'Sign'}));
  expect(await screen.findByText('Insufficient evidence',{selector:'p'})).toBeInTheDocument();
  expect(screen.getByText('supplier edit · rejected · Requested by Priya Shah')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Reject'})).not.toBeInTheDocument();
  const post = fetcher.mock.calls.find(([,init]) => init?.method === 'POST');
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({meaning:'Rejected',reason:'Insufficient evidence',password:'Demo@1234'});
});

it('shows approval load errors without signing controls', async () => {
  vi.stubGlobal('fetch',vi.fn((url:string) => Promise.resolve(url.includes('/auth/me')
    ? new Response(JSON.stringify(manager)) : new Response(JSON.stringify({detail:'Not found'}),{status:404}))));
  render(<ApprovalDetail id="missing" />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Approval not found.');
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
  expect(screen.getByText('Draft saved. Retry submission or open it from the requisition list.')).toBeInTheDocument();
  expect(screen.getByLabelText('Title')).toHaveValue('Lab supplies');
  expect(screen.getByLabelText('Title')).toBeDisabled();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  const create = fetcher.mock.calls.find(([url, init]) => url.endsWith('/requisitions') && init?.method === 'POST');
  expect(JSON.parse(String(create?.[1]?.body))).toEqual({supplier_id:1,title:'Lab supplies',reason:'Needed for work',lines:[{description:'Gloves',quantity:1,unit_price:'10.25'}]});
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/requisitions/9/submit'))).toHaveLength(1);
});

it('adds and removes lines, preserves the remaining values, and saves them as a draft', async () => {
  const fetcher = vi.fn((url:string, init?:RequestInit) => {
    if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify({...manager,id:1,role:'analyst'})));
    if (url.includes('/records/suppliers')) return Promise.resolve(new Response(JSON.stringify({items:[{id:1,name:'Thermo Fisher'}]})));
    if (init?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({id:9}),{status:201}));
    return Promise.resolve(new Response(JSON.stringify({count:0})));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<RequisitionForm />);
  await user.selectOptions(await screen.findByLabelText('Supplier'),'1');
  await user.type(screen.getByLabelText('Title'),'Lab supplies');
  await user.type(screen.getByLabelText('Reason'),'Needed for work');
  const first = screen.getByRole('group',{name:'Line 1'});
  await user.type(within(first).getByLabelText('Description'),'Gloves');
  await user.clear(within(first).getByLabelText('Quantity'));
  await user.type(within(first).getByLabelText('Quantity'),'2');
  await user.type(within(first).getByLabelText('Unit price (USD)'),'10.25');
  expect(screen.queryByRole('button',{name:'Remove line 1'})).not.toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'Add line'}));
  const second = screen.getByRole('group',{name:'Line 2'});
  await user.type(within(second).getByLabelText('Description'),'Discarded');
  await user.type(within(second).getByLabelText('Unit price (USD)'),'99');
  await user.click(screen.getByRole('button',{name:'Add line'}));
  const third = screen.getByRole('group',{name:'Line 3'});
  await user.type(within(third).getByLabelText('Description'),'Masks');
  await user.clear(within(third).getByLabelText('Quantity'));
  await user.type(within(third).getByLabelText('Quantity'),'3');
  await user.type(within(third).getByLabelText('Unit price (USD)'),'4.50');
  await user.click(screen.getByRole('button',{name:'Remove line 2'}));
  expect(screen.queryByRole('group',{name:'Line 3'})).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('Discarded')).not.toBeInTheDocument();
  expect(within(screen.getByRole('group',{name:'Line 1'})).getByLabelText('Description')).toHaveValue('Gloves');
  const remaining = screen.getByRole('group',{name:'Line 2'});
  expect(within(remaining).getByLabelText('Description')).toHaveValue('Masks');
  expect(within(remaining).getByLabelText('Quantity')).toHaveValue(3);
  expect(within(remaining).getByLabelText('Unit price (USD)')).toHaveValue('4.50');
  await user.click(screen.getByRole('button',{name:'Save as draft'}));
  expect(await screen.findByText('Draft saved. Retry submission or open it from the requisition list.')).toBeInTheDocument();
  await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith('/requisitions/9'));
  expect(within(screen.getByRole('group',{name:'Line 2'})).getByLabelText('Description')).toBeDisabled();
  expect(screen.queryByRole('button',{name:'Add line'})).not.toBeInTheDocument();
  const create = fetcher.mock.calls.find(([url, init]) => url.endsWith('/requisitions') && init?.method === 'POST');
  expect(JSON.parse(String(create?.[1]?.body))).toEqual({supplier_id:1,title:'Lab supplies',reason:'Needed for work',lines:[{description:'Gloves',quantity:2,unit_price:'10.25'},{description:'Masks',quantity:3,unit_price:'4.50'}]});
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/submit'))).toBe(false);
});

it.each([
  ['empty description', 'Description', ''],
  ['zero quantity', 'Quantity', '0'],
  ['negative quantity', 'Quantity', '-2'],
  ['fractional quantity', 'Quantity', '1.5'],
  ['negative price', 'Unit price (USD)', '-1'],
  ['price with too many decimal places', 'Unit price (USD)', '1.234'],
])('rejects a line with %s without creating or submitting', async (_case, field, value) => {
  const fetcher = vi.fn((url:string) => Promise.resolve(new Response(JSON.stringify(
    url.includes('/auth/me') ? {...manager,id:1,role:'analyst'} :
    url.includes('/records/suppliers') ? {items:[{id:1,name:'Thermo Fisher'}]} : {count:0}
  ))));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<RequisitionForm />);
  await user.selectOptions(await screen.findByLabelText('Supplier'),'1');
  await user.type(screen.getByLabelText('Title'),'Lab supplies');
  await user.type(screen.getByLabelText('Reason'),'Needed for work');
  await user.type(screen.getByLabelText('Description'),'Gloves');
  await user.type(screen.getByLabelText('Unit price (USD)'),'10.25');
  await user.clear(screen.getByLabelText(field));
  if (value) await user.type(screen.getByLabelText(field),value);
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Enter a title, reason, and valid lines. Amount must be greater than 0.');
  expect(screen.getByLabelText('Title')).toHaveValue('Lab supplies');
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/requisitions') || url.endsWith('/submit'))).toBe(false);
  expect(router.push).not.toHaveBeenCalled();
});

it('shows validation errors and does not save invalid requisitions', async () => {
  const fetcher = vi.fn((url:string) => Promise.resolve(new Response(JSON.stringify(
    url.includes('/auth/me') ? {...manager,id:1,role:'analyst'} :
    url.includes('/records/suppliers') ? {items:[{id:1,name:'Thermo Fisher'}]} : {count:0}
  ))));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<RequisitionForm />);
  await screen.findByLabelText('Supplier');
  await user.click(screen.getByRole('button',{name:'Save as draft'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Supplier is required.');
  await user.selectOptions(screen.getByLabelText('Supplier'),'1');
  await user.type(screen.getByLabelText('Title'),'Lab supplies');
  await user.type(screen.getByLabelText('Reason'),'Needed for work');
  await user.type(screen.getByLabelText('Description'),'Gloves');
  await user.type(screen.getByLabelText('Unit price (USD)'),'0');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Enter a title, reason, and valid lines. Amount must be greater than 0.');
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/requisitions'))).toBe(false);
  expect(router.push).not.toHaveBeenCalled();
});

it('preserves a saved draft after submission fails and retries without creating another', async () => {
  let submitAttempts = 0;
  const fetcher = vi.fn((url:string, init?:RequestInit) => {
    if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify({...manager,id:1,role:'analyst'})));
    if (url.includes('/records/suppliers')) return Promise.resolve(new Response(JSON.stringify({items:[{id:1,name:'Thermo Fisher'}]})));
    if (url.endsWith('/submit')) {
      submitAttempts++;
      return Promise.resolve(submitAttempts === 1 ? new Response(JSON.stringify({detail:'Approval service unavailable.'}),{status:503}) : new Response(JSON.stringify({approval_id:4})));
    }
    if (init?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({id:9}),{status:201}));
    return Promise.resolve(new Response(JSON.stringify({count:0})));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<RequisitionForm />);
  await user.selectOptions(await screen.findByLabelText('Supplier'),'1');
  await user.type(screen.getByLabelText('Title'),'Lab supplies');
  await user.type(screen.getByLabelText('Reason'),'Needed for work');
  await user.type(screen.getByLabelText('Description'),'Gloves');
  await user.type(screen.getByLabelText('Unit price (USD)'),'10.25');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Approval service unavailable.');
  expect(screen.getByText('Draft saved. Retry submission or open it from the requisition list.')).toBeInTheDocument();
  expect(screen.getByLabelText('Title')).toHaveValue('Lab supplies');
  expect(screen.getByLabelText('Title')).toBeDisabled();
  expect(screen.getByRole('button',{name:'Save as draft'})).toBeDisabled();
  expect(router.push).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith('/requisitions/9'));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url, init]) => url.endsWith('/requisitions') && init?.method === 'POST')).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/requisitions/9/submit'))).toHaveLength(2);
});

it('saves a valid draft without submitting it', async () => {
  const fetcher = vi.fn((url:string, init?:RequestInit) => {
    if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify({...manager,id:1,role:'analyst'})));
    if (url.includes('/records/suppliers')) return Promise.resolve(new Response(JSON.stringify({items:[{id:1,name:'Thermo Fisher'}]})));
    if (init?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({id:9}),{status:201}));
    return Promise.resolve(new Response(JSON.stringify({count:0})));
  });
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); render(<RequisitionForm />);
  await user.selectOptions(await screen.findByLabelText('Supplier'),'1');
  await user.type(screen.getByLabelText('Title'),'Lab supplies');
  await user.type(screen.getByLabelText('Reason'),'Needed for work');
  await user.type(screen.getByLabelText('Description'),'Gloves');
  await user.type(screen.getByLabelText('Unit price (USD)'),'10.25');
  await user.click(screen.getByRole('button',{name:'Save as draft'}));
  await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith('/requisitions/9'));
  expect(screen.getByText('Draft saved. Retry submission or open it from the requisition list.')).toBeInTheDocument();
  expect(screen.getByLabelText('Title')).toHaveValue('Lab supplies');
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/submit'))).toBe(false);
});
