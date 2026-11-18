import { test, expect, signIn } from './fixtures';

test('open a seeded requisition and inspect its line items', async ({page}) => {
  await page.goto('/');
  await signIn(page, 'analyst@procurem.demo');
  const list = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/requisitions');
  await page.getByRole('navigation', {name:'Main navigation'}).getByRole('link', {name:'Requisitions', exact:true}).click();
  const response = await list;
  expect(response.status()).toBe(200);
  const req = (await response.json()).items.find((row: {code:string}) => row.code === 'REQ-2001');
  expect(req.title).toBe('Laboratory supplies 1');
  const detail = page.waitForResponse(r => new URL(r.url()).pathname === `/api/v1/records/requisitions/${req.id}`);
  await page.getByRole('link', {name:req.code, exact:true}).click();
  const result = await detail;
  expect(result.status()).toBe(200);
  const body = await result.json();
  expect(body.relations.lines.map((line: {description:string}) => line.description)).toEqual(['Supply line 1', 'Supply line 2']);
  await expect(page.getByRole('heading', {name:/REQ-2001.*Laboratory supplies 1/})).toBeVisible();
  await expect(page.getByText('Supply line 1')).toBeVisible();
  await page.getByRole('link', {name:'← Back to Requisitions'}).click();
  await expect(page.getByRole('link', {name:'REQ-2001'})).toBeVisible();
});
