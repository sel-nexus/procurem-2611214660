import { chromium } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

/** Capture rendered structure, accessibility information and styling for review. */
async function main() {
  const browser = await chromium.launch();
  const notes = [];
  for (const [label, viewport] of [['desktop', { width: 1280, height: 900 }], ['mobile', { width: 375, height: 812 }]]) {
    const page = await browser.newPage({ viewport });
    await page.goto(process.env.PREFLIGHT_URL || 'http://127.0.0.1:3000/');
    await page.getByLabel('Email').fill('analyst@procurem.demo');
    await page.getByLabel('Password').fill('Demo@1234');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForURL('**/home');
    await page.getByRole('heading', { name: 'Home' }).waitFor();
    const accessibility = page.accessibility ? await page.accessibility.snapshot() : await page.locator('body').ariaSnapshot();
    const style = await page.evaluate(() => ({ font: getComputedStyle(document.body).fontFamily, color: getComputedStyle(document.body).color, background: getComputedStyle(document.body).backgroundColor }));
    await page.screenshot({ path: `preflight-${label}.png`, fullPage: true });
    notes.push(JSON.stringify({ label, accessibility, style, html: await page.content() }, null, 2));
    await page.close();
  }
  await writeFile('preflight-review.txt', notes.join('\n\n'), 'utf8');
  await browser.close();
}
await main();
