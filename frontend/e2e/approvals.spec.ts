import { test, expect } from '@playwright/test';

/** Sign in through the actual login screen. */
async function login(page: import('@playwright/test').Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await expect(page).toHaveURL(/\/home/);
}

test('analyst submits a low-value request and manager signs it', async ({page}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const title = `Gloves ${Date.now()}`;
  await login(page,'analyst@procurem.demo');
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
  await login(page,'proc.manager@procurem.demo');
  await page.getByRole('link',{name:'Approvals'}).click();
  await page.getByRole('link',{name:title}).click();
  await expect(page.getByText('No current record')).toBeVisible();
  await page.getByRole('button',{name:'Approve'}).click();
  await page.getByLabel('Reason').fill('Reviewed and approved');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await expect(page.getByText('Reviewed and approved')).toBeVisible();
  await expect(page.getByRole('button',{name:'Approve'})).toHaveCount(0);
  expect(errors).toEqual([]);
});
