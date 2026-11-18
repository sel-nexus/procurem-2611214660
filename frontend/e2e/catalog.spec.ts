import { test, expect, signIn } from './fixtures';

test('filter catalog by supplier and open its linked supplier', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Catalog', exact:true}).click();
  await expect(page.getByRole('link', {name:'CAT-7001'})).toBeVisible();
  const filtered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/catalog' && new URL(r.url()).searchParams.get('supplier') === '1');
  await page.getByRole('combobox', {name:'supplier', exact:true}).selectOption('1');
  const response = await filtered;
  expect(response.status()).toBe(200);
  const rows = (await response.json()).items;
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.every((row: {supplier_id:number}) => row.supplier_id === 1)).toBe(true);
  await page.getByRole('link', {name:'CAT-7001'}).click();
  await expect(page.getByRole('heading', {name:/CAT-7001.*Laboratory item 1/})).toBeVisible();
  await page.getByRole('link', {name:'Thermo Fisher', exact:true}).click();
  await expect(page.getByRole('heading', {name:/SUP-4001.*Thermo Fisher/})).toBeVisible();
});
