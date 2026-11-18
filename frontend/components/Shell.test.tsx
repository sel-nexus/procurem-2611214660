// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import Shell from './Shell';

const router = { replace: vi.fn() };
vi.mock('next/navigation', () => ({ useRouter: () => router, usePathname: () => '/suppliers/1' }));
const identity = { id: 1, email: 'a@example.com', display_name: 'Priya Shah', role: 'analyst' };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
beforeEach(() => router.replace.mockReset());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('workspace shell', () => {
  it('waits for authentication, shows identity, navigation, unread count and signs out', async () => {
    let resolveSession!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.endsWith('/auth/me')) return new Promise<Response>(resolve => { resolveSession = resolve; });
      if (url.endsWith('/unread-count')) return Promise.resolve(json({ count: 3 }));
      return Promise.resolve(new Response(null, { status: 204 }));
    }));
    const user = userEvent.setup();
    render(<Shell title="Suppliers"><p>Protected supplier content</p></Shell>);
    expect(screen.getByText('Checking session…')).toBeInTheDocument();
    expect(screen.queryByText('Protected supplier content')).not.toBeInTheDocument();
    resolveSession(json(identity));
    expect(await screen.findByText('Protected supplier content')).toBeInTheDocument();
    expect(screen.getByText('Priya Shah')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Suppliers' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
    const notifications = await screen.findByRole('link', { name: 'Notifications, 3 unread' });
    expect(notifications).toHaveAttribute('href', '/notifications');
    expect(within(notifications).getByText('3')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('button', { name: 'Close navigation' }));
    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'false');
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith('/'));
  });

  it.each(['procurement_manager', 'compliance'])('shows the %s reviewer count including zero', async role => {
    const fetcher = vi.fn((url: string) => Promise.resolve(url.endsWith('/auth/me') ? json({ ...identity, role }) : url.endsWith('/pending-count') ? json({ count: role === 'compliance' ? 0 : 4 }) : json({ count: 0 })));
    vi.stubGlobal('fetch', fetcher);
    render(<Shell title="Home"><p>Private content</p></Shell>);
    const count = role === 'compliance' ? 0 : 4;
    const link = await screen.findByRole('link', { name: `Approvals, ${count} pending` });
    expect(link).toHaveAttribute('href', '/approvals');
    expect(link).toHaveTextContent(String(count));
    expect(within(link).getByText(String(count))).toBeVisible();
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/approvals/pending-count'), expect.anything());
  });

  it.each(['analyst', 'admin'])('does not show or query reviewer counts for %s', async role => {
    const fetcher = vi.fn((url: string) => Promise.resolve(url.endsWith('/auth/me') ? json({ ...identity, role }) : json({ count: 0 })));
    vi.stubGlobal('fetch', fetcher);
    render(<Shell title="Home"><p>Private content</p></Shell>);
    const link = await screen.findByRole('link', { name: 'Approvals' });
    expect(link).toHaveAttribute('href', '/approvals');
    expect(link).toHaveTextContent(/^Approvals$/);
    expect(within(link).queryByText(/\d/)).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/pending-count'))).toBe(false);
  });

  it('does not misrepresent a failed reviewer count as zero', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.endsWith('/auth/me') ? json({ ...identity, role: 'compliance' }) : url.endsWith('/pending-count') ? json({}, 500) : json({ count: 0 }))));
    render(<Shell title="Home"><p>Private content</p></Shell>);
    const link = await screen.findByRole('link', { name: 'Approvals (pending count unavailable)' });
    expect(link).toHaveTextContent('Approvals');
    expect(link).not.toHaveTextContent('0');
  });

  it('redirects an expired session without exposing protected content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Unauthorized' }, 401)));
    render(<Shell title="Home"><p>Private content</p></Shell>);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith('/'));
    expect(screen.queryByText('Private content')).not.toBeInTheDocument();
  });

  it('shows session and sign-out failures without redirecting', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({}, 500)));
    const { unmount } = render(<Shell title="Home"><p>Private content</p></Shell>);
    expect(await screen.findByText('Unable to check your session. Please try again.')).toBeInTheDocument();
    unmount();
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url.endsWith('/auth/me') ? json({ ...identity, role: 'admin' }) : url.endsWith('/unread-count') ? json({}, 500) : json({}, 500))));
    const user = userEvent.setup();
    render(<Shell title="Home"><p>Private content</p></Shell>);
    expect(await screen.findByRole('link', { name: 'Users' })).toHaveAttribute('href', '/users');
    expect(screen.getByRole('link', { name: 'Roles' })).toHaveAttribute('href', '/roles');
    expect(await screen.findByRole('link', { name: 'Notifications (count unavailable)' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to sign out');
    expect(router.replace).not.toHaveBeenCalled();
  });
});
