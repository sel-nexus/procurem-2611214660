// @vitest-environment jsdom
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import Login from './Login';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe('Sign in', () => {
  it('shows seven demo accounts, signs in and signs out', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(JSON.stringify({id:1,email:'analyst@procurem.demo',display_name:'Priya Shah',role:'analyst'}),{status:200})).mockResolvedValueOnce(new Response(null,{status:204}));
    vi.stubGlobal('fetch',fetcher);
    const user = userEvent.setup(); render(<Login />);
    expect(await screen.findByText('Helen Cho')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(7);
    await user.type(screen.getByLabelText('Email'),'analyst@procurem.demo');
    await user.type(screen.getByLabelText('Password'),'Demo@1234');
    await user.click(screen.getByLabelText('Remember me'));
    await user.click(screen.getByRole('button',{name:'Sign in'}));
    expect(await screen.findByText('Signed in as Priya Shah.')).toBeInTheDocument();
    expect(JSON.parse(fetcher.mock.calls[1][1].body).remember_me).toBe(true);
    await user.click(screen.getByRole('button',{name:'Sign out'}));
    expect(await screen.findByRole('button',{name:'Sign in'})).toBeInTheDocument();
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
