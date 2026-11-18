import { test, expect } from '@playwright/test';

test('browse seeded records and preserve authorization', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !message.text().includes('401') && !message.text().includes('404')) errors.push(message.text()); });
  await page.goto('/');
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await expect(page).toHaveURL(/\/home/);
  await expect(page.getByText('Spend by category')).toBeVisible();
  await page.getByRole('link',{name:'Suppliers',exact:true}).first().click();
  await expect(page.getByText('Thermo Fisher')).toBeVisible();
  await page.getByLabel('Search').fill('Thermo');
  await page.getByRole('link',{name:'SUP-4001'}).click();
  await expect(page.getByText('Mock · JAGGAER')).toBeVisible();
  await expect(page.getByText('purchase orders',{exact:true})).toBeVisible();
  await page.goto('/knowledge/5');
  await expect(page.getByText('Record not found.')).toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile navigation opens and record table remains usable', async ({ page }) => {
  await page.setViewportSize({width:375,height:800});
  await page.goto('/');
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('button',{name:'Open navigation'}).click();
  await page.getByRole('link',{name:'Purchase orders'}).click();
  await expect(page.getByRole('link',{name:'PO-1001'})).toBeVisible();
});
