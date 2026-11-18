import { test, expect, signIn } from './fixtures';

test('filter matched invoices and follow the associated purchase order', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Invoices', exact:true}).click();
  const filtered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/invoices' && new URL(r.url()).searchParams.get('status') === 'matched');
  await page.getByLabel('status', {exact:true}).fill('matched');
  const response = await filtered;
  expect(response.status()).toBe(200);
  const rows = (await response.json()).items;
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.every((row: {status:string}) => row.status === 'matched')).toBe(true);
  const invoice = rows.find((row: {po_code:string | null}) => row.po_code);
  expect(invoice).toBeTruthy();
  await page.getByRole('link', {name:invoice.code, exact:true}).click();
  await expect(page.getByRole('heading', {name:new RegExp(invoice.code)})).toBeVisible();
  await page.getByRole('link', {name:invoice.po_code, exact:true}).click();
  await expect(page.getByRole('heading', {name:new RegExp(invoice.po_code)})).toBeVisible();
});
