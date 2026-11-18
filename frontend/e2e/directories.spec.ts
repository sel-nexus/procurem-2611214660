import { test, expect, signIn } from './fixtures';

// Feature-specific journeys live in their own specs. The settings spec still
// mutates the shared seeded analyst's suppliers/history; a fresh database per
// invocation and one worker do not isolate retries or individual test order.

test('dashboard and sidebar reach suppliers; empty filter can be reset', async ({page}, testInfo) => {
  await page.goto('/');
  const dashboard = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/dashboard');
  await signIn(page, 'analyst@procurem.demo');
  const response = await dashboard;
  expect(response.status()).toBe(200);
  const data = await response.json();
  const metric = page.getByRole('link', {name:/Suppliers.*Real-time/});
  await expect(metric).toContainText(String(data.supplier_count));
  await page.screenshot({path:testInfo.outputPath('desktop-home.png'), fullPage:true});
  const list = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/suppliers');
  await metric.click();
  expect((await list).status()).toBe(200);
  await expect(page.getByRole('link', {name:'SUP-4001'})).toBeVisible();
  await page.getByLabel('Search').fill('no-supplier-matches-987654321');
  await expect(page.getByText('No records match these filters.')).toBeVisible();
  await page.getByRole('button',{name:'Reset filters'}).last().click();
  await expect(page.getByRole('link', {name:'SUP-4001'})).toBeVisible();
  await page.getByRole('link',{name:'Home',exact:true}).click();
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Suppliers',exact:true}).click();
  await expect(page.getByRole('link', {name:'SUP-4001'})).toBeVisible();
});

test('purchase order pagination and sorting reflect backend pages', async ({page}) => {
  await page.goto('/');
  await signIn(page,'analyst@procurem.demo');
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Purchase orders',exact:true}).click();
  await expect(page.getByText(/Page 1 · 24 records/)).toBeVisible();
  const next = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/purchase-orders' && new URL(r.url()).searchParams.get('page') === '2');
  await page.getByRole('button',{name:'Next',exact:true}).click();
  const nextResponse = await next;
  expect(nextResponse.status()).toBe(200);
  const secondPage = await nextResponse.json();
  expect(secondPage.page).toBe(2);
  expect(secondPage.items.length).toBeGreaterThan(0);
  await expect(page.getByRole('link',{name:secondPage.items[0].code,exact:true})).toBeVisible();
  const sorted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/purchase-orders' && new URL(r.url()).searchParams.get('sort') === 'code' && new URL(r.url()).searchParams.get('order') === 'asc');
  await page.getByRole('button',{name:'PO number'}).click();
  const sortedResponse = await sorted;
  expect(sortedResponse.status()).toBe(200);
  const sortedData = await sortedResponse.json();
  expect(sortedData.page).toBe(1);
  expect(sortedData.items[0].code).toBe('PO-1001');
  await expect(page.getByRole('link',{name:sortedData.items[0].code,exact:true})).toBeVisible();
});

test('loading is visible while a genuine supplier response is held', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let fetched!: () => void;
  const backendFinished = new Promise<void>(resolve => { fetched = resolve; });
  await page.route('**/api/v1/records/suppliers*', async route => {
    const response = await route.fetch(); // forward to the real backend, retain its actual body/status
    fetched();
    await gate;
    await route.fulfill({response});
  });
  try {
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Suppliers',exact:true}).click();
    await backendFinished;
    await expect(page.getByText('Loading records…')).toBeVisible();
  } finally { release(); }
  await expect(page.getByRole('link',{name:'SUP-4001'})).toBeVisible();
});
