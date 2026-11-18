// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import ChangeForms from './ChangeForms';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const supplier = {id:1,contact_name:'Alice',contact_email:'alice@example.com',risk:'low',status:'active'};

it('hides all change actions from read-only roles', () => {
  const { rerender } = render(<ChangeForms kind="supplier" role="analyst" item={supplier} />);
  expect(screen.queryByRole('button',{name:'Propose edit'})).not.toBeInTheDocument();
  rerender(<ChangeForms kind="create" role="procurement_manager" />);
  expect(screen.queryByRole('button',{name:'Create sourcing event'})).not.toBeInTheDocument();
  rerender(<ChangeForms kind="award" role="sourcing_specialist" item={{id:1,status:'closed'}} bids={[{id:1}]} />);
  expect(screen.queryByRole('button',{name:'Request award'})).not.toBeInTheDocument();
});

it('submits only changed supplier fields and exposes the approval', async () => {
  const fetcher = vi.fn((_url: string, _init: RequestInit) => Promise.resolve(new Response(JSON.stringify({approval_id:42}),{status:201})));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup();
  render(<ChangeForms kind="supplier" role="category_manager" item={supplier} />);
  await user.click(screen.getByRole('button',{name:'Propose edit'}));
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Change at least one field');
  await user.selectOptions(screen.getByLabelText('Risk'),'high');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(await screen.findByRole('link',{name:'View pending approval'})).toHaveAttribute('href','/approvals/42');
  expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toEqual({risk:'high'});
});

it('shows server conflicts and allows retrying an award', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:'A proposal is already awaiting a decision for this record.'}),{status:409})).mockResolvedValueOnce(new Response(JSON.stringify({approval_id:9}),{status:201}));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup();
  render(<ChangeForms kind="award" role="sourcing_specialist" item={{id:2,status:'active'}} bids={[{id:7,supplier_name:'Merck',amount_usd:'120.00'}]} />);
  await user.click(screen.getByRole('button',{name:'Request award'}));
  await user.selectOptions(screen.getByLabelText('Bid'),'7');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('already awaiting');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(await screen.findByRole('link',{name:'View pending approval'})).toHaveAttribute('href','/approvals/9');
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({bid_id:7});
});

it('submits a sourcing event with exact decimal text', async () => {
  const fetcher = vi.fn((_url: string, _init: RequestInit) => Promise.resolve(new Response(JSON.stringify({approval_id:12}),{status:201})));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup();
  render(<ChangeForms kind="create" role="category_manager" />);
  await user.click(screen.getByRole('button',{name:'Create sourcing event'}));
  await user.type(screen.getByLabelText('Title'),'Gloves RFQ');
  await user.type(screen.getByLabelText('Estimated value (USD)'),'10000.01');
  await user.type(screen.getByLabelText('End date'),'2028-01-01');
  await user.click(screen.getByRole('button',{name:'Submit for approval'}));
  expect(await screen.findByRole('link',{name:'View pending approval'})).toBeInTheDocument();
  expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toMatchObject({estimated_value_usd:'10000.01',title:'Gloves RFQ'});
});
