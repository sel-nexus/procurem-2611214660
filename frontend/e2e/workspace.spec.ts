import { test, expect } from '@playwright/test';

test('analyst saves a fiscal year and sees restricted navigation', async ({ page }) => {
  const errors:string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/');
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await expect(page.getByText('Priya Shah').first()).toBeVisible();
  await expect(page.getByLabel('Preferred fiscal year')).toHaveValue('2026');
  await page.getByLabel('Preferred fiscal year').fill('2025');
  await page.getByRole('button',{name:'Save fiscal year'}).click();
  await expect(page.getByText('Fiscal year saved.')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Preferred fiscal year')).toHaveValue('2025');
  await page.getByLabel('Preferred fiscal year').fill('2026');
  await page.getByRole('button',{name:'Save fiscal year'}).click();
  await expect(page.getByText('Fiscal year saved.')).toBeVisible();
  await expect(page.getByRole('link',{name:'Audit log'})).toHaveCount(0);
  await expect(page.getByRole('link',{name:'Roles',exact:true})).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('compliance opens role directory and downloads the audit log', async ({ page }) => {
  const errors:string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/');
  await page.getByLabel('Email').fill('compliance@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('link',{name:'Roles',exact:true}).click();
  await expect(page.getByText('Priya Shah')).toBeVisible();
  await page.getByRole('link',{name:'Audit log'}).click();
  await expect(page.getByText('seed',{exact:true}).first()).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link',{name:'Export CSV'}).click();
  expect((await download).suggestedFilename()).toBe('audit.csv');
  expect(errors).toEqual([]);
});
