import { test, expect } from './fixtures';

test('sign in, restore the session and sign out', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Helen Cho')).toBeVisible();
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('wrong');
  await page.getByRole('button', {name:'Sign in'}).click();
  await expect(page.getByRole('region', {name:'Procurem'}).getByRole('alert')).toHaveText('Authentication failed. Please check your credentials.');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByLabel('Remember me').check();
  await page.getByRole('button', {name:'Sign in'}).click();
  await expect(page.getByText('Priya Shah', {exact: true})).toBeVisible();
  await page.reload();
  await expect(page.getByText('Priya Shah', {exact: true})).toBeVisible();
  await page.getByRole('button', {name:'Sign out'}).click();
  await expect(page.getByRole('button', {name:'Sign in'})).toBeVisible();
});
