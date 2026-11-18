// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import WorkspaceSettings, { Notifications, AuditLog, Roles } from './WorkspaceSettings';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const matrix = {actions:['Read procurement records','Read and export audit log'],roles:[{role:'analyst',permissions:[true,false]},{role:'compliance',permissions:[true,true]}],note:'Knowledge access is restricted.'};
const settings = {profile:{id:1,display_name:'Priya Shah',email:'analyst@procurem.demo',role:'analyst'},preferred_fiscal_year:2026,frequent_suppliers:[{id:1,name:'Thermo Fisher',code:'SUP-4001'}],matrix};
const json = (data:unknown) => new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});

it('shows saved profile and matrix, saves fiscal year and removes a saved supplier', async () => {
  let saved = settings; const fetcher = vi.fn((_url:string, init?:RequestInit) => {
    if (init?.method === 'PUT') { saved = {...saved,preferred_fiscal_year:JSON.parse(String(init.body)).preferred_fiscal_year}; return Promise.resolve(new Response(null,{status:204})); }
    if (init?.method === 'DELETE') { saved = {...saved,frequent_suppliers:[]}; return Promise.resolve(new Response(null,{status:204})); }
    return Promise.resolve(json(saved));
  });
  vi.stubGlobal('fetch',fetcher); const user = userEvent.setup(); render(<WorkspaceSettings />);
  expect(await screen.findByText('Priya Shah')).toBeInTheDocument();
  expect(screen.getByText('Thermo Fisher')).toBeInTheDocument();
  expect(screen.getByText('No')).toBeInTheDocument();
  const year = screen.getByLabelText('Preferred fiscal year'); await user.clear(year); await user.type(year,'2025'); await user.click(screen.getByRole('button',{name:'Save fiscal year'}));
  expect(await screen.findByText('Fiscal year saved.')).toBeInTheDocument(); expect(year).toHaveValue(2025);
  await user.click(screen.getByRole('button',{name:'Remove Thermo Fisher'})); expect(await screen.findByText('No saved suppliers.')).toBeInTheDocument();
});

it('confirms history clearing and reports failures', async () => {
  vi.stubGlobal('fetch',vi.fn((_url:string,init?:RequestInit) => init?.method === 'DELETE' ? Promise.reject(new Error('network')) : Promise.resolve(json(settings))));
  vi.spyOn(window,'confirm').mockReturnValue(true); const user = userEvent.setup(); render(<WorkspaceSettings />);
  await screen.findByText('Priya Shah'); await user.click(screen.getByRole('button',{name:'Clear conversation history'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to clear conversation history.');
});

it('marks an unlinked notification read and updates the list', async () => {
  let read = 0; vi.stubGlobal('fetch',vi.fn((_url:string,init?:RequestInit) => {if(init?.method === 'POST') {read = 1; return Promise.resolve(json({}));} return Promise.resolve(json({items:[{id:7,title:'Approval',body:'Please review',created_at:'2026-01-01',is_read:read,link:null}],total:1,page:1,page_size:20}));}));
  const user = userEvent.setup(); render(<Notifications />); await user.click(await screen.findByRole('button',{name:/Approval/})); expect(await screen.findByText('Read')).toBeInTheDocument();
});

it('renders filtered audit rows and export and reports directory access errors', async () => {
  vi.stubGlobal('fetch',vi.fn((url:string) => url.includes('/roles') ? Promise.resolve(new Response('{}',{status:403})) : Promise.resolve(json({items:[{id:1,display_name:'System',role:'system',action:'seed',record_type:'workspace',record_id:'1',detail:'Seeded',created_at:'2026-01-01'}],total:1,page:1,page_size:20}))));
  const user = userEvent.setup(); const view = render(<AuditLog />); expect(await screen.findByText('Seeded')).toBeInTheDocument(); await user.type(screen.getByLabelText('Action'),'seed'); expect(screen.getByRole('link',{name:'Export CSV'})).toHaveAttribute('href',expect.stringContaining('action=seed')); view.unmount(); render(<Roles />); expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load role directory');
});
