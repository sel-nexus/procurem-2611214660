// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import Home from './page';

const router = { replace: vi.fn() };
vi.mock('next/navigation', () => ({ useRouter: () => router }));
vi.mock('../../components/Shell', () => ({ default: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const dashboard = { supplier_count: 12, open_order_count: 5, no_invoice_count: 2, open_order_usd: '12345.67', pending_approval_count: 3, spend: [{ category: 'Lab equipment', amount_usd: '456.78' }], latest_month: '2026-04', demo_data_loaded: true };
beforeEach(() => router.replace.mockReset());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('home dashboard', () => {
  it('shows loading followed by metrics, filtered links and spend from the response', async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { resolve = r; })));
    render(<Home />);
    expect(screen.getByText('Loading records…')).toBeInTheDocument();
    resolve(json(dashboard));
    expect(await screen.findByText('$12,345.67')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open orders without invoice/ })).toHaveAttribute('href', '/purchase-orders?status=open&no_invoice=true');
    expect(screen.getByRole('link', { name: /Suppliers/ })).toHaveTextContent('12');
    expect(screen.getByRole('link', { name: /Suppliers/ })).toHaveAttribute('href', '/suppliers');
    expect(screen.getByRole('link', { name: /Open purchase orders/ })).toHaveAttribute('href', '/purchase-orders?status=open');
    expect(screen.getByRole('link', { name: /Open order total \(USD\)/ })).toHaveAttribute('href', '/purchase-orders?status=open');
    expect(screen.getByRole('link', { name: /Pending approvals/ })).toHaveAttribute('href', '/approvals');
    expect(screen.getByRole('link', { name: /Pending approvals/ })).toHaveTextContent('3');
    expect(screen.getByText('Lab equipment')).toBeInTheDocument();
    expect(screen.getByText('$456.78')).toBeInTheDocument();
    expect(screen.getByText('Latest month: 2026-04')).toBeInTheDocument();
  });
  it('retries a failure and reports missing demo data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({}, 500)).mockResolvedValueOnce(json({ ...dashboard, demo_data_loaded: false })));
    const user = userEvent.setup(); render(<Home />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Demo data did not load.');
    expect(screen.queryByText('$12,345.67')).not.toBeInTheDocument();
  });
  it('redirects to sign-in on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({}, 401)));
    render(<Home />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith('/'));
    expect(screen.queryByText('$12,345.67')).not.toBeInTheDocument();
  });
});
