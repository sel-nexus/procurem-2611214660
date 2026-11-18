import { test, expect, signIn } from './fixtures';

test('manager opens a notification, marks it read and follows its approval', async ({page}) => {
  await page.goto('/');
  await signIn(page,'proc.manager@procurem.demo');
  const notifications = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/notifications' && r.request().method() === 'GET');
  await page.getByRole('link',{name:/Notifications/}).click();
  const list = await notifications;
  expect(list.status()).toBe(200);
  const body = await list.json();
  const item = body.items.find((entry: {id:number}) => entry.id === 1);
  expect(item).toMatchObject({title:'Requisition awaiting approval',is_read:0,link:'/approvals/1'});
  const notification = page.getByRole('button',{name:/Requisition awaiting approval/}).filter({has:page.locator('time', {hasText:item.created_at})});
  await expect(notification).toHaveCount(1);
  await expect(notification.getByText('Unread',{exact:true})).toBeVisible();
  const read = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/notifications/1/read' && r.request().method() === 'POST');
  await notification.click();
  expect((await read).status()).toBe(200);
  await expect(page).toHaveURL(/\/approvals\/1$/);
  await expect(page.getByRole('heading',{name:'Laboratory supplies 1'})).toBeVisible();
  await page.getByRole('link',{name:/Notifications/}).click();
  await expect(notification.getByText('Read',{exact:true})).toBeVisible();
});
