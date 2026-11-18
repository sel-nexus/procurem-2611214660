// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import Users, { UserDetail } from './Users';

afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();});
const account = {id:8,display_name:'Alice Example',email:'alice@example.com',role:'analyst',status:'active'};
const json = (value:unknown, status=200) => new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});

it('creates an account, shows its password once and copies it', async () => {
  const fetcher = vi.fn((_url:string, init?:RequestInit) => Promise.resolve(init?.method === 'POST' ? json({user:account,temporary_password:'temporary-secret'},201) : json({items:[account],total:1,page:1,page_size:20})));
  vi.stubGlobal('fetch',fetcher);
  const user = userEvent.setup(); const copy = vi.spyOn(navigator.clipboard,'writeText').mockResolvedValue();
  render(<Users />);
  await screen.findByRole('link',{name:'Alice Example'});
  await user.type(screen.getByLabelText('Display name'),'Alice Example');
  await user.type(screen.getByLabelText('Email'),'alice@example.com');
  await user.click(screen.getByRole('button',{name:'Create user'}));
  const dialog = await screen.findByRole('dialog',{name:'Temporary password'});
  expect(within(dialog).getByText('This password is shown once.')).toBeInTheDocument();
  expect(within(dialog).getByText('temporary-secret')).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button',{name:'Copy'}));
  expect(copy).toHaveBeenCalledWith('temporary-secret');
  await user.keyboard('{Escape}');
  expect(screen.queryByText('temporary-secret')).not.toBeInTheDocument();
});

it('reports forbidden access without showing account controls', async () => {
  vi.stubGlobal('fetch',vi.fn(() => Promise.resolve(json({detail:'Permission denied.'},403))));
  render(<Users />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied.');
  expect(screen.queryByRole('button',{name:'Create user'})).not.toBeInTheDocument();
});

it('searches and sorts and reports duplicate account errors', async () => {
  const fetcher = vi.fn((url:string,init?:RequestInit) => Promise.resolve(init?.method === 'POST' ? json({detail:'Email is already in use.'},409) : json({items:[account],total:1,page:1,page_size:20})));
  vi.stubGlobal('fetch',fetcher); const user = userEvent.setup(); render(<Users />);
  await screen.findByText('alice@example.com');
  await user.type(screen.getByLabelText('Search by name or email'),'Alice');
  await user.click(screen.getByRole('button',{name:/Email/}));
  expect(fetcher.mock.calls.some(([url]) => String(url).includes('sort=email'))).toBe(true);
  await user.type(screen.getByLabelText('Display name'),'Alice'); await user.type(screen.getByLabelText('Email'),'alice@example.com');
  await user.click(screen.getByRole('button',{name:'Create user'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Email is already in use.');
});

it('updates a user, resets the password and reports protected self changes', async () => {
  let fail = false;
  vi.stubGlobal('fetch',vi.fn((_url:string,init?:RequestInit) => {
    if (init?.method === 'POST') return Promise.resolve(json({user:account,temporary_password:'rotated-secret'}));
    if (init?.method === 'PUT') return Promise.resolve(fail ? json({detail:'You cannot deactivate or remove your own admin role.'},403) : json({...account,display_name:'Renamed'}));
    return Promise.resolve(json(account));
  }));
  const user = userEvent.setup(); render(<UserDetail id="8" />);
  const name = await screen.findByLabelText('Display name'); await user.clear(name); await user.type(name,'Renamed');
  await user.click(screen.getByRole('button',{name:'Save'})); expect(await screen.findByText('User saved.')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'Reset password'})); expect(await screen.findByText('rotated-secret')).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'Close'})); fail = true;
  await user.click(screen.getByRole('button',{name:'Save'})); expect(await screen.findByRole('alert')).toHaveTextContent('cannot deactivate');
});
