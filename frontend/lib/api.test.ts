import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('api client', () => {
  it('returns JSON and sends cookie credentials and caller headers', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 42 }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(api('/api/v1/example', { method: 'POST', headers: { 'X-Test': 'yes' }, body: '{}' })).resolves.toEqual({ id: 42 });
    expect(fetcher).toHaveBeenCalledWith(expect.stringMatching(/\/api\/v1\/example$/), expect.objectContaining({ method: 'POST', credentials: 'include', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-Test': 'yes' }, body: '{}' }));
  });
  it('returns undefined for a 204 without parsing JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api('/logout', { method: 'POST' })).resolves.toBeUndefined();
  });
  it('preserves status and detail, and falls back for invalid error bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('{"detail":"Denied"}', { status: 403 })).mockResolvedValueOnce(new Response('not json', { status: 500 })).mockResolvedValueOnce(new Response('{"detail":[{"msg":"invalid"}]}', { status: 422 })));
    const denied = await api('/x').catch(error => error);
    expect(denied).toBeInstanceOf(ApiError);
    expect(denied).toMatchObject({ status: 403, message: 'Denied' });
    await expect(api('/x')).rejects.toMatchObject({ status: 500, message: 'Something went wrong. Please try again.' });
    await expect(api('/x')).rejects.toMatchObject({ status: 422, message: 'Something went wrong. Please try again.' });
  });
  it('propagates network errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network offline')));
    await expect(api('/x')).rejects.toThrow('Network offline');
  });
});
