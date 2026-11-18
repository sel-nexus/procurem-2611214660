// @vitest-environment jsdom
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import Login from './Login';

const router = { replace: vi.fn() };
vi.mock('next/navigation', () => ({ useRouter: () => router }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe('Sign in', () => {
  it('shows seven demo accounts and opens Home after signing in', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(JSON.stringify({id:1,email:'analyst@procurem.demo',display_name:'Priya Shah',role:'analyst'}),{status:200}));
    vi.stubGlobal('fetch',fetcher);
    const user = userEvent.setup(); render(<Login />);
    expect(await screen.findByText('Helen Cho')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(7);
    await user.type(screen.getByLabelText('Email'),'analyst@procurem.demo');
    await user.type(screen.getByLabelText('Password'),'Demo@1234');
    await user.click(screen.getByLabelText('Remember me'));
    await user.click(screen.getByRole('button',{name:'Sign in'}));
    expect(await screen.findByText('Opening Home…')).toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith('/home');
    expect(JSON.parse(fetcher.mock.calls[1][1].body).remember_me).toBe(true);

  });
  it('shows an accessible credential error without signing in', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(JSON.stringify({detail:'Authentication failed. Please check your credentials.'}),{status:401})));
    const user = userEvent.setup(); render(<Login />);
    await screen.findByText('Helen Cho');
    await user.type(screen.getByLabelText('Email'),'analyst@procurem.demo');
    await user.type(screen.getByLabelText('Password'),'wrong');
    await user.click(screen.getByRole('button',{name:'Sign in'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Authentication failed. Please check your credentials.');
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-invalid','true');
  });
});
