import { test, expect } from '@playwright/test';

test('assistant answers from stored rows and reopens a conversation', async ({ page }) => {
  const errors:string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/');
  await page.getByLabel('Email').fill('analyst@procurem.demo');
  await page.getByLabel('Password').fill('Demo@1234');
  await page.getByRole('button',{name:'Sign in'}).click();
  await page.getByRole('link',{name:'Assistant',exact:true}).click();
  const input = page.getByLabel('Ask the assistant');
  await input.fill('which purchase orders are overdue');
  await input.press('Enter');
  await expect(page.getByText('Reading records…')).toBeVisible();
  await expect(page.getByText('Mock · Oracle')).toBeVisible();
  await expect(page.getByRole('link',{name:/PO-\d+/}).first()).toBeVisible();
  await expect(page.getByText(/estimated tokens/)).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link',{name:'Export answer'}).click();
  expect((await downloadPromise).suggestedFilename()).toBe('answer.csv');
  await page.getByRole('button',{name:'New',exact:true}).click();
  await page.getByRole('button',{name:'which purchase orders are overdue'}).click();
  await expect(page.getByText('Mock · Oracle')).toBeVisible();
  expect(errors).toEqual([]);
});
