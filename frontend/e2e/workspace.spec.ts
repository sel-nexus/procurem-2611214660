import { test, expect } from './fixtures';

test('compliance opens role directory and downloads the audit log', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Email').fill('compliance@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('link',{name:'Roles',exact:true}).click();
  await expect(page.getByText('Priya Shah')).toBeVisible();
  await page.getByRole('link',{name:'Audit log'}).click();
  await page.getByLabel('Action').fill('seed');
  await expect(page.getByText('seed',{exact:true}).first()).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link',{name:'Export CSV'}).click();
  expect((await download).suggestedFilename()).toBe('audit.csv');
});
