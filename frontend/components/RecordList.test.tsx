// @vitest-environment jsdom
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import RecordList from './RecordList';

vi.mock('next/navigation', () => ({ useRouter: () => router, usePathname: () => '/suppliers' }));
const router = { replace: vi.fn() };
const identity = {id:1,email:'analyst@procurem.demo',display_name:'Priya Shah',role:'analyst'};
const result = {items:[{id:1,code:'SUP-4001',name:'Thermo Fisher',category:'Lab Reagents',country:'United States',risk:'low',status:'active',spend_ytd_usd:'12000.00'}],total:1,page:1,page_size:20,source_label:'Mock · JAGGAER',freshness:'Real-time'};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null,'','/'); });
describe('Record directory', () => {
  it('renders records, navigable details and sends sorting and search', async () => {
    const thermo = result.items[0];
    const merck = { ...thermo, id: 2, code: 'SUP-4002', name: 'Merck' };
    const fetcher = vi.fn((url: string) => {
      if (url.includes('/auth/me')) return Promise.resolve(new Response(JSON.stringify(identity), {status:200}));
      if (url.includes('/unread-count')) return Promise.resolve(new Response(JSON.stringify({count:0}), {status:200}));
      const params = new URL(url, 'http://localhost').searchParams;
      const items = params.get('sort') === 'name' && params.get('order') === 'asc' ? [merck, thermo] : [thermo, merck];
      return Promise.resolve(new Response(JSON.stringify({...result, items, total:2}), {status:200}));
    });
    vi.stubGlobal('fetch',fetcher);
    const user = userEvent.setup(); render(<RecordList resource="suppliers" />);
    expect(await screen.findByRole('link',{name:'SUP-4001'})).toHaveAttribute('href','/suppliers/1');
    expect(screen.getByText('Thermo Fisher')).toBeInTheDocument();
    expect(screen.getAllByText('12,000.00')).toHaveLength(2);
    const rowNames = () => screen.getAllByRole('row').slice(1).map(row => within(row).getAllByRole('cell')[1].textContent);
    expect(rowNames()).toEqual(['Thermo Fisher', 'Merck']);
    expect(screen.getByRole('columnheader',{name:'Supplier'})).toHaveAttribute('aria-sort','none');
    await user.click(screen.getByRole('button',{name:'Supplier'}));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('sort=name') && url.includes('order=asc'))).toBe(true));
    await waitFor(() => expect(rowNames()).toEqual(['Merck', 'Thermo Fisher']));
    expect(screen.getByRole('columnheader',{name:/Supplier/})).toHaveAttribute('aria-sort','ascending');
    await user.click(screen.getByRole('button',{name:/Supplier/}));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('sort=name') && url.includes('order=desc'))).toBe(true));
    await waitFor(() => expect(rowNames()).toEqual(['Thermo Fisher', 'Merck']));
    expect(screen.getByRole('columnheader',{name:/Supplier/})).toHaveAttribute('aria-sort','descending');
    await user.type(screen.getByLabelText('Search'),'Merck');
    await waitFor(() => expect(window.location.search).toContain('search=Merck'));
  });
  it('shows empty and failure states with retry', async () => {
    let fail = false;
    vi.stubGlobal('fetch',vi.fn((url: string) => Promise.resolve(url.includes('/auth/me') ? new Response(JSON.stringify(identity),{status:200}) : fail ? new Response('{}',{status:500}) : new Response(JSON.stringify({...result,items:[],total:0}),{status:200}))));
    const user = userEvent.setup(); render(<RecordList resource="suppliers" />);
    expect(await screen.findByText(/No records match/)).toBeInTheDocument();
    fail = true;
    await user.type(screen.getByLabelText('Search'),'x');
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong');
    fail = false; await user.click(screen.getByRole('button',{name:'Retry'}));
    expect(await screen.findByText(/No records match/)).toBeInTheDocument();
  });
});
