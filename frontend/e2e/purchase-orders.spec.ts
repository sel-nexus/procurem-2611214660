import { test, expect, signIn } from './fixtures';

test('find orders without invoices and inspect order lines', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Purchase orders', exact:true}).click();
  const filtered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/purchase-orders' && new URL(r.url()).searchParams.get('no_invoice') === 'true');
  await page.getByLabel('no invoice').selectOption('true');
  const response = await filtered;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.items.length).toBeGreaterThan(0);
  expect(body.items.every((row: {has_invoice:number}) => !row.has_invoice)).toBe(true);
  await page.getByRole('link', {name:'PO-1001'}).click();
  await expect(page.getByRole('heading', {name:/PO-1001/})).toBeVisible();
  await expect(page.getByText('Supply line 1')).toBeVisible();
  await expect(page.getByText('No related records.')).toBeVisible();
});
