import { test as base, expect, type Page } from '@playwright/test';

/** Capture browser errors before a page navigates, including secondary pages. */
export function watchPage(page: Page, errors: string[], protectedRouteTest = false) {
  page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    // Chromium reports expected authentication/knowledge rejections as resource errors.
    // Only these exact endpoint/status pairs are expected in the security journeys.
    const url = message.location().url;
    const text = message.text();
    const expected = /Failed to load resource: the server responded with a status of 401 \(Unauthorized\)/.test(text)
      && /\/api\/v1\/auth\/(me|login)(?:\?|$)/.test(url)
      || /Failed to load resource: the server responded with a status of 404 \(Not Found\)/.test(text)
      && /\/api\/v1\/records\/knowledge\/5(?:\?|$)/.test(url)
      || protectedRouteTest && /Failed to load resource: the server responded with a status of 401 \(Unauthorized\)/.test(text)
      && /\/api\/v1\/records\/suppliers(?:\?|$)/.test(url);
    if (!expected) errors.push(`console ${url}: ${text}`);
  });
}

export const test = base.extend<{ browserErrors: string[] }>({
  browserErrors: [async ({ context, page }, use, testInfo) => {
    const errors: string[] = [];
    const watched = new WeakSet<Page>();
    const watch = (p: Page) => { if (!watched.has(p)) { watched.add(p); watchPage(p, errors, testInfo.title === 'protected page redirects without a session and after session expiry'); } };
    watch(page);
    context.on('page', watch);
    await use(errors);
    context.off('page', watch);
    expect(errors, 'browser console errors and uncaught exceptions').toEqual([]);
  }, { auto: true }],
});
export { expect };

export async function signIn(page: Page, email: string, password = 'Demo@1234') {
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/login' && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in' }).click();
  expect((await response).status()).toBe(200);
  await expect(page).toHaveURL(/\/home$/);
}
