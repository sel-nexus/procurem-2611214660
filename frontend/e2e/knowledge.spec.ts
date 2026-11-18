import { test, expect, signIn } from './fixtures';

test('search accessible knowledge and open its policy through a link', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Knowledge', exact:true}).click();
  const filtered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/knowledge' && new URL(r.url()).searchParams.get('search') === 'Procurement Policy');
  await page.getByLabel('Search').fill('Procurement Policy');
  const response = await filtered;
  expect(response.status()).toBe(200);
  const rows = (await response.json()).items;
  expect(rows.map((row: {code:string}) => row.code)).toEqual(['DOC-8001']);
  await page.getByRole('link', {name:'DOC-8001'}).click();
  await expect(page.getByRole('heading', {name:/DOC-8001.*Procurement Policy/})).toBeVisible();
  await expect(page.getByText('Procurement Policy: Follow the documented review and approval process before proceeding.')).toBeVisible();
  await page.getByRole('link', {name:'← Back to Knowledge'}).click();
  await expect(page.getByRole('link', {name:'DOC-8001'})).toBeVisible();
});
