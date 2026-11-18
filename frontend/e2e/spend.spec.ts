import { test, expect, signIn } from './fixtures';

test('filter spend by category and month and inspect the analytical row', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Spend', exact:true}).click();
  await page.getByLabel('category', {exact:true}).fill('Lab Reagents');
  const filtered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/spend' && new URL(r.url()).searchParams.get('category') === 'Lab Reagents' && new URL(r.url()).searchParams.get('from_month') === '2');
  await page.getByLabel('from month').fill('2');
  const response = await filtered;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.items.length).toBeGreaterThan(0);
  expect(body.items.every((row: {category:string;month:number}) => row.category === 'Lab Reagents' && row.month >= 2)).toBe(true);
  expect(body.chart[0].month).toBe('2026-02');
  await expect(page.getByText('2026-02', {exact:true})).toBeVisible();
  const row = body.items[0];
  await page.locator(`a[href="/spend/${row.id}"]`).click();
  await expect(page).toHaveURL(new RegExp(`/spend/${row.id}$`));
  await expect(page.getByRole('link', {name:'← Back to Spend'})).toBeVisible();
  await expect(page.getByRole('heading', {name:'Spend', exact:true})).toBeVisible();
  await expect(page.getByText('Lab Reagents', {exact:true})).toBeVisible();
});
