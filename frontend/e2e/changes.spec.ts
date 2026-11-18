import { test, expect } from '@playwright/test';

/** Authenticate using the visible demo form. */
async function login(page: import('@playwright/test').Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await expect(page).toHaveURL(/\/home/);
}

test('supplier edit waits for the manager and compliance signatures', async ({page}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await login(page,'category.mgr@procurem.demo');
  await page.goto('/suppliers/1');
  await page.getByRole('button',{name:'Propose edit'}).click();
  await page.getByLabel('Risk').selectOption('high');
  await page.getByLabel('Contact name').fill(`Contact ${Date.now()}`);
  await page.getByRole('button',{name:'Submit for approval'}).click();
  const approval = page.getByRole('link',{name:'View pending approval'});
  await expect(approval).toBeVisible();
  const href = await approval.getAttribute('href');
  expect(href).toBeTruthy();
  await page.getByRole('button',{name:'Sign out'}).click();
  await login(page,'proc.manager@procurem.demo');
  await page.goto(href!);
  await expect(page.getByText('Waiting for signature')).toHaveCount(2);
  await page.getByRole('button',{name:'Approve'}).click();
  await page.getByLabel('Reason').fill('Reviewed and approved');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await expect(page.getByText('Waiting for signature')).toHaveCount(1);
  await page.getByRole('button',{name:'Sign out'}).click();
  await login(page,'compliance@procurem.demo');
  await page.goto(href!);
  await page.getByRole('button',{name:'Approve'}).click();
  await page.getByLabel('Reason').fill('Compliance reviewed');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await expect(page.getByText('Compliance reviewed')).toBeVisible();
  await expect(page.getByRole('button',{name:'Approve'})).toHaveCount(0);
  expect(errors).toEqual([]);
});
