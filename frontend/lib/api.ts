/** Share the authentication HTTP contract with the API. */
export interface User { id: number; email: string; display_name: string; role: string }
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
/** Call the same-origin proxy and preserve cookie credentials. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ''}${path}`, { ...init, credentials: 'include', headers: { 'Content-Type': 'application/json', ...init?.headers }, cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof body.detail === 'string' ? body.detail : 'Something went wrong. Please try again.');
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
