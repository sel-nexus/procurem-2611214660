import { test, expect, signIn } from './fixtures';

test('filter expiring contracts and inspect supplier relationship', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Contracts', exact:true}).click();
  const filtered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/contracts' && new URL(r.url()).searchParams.get('status') === 'expiring_soon');
  await page.getByLabel('status', {exact:true}).fill('expiring_soon');
  const response = await filtered;
  expect(response.status()).toBe(200);
  const rows = (await response.json()).items;
  expect(rows.map((row: {code:string}) => row.code)).toEqual(['CON-5001', 'CON-5002']);
  await page.getByRole('link', {name:'CON-5001'}).click();
  await expect(page.getByRole('heading', {name:/CON-5001/})).toBeVisible();
  await expect(page.getByText('2026-08-01')).toBeVisible();
  await page.getByRole('link', {name:'Thermo Fisher', exact:true}).click();
  await expect(page.getByRole('heading', {name:/SUP-4001/})).toBeVisible();
});
