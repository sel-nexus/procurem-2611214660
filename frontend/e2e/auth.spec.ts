import { test, expect } from '@playwright/test';

test('sign in, restore the session and sign out', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !message.text().includes('401')) errors.push(message.text()); });
  await page.goto('/');
  await expect(page.getByText('Helen Cho')).toBeVisible();
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('wrong');
  await page.getByRole('button', {name:'Sign in'}).click();
  await expect(page.getByRole('alert')).toHaveText('Authentication failed. Please check your credentials.');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByLabel('Remember me').check();
  await page.getByRole('button', {name:'Sign in'}).click();
  await expect(page.getByText('Signed in as Priya Shah.')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Signed in as Priya Shah.')).toBeVisible();
  await page.getByRole('button', {name:'Sign out'}).click();
  await expect(page.getByRole('button', {name:'Sign in'})).toBeVisible();
  expect(errors).toEqual([]);
});
