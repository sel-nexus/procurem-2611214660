// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import RecordDetail from './RecordDetail';

const router = { replace: vi.fn() };
vi.mock('next/navigation', () => ({ useRouter: () => router }));
vi.mock('./Shell', () => ({ default: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const invoice = { item: { id: 7, code: 'INV-7', amount: '1234.50', supplier_id: 4, supplier_name: 'Acme', po_id: 9, po_code: 'PO-9' }, relations: { 'purchase-orders': [{ id: 9, code: 'PO-9', status: 'open' }], contracts: [] }, source_label: 'Mock · Oracle', freshness: 'Real-time' };
beforeEach(() => router.replace.mockReset());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('record detail', () => {
  it('shows loading then actual record fields, provenance and related links', async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { resolve = r; })));
    render(<RecordDetail resource="invoices" id="7" />);
    expect(screen.getByText('Loading records…')).toBeInTheDocument();
    resolve(json(invoice));
    expect(await screen.findByRole('heading', { name: 'INV-7' })).toBeInTheDocument();
    expect(screen.getByText('1,234.50')).toBeInTheDocument();
    expect(screen.getByText('Mock · Oracle')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '/suppliers/4');
    expect(screen.getAllByRole('link', { name: 'PO-9' }).every(link => link.getAttribute('href') === '/purchase-orders/9')).toBe(true);
    expect(screen.getByText('No related records.')).toBeInTheDocument();
  });

  it('offers retry on errors and distinguishes missing records', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({}, 500)).mockResolvedValueOnce(json(invoice)));
    const user = userEvent.setup(); render(<RecordDetail resource="invoices" id="7" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('heading', { name: 'INV-7' })).toBeInTheDocument();
    cleanup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({}, 404)));
    render(<RecordDetail resource="invoices" id="999" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Record not found.');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('lets only the draft requester submit and displays submission errors', async () => {
    const analyst = { id: 1, email: 'analyst@example.com', display_name: 'Analyst', role: 'analyst' };
    const draft = { item: { id: 8, code: 'REQ-8', status: 'draft', requester_id: 1 }, relations: {}, source_label: 'Mock · Oracle', freshness: 'Real-time' };
    const fetcher = vi.fn((url: string, init?: RequestInit) => Promise.resolve(url.endsWith('/auth/me') ? json(analyst) : init?.method === 'POST' ? json({ detail: 'Approval unavailable' }, 409) : json(draft)));
    vi.stubGlobal('fetch', fetcher);
    const user = userEvent.setup();
    const { unmount } = render(<RecordDetail resource="requisitions" id="8" />);
    await user.click(await screen.findByRole('button', { name: 'Submit for approval' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Approval unavailable');
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/requisitions/8/submit'), expect.objectContaining({ method: 'POST' }));
    unmount();
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.endsWith('/auth/me') ? json({ ...analyst, id: 2 }) : json(draft))));
    render(<RecordDetail resource="requisitions" id="8" />);
    expect(await screen.findByRole('heading', { name: 'REQ-8' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Submit for approval' })).not.toBeInTheDocument();
  });

  it('redirects on an expired session and avoids a fetch for an unknown resource', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({}, 401)); vi.stubGlobal('fetch', fetcher);
    const { unmount } = render(<RecordDetail resource="invoices" id="1" />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith('/'));
    unmount(); fetcher.mockClear();
    render(<RecordDetail resource="invalid" id="1" />);
    expect(screen.getByText('Page not found.')).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
