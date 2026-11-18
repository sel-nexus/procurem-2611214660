import { test, expect } from './fixtures';

test('browse seeded records and preserve authorization', async ({ page }) => {
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

});

test('mobile navigation opens and record table remains usable', async ({ page }, testInfo) => {
  await page.setViewportSize({width:375,height:800});
  await page.goto('/');
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('button',{name:'Open navigation'}).click();
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Purchase orders',exact:true}).click();
  await expect(page.getByRole('link',{name:'PO-1001'})).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('mobile-purchase-orders.png'), fullPage:true});
});
