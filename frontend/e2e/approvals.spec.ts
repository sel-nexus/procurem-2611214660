import { test, expect, signIn } from './fixtures';

test('analyst submits a low-value request and manager signs it', async ({page}) => {
  const title = `Gloves ${Date.now()}`;
  await page.goto('/');
  await signIn(page,'analyst@procurem.demo');
  await page.getByRole('link',{name:'Requisitions'}).click();
  await page.getByRole('link',{name:'Create requisition'}).click();
  await page.getByLabel('Supplier').selectOption({label:'Thermo Fisher'});
  await page.getByLabel('Title').fill(title);
  await page.getByLabel('Reason').fill('Laboratory supplies');
  await page.getByLabel('Description').fill('Gloves');
  await page.getByLabel('Unit price (USD)').fill('12.50');
  await page.getByRole('button',{name:'Submit for approval'}).click();
  await expect(page.getByText('pending approval')).toBeVisible();
  await page.getByRole('button',{name:'Sign out'}).click();
  await signIn(page,'proc.manager@procurem.demo');
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Approvals'}).click();
  await page.getByRole('link',{name:title}).click();
  await expect(page.getByText('No current record')).toBeVisible();
  await page.getByRole('button',{name:'Approve'}).click();
  await page.getByLabel('Reason').fill('Reviewed and approved');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await expect(page.getByText('Reviewed and approved')).toBeVisible();
  await expect(page.getByRole('button',{name:'Approve'})).toHaveCount(0);
});
